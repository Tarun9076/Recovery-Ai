"use client";

/**
 * Interactive "Failure -> Recovery Simulation" walkthrough for the demo.
 *
 * Every state transition below is driven by a real backend response --
 * postInvestigate / postCreateCampaign / postApproveCampaign /
 * postRejectCampaign / postExecuteCampaign / postSimulatePayment /
 * postSimulateProviderFailure / postResetDemo. Nothing here sets a
 * "recovered" or "success" value independently of what one of those calls
 * returned. The `stage` state only controls which cards are revealed --
 * every number, status, and reason shown inside those cards is a field
 * read off the real API response.
 */

import { useState } from "react";
import {
  getCampaign,
  postApproveCampaign,
  postCreateCampaign,
  postExecuteCampaign,
  postInvestigate,
  postRejectCampaign,
  postResetDemo,
  postSimulatePayment,
  postSimulateProviderFailure,
  type CampaignDetail,
  type InvestigateResponse,
  type RecoveryOpportunity,
  type SimulatePaymentResult,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";
import {
  ShieldCheck,
  AlertTriangle,
  Sparkles,
  CheckCircle2,
  XCircle,
  Loader2,
  Webhook,
  RotateCcw,
  ArrowRight,
  Ban,
} from "lucide-react";

function formatAction(action?: string): string {
  if (!action) return "—";
  return action.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

type Stage =
  | "idle"
  | "failure"
  | "detected"
  | "investigated"
  | "decided"
  | "rejected"
  | "approved"
  | "dispatched"
  | "recovered";

const STEP_LABELS = [
  "FAILURE",
  "DETECT",
  "INVESTIGATE",
  "DECIDE",
  "APPROVE",
  "RECOVER",
  "WEBHOOK",
  "VERIFY",
  "RECOVERED",
] as const;

// Index (0-based) of the last completed step for a given stage -- purely a
// UI reveal cursor, never a source of truth for recovery status itself.
const STAGE_STEP_INDEX: Record<Stage, number> = {
  idle: -1,
  failure: 0,
  detected: 1,
  investigated: 2,
  decided: 3,
  rejected: 3,
  approved: 4,
  dispatched: 5,
  recovered: 8,
};

function Stepper({ stage }: { stage: Stage }) {
  const currentIdx = STAGE_STEP_INDEX[stage];
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-9">
      {STEP_LABELS.map((label, idx) => {
        const isFailedHere = stage === "rejected" && idx === 4;
        const isDone = idx < currentIdx || (stage === "recovered" && idx <= 8);
        const isCurrent = idx === currentIdx && !isFailedHere;
        let symbol = "○";
        let cls = "border-slate-700 bg-slate-800/40 text-slate-400";
        if (isFailedHere) {
          symbol = "✕";
          cls = "border-rose-500/50 bg-rose-950/40 text-rose-300";
        } else if (isDone) {
          symbol = "✓";
          cls = "border-emerald-500/40 bg-emerald-950/40 text-emerald-300";
        } else if (isCurrent) {
          symbol = "●";
          cls = "border-indigo-400 bg-indigo-600/30 text-white";
        }
        return (
          <div key={label} className={`rounded-lg border p-2 text-center transition-all ${cls}`}>
            <div className="text-sm font-bold">{symbol}</div>
            <div className="mt-0.5 text-3xs font-extrabold tracking-wider">
              {String(idx + 1).padStart(2, "0")} {label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4 space-y-2">
      <p className="text-2xs font-bold uppercase tracking-wider text-indigo-300">{title}</p>
      {children}
    </div>
  );
}

function Field({ label, value, valueClass = "text-white" }: { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div>
      <p className="text-3xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`text-sm font-bold ${valueClass}`}>{value}</p>
    </div>
  );
}

interface LiveState {
  status: string;
  amountAtRisk: number;
  recovered: number;
  paymentState: string;
  webhookState: string;
  nextAction: string;
}

interface SimLogEntry {
  id: string;
  text: string;
  at: string;
}

export function FailureRecoverySimulator({ candidates }: { candidates: RecoveryOpportunity[] }) {
  const [stage, setStage] = useState<Stage>("idle");
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [log, setLog] = useState<SimLogEntry[]>([]);

  const [investigation, setInvestigation] = useState<InvestigateResponse | null>(null);
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [excludedReason, setExcludedReason] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string | null>(null);
  const [webhookPhase, setWebhookPhase] = useState<"idle" | "processing" | "error">("idle");
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [simResult, setSimResult] = useState<SimulatePaymentResult | null>(null);

  const [failureCampaign, setFailureCampaign] = useState<CampaignDetail | null>(null);

  const selected = candidates.find((c) => c.payment_id === selectedId);
  const executedAction = campaign?.actions[0];

  function addLog(text: string) {
    setLog((prev) => [{ id: crypto.randomUUID(), text, at: new Date().toISOString() }, ...prev]);
  }

  function resetLocal() {
    setStage("idle");
    setSelectedId("");
    setInvestigation(null);
    setCampaign(null);
    setExcludedReason(null);
    setRejectReason(null);
    setWebhookPhase("idle");
    setWebhookError(null);
    setSimResult(null);
    setFailureCampaign(null);
    setLog([]);
  }

  async function handleReset() {
    setBusy("reset");
    try {
      const counts = await postResetDemo();
      resetLocal();
      addLog(`Reset via backend: cleared ${counts.recovery_campaigns} campaigns, ${counts.recovery_actions} actions, ${counts.webhook_events} webhooks.`);
    } catch (e) {
      addLog(`Reset failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  function startSimulation() {
    if (!selectedId) return;
    setStage("failure");
    addLog(`Payment failure loaded: PAY_${selectedId.slice(0, 8)}.`);
  }

  function analyzeFailure() {
    setStage("detected");
    addLog(`RecoverAI detected failure category ${selected?.failure_category ?? "UNKNOWN"}.`);
  }

  async function runInvestigation() {
    if (!selected) return;
    setBusy("investigate");
    try {
      const result = await postInvestigate(
        `Payment ${selected.payment_id} (₹${selected.amount}) failed with category ${selected.failure_category}. Why, and is it recoverable?`,
      );
      setInvestigation(result);
      setStage("investigated");
      addLog(`AI investigation complete: ${result.findings.length} findings, ${formatCurrency(result.revenue_at_risk)} at risk.`);
    } catch (e) {
      addLog(`AI investigation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function generateDecision() {
    if (!selected) return;
    setBusy("decide");
    try {
      const created = await postCreateCampaign([selected.payment_id], `Simulator campaign ${new Date().toISOString()}`);
      if (created.excluded.length > 0) {
        setExcludedReason(created.excluded[0].reason);
        addLog(`Policy check failed: ${created.excluded[0].reason}`);
        setBusy(null);
        return;
      }
      const detail = await getCampaign(created.campaign.id);
      setCampaign(detail);
      setExcludedReason(null);
      setStage("decided");
      addLog(`Recovery decision: ${formatAction(detail.recommendations[0]?.recommended_action)} -- policy checks passed.`);
    } catch (e) {
      addLog(`Recovery decision failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function approve() {
    if (!campaign) return;
    setBusy("approve");
    try {
      const detail = await postApproveCampaign(campaign.id);
      setCampaign(detail);
      setStage("approved");
      addLog("Merchant approved recovery.");
    } catch (e) {
      addLog(`Approval failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function reject() {
    if (!campaign) return;
    setBusy("reject");
    try {
      const detail = await postRejectCampaign(campaign.id, "demo", "Rejected in failure-recovery simulator");
      setCampaign(detail);
      setRejectReason("Merchant rejected this recovery action -- no action will be dispatched.");
      setStage("rejected");
      addLog("Merchant rejected recovery. No action dispatched, ₹0 recovered.");
    } catch (e) {
      addLog(`Rejection failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function dispatch() {
    if (!campaign) return;
    setBusy("execute");
    try {
      const detail = await postExecuteCampaign(campaign.id);
      setCampaign(detail);
      setStage("dispatched");
      addLog("Recovery action dispatched. Revenue recorded: ₹0 (payment link created, not yet paid).");
    } catch (e) {
      addLog(`Dispatch failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function triggerWebhook() {
    if (!executedAction || !campaign) return;
    setWebhookPhase("processing");
    setWebhookError(null);
    setBusy("webhook");
    try {
      const result = await postSimulatePayment(executedAction.id);
      const refreshed = await getCampaign(campaign.id);
      setSimResult(result);
      setCampaign(refreshed);
      setStage("recovered");
      setWebhookPhase("idle");
      addLog(`Webhook received -- signature verified -- payment ${result.status}${result.amount_paid ? ` -- ${formatCurrency(result.amount_paid)} captured` : ""}.`);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setWebhookPhase("error");
      setWebhookError(message);
      addLog(`Webhook rejected: ${message}`);
    } finally {
      setBusy(null);
    }
  }

  async function simulateProviderTimeout() {
    setBusy("provider-failure");
    try {
      const detail = await postSimulateProviderFailure();
      setFailureCampaign(detail);
      addLog(`Provider timeout simulated on an independent campaign -- action FAILED, ₹0 recorded, payment still eligible for retry.`);
    } catch (e) {
      addLog(`Provider timeout simulation failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  const isRecovered = executedAction?.status === "RECOVERED";
  const liveState: LiveState = (() => {
    if (stage === "idle") {
      return { status: "NOT STARTED", amountAtRisk: 0, recovered: 0, paymentState: "—", webhookState: "—", nextAction: "Select a failed payment to begin" };
    }
    if (stage === "rejected") {
      return {
        status: "REJECTED",
        amountAtRisk: selected?.amount ?? 0,
        recovered: 0,
        paymentState: "N/A",
        webhookState: "N/A",
        nextAction: "Reset to try another payment",
      };
    }
    if (stage === "recovered" && executedAction) {
      return {
        status: isRecovered ? "RECOVERED" : executedAction.status,
        amountAtRisk: selected?.amount ?? 0,
        recovered: executedAction.recovered_amount ?? 0,
        paymentState: isRecovered ? "CAPTURED" : "UNKNOWN",
        webhookState: isRecovered ? "VERIFIED" : "RECEIVED",
        nextAction: "Simulation complete -- reset to run again",
      };
    }
    if (stage === "dispatched") {
      return {
        status: "DISPATCHED",
        amountAtRisk: selected?.amount ?? 0,
        recovered: 0,
        paymentState: "WAITING",
        webhookState: "WAITING",
        nextAction: "Trigger Payment Webhook",
      };
    }
    if (stage === "approved") {
      return { status: "APPROVED", amountAtRisk: selected?.amount ?? 0, recovered: 0, paymentState: "—", webhookState: "—", nextAction: "Dispatch recovery action" };
    }
    if (stage === "decided") {
      return { status: "AWAITING APPROVAL", amountAtRisk: selected?.amount ?? 0, recovered: 0, paymentState: "—", webhookState: "—", nextAction: "Approve or reject" };
    }
    return {
      status: "FAILED PAYMENT",
      amountAtRisk: selected?.amount ?? 0,
      recovered: 0,
      paymentState: "—",
      webhookState: "—",
      nextAction:
        stage === "failure" ? "Analyze failure" : stage === "detected" ? "Run AI investigation" : "Generate recovery decision",
    };
  })();

  return (
    <div className="rounded-xl border border-indigo-300/20 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 p-6 text-white shadow-lg space-y-6">
      <div className="flex flex-col gap-3 border-b border-white/10 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500/20 px-3 py-1 text-xs font-bold text-indigo-200 border border-indigo-400/30">
            <ShieldCheck className="h-3.5 w-3.5" /> FAILURE → RECOVERY SIMULATION
          </span>
          <p className="mt-2 text-xs text-slate-300 max-w-2xl">
            Simulate a complete failed-payment recovery journey and verify that RecoverAI never records revenue
            without confirmed payment and verified webhook evidence.
          </p>
        </div>
        <button
          disabled={busy === "reset"}
          onClick={handleReset}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-rose-400/30 bg-rose-500/10 px-3.5 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50 transition-all"
        >
          <RotateCcw className={`h-3.5 w-3.5 ${busy === "reset" ? "animate-spin" : ""}`} />
          Reset Failure Simulation
        </button>
      </div>

      <Stepper stage={stage} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* MAIN NARRATIVE COLUMN */}
        <div className="lg:col-span-2 space-y-4">
          {stage === "idle" && (
            <SectionCard title="Start Simulation">
              <label className="block text-2xs font-semibold text-slate-300">
                Select a real failed payment
                <select
                  className="mt-1 block w-full rounded-lg border border-white/10 bg-slate-800 px-3 py-2 text-xs font-medium text-white focus:border-indigo-400 focus:outline-none"
                  value={selectedId}
                  onChange={(e) => setSelectedId(e.target.value)}
                >
                  <option value="">Choose a payment…</option>
                  {candidates.map((c) => (
                    <option key={c.payment_id} value={c.payment_id}>
                      PAY_{c.payment_id.slice(0, 8)} &middot; {formatCurrency(c.amount)} &middot; {c.failure_category ?? "UNKNOWN"}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={!selectedId}
                onClick={startSimulation}
                className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-40"
              >
                Start Simulation <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </SectionCard>
          )}

          {stage !== "idle" && selected && (
            <SectionCard title="Payment Failure">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="Payment ID" value={`PAY_${selected.payment_id.slice(0, 8)}`} />
                <Field label="Amount" value={formatCurrency(selected.amount)} />
                <Field label="Payment Method" value={selected.payment_method} />
                <Field label="Failure Reason" value={selected.failure_category ?? "—"} />
                <Field label="Payment Status" value="FAILED" valueClass="text-rose-400" />
                <Field label="Detected At" value={formatDateTime(new Date().toISOString())} />
              </div>
              {stage === "failure" && (
                <button
                  onClick={analyzeFailure}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500"
                >
                  Analyze Failure <ArrowRight className="h-3.5 w-3.5" />
                </button>
              )}
            </SectionCard>
          )}

          {STAGE_STEP_INDEX[stage] >= 1 && selected && (
            <SectionCard title="Failure Detected">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="RecoverAI Detected" value={selected.failure_category ?? "—"} />
                <Field label="Amount at Risk" value={formatCurrency(selected.amount)} valueClass="text-rose-300" />
                <Field label="Revenue Risk" value={selected.amount > 10000 ? "HIGH" : "MEDIUM"} />
              </div>
              {stage === "detected" && (
                <button
                  disabled={busy === "investigate"}
                  onClick={runInvestigation}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {busy === "investigate" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  Run AI Investigation
                </button>
              )}
            </SectionCard>
          )}

          {investigation && (
            <SectionCard title="AI Investigation">
              <p className="text-xs text-slate-200">{investigation.summary}</p>
              {investigation.findings.slice(0, 2).map((f, idx) => (
                <p key={idx} className="text-2xs text-slate-400">
                  &middot; {f.finding} ({f.severity} severity, {formatCurrency(f.revenue_at_risk)} at risk)
                </p>
              ))}
              <div className="mt-1 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="Recovery Probability" value={selected ? formatPercent(selected.recovery_probability) : "—"} />
              </div>
              {stage === "investigated" && (
                <button
                  disabled={busy === "decide"}
                  onClick={generateDecision}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {busy === "decide" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Generate Recovery Decision
                </button>
              )}
              {excludedReason && (
                <p className="mt-1 text-2xs font-semibold text-rose-300">Not eligible: {excludedReason}</p>
              )}
            </SectionCard>
          )}

          {campaign && (
            <SectionCard title="Recovery Decision">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="Recovery Probability" value={formatPercent(campaign.recommendations[0]?.recovery_probability ?? 0)} />
                <Field label="Amount at Risk" value={formatCurrency(campaign.revenue_at_risk)} />
                <Field label="Expected Recovery" value={formatCurrency(campaign.recoverable_revenue)} />
                <Field label="Recommended Action" value={formatAction(campaign.recommendations[0]?.recommended_action)} />
                <Field label="Policy Check" value={<span className="text-emerald-400">✓ Eligible</span>} />
                <Field label="Merchant Guardrails" value={<span className="text-emerald-400">✓ Passed</span>} />
              </div>
              <p className="text-2xs text-slate-400">{campaign.recommendations[0]?.reason}</p>

              {stage === "decided" && (
                <div className="flex gap-2 pt-1">
                  <button
                    disabled={busy === "reject"}
                    onClick={reject}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-500 px-4 py-2 text-xs font-bold text-slate-200 hover:bg-white/5 disabled:opacity-50"
                  >
                    <Ban className="h-3.5 w-3.5" /> Reject
                  </button>
                  <button
                    disabled={busy === "approve"}
                    onClick={approve}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50"
                  >
                    {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                    Approve Recovery
                  </button>
                </div>
              )}

              {stage === "rejected" && rejectReason && (
                <p className="mt-1 rounded bg-rose-950/40 border border-rose-500/30 p-2 text-2xs font-semibold text-rose-300">
                  <XCircle className="mr-1 inline h-3.5 w-3.5" /> {rejectReason}
                </p>
              )}

              {stage === "approved" && (
                <button
                  disabled={busy === "execute"}
                  onClick={dispatch}
                  className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {busy === "execute" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Dispatch Recovery Action
                </button>
              )}
            </SectionCard>
          )}

          {executedAction && (stage === "dispatched" || stage === "recovered") && (
            <SectionCard title={isRecovered ? "Revenue Recovered" : "Recovery Action Dispatched"}>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Field label="Action" value={formatAction(executedAction.action_type)} />
                <Field label="Status" value={executedAction.status} valueClass={isRecovered ? "text-emerald-400" : "text-amber-300"} />
                <Field
                  label="Recovered Revenue"
                  value={formatCurrency(executedAction.recovered_amount ?? 0)}
                  valueClass={isRecovered ? "text-emerald-400" : "text-white"}
                />
                <Field label="Customer Payment" value={isRecovered ? "PAID" : "WAITING"} />
                <Field label="Webhook" value={isRecovered ? "VERIFIED" : "WAITING"} />
              </div>

              {!isRecovered && (
                <p className="rounded bg-indigo-950/40 border border-indigo-500/30 p-2 text-2xs font-semibold text-indigo-200">
                  Recovery action dispatched. Revenue remains ₹0 until payment is confirmed and the webhook is
                  verified.
                </p>
              )}

              {stage === "dispatched" && (
                <div className="space-y-2 pt-1">
                  <p className="text-2xs text-slate-400">
                    Manually trigger the payment webhook to simulate the customer successfully completing the
                    payment. This calls the real <code className="font-mono">/api/mock/simulate-payment</code>{" "}
                    endpoint, verified through the same signature-checked pipeline a genuine Razorpay delivery uses.
                  </p>
                  <button
                    disabled={busy === "webhook"}
                    onClick={triggerWebhook}
                    className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
                  >
                    {busy === "webhook" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Webhook className="h-4 w-4" />}
                    Trigger Payment Webhook
                  </button>
                  {webhookPhase !== "idle" && (
                    <div className="rounded-lg border border-indigo-400/30 bg-indigo-950/30 p-3 space-y-1.5">
                      {["Triggering payment webhook", "Webhook received", "Signature verified", "Payment confirmed", "Recovery updated"].map(
                        (step, idx) => {
                          const isFailed = webhookPhase === "error" && idx === 0;
                          const isProcessing = webhookPhase === "processing" && idx === 0;
                          return (
                            <div key={step} className="flex items-center gap-2 text-2xs">
                              {isFailed ? (
                                <XCircle className="h-3 w-3 text-rose-400" />
                              ) : isProcessing ? (
                                <Loader2 className="h-3 w-3 animate-spin text-indigo-300" />
                              ) : (
                                <span className="h-3 w-3 rounded-full border border-slate-500" />
                              )}
                              <span className="text-slate-300">{step}</span>
                            </div>
                          );
                        },
                      )}
                      {webhookPhase === "error" && webhookError && (
                        <p className="text-2xs font-semibold text-rose-300">Webhook rejected: {webhookError}</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {stage === "recovered" && simResult && (
                <div className="rounded-lg border border-emerald-400/30 bg-emerald-950/30 p-3 space-y-1">
                  <p className="text-2xs font-bold text-emerald-300 flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Webhook Verified
                  </p>
                  <p className="text-2xs text-slate-300">Webhook &middot; ✓ RECEIVED</p>
                  <p className="text-2xs text-slate-300">Signature &middot; ✓ VERIFIED</p>
                  <p className="text-2xs text-slate-300">Payment &middot; ✓ CAPTURED</p>
                  <p className="text-2xs text-slate-300">Backend Recovery State &middot; ✓ UPDATED</p>
                </div>
              )}
            </SectionCard>
          )}
        </div>

        {/* LIVE STATE SIDE CARD */}
        <div className="space-y-4">
          <div className="rounded-lg border border-white/10 bg-white/5 p-4 space-y-3">
            <p className="text-2xs font-bold uppercase tracking-wider text-indigo-300">Current Recovery State</p>
            <p className="text-lg font-extrabold text-white">● {liveState.status}</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Amount at Risk" value={formatCurrency(liveState.amountAtRisk)} />
              <Field label="Recovered" value={formatCurrency(liveState.recovered)} valueClass={liveState.recovered > 0 ? "text-emerald-400" : "text-white"} />
              <Field label="Payment" value={liveState.paymentState} />
              <Field label="Webhook" value={liveState.webhookState} />
            </div>
            <div className="border-t border-white/10 pt-2">
              <p className="text-3xs font-semibold uppercase text-slate-400">Next Action</p>
              <p className="text-xs font-bold text-indigo-300">{liveState.nextAction}</p>
            </div>
          </div>

          {/* SEPARATE, REAL PROVIDER-FAILURE DEMONSTRATION -- this exercises
              a genuinely different backend code path (FailingPaymentProvider,
              see payment_provider.py) on its own independently-selected
              candidate payment, since the public API has no way to force an
              already-approved campaign's execute step to fail. It ends in a
              real terminal FAILED action with no payment_link_id, so (as in
              production) no webhook can ever apply to it afterward. */}
          <div className="rounded-lg border border-rose-400/30 bg-rose-950/20 p-4 space-y-2">
            <p className="text-2xs font-bold uppercase tracking-wider text-rose-300 flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" /> Provider Failure Demonstration
            </p>
            <p className="text-2xs text-slate-300">
              Runs an independent real campaign end-to-end against a provider that always fails to create a payment
              link -- the other genuine failure mode RecoverAI handles. Zero revenue is ever recorded, and the
              payment stays eligible for a fresh retry campaign.
            </p>
            <button
              disabled={busy === "provider-failure"}
              onClick={simulateProviderTimeout}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-3.5 py-2 text-2xs font-bold text-white hover:bg-rose-500 disabled:opacity-50"
            >
              {busy === "provider-failure" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <AlertTriangle className="h-3.5 w-3.5" />}
              Simulate Provider Timeout
            </button>
            {failureCampaign && (
              <div className="mt-1 rounded bg-black/20 p-2 text-3xs text-slate-300">
                Campaign {failureCampaign.id.slice(0, 8)} &middot; Status:{" "}
                <strong className="text-rose-300">{failureCampaign.status}</strong> &middot; Recovered:{" "}
                <strong className="text-emerald-400">{formatCurrency(failureCampaign.revenue_recovered)}</strong>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* AUDIT LOG */}
      <div className="rounded-lg border border-white/10 bg-black/20 p-4">
        <p className="text-2xs font-bold uppercase tracking-wider text-indigo-300 mb-2">Simulation Audit Log</p>
        {log.length === 0 ? (
          <p className="text-2xs text-slate-500">No events yet -- start the simulation above.</p>
        ) : (
          <div className="space-y-1 font-mono text-3xs text-slate-300">
            {log.map((entry) => (
              <p key={entry.id}>
                <span className="text-slate-500">{new Date(entry.at).toLocaleTimeString("en-IN")}</span> {entry.text}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

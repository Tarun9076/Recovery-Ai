"use client";

import { useState } from "react";
import { CampaignDetailView } from "@/components/CampaignDetailView";
import { FailureRecoverySimulator } from "@/components/FailureRecoverySimulator";
import {
  getHighRecoveryOpportunities,
  postApproveCampaign,
  postCreateCampaign,
  postExecuteCampaign,
  postInvestigate,
  postResetDemo,
  postSimulatePayment,
  getCampaign,
  type CampaignDetail,
  type InvestigateResponse,
  type RecoveryOpportunity,
  type SimulatePaymentResult,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";
import {
  Sparkles,
  CheckCircle2,
  RotateCcw,
  Activity,
  ChevronRight,
  XCircle,
  Webhook,
  Loader2,
} from "lucide-react";

interface LogEntry {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
  at: string;
}

// The only action the current PaymentProvider abstraction can actually
// execute -- mirrors app/services/action_selector.EXECUTABLE_ACTIONS on the
// backend. Used only to label a candidate in the picker, never to decide
// anything -- the backend's own `recommended_action` is always what's shown.
const EXECUTABLE_ACTION = "PAYMENT_LINK";

function formatAction(action?: string): string {
  if (!action) return "—";
  return action.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function PaymentPicker({
  candidates,
  value,
  onChange,
  label,
}: {
  candidates: RecoveryOpportunity[];
  value: string;
  onChange: (id: string) => void;
  label: string;
}) {
  const selected = candidates.find((c) => c.payment_id === value);

  return (
    <div className="space-y-2">
      <label className="block text-xs font-semibold text-slate-700">
        <span>{label}</span>
        <select
          className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-900 focus:border-indigo-500 focus:outline-none shadow-xs"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Let RecoverAI select highest probability candidate</option>
          {candidates.map((c) => (
            <option key={c.payment_id} value={c.payment_id}>
              PAY_{c.payment_id.slice(0, 8)} &middot; {formatCurrency(c.amount)} &middot;{" "}
              {formatPercent(c.recovery_probability)} score &middot; {c.payment_method}
              {c.failure_category ? ` (${c.failure_category})` : ""} &middot; {formatAction(c.recommended_action)}
              {c.recommended_action && c.recommended_action !== EXECUTABLE_ACTION ? " (recommendation only)" : ""}
            </option>
          ))}
        </select>
      </label>

      {/* The backend's real decision for the selected candidate -- never
          guessed or hardcoded client-side (spec: "the exact recommendation
          must come from the backend"). */}
      {selected && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-2xs">
          <p>
            <span className="font-bold text-slate-700">Recommended action:</span>{" "}
            <span className="font-semibold text-indigo-700">{formatAction(selected.recommended_action)}</span>
            {selected.recommended_action && selected.recommended_action !== EXECUTABLE_ACTION && (
              <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-3xs font-bold uppercase text-amber-700">
                not auto-executable
              </span>
            )}
          </p>
          {selected.reason && (
            <p className="mt-1 text-slate-600">
              <span className="font-bold text-slate-700">Reason:</span> {selected.reason}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function WorkflowPipelineVisualizer({ activeStep }: { activeStep: number }) {
  const steps = [
    { num: "01", name: "INVESTIGATE" },
    { num: "02", name: "GENERATE" },
    { num: "03", name: "APPROVE" },
    { num: "04", name: "EXECUTE" },
    { num: "05", name: "VERIFY" },
    { num: "06", name: "RECOVER" },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-900 p-4 sm:p-6 text-white shadow-md">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
        <span className="text-2xs font-mono font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-1.5">
          <Activity className="h-3.5 w-3.5" /> RECOVERY ENGINE PIPELINE
        </span>
        <span className="text-2xs font-mono text-slate-400">Step {activeStep} of 6</span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {steps.map((s, idx) => {
          const stepNum = idx + 1;
          const isDone = activeStep > stepNum;
          const isCurrent = activeStep === stepNum;

          return (
            <div
              key={s.num}
              className={`rounded-lg p-3 text-center border transition-all ${
                isCurrent
                  ? "bg-indigo-600/30 border-indigo-400 text-white shadow-xs"
                  : isDone
                  ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
                  : "bg-slate-800/40 border-slate-800 text-slate-400"
              }`}
            >
              <div className="text-2xs font-mono font-bold">{s.num}</div>
              <div className="mt-1 text-2xs font-extrabold tracking-wider">{s.name}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Every value here is read straight off the real candidate/campaign/action
 * state already fetched from the backend -- nothing is invented. This is
 * what makes DISPATCHED vs RECOVERED visible: recoveredRevenue only becomes
 * non-zero once `executedAction.recovered_amount` is set, which only ever
 * happens inside webhook_service.py after signature verification. */
function RecoveryStatusPanel({
  candidate,
  currentStatus,
  recoveredRevenue,
  customerPaymentState,
  webhookState,
}: {
  candidate?: RecoveryOpportunity;
  currentStatus: string;
  recoveredRevenue: number;
  customerPaymentState: string;
  webhookState: string;
}) {
  const statusStyles: Record<string, string> = {
    "FAILED PAYMENT": "bg-rose-50 text-rose-700 border-rose-200",
    "AWAITING APPROVAL": "bg-amber-50 text-amber-700 border-amber-200",
    APPROVED: "bg-blue-50 text-blue-700 border-blue-200",
    DISPATCHED: "bg-amber-50 text-amber-700 border-amber-200",
    RECOVERED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  };
  const badgeClass = statusStyles[currentStatus] ?? "bg-slate-100 text-slate-600 border-slate-200";

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-3">
      {candidate && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-2xs sm:grid-cols-3">
          <div>
            <p className="font-semibold text-slate-500">Payment</p>
            <p className="font-mono font-bold text-slate-900">PAY_{candidate.payment_id.slice(0, 8)}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-500">Amount</p>
            <p className="font-bold text-slate-900">{formatCurrency(candidate.amount)}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-500">Failure Reason</p>
            <p className="font-bold text-slate-900">{candidate.failure_category ?? "—"}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-500">Recovery Probability</p>
            <p className="font-bold text-slate-900">{formatPercent(candidate.recovery_probability)}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-500">Recommended Action</p>
            <p className="font-bold text-slate-900">{formatAction(candidate.recommended_action)}</p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4 border-t border-slate-200 pt-3 text-2xs">
        <div>
          <p className="font-semibold text-slate-500">Current Recovery Status</p>
          <span className={`mt-1 inline-flex items-center rounded-full border px-2.5 py-0.5 text-2xs font-bold ${badgeClass}`}>
            {currentStatus}
          </span>
        </div>
        <div>
          <p className="font-semibold text-slate-500">Recovered Revenue</p>
          <p className={`mt-1 font-bold ${recoveredRevenue > 0 ? "text-emerald-700" : "text-slate-900"}`}>
            {formatCurrency(recoveredRevenue)}
          </p>
        </div>
        <div>
          <p className="font-semibold text-slate-500">Customer Payment</p>
          <p className="mt-1 font-bold text-slate-900">{customerPaymentState}</p>
        </div>
        <div>
          <p className="font-semibold text-slate-500">Webhook</p>
          <p className="mt-1 font-bold text-slate-900">{webhookState}</p>
        </div>
      </div>
    </div>
  );
}

const WEBHOOK_CHECKLIST_STEPS = [
  "Triggering payment webhook",
  "Webhook received",
  "Verifying signature",
  "Confirming payment",
  "Updating recovery",
] as const;

/** Every checklist item reflects one atomic, already-verified backend
 * response -- there is no per-step polling, so "processing" shows only the
 * first item in flight, and the response (success or a real error) decides
 * whether the rest ever get shown as done. Nothing here is faked ahead of
 * the actual API call resolving. */
function WebhookProcessingChecklist({ phase, error }: { phase: "processing" | "done" | "error"; error?: string | null }) {
  const doneCount = phase === "processing" ? 1 : phase === "done" ? WEBHOOK_CHECKLIST_STEPS.length : 1;

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-4 space-y-2">
      <p className="text-2xs font-bold uppercase tracking-wider text-indigo-700">Webhook Processing</p>
      {WEBHOOK_CHECKLIST_STEPS.map((step, idx) => {
        const isDone = idx < doneCount;
        const isCurrent = phase === "processing" && idx === 0;
        const isFailedStep = phase === "error" && idx === 0;
        return (
          <div key={step} className="flex items-center gap-2 text-xs">
            {isFailedStep ? (
              <XCircle className="h-3.5 w-3.5 text-rose-600" />
            ) : isDone ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
            ) : isCurrent ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600" />
            ) : (
              <span className="h-3.5 w-3.5 rounded-full border border-slate-300" />
            )}
            <span className={isDone ? "text-slate-800 font-medium" : "text-slate-400"}>{step}</span>
          </div>
        );
      })}
      {phase === "error" && error && (
        <p className="mt-1 text-2xs font-semibold text-rose-700">Webhook rejected: {error}</p>
      )}
    </div>
  );
}

export function DemoControlPanel({ initialCandidates }: { initialCandidates: RecoveryOpportunity[] }) {
  const [candidates, setCandidates] = useState(initialCandidates);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [activeStepNum, setActiveStepNum] = useState<number>(1);

  const [question, setQuestion] = useState("Why are payments failing right now, and what should we do about it?");
  const [investigation, setInvestigation] = useState<InvestigateResponse | null>(null);

  const [selectedPaymentId, setSelectedPaymentId] = useState(initialCandidates[0]?.payment_id ?? "");
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [simResult, setSimResult] = useState<SimulatePaymentResult | null>(null);
  const [webhookPhase, setWebhookPhase] = useState<"idle" | "processing" | "done" | "error">("idle");
  const [webhookError, setWebhookError] = useState<string | null>(null);

  function pushLog(label: string, ok: boolean, detail: string) {
    setLog((prev) => [
      { id: crypto.randomUUID(), label, ok, detail, at: new Date().toISOString() },
      ...prev,
    ]);
  }

  async function run<T>(key: string, label: string, fn: () => Promise<T>, onSuccess: (result: T) => string) {
    setLoadingKey(key);
    try {
      const result = await fn();
      const detail = onSuccess(result);
      pushLog(label, true, detail);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      pushLog(label, false, message);
    } finally {
      setLoadingKey(null);
    }
  }

  const executedAction = campaign?.actions.find(
    (a) => a.status === "EXECUTED" || a.status === "AUTHORIZED" || a.status === "RECOVERED",
  );
  const isRecovered = executedAction?.status === "RECOVERED";
  const selectedCandidate = candidates.find((c) => c.payment_id === selectedPaymentId);

  // Every branch reads real fetched state (campaign.status / executedAction.status) --
  // nothing here is a guess. This is the DISPATCHED != RECOVERED distinction made explicit.
  const currentRecoveryStatus = !campaign
    ? "FAILED PAYMENT"
    : isRecovered
    ? "RECOVERED"
    : executedAction
    ? "DISPATCHED"
    : campaign.status === "PENDING_APPROVAL"
    ? "AWAITING APPROVAL"
    : campaign.status === "APPROVED"
    ? "APPROVED"
    : campaign.status;
  const recoveredRevenue = executedAction?.recovered_amount ?? 0;
  const customerPaymentState = isRecovered ? "PAID" : executedAction ? "WAITING" : "—";
  const webhookState = isRecovered ? "VERIFIED" : executedAction ? "WAITING" : "—";

  async function triggerWebhook() {
    if (!executedAction || !campaign) return;
    setWebhookPhase("processing");
    setWebhookError(null);
    setLoadingKey("simulate-payment");
    try {
      // The ONLY call made here is the real backend endpoint that self-signs
      // a payment_link.paid payload and runs it through the exact same
      // process_razorpay_webhook signature-verification pipeline a genuine
      // Razorpay delivery goes through (see mock_service.py). No frontend
      // state is ever set to "recovered" independently of this response.
      const result = await postSimulatePayment(executedAction.id);
      const refreshed = await getCampaign(campaign.id);
      setSimResult(result);
      setCampaign(refreshed);
      setActiveStepNum(6);
      setWebhookPhase("done");
      pushLog(
        "Trigger Payment Webhook",
        true,
        `Webhook verified: ${result.status}${result.amount_paid ? ` -- ${formatCurrency(result.amount_paid)} paid` : ""}.`,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setWebhookPhase("error");
      setWebhookError(message);
      pushLog("Trigger Payment Webhook", false, message);
    } finally {
      setLoadingKey(null);
    }
  }

  return (
    <div className="space-y-8">
      {/* Visual Workflow Pipeline Banner */}
      <WorkflowPipelineVisualizer activeStep={activeStepNum} />

      {/* RESET DEMO CARD */}
      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
        <div>
          <p className="text-sm font-bold text-slate-900">Reset Demo Environment</p>
          <p className="text-2xs text-slate-500">
            Clears campaigns, actions, webhooks, and audit logs. Synthetic base dataset remains intact.
          </p>
        </div>
        <button
          disabled={loadingKey === "reset"}
          onClick={() =>
            run(
              "reset",
              "Reset Demo",
              () => postResetDemo(),
              (counts) => {
                setInvestigation(null);
                setCampaign(null);
                setSimResult(null);
                setWebhookPhase("idle");
                setWebhookError(null);
                setActiveStepNum(1);
                getHighRecoveryOpportunities(15)
                  .then((res) => {
                    setCandidates(res);
                    setSelectedPaymentId(res[0]?.payment_id ?? "");
                  })
                  .catch(() => {});
                return `Cleared ${counts.recovery_campaigns} campaigns, ${counts.recovery_actions} actions, ${counts.webhook_events} webhooks.`;
              },
            )
          }
          className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50 transition-all"
        >
          <RotateCcw className={`h-3.5 w-3.5 ${loadingKey === "reset" ? "animate-spin" : ""}`} />
          Reset Demo State
        </button>
      </div>

      {/* STEP 1: RUN INVESTIGATION */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">1</span>
            Run AI Investigation Agent
          </h2>
          <span className="text-2xs font-mono text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded font-semibold border border-indigo-200">
            OBSERVE → DETECT → INVESTIGATE
          </span>
        </div>

        <p className="text-xs text-slate-500 leading-relaxed">
          The AI agent executes a deterministic analysis over real payment logs and invokes the LLM for prose synthesis.
        </p>

        <textarea
          className="block w-full rounded-lg border border-slate-300 p-3 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none"
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />

        <div>
          <button
            disabled={loadingKey === "investigate" || !question.trim()}
            onClick={() =>
              run(
                "investigate",
                "Run Investigation",
                () => postInvestigate(question),
                (res) => {
                  setInvestigation(res);
                  setActiveStepNum(2);
                  return `${res.findings.length} findings, ${res.recommendations.length} recommendations, ${formatCurrency(res.revenue_at_risk)} at risk.`;
                },
              )
            }
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            {loadingKey === "investigate" ? <RotateCcw className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Execute AI Investigation
          </button>
        </div>

        {investigation && (
          <div className="rounded-lg bg-slate-50 p-4 border border-slate-200 text-xs space-y-3">
            <p className="font-semibold text-slate-900">{investigation.summary}</p>
            {investigation.findings.map((f, idx) => (
              <div key={idx} className="border-t border-slate-200 pt-2">
                <span className="font-bold text-slate-800">{f.finding}</span>
                <span className="ml-2 text-2xs uppercase text-slate-400">({f.severity} severity)</span>
                <p className="text-2xs text-slate-500 mt-0.5">
                  {formatCurrency(f.revenue_at_risk)} revenue at risk across {f.affected_payment_count} payments
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* STEPS 2-4: RECOVERY CAMPAIGN LIFECYCLE */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-6">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">2-5</span>
            Execute End-to-End Recovery Workflow
          </h2>
          <span className="text-2xs font-mono text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded font-semibold border border-indigo-200">
            PREDICT → RECOMMEND → APPROVE → EXECUTE → VERIFY
          </span>
        </div>

        <PaymentPicker
          candidates={candidates}
          value={selectedPaymentId}
          onChange={setSelectedPaymentId}
          label="Select Target Failed Payment"
        />

        <RecoveryStatusPanel
          candidate={selectedCandidate}
          currentStatus={currentRecoveryStatus}
          recoveredRevenue={recoveredRevenue}
          customerPaymentState={customerPaymentState}
          webhookState={webhookState}
        />

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* 02 GENERATE */}
          <button
            disabled={loadingKey === "create" || !selectedPaymentId}
            onClick={() =>
              run(
                "create",
                "Generate Recovery Campaign",
                async () => {
                  const created = await postCreateCampaign([selectedPaymentId], `Demo campaign ${new Date().toISOString()}`);
                  return getCampaign(created.campaign.id);
                },
                (detail) => {
                  setCampaign(detail);
                  setSimResult(null);
                  setWebhookPhase("idle");
                  setWebhookError(null);
                  setActiveStepNum(3);
                  return `Campaign ${detail.id.slice(0, 8)} created -- ${formatCurrency(detail.expected_recovery)} expected recovery.`;
                },
              )
            }
            className="flex flex-col items-start justify-between rounded-lg border border-slate-200 bg-slate-50 p-3.5 hover:bg-white hover:border-indigo-300 transition-all text-left disabled:opacity-40"
          >
            <div>
              <span className="text-2xs font-mono font-bold uppercase text-indigo-600">02. GENERATE</span>
              <p className="text-xs font-bold text-slate-900 mt-0.5">Generate Campaign</p>
            </div>
            <span className="mt-3 text-2xs text-indigo-600 font-semibold flex items-center gap-1">
              Run ML Scoring <ChevronRight className="h-3 w-3" />
            </span>
          </button>

          {/* 03 APPROVE */}
          <button
            disabled={loadingKey === "approve" || !campaign || campaign.status !== "PENDING_APPROVAL"}
            onClick={() =>
              run(
                "approve",
                "Approve Campaign",
                () => postApproveCampaign(campaign!.id),
                (detail) => {
                  setCampaign(detail);
                  setActiveStepNum(4);
                  return `Campaign ${detail.id.slice(0, 8)} approved by merchant.`;
                },
              )
            }
            className="flex flex-col items-start justify-between rounded-lg border border-slate-200 bg-slate-50 p-3.5 hover:bg-white hover:border-indigo-300 transition-all text-left disabled:opacity-40"
          >
            <div>
              <span className="text-2xs font-mono font-bold uppercase text-indigo-600">03. APPROVE</span>
              <p className="text-xs font-bold text-slate-900 mt-0.5">Merchant Approval</p>
            </div>
            <span className="mt-3 text-2xs text-indigo-600 font-semibold flex items-center gap-1">
              Sign-off Campaign <ChevronRight className="h-3 w-3" />
            </span>
          </button>

          {/* 04 EXECUTE */}
          <button
            disabled={loadingKey === "execute" || !campaign || campaign.status !== "APPROVED"}
            onClick={() =>
              run(
                "execute",
                "Execute Campaign",
                () => postExecuteCampaign(campaign!.id),
                (detail) => {
                  setCampaign(detail);
                  setActiveStepNum(5);
                  return `Campaign ${detail.id.slice(0, 8)} executed -- Razorpay link created.`;
                },
              )
            }
            className="flex flex-col items-start justify-between rounded-lg border border-slate-200 bg-slate-50 p-3.5 hover:bg-white hover:border-indigo-300 transition-all text-left disabled:opacity-40"
          >
            <div>
              <span className="text-2xs font-mono font-bold uppercase text-indigo-600">04. EXECUTE</span>
              <p className="text-xs font-bold text-slate-900 mt-0.5">Execute Razorpay</p>
            </div>
            <span className="mt-3 text-2xs text-indigo-600 font-semibold flex items-center gap-1">
              Dispatch Link <ChevronRight className="h-3 w-3" />
            </span>
          </button>
        </div>

        {/* STEP 5: MANUAL WEBHOOK TRIGGER -- only ever shown between dispatch
            and confirmed recovery, and never after the action is already
            RECOVERED. Clicking it calls the real backend endpoint below;
            nothing here sets any "recovered" state directly. */}
        {executedAction && !isRecovered && (
          <div className="rounded-xl border-2 border-indigo-300 bg-indigo-50 p-5 space-y-3">
            <div>
              <span className="text-2xs font-mono font-bold uppercase text-indigo-700">05. VERIFY &middot; NEXT STEP</span>
              <p className="mt-1 text-sm font-bold text-slate-900">
                Recovery action dispatched. Revenue will only be recorded after a verified payment webhook.
              </p>
              <p className="mt-0.5 text-2xs text-slate-600">
                Manually trigger the payment webhook to simulate the customer successfully completing the payment.
                This calls the real <code className="font-mono">/api/mock/simulate-payment</code> endpoint, which is
                verified through the same signature-checked webhook pipeline a genuine Razorpay delivery uses.
              </p>
            </div>

            <button
              disabled={loadingKey === "simulate-payment"}
              onClick={triggerWebhook}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 transition-all"
            >
              {loadingKey === "simulate-payment" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Webhook className="h-4 w-4" />
              )}
              Trigger Payment Webhook
            </button>

            {webhookPhase !== "idle" && <WebhookProcessingChecklist phase={webhookPhase} error={webhookError} />}
          </div>
        )}

        {isRecovered && simResult && (
          <div className="rounded-lg bg-emerald-50 p-3 border border-emerald-200 text-xs font-semibold text-emerald-800 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Webhook verified: <strong>{simResult.status}</strong> — {simResult.amount_paid ? `${formatCurrency(simResult.amount_paid)} confirmed paid.` : ""}
          </div>
        )}

        {campaign && (
          <div className="mt-4 pt-4 border-t border-slate-100">
            <CampaignDetailView campaign={campaign} />
          </div>
        )}
      </div>

      {/* FAILURE -> RECOVERY SIMULATION -- a full interactive walkthrough of
          the failure-handling lifecycle, entirely backend-driven. Replaces
          the old single-card provider-timeout sandbox. */}
      <FailureRecoverySimulator candidates={candidates} />

      {/* ACTIVITY LOG TIMELINE */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Activity className="h-4 w-4 text-indigo-600" />
          Real-Time Activity &amp; Audit Log
        </h2>

        {log.length === 0 ? (
          <p className="text-xs text-slate-500">No actions executed in this session yet.</p>
        ) : (
          <div className="relative border-l-2 border-slate-100 pl-6 space-y-4 ml-2">
            {log.map((entry) => (
              <div key={entry.id} className="relative">
                <span
                  className={`absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 bg-white ${
                    entry.ok ? "border-emerald-500 bg-emerald-50" : "border-rose-500 bg-rose-50"
                  }`}
                />
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-bold text-slate-900">{entry.label}</span>
                  <span className="text-2xs font-mono text-slate-400">{formatDateTime(entry.at)}</span>
                </div>
                <p className={`text-2xs mt-0.5 ${entry.ok ? "text-slate-600" : "text-rose-600 font-semibold"}`}>
                  {entry.detail}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

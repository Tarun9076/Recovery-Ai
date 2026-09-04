"use client";

import { useState } from "react";
import { CampaignDetailView } from "@/components/CampaignDetailView";
import {
  getHighRecoveryOpportunities,
  postApproveCampaign,
  postCreateCampaign,
  postExecuteCampaign,
  postInvestigate,
  postResetDemo,
  postSimulatePayment,
  postSimulateProviderFailure,
  getCampaign,
  type CampaignDetail,
  type InvestigateResponse,
  type RecoveryOpportunity,
  type SimulatePaymentResult,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";
import {
  Sparkles,
  Zap,
  Play,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ShieldCheck,
  ArrowRight,
  Clock,
  Activity,
  ChevronRight,
  Send,
  XCircle,
  Lock,
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

  const [failurePaymentId, setFailurePaymentId] = useState("");
  const [failureCampaign, setFailureCampaign] = useState<CampaignDetail | null>(null);

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

  const executedAction = campaign?.actions.find((a) => a.status === "EXECUTED" || a.status === "AUTHORIZED");

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
                setFailureCampaign(null);
                setFailurePaymentId("");
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

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
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

          {/* 05 VERIFY */}
          <button
            disabled={loadingKey === "simulate-payment" || !executedAction}
            onClick={() =>
              run(
                "simulate-payment",
                "Simulate Customer Payment",
                async () => {
                  const result = await postSimulatePayment(executedAction!.id);
                  const refreshed = await getCampaign(campaign!.id);
                  return { result, refreshed };
                },
                ({ result, refreshed }) => {
                  setSimResult(result);
                  setCampaign(refreshed);
                  setActiveStepNum(6);
                  return `Webhook verified: ${result.status}${result.amount_paid ? ` -- ${formatCurrency(result.amount_paid)} paid` : ""}.`;
                },
              )
            }
            className="flex flex-col items-start justify-between rounded-lg border border-slate-200 bg-slate-50 p-3.5 hover:bg-white hover:border-emerald-300 transition-all text-left disabled:opacity-40"
          >
            <div>
              <span className="text-2xs font-mono font-bold uppercase text-emerald-600">05. VERIFY</span>
              <p className="text-xs font-bold text-slate-900 mt-0.5">Verify Webhook</p>
            </div>
            <span className="mt-3 text-2xs text-emerald-600 font-semibold flex items-center gap-1">
              Confirm Payment <ChevronRight className="h-3 w-3" />
            </span>
          </button>
        </div>

        {simResult && (
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

      {/* FAILURE RECOVERY TEST (PROMINENT SANDBOX) */}
      <div className="rounded-xl border border-rose-200 bg-gradient-to-r from-rose-900 via-slate-900 to-rose-950 p-6 text-white shadow-md">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-rose-500/20 pb-4">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-500/20 px-3 py-1 text-xs font-bold text-rose-200 border border-rose-400/30">
              <ShieldCheck className="h-3.5 w-3.5 text-rose-300" /> FAIL-SAFE BEHAVIOR SANDBOX
            </span>
            <h3 className="mt-2 text-xl font-bold text-white">Failure Recovery Test</h3>
            <p className="mt-0.5 text-xs text-slate-300 max-w-xl">
              Simulate a provider gateway timeout and verify that RecoverAI never falsely records unverified revenue as recovered.
            </p>
          </div>

          <button
            disabled={loadingKey === "provider-failure"}
            onClick={() =>
              run(
                "provider-failure",
                "Simulate Provider Failure",
                () => postSimulateProviderFailure(failurePaymentId || undefined),
                (detail) => {
                  setFailureCampaign(detail);
                  return `Provider failure simulated. Status: ${detail.status} -- ₹0 recorded as recovered. Idempotency preserved.`;
                },
              )
            }
            className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-5 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-rose-500 disabled:opacity-40 transition-all"
          >
            {loadingKey === "provider-failure" ? <RotateCcw className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
            Simulate Provider Timeout Failure
          </button>
        </div>

        {/* FAIL-SAFE WORKFLOW PIPELINE VISUALIZER */}
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7 text-2xs font-mono font-bold text-center">
          <div className="p-2 rounded bg-rose-500/20 border border-rose-400/30 text-rose-200">PROVIDER TIMEOUT</div>
          <div className="p-2 rounded bg-rose-500/20 border border-rose-400/30 text-rose-200">FAILED / PENDING</div>
          <div className="p-2 rounded bg-emerald-500/20 border border-emerald-400/30 text-emerald-300">₹0 RECOVERED</div>
          <div className="p-2 rounded bg-indigo-500/20 border border-indigo-400/30 text-indigo-200">IDEMPOTENT</div>
          <div className="p-2 rounded bg-slate-800 border border-slate-700 text-slate-300">WAIT WEBHOOK</div>
          <div className="p-2 rounded bg-slate-800 border border-slate-700 text-slate-300">PAYMENT CONFIRMED</div>
          <div className="p-2 rounded bg-emerald-600 text-white">RECOVERY SUCCESS</div>
        </div>

        {failureCampaign && (
          <div className="mt-6 pt-4 border-t border-rose-500/20 bg-white/5 rounded-lg p-4 text-slate-200 text-xs">
            <p className="font-bold text-rose-300">Failure Simulation Result Verified:</p>
            <p className="mt-1 text-2xs text-slate-300">
              Campaign ID: {failureCampaign.id} &middot; Status: <strong className="text-rose-400">{failureCampaign.status}</strong> &middot; Revenue Recovered: <strong className="text-emerald-400">{formatCurrency(failureCampaign.revenue_recovered)}</strong>
            </p>
          </div>
        )}
      </div>

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

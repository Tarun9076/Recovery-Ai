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

interface LogEntry {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
  at: string;
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
  return (
    <label className="block text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <select
        className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Let RecoverAI pick the best candidate</option>
        {candidates.map((c) => (
          <option key={c.payment_id} value={c.payment_id}>
            {formatCurrency(c.amount)} &middot; {formatPercent(c.recovery_probability)} recovery probability &middot;{" "}
            {c.payment_method}
            {c.failure_category ? ` · ${c.failure_category}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function Step({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-100 py-4 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm font-medium text-slate-900">{title}</p>
        <p className="mt-0.5 text-xs text-slate-500">{description}</p>
      </div>
      <div className="shrink-0">{action}</div>
    </div>
  );
}

function ActionButton({
  onClick,
  disabled,
  loading,
  children,
  variant = "primary",
}: {
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  children: React.ReactNode;
  variant?: "primary" | "danger" | "secondary";
}) {
  const base = "rounded-md px-3.5 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40";
  const variants: Record<string, string> = {
    primary: "bg-slate-900 text-white hover:bg-slate-700",
    danger: "bg-red-600 text-white hover:bg-red-500",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
  };
  return (
    <button className={`${base} ${variants[variant]}`} onClick={onClick} disabled={disabled || loading}>
      {loading ? "Working…" : children}
    </button>
  );
}

export function DemoControlPanel({ initialCandidates }: { initialCandidates: RecoveryOpportunity[] }) {
  const [candidates, setCandidates] = useState(initialCandidates);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);

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

  const executedAction = campaign?.actions.find((a) => a.status === "EXECUTED");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <p className="text-sm font-medium text-slate-900">Reset demo</p>
          <p className="text-xs text-slate-500">
            Clears every campaign/investigation/webhook record. The underlying synthetic dataset is never touched.
          </p>
        </div>
        <ActionButton
          variant="danger"
          loading={loadingKey === "reset"}
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
                getHighRecoveryOpportunities(15)
                  .then((res) => {
                    setCandidates(res);
                    setSelectedPaymentId(res[0]?.payment_id ?? "");
                  })
                  .catch(() => {});
                return `Cleared ${counts.recovery_campaigns} campaigns, ${counts.recovery_actions} actions, ${counts.webhook_events} webhook events, ${counts.audit_logs} audit logs.`;
              },
            )
          }
        >
          Reset Demo
        </ActionButton>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">1. Run Investigation</h2>
        <p className="mt-1 text-sm text-slate-500">
          The AI agent runs a deterministic pipeline over the real data, then asks an LLM once, only for prose.
        </p>
        <textarea
          className="mt-3 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900"
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="mt-3">
          <ActionButton
            loading={loadingKey === "investigate"}
            disabled={!question.trim()}
            onClick={() =>
              run(
                "investigate",
                "Run Investigation",
                () => postInvestigate(question),
                (res) => {
                  setInvestigation(res);
                  return `${res.findings.length} finding(s), ${res.recommendations.length} recommendation(s), ${formatCurrency(res.revenue_at_risk)} at risk.`;
                },
              )
            }
          >
            Run Investigation
          </ActionButton>
        </div>

        {investigation && (
          <div className="mt-4 rounded-md bg-slate-50 p-4 text-sm">
            <p className="text-slate-700">{investigation.summary}</p>
            {investigation.findings.map((f, i) => (
              <div key={i} className="mt-3 border-t border-slate-200 pt-3">
                <p className="font-medium text-slate-900">
                  {f.finding} <span className="text-xs uppercase text-slate-400">({f.severity})</span>
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatCurrency(f.revenue_at_risk)} at risk across {f.affected_payment_count} payments &middot;{" "}
                  {formatCurrency(f.estimated_recoverable_revenue)} estimated recoverable
                </p>
              </div>
            ))}
            {investigation.recommendations.map((r, i) => (
              <div key={i} className="mt-3 border-t border-slate-200 pt-3">
                <p className="font-medium text-slate-900">{r.recommended_action.replace(/_/g, " ")}</p>
                <p className="mt-1 text-xs text-slate-500">{r.reason}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">2-4. Recovery Campaign</h2>
        <p className="mt-1 text-sm text-slate-500">
          Generate, approve, and execute a real campaign against one failed payment -- every number is
          recomputed fresh by the backend, never trusted from the browser.
        </p>

        <div className="mt-3">
          <PaymentPicker
            candidates={candidates}
            value={selectedPaymentId}
            onChange={setSelectedPaymentId}
            label="Target payment"
          />
        </div>

        <div className="mt-4">
          <Step
            title="Generate Recovery Campaign"
            description="Runs the real ML prediction + policy engine, creates recovery_actions."
            action={
              <ActionButton
                loading={loadingKey === "create"}
                disabled={!selectedPaymentId}
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
                      return `Campaign ${detail.id.slice(0, 8)} created -- ${detail.target_count} payment(s), ${formatCurrency(detail.expected_recovery)} expected recovery.`;
                    },
                  )
                }
              >
                Generate Campaign
              </ActionButton>
            }
          />

          <Step
            title="Approve Campaign"
            description="Merchant sign-off. Re-validates policy before approving -- does not execute yet."
            action={
              <ActionButton
                loading={loadingKey === "approve"}
                disabled={!campaign || campaign.status !== "PENDING_APPROVAL"}
                onClick={() =>
                  run(
                    "approve",
                    "Approve Campaign",
                    () => postApproveCampaign(campaign!.id),
                    (detail) => {
                      setCampaign(detail);
                      return `Campaign ${detail.id.slice(0, 8)} approved.`;
                    },
                  )
                }
              >
                Approve
              </ActionButton>
            }
          />

          <Step
            title="Execute Campaign"
            description="Creates a real payment link via the provider. This alone is never counted as recovered revenue."
            action={
              <ActionButton
                loading={loadingKey === "execute"}
                disabled={!campaign || campaign.status !== "APPROVED"}
                onClick={() =>
                  run(
                    "execute",
                    "Execute Campaign",
                    () => postExecuteCampaign(campaign!.id),
                    (detail) => {
                      setCampaign(detail);
                      return `Campaign ${detail.id.slice(0, 8)} executed -- ${detail.actions.filter((a) => a.status === "EXECUTED").length} link(s) created.`;
                    },
                  )
                }
              >
                Execute
              </ActionButton>
            }
          />

          <Step
            title="Simulate Customer Payment"
            description="Feeds a self-signed payment_link.paid payload through the real webhook-verification pipeline."
            action={
              <ActionButton
                loading={loadingKey === "simulate-payment"}
                disabled={!executedAction}
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
                      return `Webhook processed: ${result.status}${result.amount_paid ? ` -- ${formatCurrency(result.amount_paid)} paid` : ""}.`;
                    },
                  )
                }
              >
                Simulate Payment
              </ActionButton>
            }
          />
        </div>

        {simResult && (
          <p className="mt-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
            Simulated webhook result: <strong>{simResult.status}</strong>
            {simResult.amount_paid ? ` -- ${formatCurrency(simResult.amount_paid)} confirmed paid.` : "."}
          </p>
        )}

        {campaign && (
          <div className="mt-6">
            <CampaignDetailView campaign={campaign} />
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">Simulate Provider Failure</h2>
        <p className="mt-1 text-sm text-slate-500">
          Runs the same create -&gt; approve -&gt; execute pipeline, but forces the provider call to fail like a
          gateway timeout. Shows the real failure path: a FAILED action, an audit entry, zero revenue recorded as
          recovered, and the payment still eligible for a fresh retry.
        </p>
        <div className="mt-3">
          <PaymentPicker
            candidates={candidates}
            value={failurePaymentId}
            onChange={setFailurePaymentId}
            label="Target payment (pick a different one than above)"
          />
        </div>
        <div className="mt-3">
          <ActionButton
            variant="secondary"
            loading={loadingKey === "provider-failure"}
            onClick={() =>
              run(
                "provider-failure",
                "Simulate Provider Failure",
                () => postSimulateProviderFailure(failurePaymentId || undefined),
                (detail) => {
                  setFailureCampaign(detail);
                  return `Campaign ${detail.id.slice(0, 8)} ended ${detail.status} -- ₹0 recorded as recovered, payment still retryable.`;
                },
              )
            }
          >
            Simulate Provider Failure
          </ActionButton>
        </div>

        {failureCampaign && (
          <div className="mt-6">
            <CampaignDetailView campaign={failureCampaign} />
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">Activity Log</h2>
        {log.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">Nothing run yet this session.</p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm">
            {log.map((entry) => (
              <li key={entry.id} className="flex items-start gap-2">
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${entry.ok ? "bg-emerald-500" : "bg-red-500"}`} />
                <div>
                  <p className="text-slate-800">
                    <span className="font-medium">{entry.label}</span>{" "}
                    <span className="text-xs text-slate-400">{formatDateTime(entry.at)}</span>
                  </p>
                  <p className={entry.ok ? "text-slate-500" : "text-red-600"}>{entry.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

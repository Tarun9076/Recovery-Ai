"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  getOpportunity,
  getCampaign,
  postCreateCampaign,
  postApproveCampaign,
  postExecuteCampaign,
  postSimulatePayment,
  postRejectCampaign,
  type RecoveryOpportunityDetail,
  type CampaignDetail,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";
import { StatusBadge } from "@/components/StatusBadge";
import { PolicyCheck } from "@/components/PolicyCheck";

// The only action the current PaymentProvider abstraction can actually
// execute -- mirrors app/services/action_selector.EXECUTABLE_ACTIONS on the
// backend. campaign_service.create_campaign rejects (422) any campaign
// whose only candidate has a non-executable recommendation, so the frontend
// must check this before offering to approve/execute/reject one.
const EXECUTABLE_ACTION = "PAYMENT_LINK";
import { RecoveryTimeline } from "@/components/RecoveryTimeline";
import {
  ArrowLeft,
  Sparkles,
  ShieldCheck,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileText,
  Clock,
  RefreshCw,
  Send,
  CreditCard,
  ChevronRight,
} from "lucide-react";

export default function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const paymentId = resolvedParams.id;
  const router = useRouter();

  const [opp, setOpp] = useState<RecoveryOpportunityDetail | null>(null);
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const data = await getOpportunity(paymentId);
      setOpp(data);
    } catch (err) {
      setError("Could not load opportunity details from the backend.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [paymentId]);

  async function handleApproveAndExecute() {
    if (!opp) return;
    setActionLoading("approve");
    setStatusMessage(null);
    setActionError(null);
    try {
      // 1. Create campaign
      const created = await postCreateCampaign([opp.payment_id], `Recovery for PAY_${opp.payment_id.slice(0, 8)}`);

      // 2. Approve campaign
      const approved = await postApproveCampaign(created.campaign.id);

      // 3. Execute campaign
      const executed = await postExecuteCampaign(approved.id);

      setCampaign(executed);
      setStatusMessage("Recovery action approved and executed! Razorpay payment link dispatched.");
    } catch (err: any) {
      setActionError(`Failed to execute recovery action: ${err.message || String(err)}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleSimulateWebhook() {
    if (!campaign) return;
    const executedAction = campaign.actions.find((a) => a.status === "EXECUTED" || a.status === "AUTHORIZED");
    if (!executedAction) return;

    setActionLoading("simulate");
    setActionError(null);
    try {
      await postSimulatePayment(executedAction.id);
      const refreshed = await getCampaign(campaign.id);
      setCampaign(refreshed);
      setStatusMessage("Payment webhook confirmed! Revenue successfully recovered & recorded.");
    } catch (err: any) {
      setActionError(`Simulate payment failed: ${err.message || String(err)}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleReject() {
    if (actionLoading) return;
    setActionLoading("reject");
    setStatusMessage(null);
    setActionError(null);
    try {
      let targetCampaignId = campaign?.id;

      // If no campaign exists yet, create one so we can reject it — this
      // records the merchant's explicit rejection decision in the backend
      // audit trail rather than silently discarding the opportunity.
      if (!targetCampaignId) {
        if (!opp) return;
        const created = await postCreateCampaign(
          [opp.payment_id],
          `Recovery for PAY_${opp.payment_id.slice(0, 8)}`,
        );
        targetCampaignId = created.campaign.id;
      }

      const rejected = await postRejectCampaign(
        targetCampaignId,
        "merchant",
        "Merchant declined recovery action via dashboard",
      );
      setCampaign(rejected);
      setStatusMessage(
        `Recovery campaign rejected. Status: ${rejected.status}. Decision recorded in audit trail.`,
      );
    } catch (err: any) {
      setActionError(`Rejection failed: ${err.message || String(err)}`);
    } finally {
      setActionLoading(null);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-12 text-center text-sm text-slate-500">
        <RefreshCw className="mx-auto h-8 w-8 animate-spin text-indigo-600 mb-3" />
        Analyzing failed payment & generating AI investigation...
      </main>
    );
  }

  if (error || !opp) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <Link href="/opportunities" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to Opportunities
        </Link>
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-800">
          <h3 className="font-bold flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-rose-600" /> Error Loading Opportunity
          </h3>
          <p className="mt-1 text-xs">{error ?? "Opportunity not found."}</p>
        </div>
      </main>
    );
  }

  const confidenceLabel = opp.recovery_probability >= 0.7 ? "HIGH" : opp.recovery_probability >= 0.4 ? "MEDIUM" : "LOW";
  // create_campaign (backend) rejects any campaign whose only candidate has
  // a non-executable recommendation with a 422 -- checking this client-side
  // is what prevents that confusing error rather than fixing anything about
  // the backend's (correct) fail-closed behavior.
  const isExecutable = opp.recommended_action === EXECUTABLE_ACTION;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      {/* Top Breadcrumb & Actions */}
      <div className="flex items-center justify-between">
        <Link
          href="/opportunities"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> Back to AI Recovery Opportunities
        </Link>
        <StatusBadge status={campaign?.status ?? "PENDING"} />
      </div>

      {/* HEADER CARD */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-slate-100 pb-5">
          <div>
            <div className="flex items-center gap-2 text-2xs font-mono font-bold text-indigo-600 uppercase tracking-wider">
              <Sparkles className="h-3.5 w-3.5" /> RECOVERY OPPORTUNITY DETAIL
            </div>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
              PAY_{opp.payment_id.slice(0, 12)}
            </h1>
            <p className="mt-1 text-xs text-slate-500">
              Customer: <span className="font-mono text-slate-800 font-semibold">{opp.customer_id ? `C-${opp.customer_id.slice(0, 8)}` : "—"}</span> &middot; Method: <span className="font-semibold text-slate-800">{opp.payment_method}</span> &middot; Failure Category: <span className="font-semibold text-slate-800">{opp.failure_category ?? "—"}</span> &middot; Failed at {formatDateTime(opp.created_at)}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              Model: {opp.model_name || "—"}{opp.model_version ? ` (v${opp.model_version})` : ""}
            </span>
          </div>
        </div>

        {/* PROMINENT RECOVERY METRICS */}
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-lg bg-emerald-50/60 border border-emerald-200/80 p-4">
            <span className="text-2xs font-bold uppercase tracking-wider text-emerald-800">
              Recovery Probability
            </span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold text-emerald-700">
              {formatPercent(opp.recovery_probability)}
            </p>
          </div>

          <div className="rounded-lg bg-slate-50 border border-slate-200 p-4">
            <span className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Expected Recovery
            </span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold text-slate-900">
              {formatCurrency(opp.expected_recovery)}
            </p>
          </div>

          <div className="rounded-lg bg-rose-50/60 border border-rose-200/80 p-4">
            <span className="text-2xs font-bold uppercase tracking-wider text-rose-800">
              Revenue at Risk
            </span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold text-rose-700">
              {formatCurrency(opp.amount)}
            </p>
          </div>

          <div className="rounded-lg bg-indigo-50/60 border border-indigo-200/80 p-4">
            <span className="text-2xs font-bold uppercase tracking-wider text-indigo-800">
              AI Score Confidence
            </span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold text-indigo-700">
              {confidenceLabel}
            </p>
          </div>
        </div>
      </div>

      {/* AI INVESTIGATION CARD */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-6">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-indigo-50 p-2 text-indigo-600">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900">AI Root Cause Investigation</h3>
              <p className="text-xs text-slate-500">ML SHAP factor attribution and rationale</p>
            </div>
          </div>
          <span className="text-2xs font-mono bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded font-bold border border-indigo-200">
            DETERMINISTIC ANALYSIS
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Root Cause & Rationale — sourced from backend RecoveryActionSelector */}
          <div className="space-y-4">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Failure Category</h4>
              <p className="mt-1 text-sm font-mono font-semibold text-slate-900 bg-slate-50 p-3 rounded-lg border border-slate-200">
                {opp.failure_category ?? "Unknown"}
              </p>
            </div>

            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">AI Rationale (from backend)</h4>
              <p className="mt-1 text-sm text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-200 leading-relaxed">
                {opp.reason ?? "No rationale provided by the backend action selector."}
              </p>
            </div>
          </div>

          {/* Evidence Used / SHAP Factors */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Evidence Used (SHAP Factors)</h4>
            {opp.top_factors && opp.top_factors.length > 0 ? (
              <div className="space-y-2">
                {opp.top_factors.map((f, idx) => (
                  <div key={idx} className="flex items-center justify-between rounded-lg bg-slate-50 p-2.5 border border-slate-100 text-xs">
                    <span className="font-mono text-slate-800 font-medium">{f.factor}</span>
                    <span className={`font-semibold ${f.direction === "increases_probability" ? "text-emerald-700" : "text-amber-700"}`}>
                      {f.direction === "increases_probability" ? "+" : "-"}{Math.abs(f.shap_value).toFixed(3)} SHAP
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500">No factor attribution returned by the backend for this prediction.</p>
            )}
          </div>
        </div>
      </div>

      {/* RECOMMENDED RECOVERY ACTION & POLICY CHECK GRID */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recommended Action Card */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Zap className="h-4 w-4 text-indigo-600" />
                Recommended Recovery Action
              </h3>
              <span className="text-2xs font-semibold uppercase bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">
                AI OPTIMIZED
              </span>
            </div>

            <div className="mt-4 space-y-3 text-xs sm:text-sm">
              <div>
                <span className="text-2xs font-bold uppercase text-slate-400">Action (from backend)</span>
                {/* opp.recommended_action comes from RecoveryActionSelector — the same
                    engine campaign_service uses. Never guessed client-side. */}
                <p className="font-bold text-slate-900 text-base">
                  {opp.recommended_action
                    ? opp.recommended_action.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c: string) => c.toUpperCase())
                    : "—"}
                </p>
              </div>
              <div>
                <span className="text-2xs font-bold uppercase text-slate-400">Expected Recovery Value</span>
                <p className="font-extrabold text-emerald-700 text-lg">{formatCurrency(opp.expected_recovery)}</p>
              </div>
              <div>
                <span className="text-2xs font-bold uppercase text-slate-400">Reason (from backend)</span>
                {/* opp.reason is the policy rationale from RecoveryActionSelector.
                    Never hardcoded — comes directly from the real per-payment decision. */}
                <p className="text-slate-700 font-medium">
                  {opp.reason ?? "No rationale returned by the backend."}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Policy Check Component -- both rules are derived from real
            backend fields (segment, recommended_action), never hardcoded. */}
        <PolicyCheck
          recoveryProbability={opp.recovery_probability}
          meetsRecoveryThreshold={opp.segment !== "LOW_RECOVERY"}
          recommendedAction={opp.recommended_action}
          isExecutable={isExecutable}
        />
      </div>

      {/* MERCHANT CONTROL ACTION BAR */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h3 className="text-base font-bold text-slate-900">Merchant Governance Control</h3>
            <p className="text-xs text-slate-500">
              RecoverAI requires explicit merchant sign-off before initiating provider execution.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Reject calls POST /api/recovery/campaigns/{id}/reject — real backend record.
                Disabled when non-executable: creating a campaign at all (a
                prerequisite even for rejecting one) is rejected by the
                backend for a recommendation the current provider can't act
                on -- see isExecutable above. */}
            <button
              onClick={handleReject}
              disabled={!!actionLoading || !isExecutable || campaign?.status === "REJECTED" || campaign?.status === "COMPLETED"}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-all"
            >
              {actionLoading === "reject" ? "Rejecting..." : "Reject Recovery"}
            </button>

            {!isExecutable && !campaign ? (
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 px-4 py-2 text-xs font-bold text-amber-800 border border-amber-200">
                <AlertTriangle className="h-4 w-4" /> Not auto-executable — requires manual handling
              </span>
            ) : !campaign || campaign.status === "PENDING_APPROVAL" ? (
              <button
                onClick={handleApproveAndExecute}
                disabled={actionLoading === "approve"}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 disabled:opacity-40 transition-all"
              >
                {actionLoading === "approve" ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Approve &amp; Execute Recovery
              </button>
            ) : campaign.actions.some((a) => a.status === "EXECUTED") && campaign.revenue_recovered === 0 ? (
              <button
                onClick={handleSimulateWebhook}
                disabled={actionLoading === "simulate"}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-emerald-500 disabled:opacity-40 transition-all"
              >
                {actionLoading === "simulate" ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                Simulate Customer Payment Webhook
              </button>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-700 border border-emerald-200">
                <CheckCircle2 className="h-4 w-4" /> Recovery Complete ({formatCurrency(campaign.revenue_recovered)})
              </span>
            )}
          </div>
        </div>

        {!isExecutable && !campaign && (
          <p className="text-2xs text-slate-500">
            RecoverAI recommends <strong>{opp.recommended_action ? opp.recommended_action.replace(/_/g, " ").toLowerCase() : "manual review"}</strong> for
            this payment. Only Payment Link recommendations can be auto-dispatched by the current provider
            integration — this one needs to be actioned outside RecoverAI's automated workflow.
          </p>
        )}

        {statusMessage && (
          <div className="rounded-lg bg-indigo-50 border border-indigo-200 p-3 text-xs font-semibold text-indigo-800">
            {statusMessage}
          </div>
        )}

        {actionError && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs font-semibold text-rose-800">
            {actionError}
          </div>
        )}
      </div>

      {/* RECOVERY TIMELINE */}
      <RecoveryTimeline
        campaignStatus={campaign?.status ?? "PENDING_APPROVAL"}
        recoveredAmount={campaign?.revenue_recovered ?? null}
        createdAt={opp.created_at}
      />
    </main>
  );
}

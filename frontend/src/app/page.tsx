import NextLink from "next/link";
import {
  getDashboardSummary,
  getRecoveryMetrics,
  getRecoveryOpportunities,
  postAnalyzeRecovery,
  type DashboardSummary,
  type RecoveryMetricsRead,
  type RecoveryOpportunityDetail,
} from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { KPICard } from "@/components/KPICard";
import { AIInsightCard } from "@/components/AIInsightCard";
import { FailureTrendChart } from "@/components/FailureTrendChart";
import {
  DollarSign,
  TrendingUp,
  ShieldAlert,
  CheckCircle,
  Percent,
  ArrowUpRight,
  ChevronRight,
  Activity,
  Layers,
  Sparkles,
  Zap,
} from "lucide-react";

function formatAction(value: string): string {
  return value.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export default async function Home() {
  let summary: DashboardSummary | null = null;
  let metrics: RecoveryMetricsRead | null = null;
  let opportunities: RecoveryOpportunityDetail[] = [];
  let error: string | null = null;

  try {
    let [summaryRes, metricsRes, oppsRes] = await Promise.all([
      getDashboardSummary(),
      getRecoveryMetrics(),
      getRecoveryOpportunities("HIGH_RECOVERY", 6, 0),
    ]);

    if (oppsRes.items.length === 0) {
      try {
        await postAnalyzeRecovery();
        const refreshed = await getRecoveryOpportunities("HIGH_RECOVERY", 6, 0);
        oppsRes = refreshed;
      } catch {}
    }

    summary = summaryRes;
    metrics = metricsRes;
    opportunities = oppsRes.items;
  } catch (err) {
    error = "Could not reach the RecoverAI API backend. Ensure the backend server is running.";
  }

  // Real data derived from the fetched summary/opportunities above -- not
  // invented text. Picks the largest failure category and the most common
  // real backend recommendation among the fetched high-recovery candidates.
  const topFailureCategory = summary?.failure_category_breakdown.length
    ? [...summary.failure_category_breakdown].sort((a, b) => b.count - a.count)[0]
    : null;

  const actionCounts = new Map<string, number>();
  for (const opp of opportunities) {
    if (!opp.recommended_action) continue;
    actionCounts.set(opp.recommended_action, (actionCounts.get(opp.recommended_action) ?? 0) + 1);
  }
  const topRecommendedAction = [...actionCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/80 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-2xs font-mono font-bold uppercase tracking-wider text-slate-500">
              LIVE RECOVERY ENGINE ACTIVE
            </span>
          </div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            RecoverAI Dashboard
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-500">
            AI-powered recovery of revenue slipping through failed payments.
          </p>
        </div>

        <div className="flex items-center gap-3 mt-4 sm:mt-0">
          <NextLink
            href="/opportunities"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs sm:text-sm font-semibold text-white shadow-xs hover:bg-indigo-500 transition-all"
          >
            <Zap className="h-4 w-4" />
            View All Opportunities
          </NextLink>
        </div>
      </div>

      {error || !summary || !metrics ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-800 shadow-xs">
          <div className="flex items-center gap-2 font-semibold">
            <ShieldAlert className="h-5 w-5 text-rose-600" />
            Backend Connection Error
          </div>
          <p className="mt-1 text-xs text-rose-600">{error}</p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* PRIMARY KPI CARDS (Row 1: Business Value) */}
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KPICard
              title="Revenue at Risk"
              value={formatCurrency(metrics.revenue_at_risk)}
              subtitle="Exposed to payment failures"
              icon={ShieldAlert}
              variant="danger"
              highlight
            />
            <KPICard
              title="Recoverable Revenue"
              value={formatCurrency(metrics.recoverable_revenue)}
              subtitle="High & medium ML recovery score"
              icon={Sparkles}
              variant="info"
              highlight
            />
            <KPICard
              title="Recovered Revenue"
              value={formatCurrency(metrics.revenue_recovered)}
              subtitle="Verified webhook confirmed"
              icon={CheckCircle}
              variant="success"
              highlight
            />
            <KPICard
              title="Recovery Rate"
              value={formatPercent(metrics.recovery_rate)}
              subtitle="Actual recovered / Recoverable"
              icon={Percent}
              variant="success"
              highlight
            />
          </section>

          {/* PROMINENT AI ALERT / OPPORTUNITY CARD -- every field below is
              derived from data already fetched from the backend above
              (summary.failure_category_breakdown, metrics, opportunities),
              never invented text (spec: no fabricated AI findings). */}
          {topFailureCategory && (
            <section>
              <AIInsightCard
                anomalyTitle={`${formatAction(topFailureCategory.failure_category)} failures are the top driver of revenue at risk`}
                revenueAtRisk={metrics.revenue_at_risk}
                recoverableRevenue={metrics.recoverable_revenue}
                affectedPayments={topFailureCategory.count}
                likelyCause={`${formatNumber(topFailureCategory.count)} failed payments were categorized as ${formatAction(topFailureCategory.failure_category)} -- the largest failure category in the current dataset window`}
                recommendedAction={topRecommendedAction ? formatAction(topRecommendedAction) : "See per-payment recommendations below"}
              />
            </section>
          )}

          {/* REVENUE RISK & RECOVERY CHART */}
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-indigo-600" />
                  Revenue Risk & Recovery
                </h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Revenue exposed to payment failures and daily payment volume across the dataset window.
                </p>
              </div>
              <span className="text-2xs font-mono font-medium text-slate-400 bg-slate-100 px-2.5 py-1 rounded">
                Trend Window: {summary.failure_trend.length} Days
              </span>
            </div>

            <div className="mt-6">
              <FailureTrendChart points={summary.failure_trend} />
            </div>
          </section>

          {/* AI RECOVERY OPPORTUNITIES TABLE PREVIEW */}
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div>
                <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Layers className="h-4 w-4 text-indigo-600" />
                  Highest-Value AI Recovery Opportunities
                </h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  ML-prioritized failed payments awaiting merchant approval or execution.
                </p>
              </div>

              <NextLink
                href="/opportunities"
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1"
              >
                View all ({opportunities.length}+) <ChevronRight className="h-3.5 w-3.5" />
              </NextLink>
            </div>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs sm:text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                    <th className="py-3 px-3">Customer</th>
                    <th className="py-3 px-3">Payment ID</th>
                    <th className="py-3 px-3">Amount at Risk</th>
                    <th className="py-3 px-3">Recovery Probability</th>
                    <th className="py-3 px-3">Failure Reason</th>
                    <th className="py-3 px-3">Recommended Action</th>
                    <th className="py-3 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium">
                  {opportunities.map((opp) => (
                    <tr key={opp.payment_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3 px-3 font-mono text-slate-600">
                        {opp.customer_id ? `C-${opp.customer_id.slice(0, 6)}` : "—"}
                      </td>
                      <td className="py-3 px-3 font-mono text-slate-900 font-semibold">
                        PAY_{opp.payment_id.slice(0, 8)}
                      </td>
                      <td className="py-3 px-3 font-bold text-rose-600">
                        {formatCurrency(opp.amount)}
                      </td>
                      <td className="py-3 px-3">
                        <span className="inline-flex items-center gap-1 font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          {formatPercent(opp.recovery_probability)}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-slate-600">
                        {opp.failure_category ?? "—"}
                      </td>
                      <td className="py-3 px-3 text-slate-800 font-semibold">
                        {/* Always the backend's own decision (RecoveryActionSelector) --
                            never guessed client-side. A qualifying payment link, an
                            alternative-method suggestion, a defer, a manual-review flag,
                            etc. all come from the same real per-payment policy decision
                            the campaign workflow itself would use. */}
                        {opp.recommended_action ? formatAction(opp.recommended_action) : "—"}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <NextLink
                          href={`/opportunities/${opp.payment_id}`}
                          className="inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1 text-2xs font-semibold text-white hover:bg-slate-800 transition-colors"
                        >
                          Review <ArrowUpRight className="h-3 w-3" />
                        </NextLink>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* SECONDARY SECTION: PAYMENT HEALTH */}
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs">
            <div className="border-b border-slate-100 pb-4">
              <h2 className="text-base font-bold text-slate-900">Payment Health Overview</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Secondary infrastructure metrics sourced directly from merchant gateway logs.
              </p>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <KPICard
                title="Total Payments"
                value={formatNumber(summary.total_payments)}
                variant="neutral"
              />
              <KPICard
                title="Successful Payments"
                value={formatNumber(summary.successful_payments)}
                variant="success"
              />
              <KPICard
                title="Failed Payments"
                value={formatNumber(summary.failed_payments)}
                variant="danger"
              />
              <KPICard
                title="Failure Rate"
                value={formatPercent(summary.failure_rate)}
                variant="danger"
              />
              <KPICard
                title="Failed Transaction Value"
                value={formatCurrency(summary.failed_transaction_value)}
                variant="danger"
              />
            </div>

            {/* Failure Category Breakdown */}
            <div className="mt-8">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
                Failure Category Breakdown
              </h3>
              <div className="overflow-x-auto rounded-lg border border-slate-100">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="bg-slate-50 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                      <th className="py-2.5 px-4">Failure Type</th>
                      <th className="py-2.5 px-4">Failed Payments</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-medium">
                    {summary.failure_category_breakdown.map((row) => (
                      <tr key={row.failure_category} className="hover:bg-slate-50/50">
                        <td className="py-2.5 px-4 font-mono font-bold text-slate-800">
                          {row.failure_category}
                        </td>
                        <td className="py-2.5 px-4 text-slate-700">
                          {formatNumber(row.count)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

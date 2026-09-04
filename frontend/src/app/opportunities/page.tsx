"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getRecoveryOpportunities,
  getRecoveryMetrics,
  postAnalyzeRecovery,
  type RecoveryOpportunityDetail,
  type RecoveryMetricsRead,
} from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { KPICard } from "@/components/KPICard";
import {
  Layers,
  Search,
  ArrowUpDown,
  ArrowUpRight,
  Sparkles,
  CheckCircle,
  RefreshCw,
  Zap,
  Play,
} from "lucide-react";

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<RecoveryOpportunityDetail[]>([]);
  const [metrics, setMetrics] = useState<RecoveryMetricsRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters & Sorting state
  const [segmentFilter, setSegmentFilter] = useState<string>("ALL");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [sortBy, setSortBy] = useState<"expected" | "amount" | "probability">("expected");

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      let [oppsRes, metricsRes] = await Promise.all([
        getRecoveryOpportunities("ALL", 100, 0),
        getRecoveryMetrics(),
      ]);

      // If predictions have not been run against DB yet, auto-trigger the analysis engine
      if (oppsRes.items.length === 0) {
        try {
          await postAnalyzeRecovery();
          oppsRes = await getRecoveryOpportunities("ALL", 100, 0);
          metricsRes = await getRecoveryMetrics();
        } catch {
          // fallback
        }
      }

      setOpportunities(oppsRes.items);
      setMetrics(metricsRes);
    } catch (err) {
      setError("Could not load recovery opportunities from backend.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRunAnalysis() {
    setAnalyzing(true);
    try {
      await postAnalyzeRecovery();
      await loadData();
    } catch (err) {
      setError("Failed to run AI analysis pipeline.");
    } finally {
      setAnalyzing(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  // Filtered and sorted dataset
  const filtered = opportunities
    .filter((opp) => {
      // Segment filter
      if (segmentFilter === "HIGH_PROBABILITY" && opp.recovery_probability < 0.7) return false;
      if (segmentFilter === "HIGH_RECOVERY" && opp.segment !== "HIGH_RECOVERY") return false;

      // Status filter
      if (statusFilter === "AWAITING_APPROVAL") return true;
      if (statusFilter === "EXECUTED" && opp.segment !== "EXECUTED") return false;
      if (statusFilter === "RECOVERED" && opp.segment !== "RECOVERED") return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const pid = opp.payment_id.toLowerCase();
        const cid = (opp.customer_id ?? "").toLowerCase();
        const cat = (opp.failure_category ?? "").toLowerCase();
        return pid.includes(q) || cid.includes(q) || cat.includes(q);
      }

      return true;
    })
    .sort((a, b) => {
      if (sortBy === "amount") return b.amount - a.amount;
      if (sortBy === "probability") return b.recovery_probability - a.recovery_probability;
      return b.expected_recovery - a.expected_recovery;
    });

  const recoverableRevenueTotal = opportunities.reduce((acc, curr) => acc + curr.expected_recovery, 0);

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/80 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
              <Sparkles className="h-3 w-3" /> CENTRAL OPERATIONS SCREEN
            </span>
          </div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
            AI Recovery Opportunities
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-500">
            Review revenue at risk and approve recovery actions recommended by RecoverAI.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleRunAnalysis}
            disabled={analyzing || loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 disabled:opacity-50 transition-all"
          >
            <Play className={`h-3.5 w-3.5 ${analyzing ? "animate-spin" : ""}`} />
            {analyzing ? "Analyzing DB Payments..." : "Run AI Analysis Pipeline"}
          </button>
          
          <button
            onClick={loadData}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* TOP SUMMARY STATS */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title="Total Opportunities"
          value={formatNumber(opportunities.length)}
          subtitle="Scored payment failure candidates"
          icon={Layers}
          variant="info"
        />
        <KPICard
          title="Recoverable Revenue"
          value={formatCurrency(Math.max(metrics?.recoverable_revenue ?? 0, recoverableRevenueTotal))}
          subtitle="Estimated AI recoverable value"
          icon={Sparkles}
          variant="success"
          highlight
        />
        <KPICard
          title="Verified Recovered"
          value={formatCurrency(metrics?.revenue_recovered ?? 0)}
          subtitle="Confirmed webhook payments"
          icon={CheckCircle}
          variant="success"
        />
      </div>

      {/* FILTER & SORT CONTROLS */}
      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          {/* Segment Filter Tabs */}
          <div className="flex flex-wrap gap-1.5">
            {[
              { id: "ALL", label: "All Opportunities" },
              { id: "HIGH_PROBABILITY", label: "High Probability (>70%)" },
              { id: "HIGH_RECOVERY", label: "High Segment" },
              { id: "AWAITING_APPROVAL", label: "Awaiting Approval" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSegmentFilter(tab.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
                  segmentFilter === tab.id
                    ? "bg-slate-900 text-white shadow-xs"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search & Sort Dropdowns */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <div className="relative flex-1 sm:w-64">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="Search payment ID or cause..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-1.5 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-2">
              <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 focus:border-indigo-500 focus:outline-none"
              >
                <option value="expected">Sort: Expected Recovery</option>
                <option value="amount">Sort: Amount at Risk</option>
                <option value="probability">Sort: Recovery Probability</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* OPPORTUNITIES TABLE */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-sm text-slate-500">
            <RefreshCw className="mx-auto h-6 w-6 animate-spin text-indigo-600 mb-2" />
            Fetching live ML scored opportunities...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-sm text-rose-600">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center text-sm text-slate-500 space-y-3">
            <p className="font-semibold text-slate-700">No recovery predictions currently generated.</p>
            <p className="text-xs text-slate-400 max-w-md mx-auto">
              Click &quot;Run AI Analysis Pipeline&quot; to execute the LightGBM model against all failed payments in the database.
            </p>
            <button
              onClick={handleRunAnalysis}
              disabled={analyzing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              <Zap className="h-3.5 w-3.5" /> Analyze Failed Payments Now
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-3.5 px-4">Customer</th>
                  <th className="py-3.5 px-4">Payment ID</th>
                  <th className="py-3.5 px-4">Amount at Risk</th>
                  <th className="py-3.5 px-4">Failure Reason</th>
                  <th className="py-3.5 px-4">Recovery Probability</th>
                  <th className="py-3.5 px-4">Expected Recovery</th>
                  <th className="py-3.5 px-4">Recommended Action</th>
                  <th className="py-3.5 px-4 text-right">Review Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-medium">
                {filtered.map((opp) => (
                  <tr key={opp.payment_id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-3.5 px-4 font-mono text-slate-600">
                      {opp.customer_id ? `C-${opp.customer_id.slice(0, 6)}` : "—"}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-900 font-bold">
                      PAY_{opp.payment_id.slice(0, 8)}
                    </td>
                    <td className="py-3.5 px-4 font-bold text-rose-600">
                      {formatCurrency(opp.amount)}
                    </td>
                    <td className="py-3.5 px-4 text-slate-700 font-medium">
                      {opp.failure_category ?? "—"}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="inline-flex items-center gap-1 font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        {formatPercent(opp.recovery_probability)}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 font-bold text-slate-900">
                      {formatCurrency(opp.expected_recovery)}
                    </td>
                    <td className="py-3.5 px-4 text-slate-800 font-semibold">
                      {/* Always the backend's own decision (RecoveryActionSelector) --
                          never guessed client-side from failure category. */}
                      {opp.recommended_action
                        ? opp.recommended_action.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c: string) => c.toUpperCase())
                        : "—"}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <Link
                        href={`/opportunities/${opp.payment_id}`}
                        className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 shadow-xs transition-colors"
                      >
                        Review
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}

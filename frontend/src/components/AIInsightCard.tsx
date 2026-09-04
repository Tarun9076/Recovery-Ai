import React from "react";
import Link from "next/link";
import { Sparkles, AlertTriangle, ArrowRight, ShieldAlert, Zap } from "lucide-react";
import { formatCurrency, formatNumber } from "@/lib/format";

interface AIInsightCardProps {
  anomalyTitle?: string;
  revenueAtRisk?: number;
  recoverableRevenue?: number;
  affectedPayments?: number;
  likelyCause?: string;
  recommendedAction?: string;
  onInvestigate?: () => void;
}

export function AIInsightCard({
  anomalyTitle = "UPI Failure Spike & Gateway Timeout Detected",
  revenueAtRisk = 17200000,
  recoverableRevenue = 55500,
  affectedPayments = 1694,
  likelyCause = "Temporary UPI provider infrastructure degradation & session timeout",
  recommendedAction = "Deploy Automated Payment Link Retry to high-intent customers",
  onInvestigate,
}: AIInsightCardProps) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-indigo-200 bg-gradient-to-r from-indigo-900 via-slate-900 to-indigo-950 p-6 text-white shadow-md">
      {/* Background glowing gradient element */}
      <div className="pointer-events-none absolute -right-10 -top-10 h-48 w-48 rounded-full bg-indigo-500/10 blur-3xl" />
      
      <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500/20 px-3 py-1 text-xs font-semibold text-indigo-200 border border-indigo-400/30">
              <Sparkles className="h-3.5 w-3.5 text-indigo-300 animate-pulse" />
              AI RECOVERY OPPORTUNITY
            </span>
            <span className="inline-flex items-center gap-1 text-xs text-rose-300 font-medium">
              <AlertTriangle className="h-3.5 w-3.5" /> High Impact
            </span>
          </div>

          <h3 className="text-xl font-bold text-white tracking-tight sm:text-2xl">
            {anomalyTitle}
          </h3>

          <p className="text-xs sm:text-sm text-slate-300 max-w-2xl leading-relaxed">
            <strong className="text-indigo-200 font-medium">Likely cause:</strong> {likelyCause}
          </p>
        </div>

        <div className="shrink-0 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <Link
            href="/opportunities"
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-slate-900"
          >
            <Zap className="h-4 w-4" />
            Investigate Opportunities
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>

      <div className="mt-6 pt-5 border-t border-indigo-500/20 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg bg-white/5 p-3 border border-white/5">
          <span className="text-2xs uppercase tracking-wider text-slate-400 font-medium">Revenue at Risk</span>
          <p className="mt-1 text-lg sm:text-xl font-bold text-rose-300">
            {formatCurrency(revenueAtRisk)}
          </p>
        </div>

        <div className="rounded-lg bg-white/5 p-3 border border-white/5">
          <span className="text-2xs uppercase tracking-wider text-slate-400 font-medium">Estimated Recoverable</span>
          <p className="mt-1 text-lg sm:text-xl font-bold text-emerald-300">
            {formatCurrency(recoverableRevenue)}
          </p>
        </div>

        <div className="rounded-lg bg-white/5 p-3 border border-white/5">
          <span className="text-2xs uppercase tracking-wider text-slate-400 font-medium">Affected Payments</span>
          <p className="mt-1 text-lg sm:text-xl font-bold text-white">
            {formatNumber(affectedPayments)}
          </p>
        </div>

        <div className="rounded-lg bg-white/5 p-3 border border-white/5">
          <span className="text-2xs uppercase tracking-wider text-slate-400 font-medium">Recommended Action</span>
          <p className="mt-1 text-xs font-semibold text-indigo-200 line-clamp-1">
            {recommendedAction}
          </p>
        </div>
      </div>
    </div>
  );
}

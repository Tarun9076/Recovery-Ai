import React from "react";
import { CheckCircle2, XCircle, ShieldCheck, AlertCircle } from "lucide-react";
import { formatPercent } from "@/lib/format";

// Only two checks are shown here, and both are backed by real fields the
// backend already computed for this exact opportunity (RecoverySegment /
// RecoveryActionSelector) -- no fabricated thresholds or hardcoded "always
// passing" checks. A per-transaction amount cap and a live contact-frequency
// result don't exist as real, fetchable values on this endpoint, so rather
// than invent a threshold or default a check to "passed", those two rows are
// left out entirely.
interface PolicyCheckProps {
  recoveryProbability: number;
  meetsRecoveryThreshold: boolean;
  recommendedAction?: string;
  isExecutable: boolean;
}

export function PolicyCheck({
  recoveryProbability,
  meetsRecoveryThreshold,
  recommendedAction,
  isExecutable,
}: PolicyCheckProps) {
  const allPassed = meetsRecoveryThreshold && isExecutable;

  const rules = [
    {
      label: "Recovery probability meets merchant's minimum threshold",
      passed: meetsRecoveryThreshold,
      detail: `Model probability ${formatPercent(recoveryProbability)}`,
    },
    {
      label: "Recommended action is auto-executable by the current provider",
      passed: isExecutable,
      detail: isExecutable
        ? "Payment Link -- dispatched automatically on approval"
        : `${recommendedAction ?? "This recommendation"} requires handling outside the automated Payment Link workflow`,
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-indigo-600" />
          <h4 className="text-sm font-semibold text-slate-900">Merchant Policy Compliance Check</h4>
        </div>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            allPassed
              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
              : "bg-rose-50 text-rose-700 border border-rose-200"
          }`}
        >
          {allPassed ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" /> All Checks Passed
            </>
          ) : (
            <>
              <AlertCircle className="h-3.5 w-3.5" /> Policy Restriction
            </>
          )}
        </span>
      </div>

      <div className="mt-4 space-y-3">
        {rules.map((rule, idx) => (
          <div key={idx} className="flex items-start justify-between text-xs sm:text-sm">
            <div className="flex items-start gap-2.5">
              {rule.passed ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
              ) : (
                <XCircle className="h-4 w-4 shrink-0 text-rose-500 mt-0.5" />
              )}
              <div>
                <span className={`font-medium ${rule.passed ? "text-slate-800" : "text-rose-700"}`}>
                  {rule.label}
                </span>
                <p className="text-2xs text-slate-500 mt-0.5">{rule.detail}</p>
              </div>
            </div>
            <span
              className={`text-2xs font-semibold uppercase px-2 py-0.5 rounded ${
                rule.passed ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
              }`}
            >
              {rule.passed ? "PASS" : "FAIL"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

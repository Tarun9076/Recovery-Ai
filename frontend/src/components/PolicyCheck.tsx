import React from "react";
import { CheckCircle2, XCircle, ShieldCheck, AlertCircle } from "lucide-react";
import { formatCurrency, formatPercent } from "@/lib/format";

interface PolicyCheckProps {
  amount: number;
  maxAmountLimit?: number;
  recoveryProbability: number;
  minProbabilityThreshold?: number;
  actionAllowed?: boolean;
  contactFrequencySatisfied?: boolean;
}

export function PolicyCheck({
  amount,
  maxAmountLimit = 500000,
  recoveryProbability,
  minProbabilityThreshold = 0.40,
  actionAllowed = true,
  contactFrequencySatisfied = true,
}: PolicyCheckProps) {
  const isAmountValid = amount <= maxAmountLimit;
  const isProbabilityValid = recoveryProbability >= minProbabilityThreshold;
  const allPassed = isAmountValid && isProbabilityValid && actionAllowed && contactFrequencySatisfied;

  const rules = [
    {
      label: `Amount within merchant safety limit (Max ${formatCurrency(maxAmountLimit)})`,
      passed: isAmountValid,
      detail: `Transaction amount ${formatCurrency(amount)}`,
    },
    {
      label: `Recovery probability meets minimum threshold (${formatPercent(minProbabilityThreshold)})`,
      passed: isProbabilityValid,
      detail: `Model probability ${formatPercent(recoveryProbability)}`,
    },
    {
      label: "Recovery action type allowed by policy",
      passed: actionAllowed,
      detail: "Automated Payment Link dispatch authorized",
    },
    {
      label: "Customer contact frequency limit satisfied",
      passed: contactFrequencySatisfied,
      detail: "No previous outreach in last 24h",
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

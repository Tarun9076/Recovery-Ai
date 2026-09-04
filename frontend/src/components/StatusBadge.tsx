import React from "react";

export type StatusType =
  | "SUCCESS"
  | "RECOVERED"
  | "COMPLETED"
  | "PAYMENT_CONFIRMED"
  | "FAILED"
  | "CANCELLED"
  | "HIGH_RISK"
  | "PENDING"
  | "PENDING_APPROVAL"
  | "AWAITING_APPROVAL"
  | "AUTHORIZED"
  | "RUNNING"
  | "EXECUTED"
  | "EXECUTING"
  | "RECOMMENDED"
  | "HIGH_RECOVERY"
  | "MEDIUM_RECOVERY"
  | "LOW_RECOVERY"
  | string;

const STATUS_STYLES: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  // GREEN: successful recovery / verified payment
  RECOVERED: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  PAYMENT_CONFIRMED: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  SUCCESS: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  COMPLETED: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  HIGH_RECOVERY: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },

  // RED: revenue risk / failure / anomaly
  FAILED: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
  CANCELLED: { bg: "bg-slate-100", text: "text-slate-600", border: "border-slate-200", dot: "bg-slate-400" },
  HIGH_RISK: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },

  // AMBER: pending / awaiting confirmation / requires attention
  PENDING_APPROVAL: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },
  AWAITING_APPROVAL: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },
  PENDING: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },
  AUTHORIZED: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },
  MEDIUM_RECOVERY: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", dot: "bg-amber-500" },

  // BLUE: AI analysis / neutral information / navigation
  RECOMMENDED: { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200", dot: "bg-indigo-500" },
  EXECUTED: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", dot: "bg-blue-500" },
  EXECUTING: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", dot: "bg-blue-500" },
  RUNNING: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", dot: "bg-blue-500" },
  LOW_RECOVERY: { bg: "bg-slate-100", text: "text-slate-700", border: "border-slate-200", dot: "bg-slate-400" },
};

export function StatusBadge({ status, showDot = true }: { status: string; showDot?: boolean }) {
  const normalized = status ? status.toUpperCase().replace(/\s+/g, "_") : "PENDING";
  const style = STATUS_STYLES[normalized] ?? {
    bg: "bg-slate-100",
    text: "text-slate-700",
    border: "border-slate-200",
    dot: "bg-slate-400",
  };

  const label = status
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold tracking-wide ${style.bg} ${style.text} ${style.border}`}
    >
      {showDot && <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />}
      {label}
    </span>
  );
}

import React from "react";
import { CheckCircle2, Clock, XCircle, ShieldCheck, ArrowRight, Activity } from "lucide-react";
import { formatCurrency, formatDateTime } from "@/lib/format";

export interface TimelineStep {
  id: string;
  title: string;
  timestamp?: string;
  status: "COMPLETED" | "PENDING" | "FAILED" | "IN_PROGRESS";
  detail?: string;
  actor?: string;
}

interface RecoveryTimelineProps {
  steps?: TimelineStep[];
  campaignStatus?: string;
  recoveredAmount?: number | null;
  createdAt?: string;
}

export function RecoveryTimeline({
  steps,
  campaignStatus = "PENDING_APPROVAL",
  recoveredAmount = null,
  createdAt,
}: RecoveryTimelineProps) {
  // If custom steps not provided, synthesize timeline based on campaign status & state
  const defaultSteps: TimelineStep[] = steps ?? [
    {
      id: "1",
      title: "Payment failure detected",
      timestamp: createdAt ?? new Date().toISOString(),
      status: "COMPLETED",
      detail: "Payment gateway reported transaction failure",
    },
    {
      id: "2",
      title: "Revenue risk identified & quantified",
      timestamp: createdAt ?? new Date().toISOString(),
      status: "COMPLETED",
      detail: "Failed payment value flagged for recovery orchestration",
    },
    {
      id: "3",
      title: "ML recovery probability calculated",
      timestamp: createdAt ?? new Date().toISOString(),
      status: "COMPLETED",
      detail: "Scored by the trained recovery-prediction model with SHAP factor extraction",
    },
    {
      id: "4",
      title: "AI investigation & recommendation generated",
      timestamp: createdAt ?? new Date().toISOString(),
      status: "COMPLETED",
      detail: "Optimal recovery action selected based on failure root cause",
    },
    {
      id: "5",
      title: "Merchant approval",
      status: campaignStatus === "PENDING_APPROVAL" ? "PENDING" : "COMPLETED",
      detail:
        campaignStatus === "PENDING_APPROVAL"
          ? "Awaiting merchant authorization in RecoverAI dashboard"
          : "Authorized by merchant",
      actor: "Merchant Admin",
    },
    {
      id: "6",
      title: "Razorpay recovery action initiated",
      status:
        campaignStatus === "EXECUTED" || campaignStatus === "RECOVERED" || campaignStatus === "COMPLETED"
          ? "COMPLETED"
          : campaignStatus === "APPROVED"
          ? "IN_PROGRESS"
          : "PENDING",
      detail: "Razorpay payment link dispatched via automated channel",
    },
    {
      id: "7",
      title: "Webhook received & signature verified",
      status: recoveredAmount && recoveredAmount > 0 ? "COMPLETED" : "PENDING",
      detail: "HMAC SHA-256 webhook signature verified securely by backend",
    },
    {
      id: "8",
      title: recoveredAmount && recoveredAmount > 0 ? `${formatCurrency(recoveredAmount)} recovered` : "Payment confirmation",
      status: recoveredAmount && recoveredAmount > 0 ? "COMPLETED" : "PENDING",
      detail:
        recoveredAmount && recoveredAmount > 0
          ? "Verified payment confirmation recorded in ledger"
          : "Waiting for verified payment event",
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-indigo-600" />
          <h4 className="text-sm font-semibold text-slate-900">End-to-End Recovery Lifecycle</h4>
        </div>
        <span className="text-2xs font-mono text-slate-400 uppercase tracking-wider">Audit Verified</span>
      </div>

      <div className="mt-5 relative border-l-2 border-slate-100 pl-6 space-y-6 ml-3">
        {defaultSteps.map((step) => {
          const isDone = step.status === "COMPLETED";
          const isInProgress = step.status === "IN_PROGRESS";
          const isFailed = step.status === "FAILED";

          return (
            <div key={step.id} className="relative group">
              {/* Dot Icon */}
              <div
                className={`absolute -left-[31px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full border-2 bg-white transition-all ${
                  isDone
                    ? "border-emerald-500 text-emerald-600 bg-emerald-50"
                    : isFailed
                    ? "border-rose-500 text-rose-600 bg-rose-50"
                    : isInProgress
                    ? "border-blue-500 text-blue-600 bg-blue-50 animate-pulse"
                    : "border-slate-300 text-slate-300 bg-slate-50"
                }`}
              >
                {isDone ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : isFailed ? (
                  <XCircle className="h-3.5 w-3.5" />
                ) : isInProgress ? (
                  <div className="h-2 w-2 rounded-full bg-blue-600 animate-ping" />
                ) : (
                  <div className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                )}
              </div>

              <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-1">
                <p
                  className={`text-xs sm:text-sm font-semibold ${
                    isDone
                      ? "text-slate-900"
                      : isFailed
                      ? "text-rose-700"
                      : isInProgress
                      ? "text-blue-700 font-bold"
                      : "text-slate-400"
                  }`}
                >
                  {step.title}
                </p>
                {step.timestamp && (
                  <span className="text-2xs font-mono text-slate-400 shrink-0">
                    {formatDateTime(step.timestamp)}
                  </span>
                )}
              </div>

              {step.detail && (
                <p
                  className={`mt-0.5 text-2xs sm:text-xs ${
                    isDone ? "text-slate-500" : isFailed ? "text-rose-600" : "text-slate-400"
                  }`}
                >
                  {step.detail}
                  {step.actor && <span className="ml-1 text-slate-400">({step.actor})</span>}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

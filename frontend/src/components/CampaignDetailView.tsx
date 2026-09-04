import type { CampaignDetail } from "@/lib/api";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";

const STATUS_COLORS: Record<string, string> = {
  PENDING_APPROVAL: "bg-amber-50 text-amber-700 border-amber-200",
  APPROVED: "bg-blue-50 text-blue-700 border-blue-200",
  RUNNING: "bg-blue-50 text-blue-700 border-blue-200",
  COMPLETED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  FAILED: "bg-red-50 text-red-700 border-red-200",
  CANCELLED: "bg-slate-100 text-slate-600 border-slate-200",
  RECOVERED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  EXECUTED: "bg-blue-50 text-blue-700 border-blue-200",
  PENDING: "bg-slate-100 text-slate-600 border-slate-200",
  AUTHORIZED: "bg-amber-50 text-amber-700 border-amber-200",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

/** "What AI concluded/recommended -> merchant approved -> system executed ->
 * what actually happened" as a single chronological list (spec section 1). */
function AuditTrailTimeline({ entries }: { entries: CampaignDetail["audit_trail"] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-slate-500">No audit events recorded yet.</p>;
  }

  return (
    <ol className="space-y-3 border-l border-slate-200 pl-4">
      {entries.map((entry) => (
        <li key={entry.id} className="relative">
          <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-slate-400" />
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium text-slate-900">{entry.event_type.replace(/_/g, " ")}</span>
            <span className="text-xs text-slate-400">by {entry.actor}</span>
            <span className="text-xs text-slate-400">{formatDateTime(entry.created_at)}</span>
          </div>
          {Object.keys(entry.details).length > 0 && (
            <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-600">
              {JSON.stringify(entry.details, null, 2)}
            </pre>
          )}
        </li>
      ))}
    </ol>
  );
}

export function CampaignDetailView({ campaign }: { campaign: CampaignDetail }) {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-medium text-slate-900">{campaign.name}</h2>
            <p className="mt-1 text-xs text-slate-400">
              Campaign {campaign.id} &middot; created by {campaign.created_by} &middot;{" "}
              {formatDateTime(campaign.created_at)}
            </p>
          </div>
          <StatusBadge status={campaign.status} />
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="text-xs font-medium text-slate-500">Revenue at risk</p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{formatCurrency(campaign.revenue_at_risk)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-slate-500">Recoverable</p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{formatCurrency(campaign.recoverable_revenue)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-slate-500">Recovered</p>
            <p className="mt-1 text-lg font-semibold text-emerald-600">{formatCurrency(campaign.revenue_recovered)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-slate-500">Recovery rate</p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{formatPercent(campaign.recovery_rate)}</p>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">What AI concluded &amp; recommended</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[500px] text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slate-400">
                <th className="pb-2 pr-4 font-medium">Action</th>
                <th className="pb-2 pr-4 font-medium">Probability</th>
                <th className="pb-2 pr-4 font-medium">Expected recovery</th>
                <th className="pb-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {campaign.recommendations.map((rec) => (
                <tr key={rec.payment_id}>
                  <td className="py-2 pr-4 font-medium text-slate-800">{rec.recommended_action.replace(/_/g, " ")}</td>
                  <td className="py-2 pr-4 text-slate-600">{formatPercent(rec.recovery_probability)}</td>
                  <td className="py-2 pr-4 text-slate-600">{formatCurrency(rec.expected_recovery)}</td>
                  <td className="py-2 text-slate-500">{rec.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">What the system executed &amp; what actually happened</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[500px] text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slate-400">
                <th className="pb-2 pr-4 font-medium">Status</th>
                <th className="pb-2 pr-4 font-medium">Provider response</th>
                <th className="pb-2 font-medium">Recovered amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {campaign.actions.map((action) => (
                <tr key={action.id}>
                  <td className="py-2 pr-4">
                    <StatusBadge status={action.status} />
                  </td>
                  <td className="py-2 pr-4 text-slate-500">
                    {action.provider_response
                      ? action.provider_response.success
                        ? "Link created"
                        : String(action.provider_response.error ?? "Failed")
                      : "—"}
                  </td>
                  <td className="py-2 text-slate-600">
                    {action.recovered_amount != null ? formatCurrency(action.recovered_amount) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">Audit trail</h3>
        <p className="mt-1 text-xs text-slate-500">
          Every recorded event for this campaign, in order.
        </p>
        <div className="mt-4">
          <AuditTrailTimeline entries={campaign.audit_trail} />
        </div>
      </div>
    </div>
  );
}

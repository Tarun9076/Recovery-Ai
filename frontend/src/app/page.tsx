import { FailureTrendChart } from "@/components/FailureTrendChart";
import { StatCard } from "@/components/StatCard";
import { getDashboardSummary } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/format";

export default async function Home() {
  let summary;
  let error: string | null = null;

  try {
    summary = await getDashboardSummary();
  } catch {
    error = "Could not reach the RecoverAI API. Is the backend running?";
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">RecoverAI Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Live snapshot of payment health, sourced from the RecoverAI backend.
        </p>
      </header>

      {error || !summary ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <>
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Total Payments" value={formatNumber(summary.total_payments)} />
            <StatCard
              label="Successful Payments"
              value={formatNumber(summary.successful_payments)}
              accent="success"
            />
            <StatCard
              label="Failed Payments"
              value={formatNumber(summary.failed_payments)}
              accent="danger"
            />
            <StatCard
              label="Failure Rate"
              value={`${(summary.failure_rate * 100).toFixed(2)}%`}
              accent="danger"
            />
            <StatCard
              label="Failed Transaction Value"
              value={formatCurrency(summary.failed_transaction_value)}
              accent="danger"
            />
          </section>

          <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-medium text-slate-900">Payment Failure Trend</h2>
            <p className="mt-1 text-sm text-slate-500">
              Daily payment volume (bars) and failure rate (red line) across the dataset window.
            </p>
            <div className="mt-6">
              <FailureTrendChart points={summary.failure_trend} />
            </div>
          </section>

          <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-medium text-slate-900">Failure Category Breakdown</h2>
            <ul className="mt-4 divide-y divide-slate-100">
              {summary.failure_category_breakdown.map((row) => (
                <li key={row.failure_category} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-slate-600">{row.failure_category}</span>
                  <span className="font-medium text-slate-900">{formatNumber(row.count)}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </main>
  );
}

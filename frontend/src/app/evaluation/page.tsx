import { StatCard } from "@/components/StatCard";
import {
  getBaselineComparison,
  getBusinessMetrics,
  getModelEvaluation,
  type BaselineComparison,
  type BusinessMetrics,
  type ModelEvaluation,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/lib/format";

function BaselineComparisonPanel({ comparison }: { comparison: BaselineComparison }) {
  if (comparison.targeted_payment_count === 0) {
    return (
      <p className="text-sm text-slate-500">
        RecoverAI hasn&apos;t targeted any failed payments with a recovery campaign yet -- run the Demo Control
        Panel to generate a comparison.
      </p>
    );
  }

  const maxValue = Math.max(comparison.baseline_recovered_revenue, comparison.recoverai_recovered_revenue, 1);
  const isPositive = comparison.incremental_recovered_revenue >= 0;

  return (
    <div>
      <p className="text-xs text-slate-500">
        Scoped to the {formatNumber(comparison.targeted_payment_count)} failed payments (
        {formatCurrency(comparison.targeted_transaction_value)}) RecoverAI has actually targeted with a recovery
        campaign -- not the whole portfolio, so this is a fair like-for-like comparison.
      </p>

      <div className="mt-5 space-y-3">
        <div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-slate-600">Baseline (no AI intervention)</span>
            <span className="text-slate-900">
              {formatCurrency(comparison.baseline_recovered_revenue)} ({formatPercent(comparison.baseline_recovery_rate)})
            </span>
          </div>
          <div className="mt-1 h-3 w-full rounded-full bg-slate-100">
            <div
              className="h-3 rounded-full bg-slate-400"
              style={{ width: `${(comparison.baseline_recovered_revenue / maxValue) * 100}%` }}
            />
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-slate-600">RecoverAI (verified recovery)</span>
            <span className="text-slate-900">
              {formatCurrency(comparison.recoverai_recovered_revenue)} ({formatPercent(comparison.recoverai_recovery_rate)})
            </span>
          </div>
          <div className="mt-1 h-3 w-full rounded-full bg-slate-100">
            <div
              className="h-3 rounded-full bg-emerald-500"
              style={{ width: `${(comparison.recoverai_recovered_revenue / maxValue) * 100}%` }}
            />
          </div>
        </div>
      </div>

      <p className={`mt-4 text-sm font-medium ${isPositive ? "text-emerald-600" : "text-red-600"}`}>
        Incremental recovered revenue: {isPositive ? "+" : ""}
        {formatCurrency(comparison.incremental_recovered_revenue)}
      </p>
    </div>
  );
}

function ModelEvaluationPanel({ model }: { model: ModelEvaluation }) {
  const metrics: { label: string; value: string }[] = [
    { label: "Precision", value: model.precision.toFixed(3) },
    { label: "Recall", value: model.recall.toFixed(3) },
    { label: "F1", value: model.f1.toFixed(3) },
    { label: "ROC-AUC", value: model.roc_auc.toFixed(3) },
    { label: "PR-AUC", value: model.pr_auc.toFixed(3) },
    { label: "Brier score", value: model.brier_score.toFixed(3) },
  ];

  return (
    <div>
      <p className="text-xs text-slate-500">
        {model.algorithm} (v{model.model_version}, feature set {model.feature_version}) &middot; trained{" "}
        {formatDateTime(model.training_timestamp)} &middot; decision threshold {model.decision_threshold} &middot;{" "}
        {model.dataset_size != null ? `${formatNumber(model.dataset_size)} training payments` : null}
      </p>

      <div className="mt-4 grid grid-cols-3 gap-4 sm:grid-cols-6">
        {metrics.map((m) => (
          <div key={m.label}>
            <p className="text-xs font-medium text-slate-500">{m.label}</p>
            <p className="mt-1 text-xl font-semibold text-slate-900">{m.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-400">
              <th className="pb-2 pr-4 font-medium">Confusion outcome</th>
              <th className="pb-2 pr-4 font-medium">Count</th>
              <th className="pb-2 font-medium">Revenue cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <tr>
              <td className="py-2 pr-4 text-slate-600">False positives (predicted recoverable, wasn&apos;t)</td>
              <td className="py-2 pr-4 text-slate-900">{formatNumber(model.false_positive_count)}</td>
              <td className="py-2 text-red-600">{formatCurrency(model.false_positive_revenue_cost)}</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-slate-600">False negatives (predicted not recoverable, was)</td>
              <td className="py-2 pr-4 text-slate-900">{formatNumber(model.false_negative_count)}</td>
              <td className="py-2 text-red-600">{formatCurrency(model.false_negative_revenue_cost)}</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-slate-600">True positives</td>
              <td className="py-2 pr-4 text-slate-900">{formatNumber(model.true_positive_count)}</td>
              <td className="py-2 text-slate-400">—</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-slate-600">True negatives</td>
              <td className="py-2 pr-4 text-slate-900">{formatNumber(model.true_negative_count)}</td>
              <td className="py-2 text-slate-400">—</td>
            </tr>
          </tbody>
        </table>
      </div>

      {model.calibration_bins.length > 0 && (
        <div className="mt-6">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Calibration (predicted probability vs. actual recovery rate)
          </h4>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[400px] text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-slate-400">
                  <th className="pb-2 pr-4 font-medium">Mean predicted</th>
                  <th className="pb-2 pr-4 font-medium">Actual rate</th>
                  <th className="pb-2 font-medium">Count</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {model.calibration_bins.map((bin, i) => (
                  <tr key={i}>
                    <td className="py-1.5 pr-4 text-slate-600">{formatPercent(bin.mean_predicted)}</td>
                    <td className="py-1.5 pr-4 text-slate-600">{formatPercent(bin.actual_rate)}</td>
                    <td className="py-1.5 text-slate-500">{formatNumber(bin.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default async function EvaluationPage() {
  const [modelResult, businessResult, baselineResult] = await Promise.allSettled([
    getModelEvaluation(),
    getBusinessMetrics(),
    getBaselineComparison(),
  ]);

  const model = modelResult.status === "fulfilled" ? modelResult.value : null;
  const business: BusinessMetrics | null = businessResult.status === "fulfilled" ? businessResult.value : null;
  const baseline: BaselineComparison | null = baselineResult.status === "fulfilled" ? baselineResult.value : null;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Evaluation</h1>
        <p className="mt-1 text-sm text-slate-500">
          Real ML and business metrics, computed fresh on every load -- nothing on this page is hardcoded.
        </p>
      </header>

      <section>
        <h2 className="text-lg font-medium text-slate-900">Business impact</h2>
        {business ? (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Failed Transaction Value" value={formatCurrency(business.failed_transaction_value)} accent="danger" />
            <StatCard label="Revenue at Risk" value={formatCurrency(business.revenue_at_risk)} accent="danger" />
            <StatCard label="Predicted Recoverable" value={formatCurrency(business.predicted_recoverable_revenue)} />
            <StatCard label="Actual Recovered" value={formatCurrency(business.actual_recovered_revenue)} accent="success" />
            <StatCard label="Recovery Rate" value={formatPercent(business.recovery_rate)} accent="success" />
          </div>
        ) : (
          <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            Could not load business metrics from the RecoverAI API.
          </p>
        )}
      </section>

      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-medium text-slate-900">Baseline vs. RecoverAI</h2>
        <p className="mt-1 text-sm text-slate-500">
          What would have recovered organically vs. what RecoverAI actually recovered, using real simulation results.
        </p>
        <div className="mt-6">
          {baseline ? (
            <BaselineComparisonPanel comparison={baseline} />
          ) : (
            <p className="text-sm text-red-700">Could not load the baseline comparison.</p>
          )}
        </div>
      </section>

      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-medium text-slate-900">Model evaluation</h2>
        <p className="mt-1 text-sm text-slate-500">
          Scored against the model&apos;s held-out temporal test split -- see ml/evaluation/evaluate.py.
        </p>
        <div className="mt-6">
          {model ? (
            <ModelEvaluationPanel model={model} />
          ) : (
            <p className="text-sm text-red-700">
              No trained model found. Run <code>python ml/training/train.py</code> first.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}

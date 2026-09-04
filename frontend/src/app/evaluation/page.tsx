import { KPICard } from "@/components/KPICard";
import {
  getBaselineComparison,
  getBusinessMetrics,
  getModelEvaluation,
  type BaselineComparison,
  type BusinessMetrics,
  type ModelEvaluation,
} from "@/lib/api";
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import {
  Activity,
  BarChart2,
  CheckCircle,
  HelpCircle,
  Info,
  Layers,
  ShieldAlert,
  Sliders,
  Sparkles,
  Target,
} from "lucide-react";

function BaselineComparisonPanel({ comparison }: { comparison: BaselineComparison }) {
  if (comparison.targeted_payment_count === 0) {
    return (
      <div className="rounded-lg bg-slate-50 p-6 text-center text-xs text-slate-500 border border-slate-200">
        <Info className="mx-auto h-5 w-5 text-slate-400 mb-1" />
        No targeted payments with a recovery campaign recorded yet. Run the Demo Control Panel or approve opportunities to generate causal baseline comparison data.
      </div>
    );
  }

  const maxValue = Math.max(
    comparison.baseline_recovered_revenue,
    comparison.recoverai_recovered_revenue,
    1,
  );
  const isPositive = comparison.incremental_recovered_revenue >= 0;

  return (
    <div className="space-y-6">
      <div className="rounded-lg bg-blue-50/60 border border-blue-200/80 p-4 text-xs text-blue-900 leading-relaxed">
        <strong className="font-semibold flex items-center gap-1.5 mb-1">
          <Info className="h-4 w-4 text-blue-600" /> Evaluation Methodology &amp; Scope Note
        </strong>
        Scoped to the <strong>{formatNumber(comparison.targeted_payment_count)} failed payments</strong> (
        {formatCurrency(comparison.targeted_transaction_value)}) targeted by RecoverAI. Organically recovered payments without AI intervention serve as the baseline comparison window to ensure transparent, causal accounting.
      </div>

      <div className="space-y-4">
        <div>
          <div className="flex items-baseline justify-between text-xs sm:text-sm mb-1.5">
            <span className="font-semibold text-slate-700">Baseline Organic Recovery (No Intervention)</span>
            <span className="font-bold text-slate-900">
              {formatCurrency(comparison.baseline_recovered_revenue)} ({formatPercent(comparison.baseline_recovery_rate)})
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
            <div
              className="h-3 rounded-full bg-slate-400 transition-all duration-300"
              style={{ width: `${Math.min(100, (comparison.baseline_recovered_revenue / maxValue) * 100)}%` }}
            />
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between text-xs sm:text-sm mb-1.5">
            <span className="font-semibold text-slate-700">RecoverAI Verified Recovery</span>
            <span className="font-bold text-emerald-700">
              {formatCurrency(comparison.recoverai_recovered_revenue)} ({formatPercent(comparison.recoverai_recovery_rate)})
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
            <div
              className="h-3 rounded-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${Math.min(100, (comparison.recoverai_recovered_revenue / maxValue) * 100)}%` }}
            />
          </div>
        </div>
      </div>

      <div className={`rounded-xl p-4 border flex items-center justify-between ${
        isPositive ? "bg-emerald-50 border-emerald-200 text-emerald-900" : "bg-rose-50 border-rose-200 text-rose-900"
      }`}>
        <div>
          <span className="text-2xs font-bold uppercase tracking-wider text-slate-500">Incremental Net Revenue Impact</span>
          <p className={`text-xl font-bold ${isPositive ? "text-emerald-700" : "text-rose-700"}`}>
            {isPositive ? "+" : ""}{formatCurrency(comparison.incremental_recovered_revenue)}
          </p>
        </div>
        <span className="text-2xs font-mono font-semibold uppercase px-2.5 py-1 rounded bg-white border">
          {isPositive ? "POSITIVE GAIN" : "SIMULATION SCOPED"}
        </span>
      </div>
    </div>
  );
}

function ModelEvaluationPanel({ model }: { model: ModelEvaluation }) {
  const metricsList = [
    { label: "Precision", value: model.precision.toFixed(3), desc: "Accuracy of predicted recoveries" },
    { label: "Recall", value: model.recall.toFixed(3), desc: "Coverage of true recoverable set" },
    { label: "F1 Score", value: model.f1.toFixed(3), desc: "Harmonic mean of precision & recall" },
    { label: "ROC-AUC", value: model.roc_auc.toFixed(3), desc: "Discriminative ability across thresholds" },
    { label: "PR-AUC", value: model.pr_auc.toFixed(3), desc: "Area under Precision-Recall curve" },
    { label: "Brier Score", value: model.brier_score.toFixed(3), desc: "Probability calibration accuracy" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 text-xs text-slate-500">
        <div>
          Algorithm: <strong className="text-slate-800 font-mono">{model.algorithm}</strong> &middot; Model v{model.model_version} &middot; Feature Set v{model.feature_version}
        </div>
        <div>
          Trained: <strong className="text-slate-800">{formatDateTime(model.training_timestamp)}</strong> &middot; Threshold: <strong className="text-slate-800 font-mono">{model.decision_threshold}</strong>
        </div>
      </div>

      {/* METRICS GRID */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {metricsList.map((m) => (
          <div key={m.label} className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
            <span className="text-2xs font-bold uppercase tracking-wider text-slate-500">{m.label}</span>
            <p className="mt-1 text-2xl font-bold tracking-tight text-slate-900">{m.value}</p>
            <p className="mt-1 text-3xs text-slate-400 line-clamp-1">{m.desc}</p>
          </div>
        ))}
      </div>

      {/* CONFUSION OUTCOMES & REVENUE COST TABLE */}
      <div>
        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
          Confusion Outcomes &amp; Revenue Cost of Errors
        </h4>
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4">Confusion Outcome</th>
                <th className="py-3 px-4">Count</th>
                <th className="py-3 px-4">Financial Cost Impact</th>
                <th className="py-3 px-4">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium">
              <tr className="hover:bg-rose-50/30">
                <td className="py-3 px-4 text-rose-800 font-bold">
                  False Positives (Predicted recoverable, wasn&apos;t)
                </td>
                <td className="py-3 px-4 font-mono font-bold text-slate-900">
                  {formatNumber(model.false_positive_count)}
                </td>
                <td className="py-3 px-4 font-bold text-rose-600">
                  {formatCurrency(model.false_positive_revenue_cost)}
                </td>
                <td className="py-3 px-4 text-slate-500 text-xs">
                  Operational outreach cost incurred without successful payment completion
                </td>
              </tr>
              <tr className="hover:bg-rose-50/30">
                <td className="py-3 px-4 text-rose-800 font-bold">
                  False Negatives (Predicted not recoverable, was)
                </td>
                <td className="py-3 px-4 font-mono font-bold text-slate-900">
                  {formatNumber(model.false_negative_count)}
                </td>
                <td className="py-3 px-4 font-bold text-rose-600">
                  {formatCurrency(model.false_negative_revenue_cost)}
                </td>
                <td className="py-3 px-4 text-slate-500 text-xs">
                  Missed recoverable revenue opportunity due to conservative AI scoring threshold
                </td>
              </tr>
              <tr className="hover:bg-emerald-50/30">
                <td className="py-3 px-4 text-emerald-800 font-bold">True Positives</td>
                <td className="py-3 px-4 font-mono font-bold text-slate-900">
                  {formatNumber(model.true_positive_count)}
                </td>
                <td className="py-3 px-4 text-emerald-600 font-bold">—</td>
                <td className="py-3 px-4 text-slate-500 text-xs">Successfully targeted and recovered failed payments</td>
              </tr>
              <tr className="hover:bg-slate-50">
                <td className="py-3 px-4 text-slate-700 font-bold">True Negatives</td>
                <td className="py-3 px-4 font-mono font-bold text-slate-900">
                  {formatNumber(model.true_negative_count)}
                </td>
                <td className="py-3 px-4 text-slate-400">—</td>
                <td className="py-3 px-4 text-slate-500 text-xs">Correctly filtered out unrecoverable payment failures</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* CALIBRATION TABLE */}
      {model.calibration_bins && model.calibration_bins.length > 0 && (
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
            Probability Calibration Bins
          </h4>
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-2.5 px-4">Mean Predicted Probability</th>
                  <th className="py-2.5 px-4">Actual Empirical Recovery Rate</th>
                  <th className="py-2.5 px-4">Sample Size</th>
                  <th className="py-2.5 px-4">Calibration Fit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-medium">
                {model.calibration_bins.map((bin, i) => {
                  const diff = Math.abs(bin.mean_predicted - bin.actual_rate);
                  const isWellCalibrated = diff < 0.1;

                  return (
                    <tr key={i} className="hover:bg-slate-50">
                      <td className="py-2.5 px-4 font-mono text-slate-800">
                        {formatPercent(bin.mean_predicted)}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-900 font-bold">
                        {formatPercent(bin.actual_rate)}
                      </td>
                      <td className="py-2.5 px-4 text-slate-600">
                        {formatNumber(bin.count)}
                      </td>
                      <td className="py-2.5 px-4">
                        <span
                          className={`inline-flex items-center gap-1 text-2xs font-semibold px-2 py-0.5 rounded ${
                            isWellCalibrated ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"
                          }`}
                        >
                          {isWellCalibrated ? "Well Calibrated" : "Mild Discrepancy"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
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
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      {/* Header */}
      <div className="border-b border-slate-200/80 pb-5">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
            <Target className="h-3 w-3" /> MODEL &amp; CAUSAL EVALUATION
          </span>
        </div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Evaluation
        </h1>
        <p className="mt-1 text-xs sm:text-sm text-slate-500">
          Measure whether RecoverAI actually identifies and recovers revenue responsibly.
        </p>
      </div>

      {/* SECTION 1: BUSINESS IMPACT */}
      <section className="space-y-4">
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Activity className="h-4 w-4 text-indigo-600" />
          1. Business Impact
        </h2>
        {business ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <KPICard title="Failed Transaction Value" value={formatCurrency(business.failed_transaction_value)} variant="danger" />
            <KPICard title="Revenue at Risk" value={formatCurrency(business.revenue_at_risk)} variant="danger" highlight />
            <KPICard title="Predicted Recoverable" value={formatCurrency(business.predicted_recoverable_revenue)} variant="info" />
            <KPICard title="Actual Recovered" value={formatCurrency(business.actual_recovered_revenue)} variant="success" highlight />
            <KPICard title="Recovery Rate" value={formatPercent(business.recovery_rate)} variant="success" highlight />
          </div>
        ) : (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
            Could not load business metrics from backend.
          </div>
        )}
      </section>

      {/* SECTION 2: BASELINE VS RECOVERAI */}
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <BarChart2 className="h-4 w-4 text-indigo-600" />
          2. Baseline vs. RecoverAI
        </h2>
        {baseline ? (
          <BaselineComparisonPanel comparison={baseline} />
        ) : (
          <div className="text-xs text-rose-600">Could not load baseline comparison data.</div>
        )}
      </section>

      {/* SECTION 3 & 4: MODEL EVALUATION & CALIBRATION */}
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <Sliders className="h-4 w-4 text-indigo-600" />
          3. Held-Out Model Evaluation &amp; Calibration
        </h2>
        {model ? (
          <ModelEvaluationPanel model={model} />
        ) : (
          <div className="text-xs text-rose-600">
            No trained model metrics found. Train the ML model using <code>python ml/training/train.py</code>.
          </div>
        )}
      </section>
    </main>
  );
}

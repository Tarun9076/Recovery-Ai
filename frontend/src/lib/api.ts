export interface FailureTrendPoint {
  date: string;
  total_payments: number;
  failed_payments: number;
  failure_rate: number;
}

export interface FailureCategoryBreakdown {
  failure_category: string;
  count: number;
}

export interface DashboardSummary {
  total_payments: number;
  successful_payments: number;
  failed_payments: number;
  total_transaction_value: number;
  failed_transaction_value: number;
  failure_rate: number;
  total_merchants: number;
  total_customers: number;
  total_orders: number;
  failure_trend: FailureTrendPoint[];
  failure_category_breakdown: FailureCategoryBreakdown[];
}

// process.env.API_URL is statically replaced with `undefined` in the browser
// bundle (only NEXT_PUBLIC_-prefixed vars survive there) -- so this single
// constant correctly resolves to a server-reachable URL in Server Components
// and a browser-reachable one in Client Components, from the same source line.
const API_URL = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON -- fall back to statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/dashboard/summary");
}

// ---------------------------------------------------------------------------
// Phase 8: evaluation
// ---------------------------------------------------------------------------

export interface CalibrationBin {
  mean_predicted: number;
  actual_rate: number;
  count: number;
}

export interface ModelEvaluation {
  model_name: string;
  model_version: string;
  feature_version: string;
  algorithm: string;
  training_timestamp: string;
  decision_threshold: number;
  dataset_size: number | null;
  positive_rate: number | null;
  precision: number;
  recall: number;
  f1: number;
  roc_auc: number;
  pr_auc: number;
  brier_score: number;
  false_positive_count: number;
  false_negative_count: number;
  true_positive_count: number;
  true_negative_count: number;
  false_positive_revenue_cost: number;
  false_negative_revenue_cost: number;
  test_predicted_recoverable_revenue: number;
  test_actual_recovered_revenue: number;
  test_prediction_error: number;
  test_prediction_error_pct: number;
  calibration_bins: CalibrationBin[];
}

export interface BusinessMetrics {
  failed_transaction_value: number;
  revenue_at_risk: number;
  predicted_recoverable_revenue: number;
  actual_recovered_revenue: number;
  recovery_rate: number;
}

export interface BaselineComparison {
  targeted_transaction_value: number;
  targeted_payment_count: number;
  baseline_recovered_revenue: number;
  recoverai_recovered_revenue: number;
  incremental_recovered_revenue: number;
  baseline_recovery_rate: number;
  recoverai_recovery_rate: number;
}

export async function getModelEvaluation(): Promise<ModelEvaluation> {
  return apiFetch<ModelEvaluation>("/api/evaluation/model");
}

export async function getBusinessMetrics(): Promise<BusinessMetrics> {
  return apiFetch<BusinessMetrics>("/api/evaluation/business");
}

export async function getBaselineComparison(): Promise<BaselineComparison> {
  return apiFetch<BaselineComparison>("/api/evaluation/baseline-comparison");
}

// ---------------------------------------------------------------------------
// Failed payments (demo payment picker)
// ---------------------------------------------------------------------------

export interface FailedPayment {
  id: string;
  customer_id: string;
  amount: number;
  currency: string;
  status: string;
  method: string;
  bank: string | null;
  email: string;
  created_at: string;
  failure: {
    failure_category: string;
    failure_severity: string;
    recoverability: string;
    raw_failure_code: string;
    raw_failure_reason: string;
  } | null;
}

export interface PaginatedFailedPayments {
  total: number;
  limit: number;
  offset: number;
  items: FailedPayment[];
}

export async function getFailedPayments(limit = 15): Promise<PaginatedFailedPayments> {
  return apiFetch<PaginatedFailedPayments>(`/api/payments/failed?limit=${limit}`);
}

export interface RecoveryOpportunity {
  payment_id: string;
  amount: number;
  recovery_probability: number;
  expected_recovery: number;
  payment_method: string;
  failure_category: string | null;
}

interface PaginatedRecoveryOpportunities {
  total: number;
  limit: number;
  offset: number;
  items: RecoveryOpportunity[];
}

/** Payments the ML model already scores above the merchant's recovery-probability
 * policy threshold -- unlike `getFailedPayments` (most-recent, regardless of
 * score), every candidate here is one `postCreateCampaign` will actually accept,
 * which is what the demo picker needs to stay reliable during a live walkthrough. */
export async function getHighRecoveryOpportunities(limit = 15): Promise<RecoveryOpportunity[]> {
  const res = await apiFetch<PaginatedRecoveryOpportunities>(
    `/api/recovery/opportunities?segment=HIGH_RECOVERY&limit=${limit}`,
  );
  return res.items;
}

// ---------------------------------------------------------------------------
// AI investigation agent
// ---------------------------------------------------------------------------

export interface InvestigationFinding {
  finding: string;
  severity: "low" | "medium" | "high";
  evidence: string[];
  affected_payment_count: number;
  revenue_at_risk: number;
  estimated_recoverable_revenue: number;
}

export interface InvestigationRecommendation {
  problem: string;
  root_cause: string;
  evidence: string[];
  revenue_at_risk: number;
  recoverable_revenue: number;
  recommended_action: string;
  expected_recovery: number;
  confidence: number;
  reason: string;
  requires_approval: boolean;
}

export interface InvestigateResponse {
  summary: string;
  findings: InvestigationFinding[];
  revenue_at_risk: number;
  recoverable_revenue: number;
  recommendations: InvestigationRecommendation[];
}

export async function postInvestigate(question: string): Promise<InvestigateResponse> {
  return apiFetch<InvestigateResponse>("/api/ai/investigate", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

// ---------------------------------------------------------------------------
// Campaigns / recovery actions / audit trail
// ---------------------------------------------------------------------------

export interface OpportunitySummary {
  payment_id: string;
  customer_id: string;
  recovery_probability: number;
  expected_recovery: number;
  recommended_action: string;
  reason: string;
  confidence: number;
  status: string;
}

export interface RecoveryActionRead {
  id: string;
  payment_id: string;
  customer_id: string;
  action_type: string;
  status: string;
  provider_response: Record<string, unknown> | null;
  created_at: string;
  authorized_at: string | null;
  executed_at: string | null;
  recovered_at: string | null;
  recovered_amount: number | null;
}

export interface AuditLogEntry {
  id: string;
  event_type: string;
  actor: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface CampaignDetail {
  id: string;
  merchant_id: string;
  name: string;
  target_count: number;
  total_amount: number;
  expected_recovery: number;
  status: string;
  created_by: string;
  approved_by: string | null;
  rejection_reason: string | null;
  created_at: string;
  approved_at: string | null;
  completed_at: string | null;
  recommendations: OpportunitySummary[];
  actions: RecoveryActionRead[];
  audit_trail: AuditLogEntry[];
  revenue_at_risk: number;
  recoverable_revenue: number;
  revenue_recovered: number;
  recovery_rate: number;
}

export interface CampaignCreateResult {
  campaign: { id: string; status: string; name: string };
  excluded: { payment_id: string; reason: string }[];
}

export async function getCampaign(id: string): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/recovery/campaigns/${id}`);
}

export async function postCreateCampaign(
  paymentIds: string[],
  name: string,
  createdBy = "demo",
): Promise<CampaignCreateResult> {
  return apiFetch<CampaignCreateResult>("/api/recovery/campaigns", {
    method: "POST",
    body: JSON.stringify({ name, payment_ids: paymentIds, created_by: createdBy }),
  });
}

export async function postApproveCampaign(id: string, approvedBy = "demo"): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/recovery/campaigns/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

export async function postExecuteCampaign(id: string): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>(`/api/recovery/campaigns/${id}/execute`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Mock provider / demo controls
// ---------------------------------------------------------------------------

export interface SimulatePaymentResult {
  status: string;
  simulated: boolean;
  recovery_action_id?: string;
  amount_paid?: number;
  webhook_event_id?: string;
  reason?: string;
}

export async function postSimulatePayment(recoveryActionId: string): Promise<SimulatePaymentResult> {
  return apiFetch<SimulatePaymentResult>("/api/mock/simulate-payment", {
    method: "POST",
    body: JSON.stringify({ recovery_action_id: recoveryActionId }),
  });
}

export async function postSimulateProviderFailure(paymentId?: string): Promise<CampaignDetail> {
  return apiFetch<CampaignDetail>("/api/demo/simulate-provider-failure", {
    method: "POST",
    body: JSON.stringify({ payment_id: paymentId ?? null, created_by: "demo" }),
  });
}

export interface DemoResetResult {
  recovery_actions: number;
  recovery_campaigns: number;
  recovery_opportunities: number;
  recovery_predictions: number;
  webhook_events: number;
  audit_logs: number;
  ai_investigations: number;
}

export async function postResetDemo(): Promise<DemoResetResult> {
  return apiFetch<DemoResetResult>("/api/demo/reset", { method: "POST" });
}

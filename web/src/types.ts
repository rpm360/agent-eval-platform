export interface ModelInfo {
  id: string;
  litellm: string;
  provider: string;
  requires_api_key: boolean;
  api_base?: string | null;
}

export interface PresetInfo {
  name: string;
  path: string;
  settings: Record<string, unknown>;
}

export interface TaskInfo {
  id: string;
  category: string;
  description: string;
  discriminates: string[];
  grader: { type: string; pass_threshold?: number };
}

export interface CatalogResponse {
  harnesses: string[];
  models: ModelInfo[];
  presets: PresetInfo[];
  tasks: TaskInfo[];
}

export interface ExperimentSummaryItem {
  id: string;
  createdAt: string | null;
  configs: string[];
  expectedTrials: number | null;
  trialCount: number;
  passedCount: number;
  infraErrors: number;
}

export interface ConfigSummary {
  completed: number;
  infra_errors: number;
  mean_score: number;
  pass_rate: number;
  avg_cost_usd: number;
  total_cost_usd: number;
  cost_per_pass_usd: number | null;
  avg_runtime_sec: number;
  p50_runtime_sec: number;
  p95_runtime_sec: number;
  avg_tokens: number;
}

export interface PerTaskRow {
  task_id: string;
  n_a: number;
  n_b: number;
  score_a: number;
  score_b: number;
  delta: number;
  ci_95: [number, number];
  is_noise: boolean;
}

export interface ComparisonReport {
  config_a: string;
  config_b: string;
  shared_tasks: number;
  summary_a: ConfigSummary;
  summary_b: ConfigSummary;
  delta_mean: number;
  ci_95: [number, number];
  mcnemar_p: number;
  verdict: string;
  per_task: PerTaskRow[];
  warnings: string[];
}

export interface CalibrationReport {
  judge_model: string;
  timestamp: string;
  n_examples: number;
  repeats: number;
  accuracy: number;
  cohens_kappa: number;
  precision: number;
  recall: number;
  score_mae: number;
  spearman_rho: number;
  self_agreement: number;
  confusion_matrix: { tp: number; fp: number; tn: number; fn: number };
  verdict: "TRUSTED" | "UNTRUSTED";
  disagreements: Array<{
    id: string;
    task_id: string;
    human_passed: boolean;
    human_score: number;
    judge_passed: boolean;
    judge_score: number;
    notes: string;
    judge_reasoning: string;
  }>;
}

export interface ExperimentDetail {
  experiment_id: string;
  manifest: Record<string, unknown>;
  config_names: string[];
  summaries: Record<string, ConfigSummary>;
  comparison: ComparisonReport | null;
  failures: Record<
    string,
    {
      total: number;
      failed: number;
      categories: Record<string, number>;
      examples: Record<string, string[]>;
    }
  >;
  failure_deltas: Array<{ category: string; count_a: number; count_b: number; delta: number }>;
  calibrations: Record<string, CalibrationReport | null>;
  trial_count: number;
}

export interface TrialItem {
  trial_id: string;
  experiment_id: string;
  config_name: string;
  config_hash: string;
  harness: string;
  model: string;
  task_id: string;
  trial_index: number;
  status: "completed" | "infra_error";
  score: number | null;
  passed: boolean | null;
  runtime_sec: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  steps: number;
  final_answer: string;
  failure_category: string | null;
  error_message: string | null;
  grade: {
    grader_type: string;
    score: number;
    passed: boolean;
    reasoning: string;
    details?: Record<string, unknown>;
  } | null;
}

export interface TraceEvent {
  seq: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
}

import type { CatalogResponse } from "../types";

// Empirical averages from hermes_langgraph__gemini-flash__2026-11-23_13-32-24
const AVG_TOKENS_BY_HARNESS: Record<string, { inTok: number; outTok: number }> = {
  hermes: { inTok: 49300, outTok: 1200 },
  langgraph: { inTok: 19900, outTok: 1800 },
};

const DEFAULT_HARNESS_TOKENS = { inTok: 34600, outTok: 1500 };
const TOKENS_PER_MILLION = 1_000_000;
const DEFAULT_INPUT_RATE_PER_MTOK = 0.75;
const DEFAULT_OUTPUT_RATE_PER_MTOK = 3.75;
const DEFAULT_JUDGE_INPUT_RATE_PER_MTOK = 0.25;
const DEFAULT_JUDGE_OUTPUT_RATE_PER_MTOK = 1.5;
const JUDGE_AVG_INPUT_TOKENS = 2000;
const JUDGE_AVG_OUTPUT_TOKENS = 400;

export interface PerConfigCostEstimate {
  name: string;
  trials: number;
  avgTokens: number;
  costUsd: number;
}

export interface ExperimentCostEstimate {
  nTasks: number;
  nTrials: number;
  nConfigs: number;
  totalTrials: number;
  totalTokens: number;
  avgTokensPerTrial: number;
  totalCostUsd: number;
  judgeTrials: number;
  judgeCostUsd: number;
  perConfig: PerConfigCostEstimate[];
}

export function computeExperimentCostEstimate(params: {
  selectedHarnesses: string[];
  selectedModels: string[];
  customModel: string;
  selectedTasks: string[];
  nTrials: number;
  catalog: CatalogResponse | null;
}): ExperimentCostEstimate {
  const { selectedHarnesses, selectedModels, customModel, selectedTasks, nTrials, catalog } = params;
  const trimmedCustom = customModel.trim();
  const activeModels = [...selectedModels, ...(trimmedCustom ? [trimmedCustom] : [])];
  const nTasks = selectedTasks.length;
  const nConfigs = selectedHarnesses.length * activeModels.length;
  const totalTrials = nTasks * nTrials * nConfigs;

  const modelLookup = new Map((catalog?.models || []).map((model) => [model.id, model]));
  let totalCostUsd = 0;
  let totalTokens = 0;
  const perConfig: PerConfigCostEstimate[] = [];

  for (const harness of selectedHarnesses) {
    const tokenProfile = AVG_TOKENS_BY_HARNESS[harness] || DEFAULT_HARNESS_TOKENS;
    const avgTokPerTrial = tokenProfile.inTok + tokenProfile.outTok;
    for (const modelId of activeModels) {
      const modelInfo = modelLookup.get(modelId);
      const inRate = modelInfo?.pricing?.input_per_mtok ?? DEFAULT_INPUT_RATE_PER_MTOK;
      const outRate = modelInfo?.pricing?.output_per_mtok ?? DEFAULT_OUTPUT_RATE_PER_MTOK;
      const costPerTrial =
        (tokenProfile.inTok / TOKENS_PER_MILLION) * inRate +
        (tokenProfile.outTok / TOKENS_PER_MILLION) * outRate;
      const cfgTrials = nTasks * nTrials;
      const cfgCost = cfgTrials * costPerTrial;
      totalCostUsd += cfgCost;
      totalTokens += cfgTrials * avgTokPerTrial;
      perConfig.push({
        name: `${harness}-${modelId.replace(/\//g, "-")}`,
        trials: cfgTrials,
        avgTokens: avgTokPerTrial,
        costUsd: cfgCost,
      });
    }
  }

  // Add LLM-as-judge grading overhead (~2,000 in + 400 out tokens per judge trial)
  const selectedTaskSet = new Set(selectedTasks);
  const judgeTaskCount = (catalog?.tasks || []).filter(
    (task) => selectedTaskSet.has(task.id) && task.grader?.type === "llm_judge"
  ).length;
  const judgeModel =
    modelLookup.get("gemini-flash") ||
    modelLookup.get("gemini-flash-lite-3.1") ||
    (catalog?.models || []).find((model) => model.id !== "mock");
  const judgeInRate = judgeModel?.pricing?.input_per_mtok ?? DEFAULT_JUDGE_INPUT_RATE_PER_MTOK;
  const judgeOutRate = judgeModel?.pricing?.output_per_mtok ?? DEFAULT_JUDGE_OUTPUT_RATE_PER_MTOK;
  const judgeCostPerTrial =
    (JUDGE_AVG_INPUT_TOKENS / TOKENS_PER_MILLION) * judgeInRate +
    (JUDGE_AVG_OUTPUT_TOKENS / TOKENS_PER_MILLION) * judgeOutRate;
  const judgeTrials = judgeTaskCount * nTrials * nConfigs;
  const judgeCostUsd = judgeTrials * judgeCostPerTrial;
  totalCostUsd += judgeCostUsd;

  const avgTokensPerTrial = totalTrials > 0 ? Math.round(totalTokens / totalTrials) : 0;
  return {
    nTasks,
    nTrials,
    nConfigs,
    totalTrials,
    totalTokens,
    avgTokensPerTrial,
    totalCostUsd,
    judgeTrials,
    judgeCostUsd,
    perConfig,
  };
}

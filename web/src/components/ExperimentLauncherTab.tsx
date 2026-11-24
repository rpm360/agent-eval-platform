import { useEffect, useRef, useState } from "react";
import type { CatalogResponse, ExperimentSummaryItem } from "../types";
import type { ExperimentCostEstimate } from "../utils/costEstimate";
import { CARD_CLS, INPUT_CLS, SUB_CARD_CLS } from "./uiStyles";

interface ExperimentLauncherTabProps {
  catalog: CatalogResponse | null;
  experiments: ExperimentSummaryItem[];
  selectedExp: string;
  selHarnesses: string[];
  setSelHarnesses: (next: string[]) => void;
  selModels: string[];
  setSelModels: (next: string[]) => void;
  customModel: string;
  setCustomModel: (next: string) => void;
  settingsPath: string;
  setSettingsPath: (next: string) => void;
  selTasks: string[];
  setSelTasks: (next: string[]) => void;
  nTrials: number;
  setNTrials: (next: number) => void;
  expIdInput: string;
  setExpIdInput: (next: string) => void;
  costEstimate: ExperimentCostEstimate;
  isLaunching: boolean;
  onLaunchRun: () => void;
  onSelectExperiment: (expId: string) => void;
}

function toggleSelection(
  currentList: string[],
  setList: (updated: string[]) => void,
  value: string
): void {
  setList(
    currentList.includes(value)
      ? currentList.filter((entry) => entry !== value)
      : [...currentList, value]
  );
}

export function ExperimentLauncherTab({
  catalog,
  experiments,
  selectedExp,
  selHarnesses,
  setSelHarnesses,
  selModels,
  setSelModels,
  customModel,
  setCustomModel,
  settingsPath,
  setSettingsPath,
  selTasks,
  setSelTasks,
  nTrials,
  setNTrials,
  expIdInput,
  setExpIdInput,
  costEstimate,
  isLaunching,
  onLaunchRun,
  onSelectExperiment,
}: ExperimentLauncherTabProps) {
  const [taskDropdownOpen, setTaskDropdownOpen] = useState<boolean>(false);
  const [taskSearch, setTaskSearch] = useState<string>("");
  const taskDropdownRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!taskDropdownOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (taskDropdownRef.current && !taskDropdownRef.current.contains(event.target as Node)) {
        setTaskDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [taskDropdownOpen]);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className={`${CARD_CLS} space-y-4 p-5`}>
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
          Launch Matrix Experiment
        </h2>

        <div>
          <div className="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Harnesses
          </div>
          <div className="flex flex-wrap gap-2">
            {(catalog?.harnesses || []).map((harness) => (
              <button
                key={harness}
                onClick={() => toggleSelection(selHarnesses, setSelHarnesses, harness)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                  selHarnesses.includes(harness)
                    ? "border-cyan-500/40 bg-cyan-50 text-cyan-800 dark:bg-cyan-500/15 dark:text-cyan-200"
                    : "border-zinc-200 bg-zinc-50 text-zinc-600 hover:border-zinc-300 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-400 dark:hover:border-white/[0.18]"
                }`}
              >
                {harness}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Models (models.yaml)
          </div>
          <div className="flex flex-wrap gap-2">
            {(catalog?.models || []).map((model) => (
              <button
                key={model.id}
                onClick={() => toggleSelection(selModels, setSelModels, model.id)}
                className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                  selModels.includes(model.id)
                    ? "border-emerald-500/40 bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200"
                    : "border-zinc-200 bg-zinc-50 text-zinc-600 hover:border-zinc-300 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-400 dark:hover:border-white/[0.18]"
                }`}
              >
                {model.id}
              </button>
            ))}
          </div>
          <input
            value={customModel}
            onChange={(e) => setCustomModel(e.target.value)}
            placeholder="Optional raw LiteLLM string (e.g. openrouter/qwen/...)"
            className={`${INPUT_CLS} mt-2.5`}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Settings Preset
            </label>
            <select
              value={settingsPath}
              onChange={(e) => setSettingsPath(e.target.value)}
              className={INPUT_CLS}
            >
              {(catalog?.presets || []).map((preset) => (
                <option key={preset.path} value={preset.path}>
                  {preset.name} ({preset.path})
                </option>
              ))}
            </select>
          </div>
          <div className="relative" ref={taskDropdownRef}>
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Tasks Scope
            </label>
            <button
              type="button"
              onClick={() => setTaskDropdownOpen((open) => !open)}
              className={`${INPUT_CLS} flex items-center justify-between text-left`}
            >
              <span className="truncate">
                {selTasks.length === 0
                  ? "No tasks selected"
                  : catalog?.tasks && selTasks.length === catalog.tasks.length
                    ? `All tasks (${catalog.tasks.length})`
                    : selTasks.length === 1
                      ? selTasks[0]
                      : `${selTasks.length} tasks selected`}
              </span>
              <span className="ml-2 text-[10px] text-zinc-400">
                {taskDropdownOpen ? "▲" : "▼"}
              </span>
            </button>

            {taskDropdownOpen && (
              <div className="absolute left-0 right-0 z-30 mt-1.5 rounded-xl border border-zinc-200 bg-white p-2 shadow-xl dark:border-white/[0.12] dark:bg-[#111114]">
                <div className="mb-2 flex items-center gap-1.5">
                  <input
                    value={taskSearch}
                    onChange={(e) => setTaskSearch(e.target.value)}
                    placeholder="Filter tasks..."
                    className="w-full rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-900 outline-none focus:border-cyan-500 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-white"
                  />
                  <button
                    type="button"
                    onClick={() => setSelTasks((catalog?.tasks || []).map((task) => task.id))}
                    className="shrink-0 rounded-md border border-zinc-200 px-2 py-1 text-[11px] font-medium text-zinc-700 hover:bg-zinc-100 dark:border-white/[0.1] dark:text-zinc-300 dark:hover:bg-white/[0.06]"
                  >
                    All
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelTasks([])}
                    className="shrink-0 rounded-md border border-zinc-200 px-2 py-1 text-[11px] font-medium text-zinc-700 hover:bg-zinc-100 dark:border-white/[0.1] dark:text-zinc-300 dark:hover:bg-white/[0.06]"
                  >
                    Clear
                  </button>
                </div>
                <div className="max-h-56 space-y-0.5 overflow-auto pr-1">
                  {(catalog?.tasks || [])
                    .filter(
                      (task) =>
                        !taskSearch.trim() ||
                        task.id.toLowerCase().includes(taskSearch.toLowerCase()) ||
                        task.category.toLowerCase().includes(taskSearch.toLowerCase())
                    )
                    .map((task) => {
                      const checked = selTasks.includes(task.id);
                      return (
                        <label
                          key={task.id}
                          className={`flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs transition ${
                            checked
                              ? "bg-cyan-50/80 text-zinc-900 dark:bg-cyan-500/10 dark:text-white"
                              : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/[0.04]"
                          }`}
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleSelection(selTasks, setSelTasks, task.id)}
                              className="h-3.5 w-3.5 rounded accent-cyan-600 dark:accent-cyan-400"
                            />
                            <span className="truncate font-mono">{task.id}</span>
                          </span>
                          <span className="shrink-0 rounded border border-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:border-white/[0.08] dark:text-zinc-400">
                            {task.category}
                          </span>
                        </label>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Trials per Task (N)
            </label>
            <input
              type="number"
              min={1}
              max={20}
              value={nTrials}
              onChange={(e) => setNTrials(Number(e.target.value) || 1)}
              className={`${INPUT_CLS} tabular-nums`}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Experiment ID (optional)
            </label>
            <input
              value={expIdInput}
              onChange={(e) => setExpIdInput(e.target.value)}
              placeholder="auto-generated"
              className={INPUT_CLS}
            />
          </div>
        </div>

        {/* Pre-run Cost Estimate Card */}
        <div className={`${SUB_CARD_CLS} space-y-2 p-3.5`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                Estimated Experiment Cost
              </div>
              <div className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                {costEstimate.nTasks} tasks × {costEstimate.nTrials} trials ×{" "}
                {costEstimate.nConfigs} configs ={" "}
                <span className="font-semibold text-zinc-700 dark:text-zinc-200">
                  {costEstimate.totalTrials} trials
                </span>{" "}
                (~{(costEstimate.totalTokens / 1000).toFixed(0)}k tokens)
              </div>
            </div>
            <div className="text-right font-mono">
              <div className="text-base font-bold text-emerald-600 dark:text-emerald-400">
                ~${costEstimate.totalCostUsd.toFixed(2)}
              </div>
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400">
                range ${(costEstimate.totalCostUsd * 0.7).toFixed(2)}–$
                {(costEstimate.totalCostUsd * 1.3).toFixed(2)}
              </div>
            </div>
          </div>

          {costEstimate.perConfig.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5 text-[11px] font-mono text-zinc-600 dark:text-zinc-400">
              {costEstimate.perConfig.map((cfg) => (
                <span
                  key={cfg.name}
                  className="rounded border border-zinc-200 bg-white px-2 py-0.5 dark:border-white/[0.08] dark:bg-[#111114]"
                >
                  {cfg.name}: ~{(cfg.avgTokens / 1000).toFixed(1)}k tok/trial → $
                  {cfg.costUsd.toFixed(2)}
                </span>
              ))}
              {costEstimate.judgeTrials > 0 && (
                <span className="rounded border border-zinc-200 bg-white px-2 py-0.5 dark:border-white/[0.08] dark:bg-[#111114]">
                  +{costEstimate.judgeTrials} judge calls: ${costEstimate.judgeCostUsd.toFixed(3)}
                </span>
              )}
            </div>
          )}
        </div>

        <button
          onClick={onLaunchRun}
          disabled={isLaunching || selTasks.length === 0 || costEstimate.nConfigs === 0}
          className="w-full rounded-lg bg-cyan-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50 dark:bg-cyan-500 dark:text-zinc-950 dark:hover:bg-cyan-400"
        >
          {isLaunching
            ? "Launching Experiment..."
            : `Run Experiment (${costEstimate.nConfigs} ${costEstimate.nConfigs === 1 ? "config" : "configs"} · ${costEstimate.totalTrials} ${costEstimate.totalTrials === 1 ? "trial" : "trials"} · ~$${costEstimate.totalCostUsd.toFixed(2)})`}
        </button>
      </section>

      <section className={`${CARD_CLS} space-y-3 p-5`}>
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
          Experiments ({experiments.length})
        </h2>
        <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
          {experiments.map((exp) => (
            <div
              key={exp.id}
              onClick={() => onSelectExperiment(exp.id)}
              className={`cursor-pointer rounded-lg border p-3 transition ${
                selectedExp === exp.id
                  ? "border-cyan-500/40 bg-cyan-50/70 dark:bg-cyan-500/[0.07]"
                  : "border-zinc-200 bg-zinc-50/70 hover:border-zinc-300 dark:border-white/[0.06] dark:bg-[#09090b]/70 dark:hover:border-white/[0.15]"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs font-medium text-zinc-900 dark:text-white">
                  {exp.id}
                </span>
                <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                  <span className="font-medium text-emerald-600 dark:text-emerald-300">
                    {exp.passedCount}
                  </span>
                  /{exp.trialCount}
                  {exp.expectedTrials && exp.trialCount < exp.expectedTrials
                    ? ` (of ${exp.expectedTrials})`
                    : ""}{" "}
                  passed
                  {exp.infraErrors > 0 && (
                    <span className="ml-2 text-amber-600 dark:text-amber-400">
                      {exp.infraErrors} infra
                    </span>
                  )}
                </span>
              </div>
              <div className="mt-1 text-xs text-zinc-500">
                Configs: {exp.configs.join(", ") || "-"}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

import type { ExperimentDetail, ExperimentSummaryItem } from "../types";
import { CARD_CLS, SUB_CARD_CLS } from "./uiStyles";

interface CompareAndFailuresTabProps {
  selectedExp: string;
  activeExpMeta: ExperimentSummaryItem | null;
  activeJobStatus: string;
  activeJobLogs: string[];
  progressPct: number | null;
  expDetail: ExperimentDetail | null;
  configA: string;
  setConfigA: (next: string) => void;
  configB: string;
  setConfigB: (next: string) => void;
  onInspectTrial: (trialId: string) => void;
}

export function CompareAndFailuresTab({
  selectedExp,
  activeExpMeta,
  activeJobStatus,
  activeJobLogs,
  progressPct,
  expDetail,
  configA,
  setConfigA,
  configB,
  setConfigB,
  onInspectTrial,
}: CompareAndFailuresTabProps) {
  const showRunningBanner =
    activeJobStatus === "running" ||
    !expDetail ||
    Boolean(activeExpMeta?.expectedTrials && activeExpMeta.trialCount < activeExpMeta.expectedTrials);

  return (
    <div className="space-y-5">
      {showRunningBanner && (
        <div className={`${CARD_CLS} flex flex-wrap items-center justify-between gap-4 p-4`}>
          <div className="flex items-center gap-3">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent" />
            <div>
              <div className="text-xs font-semibold text-zinc-900 dark:text-white">
                {activeExpMeta
                  ? `Running ${selectedExp} — ${activeExpMeta.trialCount}${activeExpMeta.expectedTrials ? ` / ${activeExpMeta.expectedTrials}` : ""} trials finished`
                  : `Starting ${selectedExp || "experiment"}...`}
              </div>
              <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {activeJobLogs[activeJobLogs.length - 1] ||
                  "Spinning up isolated harness containers and streaming results as each trial finishes..."}
              </div>
            </div>
          </div>
          {progressPct !== null && (
            <div className="flex items-center gap-2.5">
              <div className="h-2 w-36 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="font-mono text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                {progressPct}%
              </span>
            </div>
          )}
        </div>
      )}

      {expDetail && (
        <>
          <section className={`${CARD_CLS} overflow-x-auto p-5`}>
            <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-white">
              Quality vs Cost vs Latency
            </h2>
            <table className="w-full text-left text-xs tabular-nums">
              <thead className="border-b border-zinc-200 text-zinc-500 dark:border-white/[0.08]">
                <tr>
                  <th className="py-2 pr-4 font-medium">Config</th>
                  <th className="py-2 pr-4 font-medium">Completed</th>
                  <th className="py-2 pr-4 font-medium">Infra Err</th>
                  <th className="py-2 pr-4 font-medium">Mean Score</th>
                  <th className="py-2 pr-4 font-medium">Pass Rate</th>
                  <th className="py-2 pr-4 font-medium">Total Cost</th>
                  <th className="py-2 pr-4 font-medium">Avg / p95 Time</th>
                  <th className="py-2 font-medium">Avg Tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.05]">
                {Object.entries(expDetail.summaries).map(([configName, summary]) => (
                  <tr key={configName} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02]">
                    <td className="py-2.5 pr-4 font-mono font-medium text-zinc-900 dark:text-white">
                      {configName}
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">
                      {summary.completed}
                    </td>
                    <td className="py-2.5 pr-4 text-amber-600 dark:text-amber-300">
                      {summary.infra_errors}
                    </td>
                    <td className="py-2.5 pr-4 font-semibold text-emerald-600 dark:text-emerald-300">
                      {summary.mean_score.toFixed(3)}
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-800 dark:text-zinc-200">
                      {(summary.pass_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">
                      ${summary.total_cost_usd.toFixed(5)}
                    </td>
                    <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">
                      {summary.avg_runtime_sec}s / {summary.p95_runtime_sec}s
                    </td>
                    <td className="py-2.5 text-zinc-700 dark:text-zinc-300">
                      {summary.avg_tokens.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {expDetail.comparison && (
            <section className={`${CARD_CLS} space-y-4 p-5`}>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-zinc-500 dark:text-zinc-400">Compare</span>
                  <select
                    value={configA}
                    onChange={(e) => setConfigA(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-900 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-white"
                  >
                    {expDetail.config_names.map((cfgName) => (
                      <option key={cfgName} value={cfgName}>
                        {cfgName}
                      </option>
                    ))}
                  </select>
                  <span className="text-zinc-400 dark:text-zinc-500">vs</span>
                  <select
                    value={configB}
                    onChange={(e) => setConfigB(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-900 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-white"
                  >
                    {expDetail.config_names.map((cfgName) => (
                      <option key={cfgName} value={cfgName}>
                        {cfgName}
                      </option>
                    ))}
                  </select>
                </div>
                <span
                  className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                    expDetail.comparison.verdict === "NOISE"
                      ? "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-white/[0.1] dark:bg-zinc-900 dark:text-zinc-300"
                      : "border-emerald-500/30 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                  }`}
                >
                  {expDetail.comparison.verdict}
                </span>
              </div>

              <div className="grid gap-3 tabular-nums sm:grid-cols-3">
                <div className={`${SUB_CARD_CLS} p-3.5`}>
                  <div className="text-xs text-zinc-500">Delta (B - A)</div>
                  <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                    {expDetail.comparison.delta_mean >= 0 ? "+" : ""}
                    {expDetail.comparison.delta_mean.toFixed(4)}
                  </div>
                </div>
                <div className={`${SUB_CARD_CLS} p-3.5`}>
                  <div className="text-xs text-zinc-500">95% Bootstrap CI</div>
                  <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                    [{expDetail.comparison.ci_95[0]}, {expDetail.comparison.ci_95[1]}]
                  </div>
                </div>
                <div className={`${SUB_CARD_CLS} p-3.5`}>
                  <div className="text-xs text-zinc-500">Exact McNemar p-value</div>
                  <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                    {expDetail.comparison.mcnemar_p}
                  </div>
                </div>
              </div>

              {expDetail.comparison.warnings.length > 0 && (
                <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/[0.06] dark:text-amber-200">
                  {expDetail.comparison.warnings.map((warningText, index) => (
                    <div key={index}>WARNING: {warningText}</div>
                  ))}
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs tabular-nums">
                  <thead className="border-b border-zinc-200 text-zinc-500 dark:border-white/[0.08]">
                    <tr>
                      <th className="py-2 pr-4 font-medium">Task</th>
                      <th className="py-2 pr-4 font-medium">{expDetail.comparison.config_a}</th>
                      <th className="py-2 pr-4 font-medium">{expDetail.comparison.config_b}</th>
                      <th className="py-2 pr-4 font-medium">Delta</th>
                      <th className="py-2 font-medium">95% CI</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.05]">
                    {expDetail.comparison.per_task.map((taskRow) => (
                      <tr key={taskRow.task_id} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02]">
                        <td className="py-2 pr-4 font-mono text-zinc-800 dark:text-zinc-200">
                          {taskRow.task_id}
                        </td>
                        <td className="py-2 pr-4 text-zinc-700 dark:text-zinc-300">
                          {taskRow.score_a.toFixed(2)} (n={taskRow.n_a})
                        </td>
                        <td className="py-2 pr-4 text-zinc-700 dark:text-zinc-300">
                          {taskRow.score_b.toFixed(2)} (n={taskRow.n_b})
                        </td>
                        <td
                          className={`py-2 pr-4 font-semibold ${
                            taskRow.delta > 0
                              ? "text-emerald-600 dark:text-emerald-400"
                              : taskRow.delta < 0
                                ? "text-rose-600 dark:text-rose-400"
                                : "text-zinc-400 dark:text-zinc-500"
                          }`}
                        >
                          {taskRow.delta >= 0 ? "+" : ""}
                          {taskRow.delta.toFixed(2)}
                        </td>
                        <td className="py-2 text-zinc-500 dark:text-zinc-400">
                          [{taskRow.ci_95[0]}, {taskRow.ci_95[1]}] {taskRow.is_noise ? "(noise)" : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className={`${CARD_CLS} p-5`}>
            <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-white">
              Failure Breakdown
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {Object.entries(expDetail.failures).map(([cfg, info]) => (
                <div key={cfg} className={`${SUB_CARD_CLS} p-3.5 text-xs`}>
                  <div className="mb-2 flex justify-between font-mono font-semibold text-zinc-900 dark:text-white">
                    <span>{cfg}</span>
                    <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
                      {info.failed} failed out of {info.total}
                    </span>
                  </div>
                  {Object.keys(info.categories).length === 0 ? (
                    <div className="text-emerald-600 dark:text-emerald-400">No failures</div>
                  ) : (
                    <ul className="space-y-1.5">
                      {Object.entries(info.categories).map(([cat, count]) => (
                        <li key={cat} className="flex items-center justify-between">
                          <span className="text-amber-700 dark:text-amber-300">
                            {cat}: {count}
                          </span>
                          {info.examples[cat]?.[0] && (
                            <button
                              onClick={() => onInspectTrial(info.examples[cat][0])}
                              className="text-cyan-700 underline decoration-cyan-500/40 hover:text-cyan-600 dark:text-cyan-300 dark:hover:text-cyan-200"
                            >
                              inspect example
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

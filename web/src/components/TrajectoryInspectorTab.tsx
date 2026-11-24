import type { TraceEvent, TrialItem } from "../types";
import { CARD_CLS, EVENT_COLORS, SUB_CARD_CLS, type TrialFilter } from "./uiStyles";

interface TrajectoryInspectorTabProps {
  filteredTrials: TrialItem[];
  trialFilter: TrialFilter;
  setTrialFilter: (next: TrialFilter) => void;
  selectedTrialId: string;
  setSelectedTrialId: (trialId: string) => void;
  trialDetail: { trial: TrialItem; events: TraceEvent[] } | null;
}

export function TrajectoryInspectorTab({
  filteredTrials,
  trialFilter,
  setTrialFilter,
  selectedTrialId,
  setSelectedTrialId,
  trialDetail,
}: TrajectoryInspectorTabProps) {
  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <section className={`${CARD_CLS} space-y-3 p-4 lg:col-span-4`}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
            Trials ({filteredTrials.length})
          </h2>
          <select
            value={trialFilter}
            onChange={(e) => setTrialFilter(e.target.value as TrialFilter)}
            className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1 text-xs text-zinc-800 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-zinc-200"
          >
            <option value="all">All</option>
            <option value="failed">Failed</option>
            <option value="passed">Passed</option>
            <option value="infra">Infra Error</option>
          </select>
        </div>
        <div className="max-h-[620px] space-y-1.5 overflow-auto pr-1">
          {filteredTrials.map((trial) => (
            <div
              key={trial.trial_id}
              onClick={() => setSelectedTrialId(trial.trial_id)}
              className={`cursor-pointer rounded-lg border p-2.5 text-xs transition ${
                selectedTrialId === trial.trial_id
                  ? "border-cyan-500/40 bg-cyan-50/70 dark:bg-cyan-500/[0.07]"
                  : "border-zinc-200 bg-zinc-50/70 hover:border-zinc-300 dark:border-white/[0.06] dark:bg-[#09090b]/70 dark:hover:border-white/[0.15]"
              }`}
            >
              <div className="flex items-center justify-between font-medium">
                <span className="truncate font-mono text-zinc-800 dark:text-zinc-200">
                  {trial.task_id}
                </span>
                <span
                  className={
                    trial.passed
                      ? "text-emerald-600 dark:text-emerald-400"
                      : trial.status === "infra_error"
                        ? "text-amber-600 dark:text-amber-400"
                        : "text-rose-600 dark:text-rose-400"
                  }
                >
                  {trial.passed ? "PASS" : trial.status === "infra_error" ? "INFRA" : "FAIL"}
                </span>
              </div>
              <div className="mt-0.5 flex justify-between text-zinc-500">
                <span>
                  {trial.config_name} (t{trial.trial_index})
                </span>
                <span>
                  {trial.failure_category || (trial.score !== null ? `score=${trial.score}` : "")}
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={`${CARD_CLS} space-y-4 p-5 lg:col-span-8`}>
        {!trialDetail ? (
          <div className="text-sm text-zinc-500 dark:text-zinc-400">
            Select a trial to inspect its trajectory.
          </div>
        ) : (
          <>
            <div className={`${SUB_CARD_CLS} p-4 text-xs`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold text-zinc-900 dark:text-white">
                  {trialDetail.trial.trial_id}
                </span>
                <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 font-mono text-zinc-700 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-zinc-200">
                  {trialDetail.trial.failure_category ||
                    (trialDetail.trial.passed ? "PASSED" : "FAILED")}
                </span>
              </div>
              <div className="mt-2.5 grid gap-2 tabular-nums text-zinc-600 dark:text-zinc-300 sm:grid-cols-4">
                <div>
                  Score:{" "}
                  <b className="text-zinc-900 dark:text-white">{trialDetail.trial.score ?? "-"}</b>
                </div>
                <div>
                  Tokens:{" "}
                  <b className="text-zinc-900 dark:text-white">
                    {trialDetail.trial.input_tokens + trialDetail.trial.output_tokens}
                  </b>
                </div>
                <div>
                  Cost:{" "}
                  <b className="text-zinc-900 dark:text-white">
                    ${trialDetail.trial.cost_usd.toFixed(5)}
                  </b>
                </div>
                <div>
                  Time:{" "}
                  <b className="text-zinc-900 dark:text-white">{trialDetail.trial.runtime_sec}s</b>{" "}
                  ({trialDetail.trial.steps} steps)
                </div>
              </div>
              <div className="mt-2 text-zinc-600 dark:text-zinc-400">
                <b className="text-zinc-900 dark:text-zinc-200">
                  Grader ({trialDetail.trial.grade?.grader_type || "-"}):
                </b>{" "}
                {trialDetail.trial.grade?.reasoning || trialDetail.trial.error_message || "-"}
              </div>
            </div>

            <div className="max-h-[520px] space-y-2 overflow-auto pr-1">
              {trialDetail.events.map((event) => (
                <div
                  key={event.seq}
                  className={`rounded-lg border p-3 text-xs ${
                    EVENT_COLORS[event.type] ||
                    "border-zinc-200 bg-zinc-50 text-zinc-800 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-200"
                  }`}
                >
                  <div className="mb-1 flex justify-between font-mono text-[11px] opacity-75">
                    <span>
                      #{event.seq} {event.type}
                    </span>
                    <span>{event.ts}</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                    {JSON.stringify(event.payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

import type { CalibrationReport } from "../types";
import { CARD_CLS, SUB_CARD_CLS } from "./uiStyles";

interface JudgeCalibrationTabProps {
  calibrations: CalibrationReport[];
  activeJobStatus: string;
  onCalibrate: () => void;
}

export function JudgeCalibrationTab({
  calibrations,
  activeJobStatus,
  onCalibrate,
}: JudgeCalibrationTabProps) {
  return (
    <div className="space-y-4">
      <div className={`${CARD_CLS} flex flex-wrap items-center justify-between gap-3 p-4`}>
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
            LLM-as-Judge Calibration
          </h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Evaluates judge agreement against 30 human-labelled examples in
            calibration/judge_labels.jsonl
          </p>
        </div>
        <button
          onClick={onCalibrate}
          disabled={activeJobStatus === "running"}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50 dark:bg-cyan-500 dark:text-zinc-950 dark:hover:bg-cyan-400"
        >
          Run Calibration (gemini-flash × 3)
        </button>
      </div>

      {calibrations.length === 0 ? (
        <div className={`${CARD_CLS} p-6 text-sm text-zinc-500 dark:text-zinc-400`}>
          No calibration reports yet. Click &quot;Run Calibration&quot; or run{" "}
          <code className="text-cyan-700 dark:text-cyan-300">
            uv run eval-calibrate --judge gemini-flash
          </code>
          .
        </div>
      ) : (
        calibrations.map((report, idx) => (
          <section key={idx} className={`${CARD_CLS} space-y-4 p-5`}>
            <div className="flex items-center justify-between">
              <div className="font-mono text-xs font-semibold text-zinc-900 dark:text-white">
                {report.judge_model} — {report.timestamp}
              </div>
              <span
                className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                  report.verdict === "TRUSTED"
                    ? "border-emerald-500/30 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                    : "border-rose-500/30 bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
                }`}
              >
                {report.verdict}
              </span>
            </div>
            <div className="grid gap-3 tabular-nums sm:grid-cols-5">
              <div className={`${SUB_CARD_CLS} p-3 text-xs`}>
                <div className="text-zinc-500">Cohen&apos;s κ</div>
                <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">
                  {report.cohens_kappa}
                </div>
              </div>
              <div className={`${SUB_CARD_CLS} p-3 text-xs`}>
                <div className="text-zinc-500">Accuracy</div>
                <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">
                  {(report.accuracy * 100).toFixed(1)}%
                </div>
              </div>
              <div className={`${SUB_CARD_CLS} p-3 text-xs`}>
                <div className="text-zinc-500">Score MAE</div>
                <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">
                  {report.score_mae}
                </div>
              </div>
              <div className={`${SUB_CARD_CLS} p-3 text-xs`}>
                <div className="text-zinc-500">Self-Agreement</div>
                <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">
                  {(report.self_agreement * 100).toFixed(1)}%
                </div>
              </div>
              <div className={`${SUB_CARD_CLS} p-3 text-xs`}>
                <div className="text-zinc-500">Confusion (TP/FP/TN/FN)</div>
                <div className="mt-1 text-sm font-semibold text-zinc-900 dark:text-white">
                  {report.confusion_matrix.tp}/{report.confusion_matrix.fp}/
                  {report.confusion_matrix.tn}/{report.confusion_matrix.fn}
                </div>
              </div>
            </div>
            {report.disagreements.length > 0 && (
              <div className="overflow-x-auto">
                <h3 className="mb-2 text-xs font-semibold uppercase text-zinc-500">
                  Disagreements ({report.disagreements.length})
                </h3>
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-zinc-200 text-zinc-500 dark:border-white/[0.08]">
                    <tr>
                      <th className="py-1.5 pr-3 font-medium">ID</th>
                      <th className="py-1.5 pr-3 font-medium">Human</th>
                      <th className="py-1.5 pr-3 font-medium">Judge</th>
                      <th className="py-1.5 font-medium">Notes / Reasoning</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.05]">
                    {report.disagreements.map((disagreement) => (
                      <tr key={disagreement.id}>
                        <td className="py-2 pr-3 font-mono text-zinc-800 dark:text-zinc-200">
                          {disagreement.id}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-zinc-700 dark:text-zinc-300">
                          {String(disagreement.human_passed)} ({disagreement.human_score})
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-zinc-700 dark:text-zinc-300">
                          {String(disagreement.judge_passed)} ({disagreement.judge_score})
                        </td>
                        <td className="py-2 text-zinc-600 dark:text-zinc-400">
                          {disagreement.notes} | {disagreement.judge_reasoning}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))
      )}
    </div>
  );
}

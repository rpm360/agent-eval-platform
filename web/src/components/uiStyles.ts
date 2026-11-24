export type Tab = "experiments" | "compare" | "inspector" | "calibration";
export type Theme = "dark" | "light";
export type TrialFilter = "all" | "failed" | "passed" | "infra";

export const CARD_CLS =
  "rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-white/[0.08] dark:bg-[#111114] dark:shadow-none";

export const SUB_CARD_CLS =
  "rounded-lg border border-zinc-200 bg-zinc-50 dark:border-white/[0.06] dark:bg-[#09090b]";

export const INPUT_CLS =
  "w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-2 text-xs text-zinc-900 placeholder:text-zinc-400 outline-none focus:border-cyan-500 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-white dark:placeholder:text-zinc-600 dark:focus:border-cyan-500/50";

export const EVENT_COLORS: Record<string, string> = {
  session_start:
    "border-cyan-500/30 bg-cyan-50 text-cyan-900 dark:border-cyan-500/25 dark:bg-cyan-500/[0.06] dark:text-cyan-200",
  message:
    "border-zinc-200 bg-zinc-50 text-zinc-800 dark:border-white/[0.08] dark:bg-white/[0.02] dark:text-zinc-200",
  tool_call:
    "border-amber-500/30 bg-amber-50 text-amber-900 dark:border-amber-500/25 dark:bg-amber-500/[0.06] dark:text-amber-200",
  tool_result:
    "border-emerald-500/30 bg-emerald-50 text-emerald-900 dark:border-emerald-500/25 dark:bg-emerald-500/[0.06] dark:text-emerald-200",
  memory_op:
    "border-violet-500/30 bg-violet-50 text-violet-900 dark:border-violet-500/25 dark:bg-violet-500/[0.06] dark:text-violet-200",
  skill_invoked:
    "border-sky-500/30 bg-sky-50 text-sky-900 dark:border-sky-500/25 dark:bg-sky-500/[0.06] dark:text-sky-200",
  error:
    "border-rose-500/35 bg-rose-50 text-rose-900 dark:border-rose-500/35 dark:bg-rose-500/[0.08] dark:text-rose-200",
  session_end:
    "border-cyan-500/30 bg-cyan-50 text-cyan-900 dark:border-cyan-500/25 dark:bg-cyan-500/[0.06] dark:text-cyan-200",
};

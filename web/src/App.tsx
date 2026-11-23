import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CalibrationReport,
  CatalogResponse,
  ExperimentDetail,
  ExperimentSummaryItem,
  TraceEvent,
  TrialItem,
} from "./types";

type Tab = "experiments" | "compare" | "inspector" | "calibration";
type Theme = "dark" | "light";

const EVENT_COLORS: Record<string, string> = {
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

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem("aep-theme");
      return saved === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    try {
      localStorage.setItem("aep-theme", theme);
    } catch {
      // ignore storage errors
    }
  }, [theme]);

  const [tab, setTab] = useState<Tab>("experiments");
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [experiments, setExperiments] = useState<ExperimentSummaryItem[]>([]);
  const [selectedExp, setSelectedExp] = useState<string>("");
  const [expDetail, setExpDetail] = useState<ExperimentDetail | null>(null);
  const [configA, setConfigA] = useState<string>("");
  const [configB, setConfigB] = useState<string>("");
  const [trials, setTrials] = useState<TrialItem[]>([]);
  const [selectedTrialId, setSelectedTrialId] = useState<string>("");
  const [trialDetail, setTrialDetail] = useState<{ trial: TrialItem; events: TraceEvent[] } | null>(null);
  const [calibrations, setCalibrations] = useState<CalibrationReport[]>([]);

  // Matrix launcher state
  const [selHarnesses, setSelHarnesses] = useState<string[]>(["hermes", "langgraph"]);
  const [selModels, setSelModels] = useState<string[]>(["gemini-flash"]);
  const [customModel, setCustomModel] = useState<string>("");
  const [settingsPath, setSettingsPath] = useState<string>("configs/default.yaml");
  const [selTasks, setSelTasks] = useState<string[]>([]);
  const [tasksInitialized, setTasksInitialized] = useState<boolean>(false);
  const [taskDropdownOpen, setTaskDropdownOpen] = useState<boolean>(false);
  const [taskSearch, setTaskSearch] = useState<string>("");
  const taskDropdownRef = useRef<HTMLDivElement | null>(null);
  const [nTrials, setNTrials] = useState<number>(1);
  const [expIdInput, setExpIdInput] = useState<string>("");

  // Live streaming & job state
  const [liveConnected, setLiveConnected] = useState<boolean>(false);
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [activeJobLogs, setActiveJobLogs] = useState<string[]>([]);
  const [activeJobStatus, setActiveJobStatus] = useState<string>("");
  const [trialFilter, setTrialFilter] = useState<"all" | "failed" | "passed" | "infra">("all");
  const logsEndRef = useRef<HTMLPreElement | null>(null);

  const loadExperimentData = useCallback(async (expId: string, a: string, b: string) => {
    if (!expId) return;
    const qs = new URLSearchParams();
    if (a) qs.set("a", a);
    if (b) qs.set("b", b);

    const [detailRes, trialsRes] = await Promise.all([
      fetch(`/api/experiments/${encodeURIComponent(expId)}?${qs}`).then((r) => (r.ok ? r.json() : null)),
      fetch(`/api/experiments/${encodeURIComponent(expId)}/trials`).then((r) =>
        r.ok ? r.json() : { trials: [] }
      ),
    ]);

    if (detailRes) {
      setExpDetail(detailRes);
      if (detailRes.comparison) {
        setConfigA((prev) => prev || detailRes.comparison.config_a);
        setConfigB((prev) => prev || detailRes.comparison.config_b);
      }
    }
    const nextTrials: TrialItem[] = trialsRes.trials || [];
    setTrials(nextTrials);
    setSelectedTrialId((prev) =>
      nextTrials.length && !nextTrials.some((t) => t.trial_id === prev) ? nextTrials[0].trial_id : prev
    );
  }, []);

  const refreshAll = useCallback(async (keepExp?: string) => {
    const [catRes, expRes, calRes] = await Promise.all([
      fetch("/api/catalog").then((r) => r.json()),
      fetch("/api/experiments").then((r) => r.json()),
      fetch("/api/calibration").then((r) => r.json()),
    ]);
    setCatalog(catRes);
    if (!tasksInitialized && catRes?.tasks?.length) {
      setSelTasks(catRes.tasks.map((t: { id: string }) => t.id));
      setTasksInitialized(true);
    }
    if (catRes?.models?.length) {
      setSelModels((prev) => {
        const validIds = new Set(catRes.models.map((m: { id: string }) => m.id));
        const kept = prev.filter((id) => validIds.has(id));
        if (kept.length > 0) return kept;
        const firstReal = catRes.models.find((m: { id: string }) => m.id !== "mock") || catRes.models[0];
        return firstReal ? [firstReal.id] : [];
      });
    }
    setExperiments(expRes.experiments || []);
    setCalibrations(calRes.reports || []);
    setSelectedExp((prev) => keepExp || prev || expRes.experiments?.[0]?.id || "");
  }, [tasksInitialized]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (!selectedExp) return;
    loadExperimentData(selectedExp, configA, configB);
  }, [selectedExp, configA, configB, loadExperimentData]);

  // Real-time SSE stream watching results/ and the selected experiment's trials/
  useEffect(() => {
    const qs = selectedExp ? `?expId=${encodeURIComponent(selectedExp)}` : "";
    const es = new EventSource(`/api/events${qs}`);
    es.onopen = () => setLiveConnected(true);
    es.onerror = () => setLiveConnected(false);

    es.addEventListener("experiments", (ev) => {
      setLiveConnected(true);
      const data = JSON.parse((ev as MessageEvent).data) as { experiments: ExperimentSummaryItem[] };
      setExperiments(data.experiments || []);
      setSelectedExp((prev) => prev || data.experiments?.[0]?.id || "");
    });

    es.addEventListener("trial_update", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as { expId: string };
      if (data.expId === selectedExp) {
        void loadExperimentData(selectedExp, configA, configB);
      }
    });

    return () => {
      es.close();
      setLiveConnected(false);
    };
  }, [selectedExp, configA, configB, loadExperimentData]);

  useEffect(() => {
    if (!selectedExp || !selectedTrialId) {
      setTrialDetail(null);
      return;
    }
    fetch(`/api/experiments/${encodeURIComponent(selectedExp)}/trials/${encodeURIComponent(selectedTrialId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setTrialDetail);
  }, [selectedExp, selectedTrialId, trials.length]);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollTop = logsEndRef.current.scrollHeight;
    }
  }, [activeJobLogs]);

  useEffect(() => {
    if (!taskDropdownOpen) return;
    const onDown = (e: MouseEvent) => {
      if (taskDropdownRef.current && !taskDropdownRef.current.contains(e.target as Node)) {
        setTaskDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [taskDropdownOpen]);

  function streamJob(jobId: string, targetExpId?: string) {
    setActiveJobLogs([]);
    setActiveJobStatus("running");
    if (targetExpId) {
      setConfigA("");
      setConfigB("");
      setExpDetail(null);
      setTrials([]);
      setSelectedExp(targetExpId);
      setTab("compare");
    }

    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.addEventListener("log", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as { line: string };
      if (data.line.startsWith("[AEP_TRIAL] ")) {
        try {
          const payload = JSON.parse(data.line.slice("[AEP_TRIAL] ".length)) as {
            experiment_id: string;
            trial_id: string;
            status: string;
            passed: boolean | null;
            score: number | null;
          };
          const badge = payload.passed ? "PASS" : payload.status === "infra_error" ? "INFRA" : "FAIL";
          setActiveJobLogs((prev) => [
            ...prev.slice(-400),
            `✓ ${payload.trial_id} → ${badge} (score=${payload.score ?? "-"})`,
          ]);
          if (payload.experiment_id) {
            void loadExperimentData(payload.experiment_id, "", "");
          }
          return;
        } catch {
          // fall through to raw line
        }
      }
      setActiveJobLogs((prev) => [...prev.slice(-400), data.line]);
    });
    es.addEventListener("done", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as { status: string };
      setActiveJobStatus(data.status);
      es.close();
      void refreshAll(targetExpId);
      if (targetExpId) {
        void loadExperimentData(targetExpId, configA, configB);
      }
    });
  }

  async function handleLaunchRun() {
    if (isLaunching) return;
    setIsLaunching(true);
    try {
      const models = [...selModels];
      if (customModel.trim()) models.push(customModel.trim());
      const allTaskIds = (catalog?.tasks || []).map((t) => t.id);
      const tasksPaths =
        allTaskIds.length > 0 && selTasks.length === allTaskIds.length
          ? ["tasks"]
          : selTasks.map((id) => `tasks/${id}`);
      const res = await fetch("/api/experiments/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          harnesses: selHarnesses,
          models,
          settingsPath,
          tasksPaths,
          trials: nTrials,
          expId: expIdInput.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (data.jobId) {
        streamJob(data.jobId, data.expId);
      }
    } finally {
      setTimeout(() => setIsLaunching(false), 3000);
    }
  }

  async function handleRetry() {
    if (!selectedExp) return;
    const res = await fetch(`/api/experiments/${encodeURIComponent(selectedExp)}/retry`, { method: "POST" });
    const data = await res.json();
    if (data.jobId) streamJob(data.jobId, selectedExp);
  }

  async function handleCalibrate() {
    const res = await fetch("/api/calibration/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ judge: "gemini-flash", repeats: 3 }),
    });
    const data = await res.json();
    if (data.jobId) streamJob(data.jobId);
  }

  function toggleItem(list: string[], setList: (v: string[]) => void, val: string) {
    setList(list.includes(val) ? list.filter((x) => x !== val) : [...list, val]);
  }

  const activeExpMeta = useMemo(
    () => experiments.find((e) => e.id === selectedExp) || null,
    [experiments, selectedExp]
  );

  const progressPct = useMemo(() => {
    if (!activeExpMeta?.expectedTrials || activeExpMeta.expectedTrials <= 0) return null;
    return Math.min(100, Math.round((activeExpMeta.trialCount / activeExpMeta.expectedTrials) * 100));
  }, [activeExpMeta]);

  // Pre-launch cost estimate: tasks × trials × configs × average tokens × price
  const costEstimate = useMemo(() => {
    const activeModels = [...selModels, ...(customModel.trim() ? [customModel.trim()] : [])];
    const nTasks = selTasks.length;
    const nConfigs = selHarnesses.length * activeModels.length;
    const totalTrials = nTasks * nTrials * nConfigs;

    // Empirical averages from hermes_langgraph__gemini-flash__2026-11-23_13-32-24
    const AVG_TOKENS_BY_HARNESS: Record<string, { inTok: number; outTok: number }> = {
      hermes: { inTok: 49300, outTok: 1200 },
      langgraph: { inTok: 19900, outTok: 1800 },
    };
    const DEFAULT_TOKENS = { inTok: 34600, outTok: 1500 };

    const modelLookup = new Map((catalog?.models || []).map((m) => [m.id, m]));
    let totalCostUsd = 0;
    let totalTokens = 0;
    const perConfig: Array<{ name: string; trials: number; avgTokens: number; costUsd: number }> = [];

    for (const h of selHarnesses) {
      const tok = AVG_TOKENS_BY_HARNESS[h] || DEFAULT_TOKENS;
      const avgTokPerTrial = tok.inTok + tok.outTok;
      for (const mId of activeModels) {
        const mInfo = modelLookup.get(mId);
        const inRate = mInfo?.pricing?.input_per_mtok ?? 0.75;
        const outRate = mInfo?.pricing?.output_per_mtok ?? 3.75;
        const costPerTrial = (tok.inTok / 1_000_000) * inRate + (tok.outTok / 1_000_000) * outRate;
        const cfgTrials = nTasks * nTrials;
        const cfgCost = cfgTrials * costPerTrial;
        totalCostUsd += cfgCost;
        totalTokens += cfgTrials * avgTokPerTrial;
        perConfig.push({
          name: `${h}-${mId.replace(/\//g, "-")}`,
          trials: cfgTrials,
          avgTokens: avgTokPerTrial,
          costUsd: cfgCost,
        });
      }
    }

    // Add LLM-as-judge grading overhead (~2,000 in + 400 out tokens per judge trial on default gemini-flash)
    const selectedTaskSet = new Set(selTasks);
    const judgeTaskCount = (catalog?.tasks || []).filter(
      (t) => selectedTaskSet.has(t.id) && t.grader?.type === "llm_judge"
    ).length;
    const judgeModel =
      modelLookup.get("gemini-flash") ||
      modelLookup.get("gemini-flash-lite-3.1") ||
      (catalog?.models || []).find((m) => m.id !== "mock");
    const jIn = judgeModel?.pricing?.input_per_mtok ?? 0.25;
    const jOut = judgeModel?.pricing?.output_per_mtok ?? 1.5;
    const judgeCostPerTrial = (2000 / 1_000_000) * jIn + (400 / 1_000_000) * jOut;
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
  }, [selHarnesses, selModels, customModel, selTasks, nTrials, catalog]);

  const filteredTrials = trials.filter((t) => {
    if (trialFilter === "failed") return t.status === "completed" && !t.passed;
    if (trialFilter === "passed") return t.status === "completed" && Boolean(t.passed);
    if (trialFilter === "infra") return t.status === "infra_error";
    return true;
  });

  const cardCls =
    "rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-white/[0.08] dark:bg-[#111114] dark:shadow-none";
  const subCardCls =
    "rounded-lg border border-zinc-200 bg-zinc-50 dark:border-white/[0.06] dark:bg-[#09090b]";
  const inputCls =
    "w-full rounded-lg border border-zinc-300 bg-white px-2.5 py-2 text-xs text-zinc-900 placeholder:text-zinc-400 outline-none focus:border-cyan-500 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-white dark:placeholder:text-zinc-600 dark:focus:border-cyan-500/50";

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 transition-colors dark:bg-[#09090b] dark:text-zinc-100">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/85 backdrop-blur-md dark:border-white/[0.08] dark:bg-[#09090b]/85">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-500/30 bg-cyan-500/10 font-mono text-xs font-bold text-cyan-700 dark:text-cyan-300">
              AE
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-white">
                  Agent Evaluation Platform
                </h1>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                    liveConnected
                      ? "border-emerald-500/30 bg-emerald-50 text-emerald-700 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300"
                      : "border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      liveConnected ? "animate-pulse bg-emerald-500 dark:bg-emerald-400" : "bg-zinc-400 dark:bg-zinc-500"
                    }`}
                  />
                  {liveConnected ? "Live" : "Offline"}
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Harness × Model × Settings · Paired Bootstrap + McNemar · Trajectory &amp; Failure Inspector
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <nav className="flex gap-1 rounded-lg border border-zinc-200 bg-zinc-100/80 p-1 dark:border-white/[0.08] dark:bg-[#111114]">
              {(
                [
                  ["experiments", "Run & Experiments"],
                  ["compare", "Compare & Failures"],
                  ["inspector", "Trajectory Inspector"],
                  ["calibration", "Judge Calibration"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                    tab === key
                      ? "bg-white text-cyan-700 shadow-xs ring-1 ring-inset ring-cyan-500/30 dark:bg-cyan-500/15 dark:text-cyan-200 dark:shadow-none"
                      : "text-zinc-600 hover:bg-white/60 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/[0.04] dark:hover:text-zinc-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </nav>

            <button
              type="button"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              className="rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 shadow-xs transition hover:bg-zinc-100 dark:border-white/[0.1] dark:bg-[#111114] dark:text-zinc-300 dark:shadow-none dark:hover:bg-white/[0.06]"
            >
              {theme === "dark" ? "☀ Light" : "☾ Dark"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-6 py-6">
        {/* Experiment selector & live progress bar */}
        <div className={`${cardCls} px-4 py-3`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Active Experiment
              </span>
              <select
                value={selectedExp}
                onChange={(e) => {
                  setConfigA("");
                  setConfigB("");
                  setSelectedExp(e.target.value);
                }}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-900 outline-none focus:border-cyan-500 dark:border-white/[0.1] dark:bg-[#09090b] dark:text-zinc-100 dark:focus:border-cyan-500/50"
              >
                {experiments.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.id} ({e.passedCount}/{e.trialCount}
                    {e.expectedTrials && e.trialCount < e.expectedTrials ? ` of ${e.expectedTrials}` : ""} passed
                    {e.infraErrors ? `, ${e.infraErrors} infra err` : ""})
                  </option>
                ))}
              </select>
              {activeExpMeta && (
                <div className="flex items-center gap-2 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                  <span>
                    {activeExpMeta.trialCount}
                    {activeExpMeta.expectedTrials ? ` / ${activeExpMeta.expectedTrials}` : ""} trials
                  </span>
                  <span className="font-medium text-emerald-600 dark:text-emerald-400">
                    {activeExpMeta.passedCount} passed
                  </span>
                  {activeExpMeta.infraErrors > 0 && (
                    <span className="font-medium text-amber-600 dark:text-amber-400">
                      {activeExpMeta.infraErrors} infra
                    </span>
                  )}
                </div>
              )}
            </div>

            {selectedExp && (
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleRetry}
                  className="rounded-lg border border-amber-500/35 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 transition hover:bg-amber-100 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/20"
                >
                  Retry Infra Errors
                </button>
                <a
                  href={`/api/experiments/${encodeURIComponent(selectedExp)}/export?format=json`}
                  className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-white/[0.1] dark:bg-white/[0.03] dark:text-zinc-200 dark:hover:bg-white/[0.07]"
                >
                  Export JSON
                </a>
                <a
                  href={`/api/experiments/${encodeURIComponent(selectedExp)}/export?format=csv`}
                  className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-white/[0.1] dark:bg-white/[0.03] dark:text-zinc-200 dark:hover:bg-white/[0.07]"
                >
                  Export CSV
                </a>
              </div>
            )}
          </div>

          {progressPct !== null && (activeJobStatus === "running" || progressPct < 100) && (
            <div className="mt-3 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="w-10 text-right font-mono text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
                {progressPct}%
              </span>
            </div>
          )}
        </div>

        {/* Live job stream drawer */}
        {activeJobStatus && (
          <div className={`${cardCls} p-4`}>
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-700 dark:text-zinc-300">
                {activeJobStatus === "running" && (
                  <span className="h-2 w-2 animate-ping rounded-full bg-cyan-500 dark:bg-cyan-400" />
                )}
                Background Job:
                <span
                  className={
                    activeJobStatus === "running"
                      ? "text-cyan-600 dark:text-cyan-300"
                      : activeJobStatus === "completed"
                        ? "text-emerald-600 dark:text-emerald-300"
                        : "text-rose-600 dark:text-rose-300"
                  }
                >
                  {activeJobStatus}
                </span>
              </span>
              <button
                onClick={() => setActiveJobStatus("")}
                className="text-xs text-zinc-500 transition hover:text-zinc-900 dark:hover:text-zinc-200"
              >
                Dismiss
              </button>
            </div>
            <pre
              ref={logsEndRef}
              className="max-h-44 overflow-auto rounded-lg border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs leading-relaxed text-zinc-200 dark:border-white/[0.06] dark:bg-[#09090b] dark:text-zinc-300"
            >
              {activeJobLogs.join("\n") || "Starting runner..."}
            </pre>
          </div>
        )}

        {/* TAB 1: Run & Experiments */}
        {tab === "experiments" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className={`${cardCls} space-y-4 p-5`}>
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">Launch Matrix Experiment</h2>

              <div>
                <div className="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">Harnesses</div>
                <div className="flex flex-wrap gap-2">
                  {(catalog?.harnesses || []).map((h) => (
                    <button
                      key={h}
                      onClick={() => toggleItem(selHarnesses, setSelHarnesses, h)}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                        selHarnesses.includes(h)
                          ? "border-cyan-500/40 bg-cyan-50 text-cyan-800 dark:bg-cyan-500/15 dark:text-cyan-200"
                          : "border-zinc-200 bg-zinc-50 text-zinc-600 hover:border-zinc-300 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-400 dark:hover:border-white/[0.18]"
                      }`}
                    >
                      {h}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
                  Models (models.yaml)
                </div>
                <div className="flex flex-wrap gap-2">
                  {(catalog?.models || []).map((m) => (
                    <button
                      key={m.id}
                      onClick={() => toggleItem(selModels, setSelModels, m.id)}
                      className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                        selModels.includes(m.id)
                          ? "border-emerald-500/40 bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200"
                          : "border-zinc-200 bg-zinc-50 text-zinc-600 hover:border-zinc-300 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-400 dark:hover:border-white/[0.18]"
                      }`}
                    >
                      {m.id}
                    </button>
                  ))}
                </div>
                <input
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="Optional raw LiteLLM string (e.g. openrouter/qwen/...)"
                  className={`${inputCls} mt-2.5`}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">Settings Preset</label>
                  <select
                    value={settingsPath}
                    onChange={(e) => setSettingsPath(e.target.value)}
                    className={inputCls}
                  >
                    {(catalog?.presets || []).map((p) => (
                      <option key={p.path} value={p.path}>
                        {p.name} ({p.path})
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
                    onClick={() => setTaskDropdownOpen((o) => !o)}
                    className={`${inputCls} flex items-center justify-between text-left`}
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
                          onClick={() => setSelTasks((catalog?.tasks || []).map((t) => t.id))}
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
                            (t) =>
                              !taskSearch.trim() ||
                              t.id.toLowerCase().includes(taskSearch.toLowerCase()) ||
                              t.category.toLowerCase().includes(taskSearch.toLowerCase())
                          )
                          .map((t) => {
                            const checked = selTasks.includes(t.id);
                            return (
                              <label
                                key={t.id}
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
                                    onChange={() => toggleItem(selTasks, setSelTasks, t.id)}
                                    className="h-3.5 w-3.5 rounded accent-cyan-600 dark:accent-cyan-400"
                                  />
                                  <span className="truncate font-mono">{t.id}</span>
                                </span>
                                <span className="shrink-0 rounded border border-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:border-white/[0.08] dark:text-zinc-400">
                                  {t.category}
                                </span>
                              </label>
                            );
                          })}
                      </div>
                    </div>
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">Trials per Task (N)</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={nTrials}
                    onChange={(e) => setNTrials(Number(e.target.value) || 1)}
                    className={`${inputCls} tabular-nums`}
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
                    className={inputCls}
                  />
                </div>
              </div>

              {/* Pre-run Cost Estimate Card */}
              <div className={`${subCardCls} space-y-2 p-3.5`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                      Estimated Experiment Cost
                    </div>
                    <div className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                      {costEstimate.nTasks} tasks × {costEstimate.nTrials} trials × {costEstimate.nConfigs} configs ={" "}
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
                      range ${(costEstimate.totalCostUsd * 0.7).toFixed(2)}–${(costEstimate.totalCostUsd * 1.3).toFixed(2)}
                    </div>
                  </div>
                </div>

                {costEstimate.perConfig.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-0.5 text-[11px] font-mono text-zinc-600 dark:text-zinc-400">
                    {costEstimate.perConfig.map((c) => (
                      <span
                        key={c.name}
                        className="rounded border border-zinc-200 bg-white px-2 py-0.5 dark:border-white/[0.08] dark:bg-[#111114]"
                      >
                        {c.name}: ~{(c.avgTokens / 1000).toFixed(1)}k tok/trial → ${c.costUsd.toFixed(2)}
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
                onClick={handleLaunchRun}
                disabled={isLaunching || selTasks.length === 0 || costEstimate.nConfigs === 0}
                className="w-full rounded-lg bg-cyan-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50 dark:bg-cyan-500 dark:text-zinc-950 dark:hover:bg-cyan-400"
              >
                {isLaunching
                  ? "Launching Experiment..."
                  : `Run Experiment (${costEstimate.nConfigs} ${costEstimate.nConfigs === 1 ? "config" : "configs"} · ${costEstimate.totalTrials} ${costEstimate.totalTrials === 1 ? "trial" : "trials"} · ~$${costEstimate.totalCostUsd.toFixed(2)})`}
              </button>
            </section>

            <section className={`${cardCls} space-y-3 p-5`}>
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
                Experiments ({experiments.length})
              </h2>
              <div className="max-h-[420px] space-y-2 overflow-auto pr-1">
                {experiments.map((exp) => (
                  <div
                    key={exp.id}
                    onClick={() => {
                      setConfigA("");
                      setConfigB("");
                      setSelectedExp(exp.id);
                      setTab("compare");
                    }}
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
        )}

        {/* TAB 2: Compare & Failures */}
        {tab === "compare" && (
          <div className="space-y-5">
            {(activeJobStatus === "running" ||
              !expDetail ||
              (activeExpMeta?.expectedTrials && activeExpMeta.trialCount < activeExpMeta.expectedTrials)) && (
              <div className={`${cardCls} flex flex-wrap items-center justify-between gap-4 p-4`}>
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
                <section className={`${cardCls} overflow-x-auto p-5`}>
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
                  {Object.entries(expDetail.summaries).map(([name, s]) => (
                    <tr key={name} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02]">
                      <td className="py-2.5 pr-4 font-mono font-medium text-zinc-900 dark:text-white">{name}</td>
                      <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">{s.completed}</td>
                      <td className="py-2.5 pr-4 text-amber-600 dark:text-amber-300">{s.infra_errors}</td>
                      <td className="py-2.5 pr-4 font-semibold text-emerald-600 dark:text-emerald-300">
                        {s.mean_score.toFixed(3)}
                      </td>
                      <td className="py-2.5 pr-4 text-zinc-800 dark:text-zinc-200">
                        {(s.pass_rate * 100).toFixed(1)}%
                      </td>
                      <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">
                        ${s.total_cost_usd.toFixed(5)}
                      </td>
                      <td className="py-2.5 pr-4 text-zinc-700 dark:text-zinc-300">
                        {s.avg_runtime_sec}s / {s.p95_runtime_sec}s
                      </td>
                      <td className="py-2.5 text-zinc-700 dark:text-zinc-300">
                        {s.avg_tokens.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            {expDetail.comparison && (
              <section className={`${cardCls} space-y-4 p-5`}>
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-zinc-500 dark:text-zinc-400">Compare</span>
                    <select
                      value={configA}
                      onChange={(e) => setConfigA(e.target.value)}
                      className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-900 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-white"
                    >
                      {expDetail.config_names.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                    <span className="text-zinc-400 dark:text-zinc-500">vs</span>
                    <select
                      value={configB}
                      onChange={(e) => setConfigB(e.target.value)}
                      className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-900 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-white"
                    >
                      {expDetail.config_names.map((c) => (
                        <option key={c} value={c}>{c}</option>
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
                  <div className={`${subCardCls} p-3.5`}>
                    <div className="text-xs text-zinc-500">Delta (B - A)</div>
                    <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                      {expDetail.comparison.delta_mean >= 0 ? "+" : ""}
                      {expDetail.comparison.delta_mean.toFixed(4)}
                    </div>
                  </div>
                  <div className={`${subCardCls} p-3.5`}>
                    <div className="text-xs text-zinc-500">95% Bootstrap CI</div>
                    <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                      [{expDetail.comparison.ci_95[0]}, {expDetail.comparison.ci_95[1]}]
                    </div>
                  </div>
                  <div className={`${subCardCls} p-3.5`}>
                    <div className="text-xs text-zinc-500">Exact McNemar p-value</div>
                    <div className="mt-1 text-xl font-semibold text-zinc-900 dark:text-white">
                      {expDetail.comparison.mcnemar_p}
                    </div>
                  </div>
                </div>

                {expDetail.comparison.warnings.length > 0 && (
                  <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/[0.06] dark:text-amber-200">
                    {expDetail.comparison.warnings.map((w, i) => (
                      <div key={i}>WARNING: {w}</div>
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
                      {expDetail.comparison.per_task.map((r) => (
                        <tr key={r.task_id} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02]">
                          <td className="py-2 pr-4 font-mono text-zinc-800 dark:text-zinc-200">{r.task_id}</td>
                          <td className="py-2 pr-4 text-zinc-700 dark:text-zinc-300">
                            {r.score_a.toFixed(2)} (n={r.n_a})
                          </td>
                          <td className="py-2 pr-4 text-zinc-700 dark:text-zinc-300">
                            {r.score_b.toFixed(2)} (n={r.n_b})
                          </td>
                          <td
                            className={`py-2 pr-4 font-semibold ${
                              r.delta > 0
                                ? "text-emerald-600 dark:text-emerald-400"
                                : r.delta < 0
                                  ? "text-rose-600 dark:text-rose-400"
                                  : "text-zinc-400 dark:text-zinc-500"
                            }`}
                          >
                            {r.delta >= 0 ? "+" : ""}
                            {r.delta.toFixed(2)}
                          </td>
                          <td className="py-2 text-zinc-500 dark:text-zinc-400">
                            [{r.ci_95[0]}, {r.ci_95[1]}] {r.is_noise ? "(noise)" : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <section className={`${cardCls} p-5`}>
              <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-white">Failure Breakdown</h2>
              <div className="grid gap-4 md:grid-cols-2">
                {Object.entries(expDetail.failures).map(([cfg, info]) => (
                  <div key={cfg} className={`${subCardCls} p-3.5 text-xs`}>
                    <div className="mb-2 flex justify-between font-mono font-semibold text-zinc-900 dark:text-white">
                      <span>{cfg}</span>
                      <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
                        {info.failed} / {info.total} failed
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
                                onClick={() => {
                                  setSelectedTrialId(info.examples[cat][0]);
                                  setTab("inspector");
                                }}
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
        )}

        {/* TAB 3: Trajectory Inspector */}
        {tab === "inspector" && (
          <div className="grid gap-5 lg:grid-cols-12">
            <section className={`${cardCls} space-y-3 p-4 lg:col-span-4`}>
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">
                  Trials ({filteredTrials.length})
                </h2>
                <select
                  value={trialFilter}
                  onChange={(e) => setTrialFilter(e.target.value as typeof trialFilter)}
                  className="rounded-lg border border-zinc-300 bg-white px-2.5 py-1 text-xs text-zinc-800 outline-none dark:border-white/[0.1] dark:bg-[#09090b] dark:text-zinc-200"
                >
                  <option value="all">All</option>
                  <option value="failed">Failed</option>
                  <option value="passed">Passed</option>
                  <option value="infra">Infra Error</option>
                </select>
              </div>
              <div className="max-h-[620px] space-y-1.5 overflow-auto pr-1">
                {filteredTrials.map((t) => (
                  <div
                    key={t.trial_id}
                    onClick={() => setSelectedTrialId(t.trial_id)}
                    className={`cursor-pointer rounded-lg border p-2.5 text-xs transition ${
                      selectedTrialId === t.trial_id
                        ? "border-cyan-500/40 bg-cyan-50/70 dark:bg-cyan-500/[0.07]"
                        : "border-zinc-200 bg-zinc-50/70 hover:border-zinc-300 dark:border-white/[0.06] dark:bg-[#09090b]/70 dark:hover:border-white/[0.15]"
                    }`}
                  >
                    <div className="flex items-center justify-between font-medium">
                      <span className="truncate font-mono text-zinc-800 dark:text-zinc-200">{t.task_id}</span>
                      <span
                        className={
                          t.passed
                            ? "text-emerald-600 dark:text-emerald-400"
                            : t.status === "infra_error"
                              ? "text-amber-600 dark:text-amber-400"
                              : "text-rose-600 dark:text-rose-400"
                        }
                      >
                        {t.passed ? "PASS" : t.status === "infra_error" ? "INFRA" : "FAIL"}
                      </span>
                    </div>
                    <div className="mt-0.5 flex justify-between text-zinc-500">
                      <span>{t.config_name} (t{t.trial_index})</span>
                      <span>{t.failure_category || (t.score !== null ? `score=${t.score}` : "")}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className={`${cardCls} space-y-4 p-5 lg:col-span-8`}>
              {!trialDetail ? (
                <div className="text-sm text-zinc-500 dark:text-zinc-400">
                  Select a trial to inspect its trajectory.
                </div>
              ) : (
                <>
                  <div className={`${subCardCls} p-4 text-xs`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-sm font-semibold text-zinc-900 dark:text-white">
                        {trialDetail.trial.trial_id}
                      </span>
                      <span className="rounded-md border border-zinc-200 bg-white px-2 py-0.5 font-mono text-zinc-700 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-zinc-200">
                        {trialDetail.trial.failure_category || (trialDetail.trial.passed ? "PASSED" : "FAILED")}
                      </span>
                    </div>
                    <div className="mt-2.5 grid gap-2 tabular-nums text-zinc-600 dark:text-zinc-300 sm:grid-cols-4">
                      <div>Score: <b className="text-zinc-900 dark:text-white">{trialDetail.trial.score ?? "-"}</b></div>
                      <div>Tokens: <b className="text-zinc-900 dark:text-white">{trialDetail.trial.input_tokens + trialDetail.trial.output_tokens}</b></div>
                      <div>Cost: <b className="text-zinc-900 dark:text-white">${trialDetail.trial.cost_usd.toFixed(5)}</b></div>
                      <div>Time: <b className="text-zinc-900 dark:text-white">{trialDetail.trial.runtime_sec}s</b> ({trialDetail.trial.steps} steps)</div>
                    </div>
                    <div className="mt-2 text-zinc-600 dark:text-zinc-400">
                      <b className="text-zinc-900 dark:text-zinc-200">
                        Grader ({trialDetail.trial.grade?.grader_type || "-"}):
                      </b>{" "}
                      {trialDetail.trial.grade?.reasoning || trialDetail.trial.error_message || "-"}
                    </div>
                  </div>

                  <div className="max-h-[520px] space-y-2 overflow-auto pr-1">
                    {trialDetail.events.map((ev) => (
                      <div
                        key={ev.seq}
                        className={`rounded-lg border p-3 text-xs ${
                          EVENT_COLORS[ev.type] ||
                          "border-zinc-200 bg-zinc-50 text-zinc-800 dark:border-white/[0.08] dark:bg-[#09090b] dark:text-zinc-200"
                        }`}
                      >
                        <div className="mb-1 flex justify-between font-mono text-[11px] opacity-75">
                          <span>#{ev.seq} {ev.type}</span>
                          <span>{ev.ts}</span>
                        </div>
                        <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                          {JSON.stringify(ev.payload, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>
        )}

        {/* TAB 4: Judge Calibration */}
        {tab === "calibration" && (
          <div className="space-y-4">
            <div className={`${cardCls} flex flex-wrap items-center justify-between gap-3 p-4`}>
              <div>
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-white">LLM-as-Judge Calibration</h2>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Evaluates judge agreement against 30 human-labelled examples in calibration/judge_labels.jsonl
                </p>
              </div>
              <button
                onClick={handleCalibrate}
                disabled={activeJobStatus === "running"}
                className="rounded-lg bg-cyan-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50 dark:bg-cyan-500 dark:text-zinc-950 dark:hover:bg-cyan-400"
              >
                Run Calibration (gemini-flash × 3)
              </button>
            </div>

            {calibrations.length === 0 ? (
              <div className={`${cardCls} p-6 text-sm text-zinc-500 dark:text-zinc-400`}>
                No calibration reports yet. Click &quot;Run Calibration&quot; or run{" "}
                <code className="text-cyan-700 dark:text-cyan-300">uv run eval-calibrate --judge gemini-flash</code>.
              </div>
            ) : (
              calibrations.map((c, idx) => (
                <section key={idx} className={`${cardCls} space-y-4 p-5`}>
                  <div className="flex items-center justify-between">
                    <div className="font-mono text-xs font-semibold text-zinc-900 dark:text-white">
                      {c.judge_model} — {c.timestamp}
                    </div>
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        c.verdict === "TRUSTED"
                          ? "border-emerald-500/30 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                          : "border-rose-500/30 bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
                      }`}
                    >
                      {c.verdict}
                    </span>
                  </div>
                  <div className="grid gap-3 tabular-nums sm:grid-cols-5">
                    <div className={`${subCardCls} p-3 text-xs`}>
                      <div className="text-zinc-500">Cohen&apos;s κ</div>
                      <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">{c.cohens_kappa}</div>
                    </div>
                    <div className={`${subCardCls} p-3 text-xs`}>
                      <div className="text-zinc-500">Accuracy</div>
                      <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">{(c.accuracy * 100).toFixed(1)}%</div>
                    </div>
                    <div className={`${subCardCls} p-3 text-xs`}>
                      <div className="text-zinc-500">Score MAE</div>
                      <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">{c.score_mae}</div>
                    </div>
                    <div className={`${subCardCls} p-3 text-xs`}>
                      <div className="text-zinc-500">Self-Agreement</div>
                      <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-white">{(c.self_agreement * 100).toFixed(1)}%</div>
                    </div>
                    <div className={`${subCardCls} p-3 text-xs`}>
                      <div className="text-zinc-500">Confusion (TP/FP/TN/FN)</div>
                      <div className="mt-1 text-sm font-semibold text-zinc-900 dark:text-white">
                        {c.confusion_matrix.tp}/{c.confusion_matrix.fp}/{c.confusion_matrix.tn}/{c.confusion_matrix.fn}
                      </div>
                    </div>
                  </div>
                  {c.disagreements.length > 0 && (
                    <div className="overflow-x-auto">
                      <h3 className="mb-2 text-xs font-semibold uppercase text-zinc-500">
                        Disagreements ({c.disagreements.length})
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
                          {c.disagreements.map((d) => (
                            <tr key={d.id}>
                              <td className="py-2 pr-3 font-mono text-zinc-800 dark:text-zinc-200">{d.id}</td>
                              <td className="py-2 pr-3 tabular-nums text-zinc-700 dark:text-zinc-300">{String(d.human_passed)} ({d.human_score})</td>
                              <td className="py-2 pr-3 tabular-nums text-zinc-700 dark:text-zinc-300">{String(d.judge_passed)} ({d.judge_score})</td>
                              <td className="py-2 text-zinc-600 dark:text-zinc-400">{d.notes} | {d.judge_reasoning}</td>
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
        )}
      </main>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CompareAndFailuresTab } from "./components/CompareAndFailuresTab";
import { ExperimentLauncherTab } from "./components/ExperimentLauncherTab";
import { JudgeCalibrationTab } from "./components/JudgeCalibrationTab";
import { TrajectoryInspectorTab } from "./components/TrajectoryInspectorTab";
import { CARD_CLS, type Tab, type Theme, type TrialFilter } from "./components/uiStyles";
import type {
  CalibrationReport,
  CatalogResponse,
  ExperimentDetail,
  ExperimentSummaryItem,
  TraceEvent,
  TrialItem,
} from "./types";
import { computeExperimentCostEstimate } from "./utils/costEstimate";

const TRIAL_STREAM_PREFIX = "[AEP_TRIAL] ";
const MAX_ACTIVE_JOB_LOG_LINES = 400;
const LAUNCH_COOLDOWN_MS = 3000;

const NAV_TABS: ReadonlyArray<readonly [Tab, string]> = [
  ["experiments", "Run & Experiments"],
  ["compare", "Compare & Failures"],
  ["inspector", "Trajectory Inspector"],
  ["calibration", "Judge Calibration"],
];

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
      // Ignore localStorage quota/privacy errors
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
  const [trialDetail, setTrialDetail] = useState<{
    trial: TrialItem;
    events: TraceEvent[];
  } | null>(null);
  const [calibrations, setCalibrations] = useState<CalibrationReport[]>([]);

  // Matrix launcher state
  const [selHarnesses, setSelHarnesses] = useState<string[]>(["hermes", "langgraph"]);
  const [selModels, setSelModels] = useState<string[]>(["gemini-flash"]);
  const [customModel, setCustomModel] = useState<string>("");
  const [settingsPath, setSettingsPath] = useState<string>("configs/default.yaml");
  const [selTasks, setSelTasks] = useState<string[]>([]);
  const [tasksInitialized, setTasksInitialized] = useState<boolean>(false);
  const [nTrials, setNTrials] = useState<number>(1);
  const [expIdInput, setExpIdInput] = useState<string>("");

  // Live streaming & job state
  const [liveConnected, setLiveConnected] = useState<boolean>(false);
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [activeJobLogs, setActiveJobLogs] = useState<string[]>([]);
  const [activeJobStatus, setActiveJobStatus] = useState<string>("");
  const [trialFilter, setTrialFilter] = useState<TrialFilter>("all");
  const logsEndRef = useRef<HTMLPreElement | null>(null);

  const loadExperimentData = useCallback(async (expId: string, a: string, b: string) => {
    if (!expId) return;
    const qs = new URLSearchParams();
    if (a) qs.set("a", a);
    if (b) qs.set("b", b);

    const [detailRes, trialsRes] = await Promise.all([
      fetch(`/api/experiments/${encodeURIComponent(expId)}?${qs}`).then((res) =>
        res.ok ? res.json() : null
      ),
      fetch(`/api/experiments/${encodeURIComponent(expId)}/trials`).then((res) =>
        res.ok ? res.json() : { trials: [] }
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
      nextTrials.length && !nextTrials.some((trial) => trial.trial_id === prev)
        ? nextTrials[0].trial_id
        : prev
    );
  }, []);

  const refreshAll = useCallback(
    async (keepExp?: string) => {
      const [catRes, expRes, calRes] = await Promise.all([
        fetch("/api/catalog").then((res) => res.json()),
        fetch("/api/experiments").then((res) => res.json()),
        fetch("/api/calibration").then((res) => res.json()),
      ]);
      setCatalog(catRes);
      if (!tasksInitialized && catRes?.tasks?.length) {
        setSelTasks(catRes.tasks.map((task: { id: string }) => task.id));
        setTasksInitialized(true);
      }
      if (catRes?.models?.length) {
        setSelModels((prev) => {
          const validIds = new Set(catRes.models.map((model: { id: string }) => model.id));
          const kept = prev.filter((id) => validIds.has(id));
          if (kept.length > 0) return kept;
          const firstReal =
            catRes.models.find((model: { id: string }) => model.id !== "mock") ||
            catRes.models[0];
          return firstReal ? [firstReal.id] : [];
        });
      }
      setExperiments(expRes.experiments || []);
      setCalibrations(calRes.reports || []);
      setSelectedExp((prev) => keepExp || prev || expRes.experiments?.[0]?.id || "");
    },
    [tasksInitialized]
  );

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
    const eventSource = new EventSource(`/api/events${qs}`);
    eventSource.onopen = () => setLiveConnected(true);
    eventSource.onerror = () => setLiveConnected(false);

    eventSource.addEventListener("experiments", (ev) => {
      setLiveConnected(true);
      const payload = JSON.parse((ev as MessageEvent).data) as {
        experiments: ExperimentSummaryItem[];
      };
      setExperiments(payload.experiments || []);
      setSelectedExp((prev) => prev || payload.experiments?.[0]?.id || "");
    });

    eventSource.addEventListener("trial_update", (ev) => {
      const payload = JSON.parse((ev as MessageEvent).data) as { expId: string };
      if (payload.expId === selectedExp) {
        void loadExperimentData(selectedExp, configA, configB);
      }
    });

    return () => {
      eventSource.close();
      setLiveConnected(false);
    };
  }, [selectedExp, configA, configB, loadExperimentData]);

  useEffect(() => {
    if (!selectedExp || !selectedTrialId) {
      setTrialDetail(null);
      return;
    }
    fetch(
      `/api/experiments/${encodeURIComponent(selectedExp)}/trials/${encodeURIComponent(selectedTrialId)}`
    )
      .then((res) => (res.ok ? res.json() : null))
      .then(setTrialDetail);
  }, [selectedExp, selectedTrialId, trials.length]);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollTop = logsEndRef.current.scrollHeight;
    }
  }, [activeJobLogs]);

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

    const eventSource = new EventSource(`/api/jobs/${jobId}/stream`);
    eventSource.addEventListener("log", (ev) => {
      const logMessage = JSON.parse((ev as MessageEvent).data) as { line: string };
      if (logMessage.line.startsWith(TRIAL_STREAM_PREFIX)) {
        try {
          const payload = JSON.parse(logMessage.line.slice(TRIAL_STREAM_PREFIX.length)) as {
            experiment_id: string;
            trial_id: string;
            status: string;
            passed: boolean | null;
            score: number | null;
          };
          const badge = payload.passed
            ? "PASS"
            : payload.status === "infra_error"
              ? "INFRA"
              : "FAIL";
          setActiveJobLogs((prev) => [
            ...prev.slice(-MAX_ACTIVE_JOB_LOG_LINES),
            `✓ ${payload.trial_id} → ${badge} (score=${payload.score ?? "-"})`,
          ]);
          if (payload.experiment_id) {
            void loadExperimentData(payload.experiment_id, "", "");
          }
          return;
        } catch {
          // Fall through to raw line
        }
      }
      setActiveJobLogs((prev) => [...prev.slice(-MAX_ACTIVE_JOB_LOG_LINES), logMessage.line]);
    });
    eventSource.addEventListener("done", (ev) => {
      const completionPayload = JSON.parse((ev as MessageEvent).data) as { status: string };
      setActiveJobStatus(completionPayload.status);
      eventSource.close();
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
      const allTaskIds = (catalog?.tasks || []).map((task) => task.id);
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
      const responseData = await res.json();
      if (responseData.jobId) {
        streamJob(responseData.jobId, responseData.expId);
      }
    } finally {
      setTimeout(() => setIsLaunching(false), LAUNCH_COOLDOWN_MS);
    }
  }

  async function handleRetry() {
    if (!selectedExp) return;
    const res = await fetch(`/api/experiments/${encodeURIComponent(selectedExp)}/retry`, {
      method: "POST",
    });
    const responseData = await res.json();
    if (responseData.jobId) streamJob(responseData.jobId, selectedExp);
  }

  async function handleCalibrate() {
    const res = await fetch("/api/calibration/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ judge: "gemini-flash", repeats: 3 }),
    });
    const responseData = await res.json();
    if (responseData.jobId) streamJob(responseData.jobId);
  }

  const activeExpMeta = useMemo(
    () => experiments.find((exp) => exp.id === selectedExp) || null,
    [experiments, selectedExp]
  );

  const progressPct = useMemo(() => {
    if (!activeExpMeta?.expectedTrials || activeExpMeta.expectedTrials <= 0) return null;
    return Math.min(
      100,
      Math.round((activeExpMeta.trialCount / activeExpMeta.expectedTrials) * 100)
    );
  }, [activeExpMeta]);

  const costEstimate = useMemo(
    () =>
      computeExperimentCostEstimate({
        selectedHarnesses: selHarnesses,
        selectedModels: selModels,
        customModel,
        selectedTasks: selTasks,
        nTrials,
        catalog,
      }),
    [selHarnesses, selModels, customModel, selTasks, nTrials, catalog]
  );

  const filteredTrials = useMemo(
    () =>
      trials.filter((trial) => {
        if (trialFilter === "failed") return trial.status === "completed" && !trial.passed;
        if (trialFilter === "passed") return trial.status === "completed" && Boolean(trial.passed);
        if (trialFilter === "infra") return trial.status === "infra_error";
        return true;
      }),
    [trials, trialFilter]
  );

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
                      liveConnected
                        ? "animate-pulse bg-emerald-500 dark:bg-emerald-400"
                        : "bg-zinc-400 dark:bg-zinc-500"
                    }`}
                  />
                  {liveConnected ? "Live" : "Offline"}
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Harness × Model × Settings · Paired Bootstrap + McNemar · Trajectory &amp; Failure
                Inspector
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <nav className="flex gap-1 rounded-lg border border-zinc-200 bg-zinc-100/80 p-1 dark:border-white/[0.08] dark:bg-[#111114]">
              {NAV_TABS.map(([key, label]) => (
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
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
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
        <div className={`${CARD_CLS} px-4 py-3`}>
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
                {experiments.map((exp) => (
                  <option key={exp.id} value={exp.id}>
                    {exp.id} ({exp.passedCount}/{exp.trialCount}
                    {exp.expectedTrials && exp.trialCount < exp.expectedTrials
                      ? ` of ${exp.expectedTrials}`
                      : ""}{" "}
                    passed
                    {exp.infraErrors ? `, ${exp.infraErrors} infra err` : ""})
                  </option>
                ))}
              </select>
              {activeExpMeta && (
                <div className="flex items-center gap-2 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                  <span>
                    {activeExpMeta.trialCount}
                    {activeExpMeta.expectedTrials ? ` / ${activeExpMeta.expectedTrials}` : ""}{" "}
                    trials
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
          <div className={`${CARD_CLS} p-4`}>
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

        {tab === "experiments" && (
          <ExperimentLauncherTab
            catalog={catalog}
            experiments={experiments}
            selectedExp={selectedExp}
            selHarnesses={selHarnesses}
            setSelHarnesses={setSelHarnesses}
            selModels={selModels}
            setSelModels={setSelModels}
            customModel={customModel}
            setCustomModel={setCustomModel}
            settingsPath={settingsPath}
            setSettingsPath={setSettingsPath}
            selTasks={selTasks}
            setSelTasks={setSelTasks}
            nTrials={nTrials}
            setNTrials={setNTrials}
            expIdInput={expIdInput}
            setExpIdInput={setExpIdInput}
            costEstimate={costEstimate}
            isLaunching={isLaunching}
            onLaunchRun={handleLaunchRun}
            onSelectExperiment={(expId) => {
              setConfigA("");
              setConfigB("");
              setSelectedExp(expId);
              setTab("compare");
            }}
          />
        )}

        {tab === "compare" && (
          <CompareAndFailuresTab
            selectedExp={selectedExp}
            activeExpMeta={activeExpMeta}
            activeJobStatus={activeJobStatus}
            activeJobLogs={activeJobLogs}
            progressPct={progressPct}
            expDetail={expDetail}
            configA={configA}
            setConfigA={setConfigA}
            configB={configB}
            setConfigB={setConfigB}
            onInspectTrial={(trialId) => {
              setSelectedTrialId(trialId);
              setTab("inspector");
            }}
          />
        )}

        {tab === "inspector" && (
          <TrajectoryInspectorTab
            filteredTrials={filteredTrials}
            trialFilter={trialFilter}
            setTrialFilter={setTrialFilter}
            selectedTrialId={selectedTrialId}
            setSelectedTrialId={setSelectedTrialId}
            trialDetail={trialDetail}
          />
        )}

        {tab === "calibration" && (
          <JudgeCalibrationTab
            calibrations={calibrations}
            activeJobStatus={activeJobStatus}
            onCalibrate={handleCalibrate}
          />
        )}
      </main>
    </div>
  );
}

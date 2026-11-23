import { useEffect, useState } from "react";
import type {
  CalibrationReport,
  CatalogResponse,
  ExperimentDetail,
  ExperimentSummaryItem,
  TraceEvent,
  TrialItem,
} from "./types";

type Tab = "experiments" | "compare" | "inspector" | "calibration";

const EVENT_COLORS: Record<string, string> = {
  session_start: "border-sky-500/40 bg-sky-950/30 text-sky-300",
  message: "border-slate-700 bg-slate-900/60 text-slate-200",
  tool_call: "border-amber-500/40 bg-amber-950/30 text-amber-200",
  tool_result: "border-emerald-500/40 bg-emerald-950/30 text-emerald-200",
  memory_op: "border-fuchsia-500/40 bg-fuchsia-950/30 text-fuchsia-200",
  skill_invoked: "border-cyan-500/40 bg-cyan-950/30 text-cyan-200",
  error: "border-rose-500/50 bg-rose-950/40 text-rose-200",
  session_end: "border-sky-500/40 bg-sky-950/30 text-sky-300",
};

export default function App() {
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
  const [tasksPath, setTasksPath] = useState<string>("tasks");
  const [nTrials, setNTrials] = useState<number>(1);
  const [expIdInput, setExpIdInput] = useState<string>("");

  // Job stream state
  const [activeJobLogs, setActiveJobLogs] = useState<string[]>([]);
  const [activeJobStatus, setActiveJobStatus] = useState<string>("");
  const [trialFilter, setTrialFilter] = useState<"all" | "failed" | "passed" | "infra">("all");

  async function refreshAll(keepExp?: string) {
    const [catRes, expRes, calRes] = await Promise.all([
      fetch("/api/catalog").then((r) => r.json()),
      fetch("/api/experiments").then((r) => r.json()),
      fetch("/api/calibration").then((r) => r.json()),
    ]);
    setCatalog(catRes);
    setExperiments(expRes.experiments || []);
    setCalibrations(calRes.reports || []);
    const target = keepExp || selectedExp || expRes.experiments?.[0]?.id || "";
    if (target) setSelectedExp(target);
  }

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    if (!selectedExp) return;
    const qs = new URLSearchParams();
    if (configA) qs.set("a", configA);
    if (configB) qs.set("b", configB);
    fetch(`/api/experiments/${selectedExp}?${qs}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: ExperimentDetail | null) => {
        setExpDetail(d);
        if (d?.comparison) {
          setConfigA(d.comparison.config_a);
          setConfigB(d.comparison.config_b);
        }
      });
    fetch(`/api/experiments/${selectedExp}/trials`)
      .then((r) => (r.ok ? r.json() : { trials: [] }))
      .then((d) => {
        setTrials(d.trials || []);
        if (d.trials?.length && !d.trials.some((t: TrialItem) => t.trial_id === selectedTrialId)) {
          setSelectedTrialId(d.trials[0].trial_id);
        }
      });
  }, [selectedExp, configA, configB]);

  useEffect(() => {
    if (!selectedExp || !selectedTrialId) {
      setTrialDetail(null);
      return;
    }
    fetch(`/api/experiments/${selectedExp}/trials/${selectedTrialId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setTrialDetail);
  }, [selectedExp, selectedTrialId]);

  function streamJob(jobId: string, onDone?: () => void) {
    setActiveJobLogs([]);
    setActiveJobStatus("running");
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.addEventListener("log", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveJobLogs((prev) => [...prev.slice(-400), data.line]);
    });
    es.addEventListener("done", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveJobStatus(data.status);
      es.close();
      onDone?.();
    });
  }

  async function handleLaunchRun() {
    const models = [...selModels];
    if (customModel.trim()) models.push(customModel.trim());
    const res = await fetch("/api/experiments/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        harnesses: selHarnesses,
        models,
        settingsPath,
        tasksPath,
        trials: nTrials,
        expId: expIdInput.trim() || undefined,
      }),
    });
    const data = await res.json();
    if (data.jobId) {
      streamJob(data.jobId, () => refreshAll(expIdInput.trim() || undefined));
    }
  }

  async function handleRetry() {
    if (!selectedExp) return;
    const res = await fetch(`/api/experiments/${selectedExp}/retry`, { method: "POST" });
    const data = await res.json();
    if (data.jobId) streamJob(data.jobId, () => refreshAll(selectedExp));
  }

  async function handleCalibrate() {
    const res = await fetch("/api/calibration/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ judge: "gemini-flash", repeats: 3 }),
    });
    const data = await res.json();
    if (data.jobId) streamJob(data.jobId, () => refreshAll());
  }

  function toggleItem(list: string[], setList: (v: string[]) => void, val: string) {
    setList(list.includes(val) ? list.filter((x) => x !== val) : [...list, val]);
  }

  const filteredTrials = trials.filter((t) => {
    if (trialFilter === "failed") return t.status === "completed" && !t.passed;
    if (trialFilter === "passed") return t.status === "completed" && Boolean(t.passed);
    if (trialFilter === "infra") return t.status === "infra_error";
    return true;
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/70 px-6 py-4">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">
              Agent Evaluation Platform
            </h1>
            <p className="text-xs text-slate-400">
              Harness × Model × Settings · Paired Bootstrap + McNemar · Trajectory & Failure Inspector
            </p>
          </div>
          <nav className="flex gap-2">
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
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  tab === key
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {/* Experiment selector bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/50 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
              Active Experiment
            </span>
            <select
              value={selectedExp}
              onChange={(e) => {
                setConfigA("");
                setConfigB("");
                setSelectedExp(e.target.value);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-white"
            >
              {experiments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.id} ({e.passedCount}/{e.trialCount} passed
                  {e.infraErrors ? `, ${e.infraErrors} infra err` : ""})
                </option>
              ))}
            </select>
          </div>
          {selectedExp && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleRetry}
                className="rounded border border-amber-500/40 bg-amber-950/40 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-900/50"
              >
                Retry Infra Errors
              </button>
              <a
                href={`/api/experiments/${selectedExp}/export?format=json`}
                className="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
              >
                Export JSON
              </a>
              <a
                href={`/api/experiments/${selectedExp}/export?format=csv`}
                className="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
              >
                Export CSV
              </a>
            </div>
          )}
        </div>

        {/* Live job output drawer */}
        {activeJobStatus && (
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                Background Job:{" "}
                <span
                  className={
                    activeJobStatus === "running"
                      ? "text-sky-400"
                      : activeJobStatus === "completed"
                        ? "text-emerald-400"
                        : "text-rose-400"
                  }
                >
                  {activeJobStatus}
                </span>
              </span>
              <button
                onClick={() => setActiveJobStatus("")}
                className="text-xs text-slate-400 hover:text-white"
              >
                Dismiss
              </button>
            </div>
            <pre className="max-h-48 overflow-auto rounded bg-slate-950 p-3 font-mono text-xs text-slate-300">
              {activeJobLogs.join("\n") || "Waiting for output..."}
            </pre>
          </div>
        )}

        {/* TAB 1: Run & Experiments */}
        {tab === "experiments" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="text-base font-semibold text-white">Launch Matrix Experiment</h2>

              <div>
                <div className="mb-1.5 text-xs font-medium text-slate-400">Harnesses</div>
                <div className="flex flex-wrap gap-2">
                  {(catalog?.harnesses || []).map((h) => (
                    <button
                      key={h}
                      onClick={() => toggleItem(selHarnesses, setSelHarnesses, h)}
                      className={`rounded border px-3 py-1 text-xs font-medium ${
                        selHarnesses.includes(h)
                          ? "border-indigo-500 bg-indigo-600/30 text-indigo-200"
                          : "border-slate-700 bg-slate-950 text-slate-400"
                      }`}
                    >
                      {h}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-1.5 text-xs font-medium text-slate-400">Models (models.yaml)</div>
                <div className="flex flex-wrap gap-2">
                  {(catalog?.models || []).map((m) => (
                    <button
                      key={m.id}
                      onClick={() => toggleItem(selModels, setSelModels, m.id)}
                      className={`rounded border px-2.5 py-1 text-xs ${
                        selModels.includes(m.id)
                          ? "border-emerald-500 bg-emerald-600/20 text-emerald-200"
                          : "border-slate-700 bg-slate-950 text-slate-400"
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
                  className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-white placeholder:text-slate-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Settings Preset</label>
                  <select
                    value={settingsPath}
                    onChange={(e) => setSettingsPath(e.target.value)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-white"
                  >
                    {(catalog?.presets || []).map((p) => (
                      <option key={p.path} value={p.path}>
                        {p.name} ({p.path})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Tasks Scope</label>
                  <select
                    value={tasksPath}
                    onChange={(e) => setTasksPath(e.target.value)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-white"
                  >
                    <option value="tasks">All tasks ({catalog?.tasks.length || 0})</option>
                    {(catalog?.tasks || []).map((t) => (
                      <option key={t.id} value={`tasks/${t.id}`}>
                        {t.id} ({t.grader.type})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Trials per Task (N)</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={nTrials}
                    onChange={(e) => setNTrials(Number(e.target.value) || 1)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">Experiment ID (optional)</label>
                  <input
                    value={expIdInput}
                    onChange={(e) => setExpIdInput(e.target.value)}
                    placeholder="auto-generated"
                    className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-white"
                  />
                </div>
              </div>

              <button
                onClick={handleLaunchRun}
                disabled={activeJobStatus === "running"}
                className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                Run Experiment ({selHarnesses.length} × {selModels.length + (customModel.trim() ? 1 : 0)} arms)
              </button>
            </section>

            <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="text-base font-semibold text-white">Experiments ({experiments.length})</h2>
              <div className="max-h-96 space-y-2 overflow-auto">
                {experiments.map((exp) => (
                  <div
                    key={exp.id}
                    onClick={() => {
                      setSelectedExp(exp.id);
                      setTab("compare");
                    }}
                    className={`cursor-pointer rounded-md border p-3 transition ${
                      selectedExp === exp.id
                        ? "border-indigo-500 bg-indigo-950/30"
                        : "border-slate-800 bg-slate-950/60 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-medium text-white">{exp.id}</span>
                      <span className="text-xs text-slate-400">
                        {exp.passedCount}/{exp.trialCount} passed
                        {exp.infraErrors > 0 && (
                          <span className="ml-2 text-amber-400">{exp.infraErrors} infra</span>
                        )}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      Configs: {exp.configs.join(", ") || "-"}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}

        {/* TAB 2: Compare & Failures */}
        {tab === "compare" && expDetail && (
          <div className="space-y-6">
            {/* Summary table */}
            <section className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="mb-3 text-base font-semibold text-white">
                Quality vs Cost vs Latency
              </h2>
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-800 text-slate-400">
                  <tr>
                    <th className="py-2 pr-4">Config</th>
                    <th className="py-2 pr-4">Completed</th>
                    <th className="py-2 pr-4">Infra Err</th>
                    <th className="py-2 pr-4">Mean Score</th>
                    <th className="py-2 pr-4">Pass Rate</th>
                    <th className="py-2 pr-4">Total Cost</th>
                    <th className="py-2 pr-4">Avg / p95 Time</th>
                    <th className="py-2">Avg Tokens</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {Object.entries(expDetail.summaries).map(([name, s]) => (
                    <tr key={name}>
                      <td className="py-2 pr-4 font-mono font-medium text-white">{name}</td>
                      <td className="py-2 pr-4">{s.completed}</td>
                      <td className="py-2 pr-4 text-amber-300">{s.infra_errors}</td>
                      <td className="py-2 pr-4 font-semibold text-emerald-300">
                        {s.mean_score.toFixed(3)}
                      </td>
                      <td className="py-2 pr-4">{(s.pass_rate * 100).toFixed(1)}%</td>
                      <td className="py-2 pr-4">${s.total_cost_usd.toFixed(5)}</td>
                      <td className="py-2 pr-4">
                        {s.avg_runtime_sec}s / {s.p95_runtime_sec}s
                      </td>
                      <td className="py-2">{s.avg_tokens.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            {/* Paired Comparison */}
            {expDetail.comparison && (
              <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/50 p-5">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-slate-400">Compare</span>
                    <select
                      value={configA}
                      onChange={(e) => setConfigA(e.target.value)}
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
                    >
                      {expDetail.config_names.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                    <span className="text-slate-400">vs</span>
                    <select
                      value={configB}
                      onChange={(e) => setConfigB(e.target.value)}
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
                    >
                      {expDetail.config_names.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      expDetail.comparison.verdict === "NOISE"
                        ? "bg-slate-800 text-slate-300"
                        : "bg-emerald-600/30 text-emerald-300"
                    }`}
                  >
                    {expDetail.comparison.verdict}
                  </span>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded bg-slate-950 p-3">
                    <div className="text-xs text-slate-400">Delta (B - A)</div>
                    <div className="text-xl font-bold text-white">
                      {expDetail.comparison.delta_mean >= 0 ? "+" : ""}
                      {expDetail.comparison.delta_mean.toFixed(4)}
                    </div>
                  </div>
                  <div className="rounded bg-slate-950 p-3">
                    <div className="text-xs text-slate-400">95% Bootstrap CI</div>
                    <div className="text-xl font-bold text-white">
                      [{expDetail.comparison.ci_95[0]}, {expDetail.comparison.ci_95[1]}]
                    </div>
                  </div>
                  <div className="rounded bg-slate-950 p-3">
                    <div className="text-xs text-slate-400">Exact McNemar p-value</div>
                    <div className="text-xl font-bold text-white">
                      {expDetail.comparison.mcnemar_p}
                    </div>
                  </div>
                </div>

                {expDetail.comparison.warnings.length > 0 && (
                  <div className="space-y-1 rounded border border-amber-500/30 bg-amber-950/20 p-3 text-xs text-amber-200">
                    {expDetail.comparison.warnings.map((w, i) => (
                      <div key={i}>WARNING: {w}</div>
                    ))}
                  </div>
                )}

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-slate-800 text-slate-400">
                      <tr>
                        <th className="py-2 pr-4">Task</th>
                        <th className="py-2 pr-4">{expDetail.comparison.config_a}</th>
                        <th className="py-2 pr-4">{expDetail.comparison.config_b}</th>
                        <th className="py-2 pr-4">Delta</th>
                        <th className="py-2">95% CI</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {expDetail.comparison.per_task.map((r) => (
                        <tr key={r.task_id}>
                          <td className="py-1.5 pr-4 font-mono text-slate-200">{r.task_id}</td>
                          <td className="py-1.5 pr-4">{r.score_a.toFixed(2)} (n={r.n_a})</td>
                          <td className="py-1.5 pr-4">{r.score_b.toFixed(2)} (n={r.n_b})</td>
                          <td
                            className={`py-1.5 pr-4 font-semibold ${
                              r.delta > 0
                                ? "text-emerald-400"
                                : r.delta < 0
                                  ? "text-rose-400"
                                  : "text-slate-400"
                            }`}
                          >
                            {r.delta >= 0 ? "+" : ""}
                            {r.delta.toFixed(2)}
                          </td>
                          <td className="py-1.5 text-slate-400">
                            [{r.ci_95[0]}, {r.ci_95[1]}] {r.is_noise ? "(noise)" : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* Failure Breakdown */}
            <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="mb-3 text-base font-semibold text-white">Failure Breakdown</h2>
              <div className="grid gap-4 md:grid-cols-2">
                {Object.entries(expDetail.failures).map(([cfg, info]) => {
                  const summary = expDetail.summaries[cfg];
                  const passedCount = summary ? Math.round(summary.pass_rate * summary.completed) : 0;
                  const infraCount = summary?.infra_errors ?? 0;
                  const agentFailedCount = Math.max(0, info.failed - infraCount);
                  return (
                    <div key={cfg} className="rounded border border-slate-800 bg-slate-950 p-3 text-xs">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 font-mono font-semibold text-white">
                        <span>{cfg}</span>
                        <span className="text-[11px] font-normal text-slate-300">
                          <span className="text-emerald-400">{passedCount} passed</span>
                          {" · "}
                          <span className={agentFailedCount ? "text-rose-400" : "text-slate-400"}>
                            {agentFailedCount} failed
                          </span>
                          {infraCount > 0 && (
                            <>
                              {" · "}
                              <span className="text-amber-400">{infraCount} infra err</span>
                            </>
                          )}
                          {" "}
                          <span className="text-slate-500">({info.total} total)</span>
                        </span>
                      </div>
                      {Object.keys(info.categories).length === 0 ? (
                        <div className="text-emerald-400">All {info.total} trial(s) passed</div>
                      ) : (
                        <ul className="space-y-1">
                          {Object.entries(info.categories).map(([cat, count]) => (
                            <li key={cat} className="flex items-center justify-between">
                              <span className={cat === "infra_error" ? "text-amber-300" : "text-rose-300"}>
                                {cat}: {count}
                              </span>
                              {info.examples[cat]?.[0] && (
                                <button
                                  onClick={() => {
                                    setSelectedTrialId(info.examples[cat][0]);
                                    setTab("inspector");
                                  }}
                                  className="text-sky-400 underline hover:text-sky-300"
                                >
                                  inspect example
                                </button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        )}

        {/* TAB 3: Trajectory Inspector */}
        {tab === "inspector" && (
          <div className="grid gap-6 lg:grid-cols-12">
            <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/50 p-4 lg:col-span-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Trials ({filteredTrials.length})</h2>
                <select
                  value={trialFilter}
                  onChange={(e) => setTrialFilter(e.target.value as typeof trialFilter)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
                >
                  <option value="all">All</option>
                  <option value="failed">Failed</option>
                  <option value="passed">Passed</option>
                  <option value="infra">Infra Error</option>
                </select>
              </div>
              <div className="max-h-[600px] space-y-1.5 overflow-auto">
                {filteredTrials.map((t) => (
                  <div
                    key={t.trial_id}
                    onClick={() => setSelectedTrialId(t.trial_id)}
                    className={`cursor-pointer rounded border p-2.5 text-xs ${
                      selectedTrialId === t.trial_id
                        ? "border-indigo-500 bg-indigo-950/30"
                        : "border-slate-800 bg-slate-950/60 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between font-medium">
                      <span className="truncate font-mono text-slate-200">{t.task_id}</span>
                      <span
                        className={
                          t.passed
                            ? "text-emerald-400"
                            : t.status === "infra_error"
                              ? "text-amber-400"
                              : "text-rose-400"
                        }
                      >
                        {t.passed ? "PASS" : t.status === "infra_error" ? "INFRA" : "FAIL"}
                      </span>
                    </div>
                    <div className="mt-0.5 flex justify-between text-slate-400">
                      <span>{t.config_name} (t{t.trial_index})</span>
                      <span>{t.failure_category || (t.score !== null ? `score=${t.score}` : "")}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/50 p-5 lg:col-span-8">
              {!trialDetail ? (
                <div className="text-sm text-slate-400">Select a trial to inspect its trajectory.</div>
              ) : (
                <>
                  <div className="rounded-md border border-slate-700 bg-slate-950 p-4 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-sm font-semibold text-white">
                        {trialDetail.trial.trial_id}
                      </span>
                      <span className="rounded bg-slate-800 px-2 py-0.5 font-mono">
                        {trialDetail.trial.failure_category || (trialDetail.trial.passed ? "PASSED" : "FAILED")}
                      </span>
                    </div>
                    <div className="mt-2 grid gap-2 text-slate-300 sm:grid-cols-4">
                      <div>Score: <b>{trialDetail.trial.score ?? "-"}</b></div>
                      <div>Tokens: <b>{trialDetail.trial.input_tokens + trialDetail.trial.output_tokens}</b></div>
                      <div>Cost: <b>${trialDetail.trial.cost_usd.toFixed(5)}</b></div>
                      <div>Time: <b>{trialDetail.trial.runtime_sec}s</b> ({trialDetail.trial.steps} steps)</div>
                    </div>
                    <div className="mt-2 text-slate-400">
                      <b>Grader ({trialDetail.trial.grade?.grader_type || "-"}):</b>{" "}
                      {trialDetail.trial.grade?.reasoning || trialDetail.trial.error_message || "-"}
                    </div>
                  </div>

                  <div className="max-h-[500px] space-y-2 overflow-auto">
                    {trialDetail.events.map((ev) => (
                      <div
                        key={ev.seq}
                        className={`rounded border p-3 text-xs ${EVENT_COLORS[ev.type] || "border-slate-700 bg-slate-950"}`}
                      >
                        <div className="mb-1 flex justify-between font-mono text-[11px] opacity-80">
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
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <h2 className="text-base font-semibold text-white">LLM-as-Judge Calibration</h2>
                <p className="text-xs text-slate-400">
                  Evaluates judge agreement against 30 human-labelled examples in calibration/judge_labels.jsonl
                </p>
              </div>
              <button
                onClick={handleCalibrate}
                disabled={activeJobStatus === "running"}
                className="rounded-md bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                Run Calibration (gemini-flash × 3)
              </button>
            </div>

            {calibrations.length === 0 ? (
              <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-sm text-slate-400">
                No calibration reports yet. Click "Run Calibration" or run{" "}
                <code>uv run eval-calibrate --judge gemini-flash</code>.
              </div>
            ) : (
              calibrations.map((c, idx) => (
                <section key={idx} className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/50 p-5">
                  <div className="flex items-center justify-between">
                    <div className="font-mono text-sm font-semibold text-white">
                      {c.judge_model} — {c.timestamp}
                    </div>
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${
                        c.verdict === "TRUSTED"
                          ? "bg-emerald-600/30 text-emerald-300"
                          : "bg-rose-600/30 text-rose-300"
                      }`}
                    >
                      {c.verdict}
                    </span>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-5">
                    <div className="rounded bg-slate-950 p-3 text-xs">
                      <div className="text-slate-400">Cohen&apos;s κ</div>
                      <div className="text-lg font-bold text-white">{c.cohens_kappa}</div>
                    </div>
                    <div className="rounded bg-slate-950 p-3 text-xs">
                      <div className="text-slate-400">Accuracy</div>
                      <div className="text-lg font-bold text-white">{(c.accuracy * 100).toFixed(1)}%</div>
                    </div>
                    <div className="rounded bg-slate-950 p-3 text-xs">
                      <div className="text-slate-400">Score MAE</div>
                      <div className="text-lg font-bold text-white">{c.score_mae}</div>
                    </div>
                    <div className="rounded bg-slate-950 p-3 text-xs">
                      <div className="text-slate-400">Self-Agreement</div>
                      <div className="text-lg font-bold text-white">{(c.self_agreement * 100).toFixed(1)}%</div>
                    </div>
                    <div className="rounded bg-slate-950 p-3 text-xs">
                      <div className="text-slate-400">Confusion (TP/FP/TN/FN)</div>
                      <div className="text-sm font-bold text-white">
                        {c.confusion_matrix.tp}/{c.confusion_matrix.fp}/{c.confusion_matrix.tn}/{c.confusion_matrix.fn}
                      </div>
                    </div>
                  </div>
                  {c.disagreements.length > 0 && (
                    <div className="overflow-x-auto">
                      <h3 className="mb-2 text-xs font-semibold uppercase text-slate-400">
                        Disagreements ({c.disagreements.length})
                      </h3>
                      <table className="w-full text-left text-xs">
                        <thead className="border-b border-slate-800 text-slate-400">
                          <tr>
                            <th className="py-1.5 pr-3">ID</th>
                            <th className="py-1.5 pr-3">Human</th>
                            <th className="py-1.5 pr-3">Judge</th>
                            <th className="py-1.5">Notes / Reasoning</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          {c.disagreements.map((d) => (
                            <tr key={d.id}>
                              <td className="py-1.5 pr-3 font-mono">{d.id}</td>
                              <td className="py-1.5 pr-3">{String(d.human_passed)} ({d.human_score})</td>
                              <td className="py-1.5 pr-3">{String(d.judge_passed)} ({d.judge_score})</td>
                              <td className="py-1.5 text-slate-300">{d.notes} | {d.judge_reasoning}</td>
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

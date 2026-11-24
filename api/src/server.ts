import { execFile } from "node:child_process";
import { watch as fsWatch, type FSWatcher } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import cors from "@fastify/cors";
import fastifyStatic from "@fastify/static";
import Fastify, { type FastifyInstance } from "fastify";
import { getJob, listJobs, startJob } from "./jobs.js";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(__dirname, "..", "..");

const BRIDGE_MAX_BUFFER_BYTES = 20 * 1024 * 1024;
const SSE_DEBOUNCE_MS = 150;
const SSE_POLL_INTERVAL_MS = 1200;
const SSE_KEEPALIVE_INTERVAL_MS = 15000;
const SLUG_DISPLAY_LIMIT = 2;
const DEFAULT_CONCURRENCY = 2;
const DEFAULT_JUDGE_MODEL = "gemini-flash";
const DEFAULT_CALIBRATION_REPEATS = 3;

const EXPORT_CSV_COLUMNS = [
  "trial_id",
  "config_name",
  "config_hash",
  "harness",
  "model",
  "task_id",
  "trial_index",
  "status",
  "score",
  "passed",
  "runtime_sec",
  "input_tokens",
  "output_tokens",
  "cost_usd",
  "steps",
  "failure_category",
  "error_message",
] as const;

function slugPart(val: string): string {
  return val
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function formatSlugItems(items: string[], maxItems = SLUG_DISPLAY_LIMIT): string {
  if (items.length === 0) return "";
  if (items.length <= maxItems) return items.join("_");
  return `${items.slice(0, maxItems).join("_")}_+${items.length - maxItems}`;
}

function makeExpId(harnesses: string[] = [], models: string[] = []): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const ts = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;

  const harnessSlugs = Array.from(new Set(harnesses.map(slugPart).filter(Boolean)));
  const modelSlugs = Array.from(
    new Set(
      models
        .map((m) => slugPart(m.includes("/") ? m.split("/").pop() || m : m))
        .filter(Boolean)
    )
  );

  const parts = [formatSlugItems(harnessSlugs), formatSlugItems(modelSlugs), ts].filter(Boolean);
  return parts.length > 1 ? parts.join("__") : `exp_${ts}`;
}

async function summarizeExperimentDirectory(resultsDir: string, experimentId: string) {
  const expDir = path.join(resultsDir, experimentId);
  let createdAt: string | null = null;
  let configs: string[] = [];
  let expectedTrials: number | null = null;

  try {
    const manifest = JSON.parse(await fs.readFile(path.join(expDir, "manifest.json"), "utf-8"));
    createdAt = manifest.created_at ?? null;
    configs = (manifest.configs ?? [])
      .map((entry: { config?: { name?: string } }) => entry.config?.name)
      .filter(Boolean);
    const nConfigs = Array.isArray(manifest.configs) ? manifest.configs.length : 0;
    const nTasks = Array.isArray(manifest.tasks) ? manifest.tasks.length : 0;
    const nTrials = Number(manifest.n_trials ?? 0);
    if (nConfigs > 0 && nTasks > 0 && nTrials > 0) {
      expectedTrials = nConfigs * nTasks * nTrials;
    }
  } catch {
    // Manifest may not be written yet during job startup
  }

  let trialCount = 0;
  let passedCount = 0;
  let infraErrors = 0;
  try {
    const trialsDir = path.join(expDir, "trials");
    const jsonFiles = (await fs.readdir(trialsDir)).filter((name) => name.endsWith(".json"));
    trialCount = jsonFiles.length;
    for (const fileName of jsonFiles) {
      const trial = JSON.parse(await fs.readFile(path.join(trialsDir, fileName), "utf-8"));
      if (trial.status === "infra_error") infraErrors++;
      else if (trial.passed) passedCount++;
    }
  } catch {
    // trials/ directory may not exist yet
  }

  return {
    id: experimentId,
    createdAt,
    configs,
    expectedTrials,
    trialCount,
    passedCount,
    infraErrors,
  };
}

async function listExperiments(rootDir: string) {
  const resultsDir = path.join(rootDir, "results");
  let experimentIds: string[] = [];
  try {
    const dirEntries = await fs.readdir(resultsDir, { withFileTypes: true });
    experimentIds = dirEntries
      .filter((entry) => entry.isDirectory() && entry.name !== "calibration")
      .map((entry) => entry.name)
      .sort()
      .reverse();
  } catch {
    return [];
  }

  return Promise.all(experimentIds.map((id) => summarizeExperimentDirectory(resultsDir, id)));
}

async function readSortedExperimentTrials(
  rootDir: string,
  experimentId: string
): Promise<Record<string, unknown>[]> {
  const trialsDir = path.join(rootDir, "results", experimentId, "trials");
  const jsonFiles = (await fs.readdir(trialsDir)).filter((name) => name.endsWith(".json")).sort();
  return Promise.all(
    jsonFiles.map(async (fileName) =>
      JSON.parse(await fs.readFile(path.join(trialsDir, fileName), "utf-8"))
    )
  );
}

function formatTrialsAsCsv(trials: Record<string, unknown>[]): string {
  const escapeCsvCell = (value: unknown): string => {
    const str = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const rows = [
    EXPORT_CSV_COLUMNS.join(","),
    ...trials.map((trial) =>
      EXPORT_CSV_COLUMNS.map((col) => escapeCsvCell(trial[col])).join(",")
    ),
  ];
  return `${rows.join("\n")}\n`;
}

function resolvePythonRunner(): { bin: string; prefix: string[] } {
  const envBin = process.env.EVAL_PYTHON_BIN;
  if (envBin) {
    return envBin.endsWith("uv")
      ? { bin: envBin, prefix: ["run", "python"] }
      : { bin: envBin, prefix: [] };
  }
  return { bin: "uv", prefix: ["run", "python"] };
}

async function runBridge(root: string, args: string[]): Promise<unknown> {
  const { bin, prefix } = resolvePythonRunner();
  const { stdout } = await execFileAsync(
    bin,
    [...prefix, "-m", "eval_runner.api_bridge", ...args, "--root", root],
    { cwd: root, maxBuffer: BRIDGE_MAX_BUFFER_BYTES }
  );
  return JSON.parse(stdout);
}

async function computeTrialsDirectorySignature(trialsDir: string): Promise<string> {
  try {
    const jsonFiles = (await fs.readdir(trialsDir)).filter((name) => name.endsWith(".json")).sort();
    const fileStats = await Promise.all(
      jsonFiles.map(async (fileName) => {
        const stat = await fs.stat(path.join(trialsDir, fileName));
        return `${fileName}:${stat.mtimeMs}:${stat.size}`;
      })
    );
    return fileStats.join("|");
  } catch {
    return "";
  }
}

export async function buildServer(
  opts: { rootDir?: string; serveStatic?: boolean } = {}
): Promise<FastifyInstance> {
  const rootDir = opts.rootDir || process.env.EVAL_ROOT_DIR || DEFAULT_ROOT;
  const app = Fastify({ logger: false });
  await app.register(cors, { origin: true });

  app.get("/api/health", async () => ({ status: "ok", rootDir }));

  app.get("/api/catalog", async () => runBridge(rootDir, ["catalog"]));

  app.get("/api/experiments", async () => {
    const experiments = await listExperiments(rootDir);
    return { experiments };
  });

  app.get<{ Querystring: { expId?: string; once?: string } }>("/api/events", async (req, reply) => {
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });

    const watchedExpId = req.query.expId || "";
    const closeAfterInitial = req.query.once === "1";
    let closed = false;
    let lastExpsSig = "";
    let lastTrialsSig = "";

    const emitState = async () => {
      if (closed) return;
      try {
        const experiments = await listExperiments(rootDir);
        const expsSig = JSON.stringify(
          experiments.map((e) => [e.id, e.trialCount, e.passedCount, e.infraErrors, e.expectedTrials])
        );
        if (expsSig !== lastExpsSig) {
          lastExpsSig = expsSig;
          reply.raw.write(`event: experiments\ndata: ${JSON.stringify({ experiments })}\n\n`);
        }

        if (watchedExpId) {
          const trialsDir = path.join(rootDir, "results", watchedExpId, "trials");
          const trialsSig = await computeTrialsDirectorySignature(trialsDir);
          if (trialsSig !== lastTrialsSig) {
            const hadPreviousSnapshot = lastTrialsSig !== "";
            lastTrialsSig = trialsSig;
            if (hadPreviousSnapshot || trialsSig !== "") {
              reply.raw.write(
                `event: trial_update\ndata: ${JSON.stringify({ expId: watchedExpId, ts: Date.now() })}\n\n`
              );
            }
          }
        }
      } catch {
        // Ignore transient fs read races during atomic rename
      }
    };

    await emitState();

    if (closeAfterInitial) {
      closed = true;
      reply.raw.end();
      return reply;
    }

    let debounceTimer: NodeJS.Timeout | null = null;
    const scheduleEmit = () => {
      if (closed || debounceTimer) return;
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        void emitState();
      }, SSE_DEBOUNCE_MS);
    };

    const watchers: FSWatcher[] = [];
    const resultsDir = path.join(rootDir, "results");
    try {
      watchers.push(fsWatch(resultsDir, { persistent: false }, scheduleEmit));
    } catch {
      // results/ may not exist yet
    }
    if (watchedExpId) {
      try {
        const expTrialsDir = path.join(resultsDir, watchedExpId, "trials");
        watchers.push(fsWatch(expTrialsDir, { persistent: false }, scheduleEmit));
      } catch {
        // trials/ may not exist yet
      }
    }

    const pollInterval = setInterval(() => void emitState(), SSE_POLL_INTERVAL_MS);
    const keepaliveInterval = setInterval(() => {
      if (!closed) reply.raw.write(": keepalive\n\n");
    }, SSE_KEEPALIVE_INTERVAL_MS);

    req.raw.on("close", () => {
      closed = true;
      if (debounceTimer) clearTimeout(debounceTimer);
      clearInterval(pollInterval);
      clearInterval(keepaliveInterval);
      for (const watcher of watchers) {
        try {
          watcher.close();
        } catch {
          // Ignore watcher close errors
        }
      }
    });

    return reply;
  });

  app.get<{ Params: { id: string }; Querystring: { a?: string; b?: string } }>(
    "/api/experiments/:id",
    async (req, reply) => {
      const { id } = req.params;
      const expDir = path.join(rootDir, "results", id);
      try {
        await fs.access(expDir);
      } catch {
        return reply.code(404).send({ error: `Experiment '${id}' not found` });
      }
      const args = ["analyze", "--exp", id];
      if (req.query.a) args.push("--a", req.query.a);
      if (req.query.b) args.push("--b", req.query.b);
      return runBridge(rootDir, args);
    }
  );

  app.get<{ Params: { id: string } }>("/api/experiments/:id/trials", async (req, reply) => {
    try {
      const trials = await readSortedExperimentTrials(rootDir, req.params.id);
      return { trials };
    } catch {
      return reply.code(404).send({ error: `Trials not found for '${req.params.id}'` });
    }
  });

  app.get<{ Params: { id: string; trialId: string } }>(
    "/api/experiments/:id/trials/:trialId",
    async (req, reply) => {
      const trialsDir = path.join(rootDir, "results", req.params.id, "trials");
      const trialPath = path.join(trialsDir, `${req.params.trialId}.json`);
      try {
        const trial = JSON.parse(await fs.readFile(trialPath, "utf-8"));
        const tracePath = path.join(trialsDir, `${req.params.trialId}.trace.jsonl`);
        let events: unknown[] = [];
        try {
          const rawTrace = await fs.readFile(tracePath, "utf-8");
          events = rawTrace
            .split(/\r?\n/)
            .filter((line) => line.trim())
            .map((line) => JSON.parse(line));
        } catch {
          events = [];
        }
        return { trial, events };
      } catch {
        return reply.code(404).send({ error: `Trial '${req.params.trialId}' not found` });
      }
    }
  );

  app.get<{ Params: { id: string }; Querystring: { format?: string } }>(
    "/api/experiments/:id/export",
    async (req, reply) => {
      const fmt = req.query.format === "csv" ? "csv" : "json";
      let trials: Record<string, unknown>[];
      try {
        trials = await readSortedExperimentTrials(rootDir, req.params.id);
      } catch {
        return reply.code(404).send({ error: `Experiment '${req.params.id}' not found` });
      }

      if (fmt === "json") {
        reply.header("Content-Disposition", `attachment; filename="${req.params.id}.json"`);
        reply.type("application/json");
        return JSON.stringify(trials, null, 2);
      }

      reply.header("Content-Disposition", `attachment; filename="${req.params.id}.csv"`);
      reply.type("text/csv");
      return formatTrialsAsCsv(trials);
    }
  );

  app.get("/api/calibration", async () => {
    const calDir = path.join(rootDir, "results", "calibration");
    try {
      const reportFiles = (await fs.readdir(calDir))
        .filter((name) => name.endsWith(".json"))
        .sort()
        .reverse();
      const reports = await Promise.all(
        reportFiles.map(async (fileName) =>
          JSON.parse(await fs.readFile(path.join(calDir, fileName), "utf-8"))
        )
      );
      return { reports };
    } catch {
      return { reports: [] };
    }
  });

  app.post<{
    Body: {
      harnesses: string[];
      models: string[];
      settingsPath?: string;
      tasksPath?: string;
      tasksPaths?: string[];
      trials?: number;
      concurrency?: number;
      expId?: string;
    };
  }>("/api/experiments/run", async (req, reply) => {
    const body = req.body || {};
    if (!body.harnesses?.length || !body.models?.length) {
      return reply.code(400).send({ error: "Select at least one harness and one model." });
    }
    const expId = body.expId?.trim() || makeExpId(body.harnesses, body.models);
    const { bin, prefix } = resolvePythonRunner();
    const cliArgs = [...prefix, "-m", "eval_runner.cli_exec", "run"];
    for (const harness of body.harnesses) cliArgs.push("-H", harness);
    for (const model of body.models) cliArgs.push("-m", model);
    if (body.settingsPath) cliArgs.push("--settings", body.settingsPath);
    const taskTargets =
      Array.isArray(body.tasksPaths) && body.tasksPaths.length > 0
        ? body.tasksPaths
        : [body.tasksPath || "tasks"];
    for (const taskPath of taskTargets) cliArgs.push("-t", taskPath);
    cliArgs.push(
      "-n",
      String(body.trials || 1),
      "-j",
      String(body.concurrency || DEFAULT_CONCURRENCY),
      "--exp-id",
      expId
    );

    const job = startJob("run", bin, cliArgs, rootDir);
    return { jobId: job.id, expId, status: job.status };
  });

  app.post<{ Params: { id: string } }>("/api/experiments/:id/retry", async (req) => {
    const { bin, prefix } = resolvePythonRunner();
    const job = startJob(
      "retry",
      bin,
      [...prefix, "-m", "eval_runner.cli_exec", "retry", "--exp", req.params.id],
      rootDir
    );
    return { jobId: job.id, status: job.status };
  });

  app.post<{ Body: { judge?: string; repeats?: number } }>("/api/calibration/run", async (req) => {
    const { bin, prefix } = resolvePythonRunner();
    const judge = req.body?.judge || DEFAULT_JUDGE_MODEL;
    const repeats = req.body?.repeats || DEFAULT_CALIBRATION_REPEATS;
    const job = startJob(
      "calibrate",
      bin,
      [
        ...prefix,
        "-m",
        "eval_runner.cli_exec",
        "calibrate",
        "--judge",
        judge,
        "--repeats",
        String(repeats),
      ],
      rootDir
    );
    return { jobId: job.id, status: job.status };
  });

  app.get("/api/jobs", async () => ({ jobs: listJobs() }));

  app.get<{ Params: { jobId: string } }>("/api/jobs/:jobId", async (req, reply) => {
    const job = getJob(req.params.jobId);
    if (!job) return reply.code(404).send({ error: "Job not found" });
    const { emitter: _e, proc: _p, ...rest } = job;
    return rest;
  });

  app.get<{ Params: { jobId: string } }>("/api/jobs/:jobId/stream", async (req, reply) => {
    const job = getJob(req.params.jobId);
    if (!job) return reply.code(404).send({ error: "Job not found" });

    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });

    for (const line of job.logs) {
      reply.raw.write(`event: log\ndata: ${JSON.stringify({ line })}\n\n`);
    }
    if (job.status !== "running") {
      reply.raw.write(
        `event: done\ndata: ${JSON.stringify({ status: job.status, exitCode: job.exitCode })}\n\n`
      );
      reply.raw.end();
      return reply;
    }

    const onLog = (line: string) =>
      reply.raw.write(`event: log\ndata: ${JSON.stringify({ line })}\n\n`);
    const onDone = (payload: unknown) => {
      reply.raw.write(`event: done\ndata: ${JSON.stringify(payload)}\n\n`);
      cleanup();
      reply.raw.end();
    };
    const cleanup = () => {
      job.emitter.off("log", onLog);
      job.emitter.off("done", onDone);
    };
    job.emitter.on("log", onLog);
    job.emitter.on("done", onDone);
    req.raw.on("close", cleanup);
    return reply;
  });

  if (opts.serveStatic !== false) {
    const webDist = path.join(rootDir, "web", "dist");
    try {
      await fs.access(webDist);
      await app.register(fastifyStatic, { root: webDist, wildcard: false });
      app.setNotFoundHandler((_req, reply) => reply.sendFile("index.html"));
    } catch {
      // web/dist not built yet (e.g. dev mode)
    }
  }

  return app;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3000);
  const host = process.env.HOST || "0.0.0.0";
  const server = await buildServer();
  await server.listen({ port, host });
  console.log(`Agent Eval Platform API listening on http://${host}:${port}`);
}

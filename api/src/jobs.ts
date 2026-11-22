import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";

export interface JobRecord {
  id: string;
  kind: "run" | "retry" | "calibrate";
  command: string[];
  status: "running" | "completed" | "failed";
  exitCode: number | null;
  startedAt: string;
  finishedAt: string | null;
  logs: string[];
  emitter: EventEmitter;
  proc?: ChildProcess;
}

const jobs = new Map<string, JobRecord>();

export function getPythonBin(): string {
  return process.env.EVAL_PYTHON_BIN || "uv";
}

export function buildUvOrPythonArgs(moduleOrScript: string, args: string[]): { bin: string; argv: string[] } {
  const bin = getPythonBin();
  if (bin === "uv" || bin.endsWith("/uv")) {
    return { bin, argv: ["run", moduleOrScript, ...args] };
  }
  return { bin, argv: ["-m", moduleOrScript, ...args] };
}

export function startJob(
  kind: JobRecord["kind"],
  bin: string,
  argv: string[],
  cwd: string
): JobRecord {
  const id = randomUUID().slice(0, 8);
  const emitter = new EventEmitter();
  const job: JobRecord = {
    id,
    kind,
    command: [bin, ...argv],
    status: "running",
    exitCode: null,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    logs: [],
    emitter,
  };
  jobs.set(id, job);

  const proc = spawn(bin, argv, { cwd, env: process.env });
  job.proc = proc;

  const pushLines = (chunk: Buffer) => {
    const lines = chunk.toString("utf-8").split(/\r?\n/);
    for (const line of lines) {
      if (!line) continue;
      job.logs.push(line);
      if (job.logs.length > 2000) job.logs.shift();
      emitter.emit("log", line);
    }
  };

  proc.stdout.on("data", pushLines);
  proc.stderr.on("data", pushLines);

  proc.on("close", (code) => {
    job.exitCode = code ?? 1;
    job.status = code === 0 ? "completed" : "failed";
    job.finishedAt = new Date().toISOString();
    emitter.emit("done", { status: job.status, exitCode: job.exitCode });
  });

  proc.on("error", (err) => {
    job.logs.push(`Process error: ${err.message}`);
    job.exitCode = 1;
    job.status = "failed";
    job.finishedAt = new Date().toISOString();
    emitter.emit("done", { status: "failed", exitCode: 1 });
  });

  return job;
}

export function getJob(id: string): JobRecord | undefined {
  return jobs.get(id);
}

export function listJobs(): Omit<JobRecord, "emitter" | "proc">[] {
  return Array.from(jobs.values())
    .map(({ emitter: _e, proc: _p, ...rest }) => rest)
    .reverse();
}

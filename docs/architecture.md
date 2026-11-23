# 1. System Architecture & Execution Flow

[← Back to Documentation Hub](./README.md)

The platform splits responsibilities cleanly between a **TypeScript Control Plane & React UI** (for interactive matrix launches, live SSE job streaming, comparison dashboards, and trajectory inspection) and a **Python Evaluation & Statistical Engine** (for Docker container orchestration, LiteLLM model routing, grading, and SciPy statistical tests).

---

## Architectural Layers

### 1. Presentation & Control Plane (`web/` + `api/`)
- **React Web UI ([`web/src/App.tsx`](../web/src/App.tsx)):** Single-page application built with React 19, Vite, and Tailwind CSS. Organizes evaluation workflows into four tabs: *Run & Experiments*, *Compare & Failures*, *Trajectory Inspector*, and *Judge Calibration*.
- **Fastify API Server ([`api/src/server.ts`](../api/src/server.ts)):** Serves the built React static bundle (`web/dist`) and exposes `/api/*` REST and Server-Sent Events (SSE) endpoints.
- **Background Job Manager ([`api/src/jobs.ts`](../api/src/jobs.ts)):** Spawns non-blocking evaluation, retry, and calibration subprocesses via [`eval_runner/cli_exec.py`](../eval_runner/cli_exec.py) and streams live log lines over SSE (`GET /api/jobs/:jobId/stream`).
- **Python↔TypeScript JSON Bridge ([`eval_runner/api_bridge.py`](../eval_runner/api_bridge.py)):** Invoked by the TypeScript API for `catalog` discovery and `analyze` reports so the CLI and Web UI share the exact same statistical, failure-classification, and calibration logic with zero duplication.

### 2. Core Evaluation Engine (`eval_runner/`)
- **Orchestrator ([`eval_runner/runner.py`](../eval_runner/runner.py)):** Expands `--config` YAML files or `--harness × --model` CLI matrices into `(config, task, trial_index)` jobs, shuffles job order with a deterministic seed to prevent time-of-day provider drift from biasing one configuration, and executes trials in parallel via `ThreadPoolExecutor`.
- **Container Sandbox Manager ([`eval_runner/container.py`](../eval_runner/container.py)):** Manages ephemeral Docker containers via `docker-py` with strict CPU/RAM/PID limits, tar-archive file injection (`put_archive`), dual timeouts, `SIGINT` traps, and orphan container reaping.
- **Adapter Registries ([`eval_runner/agents/`](../eval_runner/agents/) & [`eval_runner/models.py`](../eval_runner/models.py)):** Auto-discovering registries for agent harnesses (`hermes`, `langgraph`) and model backends (`litellm`, `mock`). See [Harness & Model Adapters](./adapters.md).
- **Graders & Post-Run Analysis ([`graders.py`](../eval_runner/graders.py), [`stats.py`](../eval_runner/stats.py), [`failures.py`](../eval_runner/failures.py), [`calibration.py`](../eval_runner/calibration.py)):** Executes deterministic or rubric-based verifiers, classifies failures into 12 categories, and computes paired bootstrap CIs and McNemar $p$-values.

### 3. Pre-Baked Isolated Worker Images (`Dockerfile.*`)
To avoid per-trial dependency installation overhead (which can add 5+ minutes per trial in generic frameworks) and prevent dependency conflicts between agent frameworks, each harness runs in its own pre-baked Docker image:
- **[`Dockerfile.hermes`](../Dockerfile.hermes) (`agent-eval-hermes:latest`):** Built on `python:3.14-slim` (required by `NousResearch/hermes-agent`'s Python 3.14 dependency pins) and installed deterministically from Hermes's `uv.lock`.
- **[`Dockerfile.langgraph`](../Dockerfile.langgraph) (`agent-eval-langgraph:latest`):** Built on `python:3.11-slim` with `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-litellm`, `litellm`, and `pytest`.
- **[`Dockerfile.app`](../Dockerfile.app):** Multi-stage production container packaging the Node 22 TypeScript API, built React frontend, Python 3.11 `eval_runner`, and Docker CLI for single-command `docker compose up` deployment.

---

## Single-Trial Execution Sequence

```mermaid
sequenceDiagram
  autonumber
  participant Orch as runner.py (Host)
  participant Docker as Docker Daemon
  participant Box as Ephemeral Trial Container
  participant LLM as Model Provider (via LiteLLM)
  participant Disk as results/<exp_id>/trials/

  Orch->>Orch: Resolve ConfigSpec, ModelEntry, compute_config_hash()
  Orch->>Docker: Create & start container (mem=4g, cpus=2, pids=256, label=aep.managed=true)
  Orch->>Box: put_archive(/workspace) <- task fixtures/
  Orch->>Box: adapter.prepare_container() -> /io/spec.json, skills/, MEMORY.md
  Orch->>Box: exec_with_timeout(adapter.build_command(), timeout_sec)
  loop Agent Turn Loop (up to max_steps)
    Box->>LLM: Chat completion + tool definitions
    LLM-->>Box: Assistant message / tool_calls
    Box->>Box: Execute tools in /workspace & append TraceEvent to /io/trace.jsonl
  end
  Box->>Box: Write /io/result.json (final_answer, steps, input_tokens, output_tokens)
  Orch->>Box: adapter.extract_outputs() -> result.json + trace.jsonl
  alt Infrastructure Error (429/5xx exhausted, 401/404, runner crash)
    Orch->>Disk: Atomic write <trial_id>.json (status="infra_error", score=null)
  else Completed Trial (or Agent Timeout / Token Budget Exceeded)
    Orch->>Box: put_archive(/grader-tests) <- tasks/<id>/tests/ (post-agent!)
    Orch->>Box: Run /grader-tests/test.sh OR call LLM Judge
    Box-->>Orch: GradeResult (score, passed, reasoning)
    Orch->>Orch: classify_failure() -> failure_category
    Orch->>Disk: Atomic write <trial_id>.trace.jsonl & <trial_id>.json (status="completed")
  end
  Orch->>Docker: container.remove(force=True, v=True) (guaranteed finally block)
```

---

## Related Documents
- **Next:** [2. Harness & Model Adapters](./adapters.md)
- **Isolation & Crash Recovery:** [3. Data Model, Isolation & Reproducibility](./data-model-and-isolation.md)
- **API & UI Wiring:** [6. TypeScript API, Web UI & CLI Reference](./api-and-ui.md)

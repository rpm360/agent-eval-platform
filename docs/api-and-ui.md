# 6. TypeScript API, Web UI & CLI Reference

[← Back to Documentation Hub](./README.md) · [← Statistical Engine & Failure Taxonomy](./statistics-and-failures.md)

The platform can be driven either from the **React Web UI + Fastify TypeScript API** (`http://localhost:3000`) or directly from the **Python CLI** (`uv run eval-*`). Both interfaces read and write the exact same `results/` directory and use the same statistical and grading code via [`eval_runner/api_bridge.py`](../eval_runner/api_bridge.py).

---

## 1. Running the Web UI & TypeScript API

### Option A: One-Command Docker Compose
```bash
cp .env.example .env
# Add GEMINI_API_KEY (and optional ANTHROPIC_API_KEY / OPENROUTER_API_KEY) to .env

# Builds the API/UI + both isolated worker images and starts http://localhost:3000
docker compose up --build
```

### Option B: Local Development Mode
```bash
# Terminal 1: Start the Fastify TypeScript API (port 3000)
cd api && npm install && npm run dev

# Terminal 2: Start the Vite React dev server (port 5173, proxies /api to :3000)
cd web && npm install && npm run dev
```

---

## 2. TypeScript REST & SSE API (`api/src/server.ts`)

All backend endpoints are namespaced under `/api/*` so they never collide with SPA client navigation:

| Method & Route | Description |
| :--- | :--- |
| `GET /api/health` | Health check returning `{"status": "ok", "rootDir": "..."}`. |
| `GET /api/catalog` | Calls `api_bridge.py catalog` to return registered `harnesses`, `models` (`models.yaml`), settings `presets` (`configs/*.yaml`), and all 24 `tasks`. |
| `GET /api/experiments` | Lists all experiments under `results/` with trial counts, pass counts, and `infra_error` counts. |
| `GET /api/experiments/:id?a=&b=` | Calls `api_bridge.py analyze --exp :id` to return per-config summaries, paired bootstrap/McNemar comparison between `a` and `b`, failure breakdowns, failure deltas, and judge calibration status. |
| `GET /api/experiments/:id/trials` | Returns all `TrialResult` JSON records for the experiment. |
| `GET /api/experiments/:id/trials/:trialId` | Returns `{trial, events}` combining the trial summary JSON and its full `.trace.jsonl` event stream. |
| `GET /api/experiments/:id/export?format=json\|csv` | Downloads the experiment's trials as a formatted `.json` or `.csv` file. |
| `POST /api/experiments/run` | Spawns a background matrix evaluation job (`harnesses × models × settingsPath × tasksPath × trials`) and returns `{jobId, status: "running"}`. |
| `POST /api/experiments/:id/retry` | Spawns a background `eval-retry` job that re-runs only `infra_error` or missing trials. |
| `GET /api/calibration` | Lists all judge calibration reports under `results/calibration/`. |
| `POST /api/calibration/run` | Spawns a background `eval-calibrate` job (`{judge, repeats}`). |
| `GET /api/jobs` / `GET /api/jobs/:jobId` | Lists background jobs or returns a single job's status and log buffer. |
| `GET /api/jobs/:jobId/stream` | **Server-Sent Events (SSE)** stream emitting live `event: log` lines and a terminal `event: done` event (`{status, exitCode}`). |

---

## 3. React Web UI (`web/src/App.tsx`)

The Web UI provides a persistent top experiment selector bar (with one-click **Retry Infra Errors**, **Export JSON**, and **Export CSV** actions), a collapsible live SSE job log drawer, and four main tabs:

1. **Run & Experiments:**
   - **Matrix Builder:** Toggle any combination of registered harnesses (`hermes`, `langgraph`), catalog models (`gemini-flash`, `gemini-pro`, `claude-sonnet`, `openrouter-qwen-coder`, `ollama-qwen-coder`, `mock`), or enter a raw LiteLLM `provider/model` string; pick a settings preset (`configs/default.yaml` or `configs/nomem.yaml`), task scope (all 24 tasks or a single task), and $N$ trials.
   - **Experiment List:** Click any past or newly completed experiment to jump straight to its comparison view.
2. **Compare & Failures:**
   - **Quality vs. Cost vs. Latency Table:** Displays completed trials, `infra_errors`, mean score, pass rate, total cost, average/p95 runtime, and average tokens for every config in the experiment.
   - **Paired Statistical Comparison:** Interactive Config A vs. Config B selector showing $\hat{\Delta}$ (`B - A`), the 95% paired bootstrap CI, exact McNemar $p$-value, a `NOISE` vs. `<Config> BETTER` verdict badge, automated power warnings, and a color-coded per-task delta table.
   - **Failure Breakdown:** Groups failed trials by category (`missed_memory`, `missed_skill`, `loop`, `timeout`, `wrong_output`, etc.) with one-click **`inspect example`** links that open the offending trial directly in the Trajectory Inspector.
3. **Trajectory Inspector:**
   - Filter trials by `All`, `Failed`, `Passed`, or `Infra Error`.
   - Displays the trial's score, failure category badge, token/cost/latency metrics, grader reasoning, and a color-coded sequential timeline of every `TraceEvent` (`session_start`, `message`, `tool_call`, `tool_result`, `memory_op`, `skill_invoked`, `error`, `session_end`).
4. **Judge Calibration:**
   - Launch a live 30-example × 3-repeat judge calibration run and inspect Cohen's $\kappa$, accuracy, score MAE, self-agreement, confusion matrix (`TP/FP/TN/FN`), `TRUSTED`/`UNTRUSTED` badge, and a table of human-vs-judge disagreements.

---

## 4. Python CLI Reference (`eval_runner/cli.py`)

All 7 CLI commands are installed via `pyproject.toml` and runnable with `uv run`:

```bash
# 1. Run an experiment (matrix mode with -H and -m, or config files with -c)
uv run eval-run \
  -H hermes -H langgraph \
  -m gemini-flash \
  --settings configs/default.yaml \
  --tasks tasks/ \
  --trials 2 \
  --concurrency 2 \
  --exp-id my_experiment

# 2. Retry ONLY infra_error or missing trials in an existing experiment
uv run eval-retry --exp my_experiment

# 3. Statistical comparison (paired bootstrap 95% CI, McNemar p-value, per-task deltas, trade-offs)
uv run eval-compare --exp my_experiment --a hermes-gemini-flash --b langgraph-gemini-flash

# 4. Failure taxonomy summary & per-category regression deltas
uv run eval-failures --exp my_experiment

# 5. Inspect a single trial's full trajectory & grader verdict
uv run eval-inspect --trial results/my_experiment/trials/<trial_id>.json

# 6. Export trial results to JSON or CSV
uv run eval-export --exp my_experiment --format csv --out results/my_experiment/export.csv

# 7. Validate LLM-as-judge trustworthiness against 30 human-labelled examples
uv run eval-calibrate --judge gemini-flash --repeats 3
```

---

## Related Documents
- **Next:** [7. Cost Model, Assumptions & Known Limits](./cost-and-limits.md)
- **Live Experiment Walkthrough:** [8. Real Experiment Report & Trajectories](./experiments.md)

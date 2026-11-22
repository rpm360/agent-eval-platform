# Agent Evaluation Platform

Evaluates **Hermes Agent** and **LangGraph** (plus any external `HarnessAdapter`) across **Gemini**, **Claude**, **OpenRouter**, and local **Ollama/vLLM** open-weight models in isolated ephemeral Docker containers, with a **TypeScript API & React Web UI**, LiteLLM Router retries, Inspect-style atomic trial logging & `eval-retry`, deterministic + artifact-aware LLM-as-judge graders, judge calibration (`eval-calibrate`), paired bootstrap / McNemar statistics, and rule-based failure analysis (`eval-failures`).

## One-Command Local Run (`docker compose up`)

```bash
cp .env.example .env
# Add GEMINI_API_KEY (and optional ANTHROPIC_API_KEY / OPENROUTER_API_KEY) to .env

# Build the two isolated agent worker images once
docker compose --profile workers build

# Start the TypeScript API + React UI at http://localhost:3000
docker compose up --build
```

## Local Development (CLI + Dev Servers)

```bash
# 1. Install Python dependencies
uv sync --extra dev

# 2. Run unit tests (no Docker or API keys required)
uv run pytest -v

# 3. Start Docker Desktop, then build the two isolated harness images
docker build -f Dockerfile.hermes -t agent-eval-hermes:latest .
docker build -f Dockerfile.langgraph -t agent-eval-langgraph:latest .

# 4. Smoke test end-to-end on the free mock model (Hermes vs LangGraph)
uv run eval-run \
  -H hermes -H langgraph \
  -m mock \
  --settings configs/default.yaml \
  --tasks tasks/ \
  --trials 1

# 5. Compare configs, inspect a trajectory, or export JSON/CSV
uv run eval-compare --exp <exp_id>
uv run eval-inspect --trial results/<exp_id>/trials/<trial_id>.json
uv run eval-export --exp <exp_id> --format csv
```

## Running Live (Multi-Provider & Open-Weight via LiteLLM)

```bash
cp .env.example .env
# Add GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY, etc. to .env

# Run any harness × model matrix with catalog IDs OR raw LiteLLM strings
uv run eval-run \
  -H hermes -H langgraph \
  -m gemini-flash -m openrouter/qwen/qwen-2.5-coder-32b-instruct \
  --settings configs/default.yaml \
  --tasks tasks/ \
  --trials 2

# Memory/skills ablation using configs/nomem.yaml
uv run eval-run \
  -H hermes -m gemini-flash \
  --settings configs/nomem.yaml \
  --tasks tasks/ \
  --trials 2

# If any trials hit infra_error (e.g. exhausted 429s), re-run ONLY those trials:
uv run eval-retry --exp <exp_id>
```

## Extending the Platform (Zero Core Edits)

- **Add a model:** Pass any LiteLLM `provider/model` string directly via `-m` (e.g. `openai/gpt-4o`, `openrouter/...`, `ollama/qwen2.5-coder:7b`), or add an entry to `models.yaml` for custom pricing/fallbacks/`api_base`. For custom non-LiteLLM gateways, register a `ModelAdapter` via `@register_model_adapter` or an `agent_eval.models` entry point.
- **Add a harness:** Drop one adapter file in `eval_runner/agents/<name>.py` subclassing `HarnessAdapter` and decorated with `@register_adapter` (auto-discovered automatically—no edits to `schemas.py`, `runner.py`, or `agents/__init__.py`), or publish an external package with an `agent_eval.harnesses` entry point.
- **Add a task:** Create a folder under `tasks/<task-id>/` with `task.yaml`, `instruction.md`, optional `fixtures/` or `seed/MEMORY.md`, and `tests/test.sh`.

## Documentation

- [Architecture Summary](docs/agent_evaluation_platform_problem_statement_architecture_summary.md)
- [Design Notes](docs/notes.md)

## Assumptions & Known Limits

1. **Docker-in-Docker via host socket:** `docker-compose.yml` mounts `/var/run/docker.sock` so the platform can launch ephemeral `agent-eval-hermes:latest` and `agent-eval-langgraph:latest` sibling containers. Worker images must be built on the host (`docker compose --profile workers build`).
2. **Stateless trial isolation:** Each trial gets a fresh container and cleaned home directory; `memory: true` seeds `tasks/<id>/seed/MEMORY.md` at trial start rather than persisting across independent tasks.
3. **Hermes tool allow-list:** `Settings.tools` is enforced strictly in LangGraph; in Hermes it is forwarded via `enabled_toolsets` when supported by the installed `hermes-agent` version and recorded in `session_start`.
4. **Judge calibration:** `calibration/judge_labels.jsonl` ships with 30 proposed labels that should be reviewed by a human before treating `TRUSTED` (`κ >= 0.6`, `accuracy >= 0.8`) as ground truth.
5. **Statistical power:** Paired bootstrap CIs and McNemar's test assume task-level pairing; `eval-compare` emits warnings when shared tasks `< 10`, trials/task `< 3`, or infra error rate `> 10%`.

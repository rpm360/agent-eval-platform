# Agent Evaluation Platform (Phase 1 — Lean Execution Engine)

Evaluates **Hermes Agent** and **LangGraph** across **Gemini** and **Claude** (plus a zero-cost `mock` model) in isolated ephemeral Docker containers, with LiteLLM Router 429 retries, Inspect-style atomic trial logging & `eval-retry`, deterministic + LLM-as-judge graders, and paired bootstrap / McNemar statistics.

## Quick Start

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

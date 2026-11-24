"""In-container entrypoint for Hermes Agent.

Reads `/io/spec.json`, runs NousResearch/hermes-agent (`AIAgent`), tracks MEMORY.md diffs,
and writes normalized `/io/trace.jsonl` and `/io/result.json`.

Note: Copied standalone into `/opt/eval_agents/container_hermes.py` inside the worker image;
must remain self-contained without host `eval_runner` imports.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import sys
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path("/workspace")
IO_DIR = Path("/io")
TRACE_OUTPUT_PATH = IO_DIR / "trace.jsonl"
RESULT_OUTPUT_PATH = IO_DIR / "result.json"
DEFAULT_HERMES_HOME = "/root/.hermes"
HERMES_INSTALL_PATH = "/opt/hermes-agent"
BRIDGE_PLACEHOLDER_KEY = "litellm-bridge"

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_STEPS = 20
MAX_ASSISTANT_TRACE_CHARS = 4000
MAX_TOOL_RESULT_TRACE_CHARS = 2000
MAX_MEMORY_DIFF_TRACE_CHARS = 2000
INFRA_ERROR_EXIT_CODE = 2

EXCEPTION_INFRA_ERROR_PATTERNS: tuple[str, ...] = (
    "429",
    "404",
    "401",
    "403",
    "not_found",
    "permission_denied",
    "invalid_argument",
    "rate limit",
    "ratelimit",
    "connection",
    "503",
    "502",
    "api key",
    "no llm provider configured",
    "providernotconfigured",
)

RESPONSE_INFRA_ERROR_PATTERNS: tuple[str, ...] = (
    "404",
    "429",
    "401",
    "403",
    "not_found",
    "rate limit",
    "503",
    "502",
    "api key",
    "no llm provider configured",
    "empty stream",
    "temporarily unavailable",
    "didn't answer after",
)


def _build_completion_kwargs(
    request_body: dict[str, Any],
    *,
    target_model: str,
    api_base: Any,
    default_temperature: float,
    max_output_tokens: Any,
) -> dict[str, Any]:
    """Build LiteLLM `completion()` keyword arguments from an incoming OpenAI-style request body."""
    completion_kwargs: dict[str, Any] = {
        "model": target_model,
        "messages": request_body.get("messages") or [],
        "temperature": request_body.get("temperature", default_temperature),
    }
    if request_body.get("tools"):
        completion_kwargs["tools"] = request_body["tools"]
    if request_body.get("tool_choice") is not None:
        completion_kwargs["tool_choice"] = request_body["tool_choice"]
    if max_output_tokens or request_body.get("max_tokens"):
        completion_kwargs["max_tokens"] = int(max_output_tokens or request_body["max_tokens"])
    if api_base:
        completion_kwargs["api_base"] = str(api_base)
        if not os.environ.get("OPENAI_API_KEY"):
            completion_kwargs["api_key"] = "unauthenticated"
    return completion_kwargs


def _accumulate_usage(usage_payload: Any, usage_totals: dict[str, int]) -> None:
    if not isinstance(usage_payload, dict) or not usage_payload:
        return
    usage_totals["input_tokens"] += int(usage_payload.get("prompt_tokens", 0) or 0)
    usage_totals["output_tokens"] += int(usage_payload.get("completion_tokens", 0) or 0)


@contextlib.contextmanager
def _litellm_openai_bridge(
    spec: dict[str, Any],
    usage_totals: dict[str, int],
) -> Iterator[str | None]:
    """Start an in-process OpenAI-compatible `/v1/chat/completions` bridge backed by LiteLLM.

    Routes Hermes (`AIAgent`) through the exact same LiteLLM interface as LangGraph and
    LLM-as-judge—with zero provider-specific branching inside the harness adapter.
    """
    try:
        import litellm
    except ImportError:
        yield None
        return

    litellm.drop_params = True
    target_model = str(spec["litellm_model"])
    api_base = spec.get("api_base")
    settings = spec.get("settings") or {}
    default_temperature = float(settings.get("temperature", DEFAULT_TEMPERATURE))
    max_output_tokens = settings.get("max_output_tokens")

    class _CompletionBridgeHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                request_body = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                request_body = {}

            completion_kwargs = _build_completion_kwargs(
                request_body,
                target_model=target_model,
                api_base=api_base,
                default_temperature=default_temperature,
                max_output_tokens=max_output_tokens,
            )

            try:
                if bool(request_body.get("stream")):
                    completion_kwargs["stream"] = True
                    completion_kwargs["stream_options"] = {"include_usage": True}
                    stream_response = litellm.completion(**completion_kwargs)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    for chunk in stream_response:
                        chunk_dict = (
                            chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
                        )
                        _accumulate_usage(chunk_dict.get("usage"), usage_totals)
                        sse_line = f"data: {json.dumps(chunk_dict)}\n\n".encode("utf-8")
                        self.wfile.write(sse_line)
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    response = litellm.completion(**completion_kwargs)
                    response_dict = (
                        response.model_dump() if hasattr(response, "model_dump") else dict(response)
                    )
                    _accumulate_usage(response_dict.get("usage"), usage_totals)
                    self._send_json(200, response_dict)
            except Exception as exc:
                self._send_json(
                    502,
                    {
                        "error": {
                            "message": str(exc),
                            "type": type(exc).__name__,
                            "code": "litellm_bridge_error",
                        }
                    },
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CompletionBridgeHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _append_trace_event(
    trace_path: Path,
    seq: int,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Append one JSONL trajectory event and return the next sequence number."""
    record = {
        "seq": seq,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    with trace_path.open("a", encoding="utf-8") as trace_file:
        trace_file.write(json.dumps(record) + "\n")
    return seq + 1


def _run_mock(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    """Deterministic zero-cost mock execution for CI/smoke tests."""
    seq = 1
    task_id = spec["task_id"]
    settings = spec["settings"]
    seq = _append_trace_event(
        trace_path, seq, "session_start", {"harness": "hermes", "model": "mock", "task_id": task_id}
    )
    seq = _append_trace_event(
        trace_path, seq, "message", {"role": "user", "content": spec["instruction"]}
    )

    final_answer = "Done."

    if task_id == "calc-compound-interest":
        (WORKSPACE_DIR / "answer.txt").write_text("16288.95\n", encoding="utf-8")
        final_answer = "16288.95"
    elif task_id == "file-csv-aggregate":
        region_totals: dict[str, float] = {}
        with (WORKSPACE_DIR / "sales.csv").open(encoding="utf-8") as sales_file:
            for row in csv.DictReader(sales_file):
                region = row["region"]
                region_totals[region] = round(
                    region_totals.get(region, 0.0) + float(row["amount"]), 2
                )
        (WORKSPACE_DIR / "summary.json").write_text(
            json.dumps(region_totals, indent=2), encoding="utf-8"
        )
        final_answer = json.dumps(region_totals)
    elif task_id == "code-fix-lru-cache":
        lru_source = WORKSPACE_DIR / "lru.py"
        if lru_source.exists():
            patched_source = lru_source.read_text(encoding="utf-8").replace(
                "popitem(last=True)", "popitem(last=False)"
            )
            lru_source.write_text(patched_source, encoding="utf-8")
        final_answer = "Fixed LRU eviction order to popitem(last=False)."
    elif task_id == "mem-deploy-convention":
        memory_file = Path(DEFAULT_HERMES_HOME) / "MEMORY.md"
        if settings.get("memory") and memory_file.exists():
            seq = _append_trace_event(
                trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"}
            )
            (WORKSPACE_DIR / "DEPLOY_TARGET.txt").write_text(
                "prod-eu-west-payments-v2\n", encoding="utf-8"
            )
            final_answer = "prod-eu-west-payments-v2"
        else:
            (WORKSPACE_DIR / "DEPLOY_TARGET.txt").write_text("payments-prod\n", encoding="utf-8")
            final_answer = "payments-prod"
    elif task_id == "skill-release-tag":
        skill_file = Path(DEFAULT_HERMES_HOME) / "skills" / "release-tag-format" / "SKILL.md"
        if skill_file.exists():
            seq = _append_trace_event(
                trace_path,
                seq,
                "skill_invoked",
                {"skill": "release-tag-format", "via": "hermes_skills"},
            )
            (WORKSPACE_DIR / "TAG.txt").write_text("aep-rel-20260305-a1b2c3\n", encoding="utf-8")
            final_answer = "aep-rel-20260305-a1b2c3"
        else:
            (WORKSPACE_DIR / "TAG.txt").write_text("release-20260305\n", encoding="utf-8")
            final_answer = "release-20260305"

    seq = _append_trace_event(
        trace_path, seq, "message", {"role": "assistant", "content": final_answer}
    )
    _append_trace_event(trace_path, seq, "session_end", {"reason": "final"})
    return {
        "final_answer": final_answer,
        "steps": 1,
        "input_tokens": 120,
        "output_tokens": 40,
        "status": "ok",
    }


def _build_hermes_extra_prompt(
    *,
    settings: dict[str, Any],
    hermes_home: Path,
    memory_enabled: bool,
    memory_before: str,
    trace_path: Path,
    seq: int,
) -> tuple[list[str], int]:
    """Assemble optional system prompt sections for `system_prompt_append`, memory, and skills."""
    prompt_sections: list[str] = []
    if settings.get("system_prompt_append"):
        prompt_sections.append(str(settings["system_prompt_append"]))
    if memory_enabled and memory_before:
        seq = _append_trace_event(trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"})
        prompt_sections.append(f"## Persistent Memory (MEMORY.md)\n{memory_before}")
    for skill_id in settings.get("skills", []):
        skill_path = hermes_home / "skills" / skill_id / "SKILL.md"
        if skill_path.exists():
            seq = _append_trace_event(
                trace_path, seq, "skill_invoked", {"skill": skill_id, "via": "hermes_skills"}
            )
            prompt_sections.append(
                f"## Skill: {skill_id}\n{skill_path.read_text(encoding='utf-8')}"
            )
    return prompt_sections, seq


def _instantiate_hermes_agent(
    agent_cls: Any,
    spec: dict[str, Any],
    settings: dict[str, Any],
    effective_base_url: str | None,
) -> Any:
    """Create `AIAgent`, falling back gracefully if older Hermes builds omit `base_url`/`api_key`."""
    agent_kwargs: dict[str, Any] = {
        "model": spec["litellm_model"],
        "max_iterations": int(settings.get("max_steps", DEFAULT_MAX_STEPS)),
        "quiet_mode": True,
    }
    if settings.get("tools") is not None:
        agent_kwargs["enabled_toolsets"] = list(settings["tools"])
    if settings.get("max_output_tokens"):
        agent_kwargs["max_tokens"] = int(settings["max_output_tokens"])
    if effective_base_url:
        agent_kwargs["base_url"] = effective_base_url
        agent_kwargs["api_key"] = BRIDGE_PLACEHOLDER_KEY
    try:
        return agent_cls(**agent_kwargs)
    except TypeError:
        agent_kwargs.pop("base_url", None)
        agent_kwargs.pop("api_key", None)
        return agent_cls(**agent_kwargs)


def _detect_inline_hermes_infra_error(response_dict: dict[str, Any], final_answer: str) -> str | None:
    """Detect upstream provider errors caught internally by Hermes and surfaced as text."""
    error_blob = str(response_dict.get("error") or "")
    if not error_blob and (
        "Provider said:" in final_answer or "didn't answer after" in final_answer
    ):
        error_blob = final_answer
    if not error_blob:
        return None
    lowered = error_blob.lower()
    if any(pattern in lowered for pattern in RESPONSE_INFRA_ERROR_PATTERNS):
        return error_blob
    return None


def _record_hermes_messages(
    messages: list[Any],
    initial_instruction: str,
    trace_path: Path,
    seq: int,
) -> tuple[int, int]:
    """Replay Hermes conversation history into `trace.jsonl`, returning `(steps, next_seq)`."""
    steps = 0
    skipped_initial_user = False

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "assistant"))
        if role == "assistant" and msg.get("tool_calls"):
            steps += 1
            for tool_call in msg["tool_calls"]:
                fn_spec = tool_call.get("function") or {}
                seq = _append_trace_event(
                    trace_path,
                    seq,
                    "tool_call",
                    {"name": fn_spec.get("name", ""), "args": fn_spec.get("arguments", "")},
                )
        elif role == "tool":
            seq = _append_trace_event(
                trace_path,
                seq,
                "tool_result",
                {"output": str(msg.get("content", ""))[:MAX_TOOL_RESULT_TRACE_CHARS]},
            )
        elif role in ("assistant", "user"):
            content = str(msg.get("content") or "")
            if (
                role == "user"
                and not skipped_initial_user
                and content.strip() == initial_instruction.strip()
            ):
                skipped_initial_user = True
                continue
            if content:
                seq = _append_trace_event(
                    trace_path,
                    seq,
                    "message",
                    {"role": role, "content": content[:MAX_ASSISTANT_TRACE_CHARS]},
                )

    return steps, seq


def _resolve_hermes_token_counts(
    response_dict: dict[str, Any],
    usage_totals: dict[str, int],
    agent: Any,
) -> tuple[int, int]:
    """Resolve input/output token counts preferring the LiteLLM bridge tally over session fallbacks."""
    usage = response_dict.get("usage") or response_dict.get("token_usage") or {}
    input_tokens = int(
        usage_totals["input_tokens"]
        or usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or getattr(agent, "session_input_tokens", 0)
        or getattr(agent, "session_prompt_tokens", 0)
        or 0
    )
    output_tokens = int(
        usage_totals["output_tokens"]
        or usage.get("completion_tokens")
        or usage.get("output_tokens")
        or getattr(agent, "session_output_tokens", 0)
        or getattr(agent, "session_completion_tokens", 0)
        or 0
    )
    return input_tokens, output_tokens


def _run_hermes(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    """Execute a live Hermes `AIAgent` trial via the local LiteLLM OpenAI-compatible bridge."""
    seq = 1
    settings = spec["settings"]
    memory_enabled = bool(settings.get("memory", False))
    hermes_home = Path(os.environ.get("HERMES_HOME", DEFAULT_HERMES_HOME))
    memory_file = hermes_home / "MEMORY.md"
    memory_before = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""

    seq = _append_trace_event(
        trace_path,
        seq,
        "session_start",
        {
            "harness": "hermes",
            "model": spec["litellm_model"],
            "memory": memory_enabled,
            "skills": settings.get("skills", []),
            "tools_requested": settings.get("tools"),
            "tools_enforced": settings.get("tools") is not None,
        },
    )
    seq = _append_trace_event(
        trace_path, seq, "message", {"role": "user", "content": spec["instruction"]}
    )

    if HERMES_INSTALL_PATH not in sys.path:
        sys.path.insert(0, HERMES_INSTALL_PATH)

    try:
        from run_agent import AIAgent  # type: ignore[import-not-found]
    except Exception as exc:
        _append_trace_event(trace_path, seq, "error", {"kind": "infra_error", "message": str(exc)})
        return {"status": "infra_error", "error": f"Failed to import Hermes AIAgent: {exc}"}

    extra_prompt_sections, seq = _build_hermes_extra_prompt(
        settings=settings,
        hermes_home=hermes_home,
        memory_enabled=memory_enabled,
        memory_before=memory_before,
        trace_path=trace_path,
        seq=seq,
    )

    usage_totals = {"input_tokens": 0, "output_tokens": 0}
    try:
        with _litellm_openai_bridge(spec, usage_totals) as bridge_url:
            effective_base = bridge_url or (str(spec["api_base"]) if spec.get("api_base") else None)
            if effective_base:
                os.environ["OPENAI_API_BASE"] = effective_base
                os.environ["OPENAI_BASE_URL"] = effective_base
                os.environ.setdefault("OPENAI_API_KEY", BRIDGE_PLACEHOLDER_KEY)

            agent = _instantiate_hermes_agent(AIAgent, spec, settings, effective_base)
            conversation_kwargs: dict[str, Any] = {
                "user_message": spec["instruction"],
                "task_id": spec["task_id"],
            }
            if extra_prompt_sections:
                conversation_kwargs["system_message"] = "\n\n".join(extra_prompt_sections)
            raw_response = agent.run_conversation(**conversation_kwargs)
    except Exception as exc:
        error_message = str(exc)
        lowered = error_message.lower()
        is_infra = any(pattern in lowered for pattern in EXCEPTION_INFRA_ERROR_PATTERNS)
        error_kind = "infra_error" if is_infra else "agent_error"
        _append_trace_event(trace_path, seq, "error", {"kind": error_kind, "message": error_message})
        return {"status": error_kind, "error": error_message}

    if isinstance(raw_response, dict):
        final_answer = str(
            raw_response.get("final_response") or raw_response.get("response") or ""
        )
        inline_infra_error = _detect_inline_hermes_infra_error(raw_response, final_answer)
        if inline_infra_error is not None:
            _append_trace_event(
                trace_path, seq, "error", {"kind": "infra_error", "message": inline_infra_error}
            )
            return {"status": "infra_error", "error": inline_infra_error}

        steps, seq = _record_hermes_messages(
            raw_response.get("messages") or [], spec["instruction"], trace_path, seq
        )
        input_tokens, output_tokens = _resolve_hermes_token_counts(
            raw_response, usage_totals, agent
        )
    else:
        final_answer = str(raw_response)
        steps = 0
        input_tokens = 0
        output_tokens = 0
        seq = _append_trace_event(
            trace_path, seq, "message", {"role": "assistant", "content": final_answer}
        )

    memory_after = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
    if memory_after != memory_before:
        seq = _append_trace_event(
            trace_path,
            seq,
            "memory_op",
            {
                "op": "write",
                "target": "MEMORY.md",
                "content": memory_after[:MAX_MEMORY_DIFF_TRACE_CHARS],
            },
        )

    _append_trace_event(trace_path, seq, "session_end", {"reason": "final"})
    return {
        "final_answer": final_answer,
        "steps": max(steps, 1),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status": "ok",
    }


def main() -> None:
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    TRACE_OUTPUT_PATH.write_text("", encoding="utf-8")

    if spec.get("provider") == "mock":
        trial_output = _run_mock(spec, TRACE_OUTPUT_PATH)
    else:
        trial_output = _run_hermes(spec, TRACE_OUTPUT_PATH)

    RESULT_OUTPUT_PATH.write_text(json.dumps(trial_output, indent=2), encoding="utf-8")
    if trial_output.get("status") == "infra_error":
        sys.exit(INFRA_ERROR_EXIT_CODE)


if __name__ == "__main__":
    main()

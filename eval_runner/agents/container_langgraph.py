"""In-container entrypoint for LangGraph (`create_react_agent` + `SqliteSaver`).

Reads `/io/spec.json`, runs a LangGraph ReAct agent with bash/file/memory/skill tools
and SQLite step checkpointing (`/io/checkpoints.db`), and writes `/io/trace.jsonl` + `/io/result.json`.

Note: Copied standalone into `/opt/eval_agents/container_langgraph.py` inside the worker image;
must remain self-contained without host `eval_runner` imports.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path("/workspace")
IO_DIR = Path("/io")
SKILLS_DIR = IO_DIR / "skills"
MEMORY_FILE_PATH = Path("/agent-home/MEMORY.md")
CHECKPOINTS_DB_PATH = IO_DIR / "checkpoints.db"
TRACE_OUTPUT_PATH = IO_DIR / "trace.jsonl"
RESULT_OUTPUT_PATH = IO_DIR / "result.json"

BASH_TOOL_TIMEOUT_SEC = 30
MAX_BASH_OUTPUT_CHARS = 4000
MAX_READ_FILE_CHARS = 8000
MAX_ASSISTANT_TRACE_CHARS = 4000
MAX_TOOL_RESULT_TRACE_CHARS = 2000
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_STEPS = 20
INFRA_ERROR_EXIT_CODE = 2

UPSTREAM_INFRA_ERROR_PATTERNS: tuple[str, ...] = (
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
)


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
        trace_path,
        seq,
        "session_start",
        {"harness": "langgraph", "model": "mock", "task_id": task_id},
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
        final_answer = "Fixed LRU cache eviction."
    elif task_id == "mem-deploy-convention":
        if settings.get("memory") and MEMORY_FILE_PATH.exists():
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
        skill_file = SKILLS_DIR / "release-tag-format.md"
        if skill_file.exists():
            seq = _append_trace_event(
                trace_path,
                seq,
                "skill_invoked",
                {"skill": "release-tag-format", "via": "read_skill"},
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
        "input_tokens": 100,
        "output_tokens": 35,
        "status": "ok",
    }


def _build_workspace_tools(
    *,
    memory_enabled: bool,
    enabled_skills: list[str],
    allowed_tools: list[str] | None,
) -> list[Any]:
    """Construct the LangChain tool list for `/workspace`, optional skills, and optional memory."""
    from langchain_core.tools import tool

    @tool
    def run_bash(command: str) -> str:
        """Execute a bash command inside /workspace (30s timeout)."""
        try:
            completed = subprocess.run(
                ["bash", "-c", command],
                cwd=str(WORKSPACE_DIR),
                capture_output=True,
                text=True,
                timeout=BASH_TOOL_TIMEOUT_SEC,
            )
            combined_output = (completed.stdout + completed.stderr).strip()
            return f"exit_code={completed.returncode}\n{combined_output[:MAX_BASH_OUTPUT_CHARS]}"
        except subprocess.TimeoutExpired:
            return f"error: command timed out after {BASH_TOOL_TIMEOUT_SEC}s"

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 file relative to /workspace."""
        resolved_path = (WORKSPACE_DIR / path).resolve()
        if not resolved_path.exists():
            return f"error: file not found: {path}"
        return resolved_path.read_text(encoding="utf-8", errors="replace")[:MAX_READ_FILE_CHARS]

    @tool
    def write_file(path: str, content: str) -> str:
        """Write UTF-8 text to a file relative to /workspace."""
        resolved_path = (WORKSPACE_DIR / path).resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path}"

    @tool
    def list_dir(path: str = ".") -> str:
        """List files in a directory relative to /workspace."""
        resolved_path = (WORKSPACE_DIR / path).resolve()
        if not resolved_path.exists():
            return f"error: directory not found: {path}"
        return "\n".join(sorted(entry.name for entry in resolved_path.iterdir()))

    tools: list[Any] = [run_bash, read_file, write_file, list_dir]

    if enabled_skills:

        @tool
        def read_skill(skill_name: str) -> str:
            """Read the instructions for an enabled skill by name."""
            skill_path = SKILLS_DIR / f"{skill_name}.md"
            if not skill_path.exists():
                return f"error: unknown skill '{skill_name}'"
            return skill_path.read_text(encoding="utf-8")

        tools.append(read_skill)

    if memory_enabled:

        @tool
        def read_memory() -> str:
            """Read persistent notes from MEMORY.md."""
            return MEMORY_FILE_PATH.read_text(encoding="utf-8") if MEMORY_FILE_PATH.exists() else "(empty)"

        @tool
        def write_memory(note: str) -> str:
            """Append a note to persistent MEMORY.md."""
            MEMORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with MEMORY_FILE_PATH.open("a", encoding="utf-8") as memory_file:
                memory_file.write(note.strip() + "\n")
            return "saved to MEMORY.md"

        tools.extend([read_memory, write_memory])

    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tools = [registered_tool for registered_tool in tools if registered_tool.name in allowed_set]

    return tools


def _build_chat_llm(spec: dict[str, Any], settings: dict[str, Any]) -> Any:
    """Instantiate `ChatLiteLLM` from normalized trial spec and settings."""
    from langchain_litellm import ChatLiteLLM

    temperature = float(settings.get("temperature", DEFAULT_TEMPERATURE))
    llm_kwargs: dict[str, Any] = {
        "model": spec["litellm_model"],
        "temperature": temperature,
    }
    if settings.get("max_output_tokens"):
        llm_kwargs["max_tokens"] = int(settings["max_output_tokens"])
    if spec.get("api_base"):
        llm_kwargs["api_base"] = spec["api_base"]
        if not os.environ.get("OPENAI_API_KEY") and str(spec["litellm_model"]).startswith("openai/"):
            llm_kwargs["api_key"] = "unauthenticated"
    return ChatLiteLLM(**llm_kwargs)


def _build_system_prompt(
    *,
    trace_path: Path,
    seq: int,
    memory_enabled: bool,
    enabled_skills: list[str],
    system_prompt_append: str | None,
) -> tuple[str, int]:
    """Assemble the ReAct system prompt and record initial `MEMORY.md` read when present."""
    prompt_sections = ["You are a precise coding and automation agent working inside /workspace."]
    if memory_enabled and MEMORY_FILE_PATH.exists():
        seq = _append_trace_event(trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"})
        prompt_sections.append(
            f"## Persistent Memory (MEMORY.md)\n{MEMORY_FILE_PATH.read_text('utf-8')}"
        )
    if enabled_skills:
        prompt_sections.append(
            f"Available skills (call `read_skill` to inspect): {', '.join(enabled_skills)}"
        )
    if system_prompt_append:
        prompt_sections.append(str(system_prompt_append))
    return "\n\n".join(prompt_sections), seq


def _is_upstream_infra_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(pattern in lowered for pattern in UPSTREAM_INFRA_ERROR_PATTERNS)


def _normalize_message_content(raw_content: Any) -> str:
    if isinstance(raw_content, list):
        return "\n".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in raw_content
        )
    return str(raw_content)


def _record_langgraph_messages(
    messages: list[Any],
    trace_path: Path,
    seq: int,
) -> tuple[str, int, int, int, int]:
    """Replay LangGraph state messages into `trace.jsonl` and tally tokens/steps."""
    input_tokens = 0
    output_tokens = 0
    steps = 0
    final_answer = ""

    for message in messages:
        message_type = getattr(message, "type", "")
        content_str = _normalize_message_content(getattr(message, "content", ""))

        usage = getattr(message, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)

        if message_type == "human":
            seq = _append_trace_event(
                trace_path, seq, "message", {"role": "user", "content": content_str}
            )
            continue

        if message_type == "tool":
            seq = _append_trace_event(
                trace_path,
                seq,
                "tool_result",
                {
                    "name": getattr(message, "name", ""),
                    "output": content_str[:MAX_TOOL_RESULT_TRACE_CHARS],
                },
            )
            continue

        if message_type == "ai":
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                steps += 1
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    seq = _append_trace_event(
                        trace_path, seq, "tool_call", {"name": tool_name, "args": tool_args}
                    )
                    if tool_name == "read_skill":
                        seq = _append_trace_event(
                            trace_path,
                            seq,
                            "skill_invoked",
                            {"skill": tool_args.get("skill_name", ""), "via": "read_skill"},
                        )
                    elif tool_name in ("read_memory", "write_memory"):
                        op_kind = "read" if tool_name == "read_memory" else "write"
                        seq = _append_trace_event(
                            trace_path,
                            seq,
                            "memory_op",
                            {"op": op_kind, "target": "MEMORY.md"},
                        )
            if content_str:
                final_answer = content_str
                seq = _append_trace_event(
                    trace_path,
                    seq,
                    "message",
                    {"role": "assistant", "content": content_str[:MAX_ASSISTANT_TRACE_CHARS]},
                )

    return final_answer, steps, input_tokens, output_tokens, seq


def _run_langgraph(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    """Execute a real LangGraph ReAct trial with SQLite checkpointing and trace recording."""
    import litellm
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.prebuilt import create_react_agent

    litellm.drop_params = True

    settings = spec["settings"]
    memory_enabled = bool(settings.get("memory", False))
    enabled_skills: list[str] = list(settings.get("skills", []))
    seq = 1

    seq = _append_trace_event(
        trace_path,
        seq,
        "session_start",
        {
            "harness": "langgraph",
            "model": spec["litellm_model"],
            "memory": memory_enabled,
            "skills": enabled_skills,
        },
    )

    tools = _build_workspace_tools(
        memory_enabled=memory_enabled,
        enabled_skills=enabled_skills,
        allowed_tools=settings.get("tools"),
    )
    chat_llm = _build_chat_llm(spec, settings)
    system_prompt, seq = _build_system_prompt(
        trace_path=trace_path,
        seq=seq,
        memory_enabled=memory_enabled,
        enabled_skills=enabled_skills,
        system_prompt_append=settings.get("system_prompt_append"),
    )
    max_steps = int(settings.get("max_steps", DEFAULT_MAX_STEPS))

    with contextlib.closing(sqlite3.connect(str(CHECKPOINTS_DB_PATH), check_same_thread=False)) as db_conn:
        checkpointer = SqliteSaver(db_conn)
        agent_graph = create_react_agent(
            chat_llm, tools=tools, prompt=system_prompt, checkpointer=checkpointer
        )
        try:
            graph_state = agent_graph.invoke(
                {"messages": [("user", spec["instruction"])]},
                config={
                    "configurable": {"thread_id": spec["task_id"]},
                    "recursion_limit": max_steps * 2 + 2,
                },
            )
        except Exception as exc:
            error_message = str(exc)
            error_kind = "infra_error" if _is_upstream_infra_error(error_message) else "agent_error"
            _append_trace_event(
                trace_path, seq, "error", {"kind": error_kind, "message": error_message}
            )
            return {"status": error_kind, "error": error_message}

    final_answer, steps, input_tokens, output_tokens, seq = _record_langgraph_messages(
        graph_state.get("messages", []), trace_path, seq
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
        trial_output = _run_langgraph(spec, TRACE_OUTPUT_PATH)

    RESULT_OUTPUT_PATH.write_text(json.dumps(trial_output, indent=2), encoding="utf-8")
    if trial_output.get("status") == "infra_error":
        sys.exit(INFRA_ERROR_EXIT_CODE)


if __name__ == "__main__":
    main()

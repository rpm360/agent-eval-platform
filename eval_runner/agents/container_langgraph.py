"""In-container entrypoint for LangGraph (`create_react_agent` + `SqliteSaver`).

Reads `/io/spec.json`, runs a LangGraph ReAct agent with bash/file/memory/skill tools
and SQLite step checkpointing (`/io/checkpoints.db`), and writes `/io/trace.jsonl` + `/io/result.json`.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _write_trace(trace_path: Path, seq: int, ev_type: str, payload: dict[str, Any]) -> int:
    record = {
        "seq": seq,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": ev_type,
        "payload": payload,
    }
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return seq + 1


def _run_mock(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    """Deterministic zero-cost mock execution for CI/smoke tests."""
    seq = 1
    task_id = spec["task_id"]
    settings = spec["settings"]
    seq = _write_trace(
        trace_path,
        seq,
        "session_start",
        {"harness": "langgraph", "model": "mock", "task_id": task_id},
    )
    seq = _write_trace(trace_path, seq, "message", {"role": "user", "content": spec["instruction"]})

    ws = Path("/workspace")
    final_answer = "Done."

    if task_id == "calc-compound-interest":
        (ws / "answer.txt").write_text("16288.95\n", encoding="utf-8")
        final_answer = "16288.95"
    elif task_id == "file-csv-aggregate":
        import csv

        totals: dict[str, float] = {}
        with (ws / "sales.csv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                reg = row["region"]
                totals[reg] = round(totals.get(reg, 0.0) + float(row["amount"]), 2)
        (ws / "summary.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")
        final_answer = json.dumps(totals)
    elif task_id == "code-fix-lru-cache":
        lru = ws / "lru.py"
        if lru.exists():
            txt = lru.read_text(encoding="utf-8").replace(
                "popitem(last=True)", "popitem(last=False)"
            )
            lru.write_text(txt, encoding="utf-8")
        final_answer = "Fixed LRU cache eviction."
    elif task_id == "mem-deploy-convention":
        mem_file = Path("/agent-home/MEMORY.md")
        if settings.get("memory") and mem_file.exists():
            seq = _write_trace(trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"})
            (ws / "DEPLOY_TARGET.txt").write_text("prod-eu-west-payments-v2\n", encoding="utf-8")
            final_answer = "prod-eu-west-payments-v2"
        else:
            (ws / "DEPLOY_TARGET.txt").write_text("payments-prod\n", encoding="utf-8")
            final_answer = "payments-prod"
    elif task_id == "skill-release-tag":
        skill_file = Path("/io/skills/release-tag-format.md")
        if skill_file.exists():
            seq = _write_trace(
                trace_path,
                seq,
                "skill_invoked",
                {"skill": "release-tag-format", "via": "read_skill"},
            )
            (ws / "TAG.txt").write_text("aep-rel-20260305-a1b2c3\n", encoding="utf-8")
            final_answer = "aep-rel-20260305-a1b2c3"
        else:
            (ws / "TAG.txt").write_text("release-20260305\n", encoding="utf-8")
            final_answer = "release-20260305"

    seq = _write_trace(trace_path, seq, "message", {"role": "assistant", "content": final_answer})
    _write_trace(trace_path, seq, "session_end", {"reason": "final"})
    return {
        "final_answer": final_answer,
        "steps": 1,
        "input_tokens": 100,
        "output_tokens": 35,
        "status": "ok",
    }


def _run_langgraph(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    import litellm
    from langchain_core.tools import tool
    from langchain_litellm import ChatLiteLLM
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.prebuilt import create_react_agent

    litellm.drop_params = True

    settings = spec["settings"]
    memory_enabled = bool(settings.get("memory", False))
    enabled_skills: list[str] = list(settings.get("skills", []))
    seq = 1

    seq = _write_trace(
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

    @tool
    def run_bash(command: str) -> str:
        """Execute a bash command inside /workspace (30s timeout)."""
        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd="/workspace",
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = (proc.stdout + proc.stderr).strip()
            return f"exit_code={proc.returncode}\n{out[:4000]}"
        except subprocess.TimeoutExpired:
            return "error: command timed out after 30s"

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 file relative to /workspace."""
        p = (Path("/workspace") / path).resolve()
        if not p.exists():
            return f"error: file not found: {path}"
        return p.read_text(encoding="utf-8", errors="replace")[:8000]

    @tool
    def write_file(path: str, content: str) -> str:
        """Write UTF-8 text to a file relative to /workspace."""
        p = (Path("/workspace") / path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path}"

    @tool
    def list_dir(path: str = ".") -> str:
        """List files in a directory relative to /workspace."""
        p = (Path("/workspace") / path).resolve()
        if not p.exists():
            return f"error: directory not found: {path}"
        return "\n".join(sorted(x.name for x in p.iterdir()))

    tools: list[Any] = [run_bash, read_file, write_file, list_dir]

    if enabled_skills:

        @tool
        def read_skill(skill_name: str) -> str:
            """Read the instructions for an enabled skill by name."""
            sp = Path("/io/skills") / f"{skill_name}.md"
            if not sp.exists():
                return f"error: unknown skill '{skill_name}'"
            return sp.read_text(encoding="utf-8")

        tools.append(read_skill)

    if memory_enabled:

        @tool
        def read_memory() -> str:
            """Read persistent notes from MEMORY.md."""
            mp = Path("/agent-home/MEMORY.md")
            return mp.read_text(encoding="utf-8") if mp.exists() else "(empty)"

        @tool
        def write_memory(note: str) -> str:
            """Append a note to persistent MEMORY.md."""
            mp = Path("/agent-home/MEMORY.md")
            mp.parent.mkdir(parents=True, exist_ok=True)
            with mp.open("a", encoding="utf-8") as f:
                f.write(note.strip() + "\n")
            return "saved to MEMORY.md"

        tools.extend([read_memory, write_memory])

    allowed_tools = settings.get("tools")
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tools = [t for t in tools if t.name in allowed_set]

    temp = float(settings.get("temperature", 0.2))
    llm_kwargs: dict[str, Any] = {
        "model": spec["litellm_model"],
        "temperature": temp,
    }
    if settings.get("max_output_tokens"):
        llm_kwargs["max_tokens"] = int(settings["max_output_tokens"])
    if spec.get("api_base"):
        llm_kwargs["api_base"] = spec["api_base"]
    llm: Any = ChatLiteLLM(**llm_kwargs)

    sys_parts = ["You are a precise coding and automation agent working inside /workspace."]
    if memory_enabled:
        mem_file = Path("/agent-home/MEMORY.md")
        if mem_file.exists():
            seq = _write_trace(trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"})
            sys_parts.append(f"## Persistent Memory (MEMORY.md)\n{mem_file.read_text('utf-8')}")
    if enabled_skills:
        sys_parts.append(
            f"Available skills (call `read_skill` to inspect): {', '.join(enabled_skills)}"
        )
    if settings.get("system_prompt_append"):
        sys_parts.append(str(settings["system_prompt_append"]))

    conn = sqlite3.connect("/io/checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    graph = create_react_agent(llm, tools=tools, prompt="\n\n".join(sys_parts), checkpointer=checkpointer)

    try:
        state = graph.invoke(
            {"messages": [("user", spec["instruction"])]},
            config={
                "configurable": {"thread_id": spec["task_id"]},
                "recursion_limit": int(settings.get("max_steps", 20)) * 2 + 2,
            },
        )
    except Exception as exc:
        err_str = str(exc)
        is_infra = any(
            k in err_str.lower()
            for k in (
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
        )
        kind = "infra_error" if is_infra else "agent_error"
        _write_trace(trace_path, seq, "error", {"kind": kind, "message": err_str})
        return {"status": kind, "error": err_str}
    finally:
        conn.close()

    in_tok = 0
    out_tok = 0
    steps = 0
    final_answer = ""

    for msg in state.get("messages", []):
        mtype = getattr(msg, "type", "")
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content
            )
        content_str = str(content)

        usage = getattr(msg, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            in_tok += int(usage.get("input_tokens", 0) or 0)
            out_tok += int(usage.get("output_tokens", 0) or 0)

        if mtype == "human":
            seq = _write_trace(trace_path, seq, "message", {"role": "user", "content": content_str})
        elif mtype == "ai":
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                steps += 1
                for tc in tool_calls:
                    name = tc.get("name", "")
                    args = tc.get("args", {})
                    seq = _write_trace(
                        trace_path, seq, "tool_call", {"name": name, "args": args}
                    )
                    if name == "read_skill":
                        seq = _write_trace(
                            trace_path,
                            seq,
                            "skill_invoked",
                            {"skill": args.get("skill_name", ""), "via": "read_skill"},
                        )
                    elif name in ("read_memory", "write_memory"):
                        seq = _write_trace(
                            trace_path,
                            seq,
                            "memory_op",
                            {"op": "read" if name == "read_memory" else "write", "target": "MEMORY.md"},
                        )
            if content_str:
                final_answer = content_str
                seq = _write_trace(
                    trace_path, seq, "message", {"role": "assistant", "content": content_str[:4000]}
                )
        elif mtype == "tool":
            seq = _write_trace(
                trace_path,
                seq,
                "tool_result",
                {"name": getattr(msg, "name", ""), "output": content_str[:2000]},
            )

    _write_trace(trace_path, seq, "session_end", {"reason": "final"})
    return {
        "final_answer": final_answer,
        "steps": max(steps, 1),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "status": "ok",
    }


def main() -> None:
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    trace_path = Path("/io/trace.jsonl")
    trace_path.write_text("", encoding="utf-8")

    if spec.get("provider") == "mock":
        result = _run_mock(spec, trace_path)
    else:
        result = _run_langgraph(spec, trace_path)

    Path("/io/result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result.get("status") == "infra_error":
        sys.exit(2)


if __name__ == "__main__":
    main()

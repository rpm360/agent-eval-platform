"""In-container entrypoint for Hermes Agent.

Reads `/io/spec.json`, runs NousResearch/hermes-agent (`AIAgent`), tracks MEMORY.md diffs,
and writes normalized `/io/trace.jsonl` and `/io/result.json`.
"""

from __future__ import annotations

import json
import os
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
        trace_path, seq, "session_start", {"harness": "hermes", "model": "mock", "task_id": task_id}
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
        final_answer = "Fixed LRU eviction order to popitem(last=False)."
    elif task_id == "mem-deploy-convention":
        mem_file = Path("/root/.hermes/MEMORY.md")
        if settings.get("memory") and mem_file.exists():
            seq = _write_trace(
                trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"}
            )
            (ws / "DEPLOY_TARGET.txt").write_text("prod-eu-west-payments-v2\n", encoding="utf-8")
            final_answer = "prod-eu-west-payments-v2"
        else:
            (ws / "DEPLOY_TARGET.txt").write_text("payments-prod\n", encoding="utf-8")
            final_answer = "payments-prod"
    elif task_id == "skill-release-tag":
        skill_file = Path("/root/.hermes/skills/release-tag-format/SKILL.md")
        if skill_file.exists():
            seq = _write_trace(
                trace_path,
                seq,
                "skill_invoked",
                {"skill": "release-tag-format", "via": "hermes_skills"},
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
        "input_tokens": 120,
        "output_tokens": 40,
        "status": "ok",
    }


def _run_hermes(spec: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    seq = 1
    settings = spec["settings"]
    memory_enabled = bool(settings.get("memory", False))
    hermes_home = Path(os.environ.get("HERMES_HOME", "/root/.hermes"))
    mem_file = hermes_home / "MEMORY.md"
    mem_before = mem_file.read_text(encoding="utf-8") if mem_file.exists() else ""

    seq = _write_trace(
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
    seq = _write_trace(trace_path, seq, "message", {"role": "user", "content": spec["instruction"]})

    # Make /opt/hermes-agent importable
    if "/opt/hermes-agent" not in sys.path:
        sys.path.insert(0, "/opt/hermes-agent")

    try:
        from run_agent import AIAgent  # type: ignore[import-not-found]
    except Exception as exc:
        _write_trace(trace_path, seq, "error", {"kind": "infra_error", "message": str(exc)})
        return {"status": "infra_error", "error": f"Failed to import Hermes AIAgent: {exc}"}

    # Inject skill content into system prompt append if Hermes skills are enabled
    extra_prompt_parts: list[str] = []
    if settings.get("system_prompt_append"):
        extra_prompt_parts.append(str(settings["system_prompt_append"]))
    if memory_enabled and mem_before:
        seq = _write_trace(trace_path, seq, "memory_op", {"op": "read", "target": "MEMORY.md"})
        extra_prompt_parts.append(f"## Persistent Memory (MEMORY.md)\n{mem_before}")
    for skill_id in settings.get("skills", []):
        skill_path = hermes_home / "skills" / skill_id / "SKILL.md"
        if skill_path.exists():
            seq = _write_trace(
                trace_path, seq, "skill_invoked", {"skill": skill_id, "via": "hermes_skills"}
            )
            extra_prompt_parts.append(
                f"## Skill: {skill_id}\n{skill_path.read_text(encoding='utf-8')}"
            )

    try:
        if spec.get("api_base"):
            os.environ.setdefault("OPENAI_API_BASE", str(spec["api_base"]))
            os.environ.setdefault("LITELLM_API_BASE", str(spec["api_base"]))
        agent_kwargs: dict[str, Any] = {
            "model": spec["litellm_model"],
            "max_iterations": int(settings.get("max_steps", 20)),
            "quiet_mode": True,
        }
        if settings.get("tools") is not None:
            agent_kwargs["enabled_toolsets"] = list(settings["tools"])
        if settings.get("max_output_tokens"):
            agent_kwargs["max_tokens"] = int(settings["max_output_tokens"])
        if spec.get("api_base"):
            agent_kwargs["base_url"] = str(spec["api_base"])
        try:
            agent = AIAgent(**agent_kwargs)
        except TypeError:
            agent_kwargs.pop("base_url", None)
            agent = AIAgent(**agent_kwargs)
        run_kwargs: dict[str, Any] = {
            "user_message": spec["instruction"],
            "task_id": spec["task_id"],
        }
        if extra_prompt_parts:
            run_kwargs["system_message"] = "\n\n".join(extra_prompt_parts)
        res = agent.run_conversation(**run_kwargs)
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

    final_answer = ""
    in_tok = 0
    out_tok = 0
    steps = 0

    if isinstance(res, dict):
        final_answer = str(res.get("final_response") or res.get("response") or "")
        # Hermes catches some provider errors internally and returns them as final_response
        err_blob = str(res.get("error") or "")
        if not err_blob and (
            "Provider said:" in final_answer or "didn't answer after" in final_answer
        ):
            err_blob = final_answer
        if err_blob and any(
            k in err_blob.lower()
            for k in ("404", "429", "401", "403", "not_found", "rate limit", "503", "502", "api key")
        ):
            _write_trace(trace_path, seq, "error", {"kind": "infra_error", "message": err_blob})
            return {"status": "infra_error", "error": err_blob}
        messages = res.get("messages") or []
        skipped_initial_user = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "assistant"))
            if role == "assistant" and msg.get("tool_calls"):
                steps += 1
                for tc in msg["tool_calls"]:
                    fn = tc.get("function") or {}
                    seq = _write_trace(
                        trace_path,
                        seq,
                        "tool_call",
                        {"name": fn.get("name", ""), "args": fn.get("arguments", "")},
                    )
            elif role == "tool":
                seq = _write_trace(
                    trace_path,
                    seq,
                    "tool_result",
                    {"output": str(msg.get("content", ""))[:2000]},
                )
            elif role in ("assistant", "user"):
                content = str(msg.get("content") or "")
                if (
                    role == "user"
                    and not skipped_initial_user
                    and content.strip() == spec["instruction"].strip()
                ):
                    skipped_initial_user = True
                    continue
                if content:
                    seq = _write_trace(
                        trace_path, seq, "message", {"role": role, "content": content[:4000]}
                    )
        usage = res.get("usage") or res.get("token_usage") or {}
        in_tok = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or getattr(agent, "session_input_tokens", 0)
            or getattr(agent, "session_prompt_tokens", 0)
            or 0
        )
        out_tok = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or getattr(agent, "session_output_tokens", 0)
            or getattr(agent, "session_completion_tokens", 0)
            or 0
        )
    else:
        final_answer = str(res)
        seq = _write_trace(trace_path, seq, "message", {"role": "assistant", "content": final_answer})

    mem_after = mem_file.read_text(encoding="utf-8") if mem_file.exists() else ""
    if mem_after != mem_before:
        seq = _write_trace(
            trace_path,
            seq,
            "memory_op",
            {"op": "write", "target": "MEMORY.md", "content": mem_after[:2000]},
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
        result = _run_hermes(spec, trace_path)

    Path("/io/result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result.get("status") == "infra_error":
        sys.exit(2)


if __name__ == "__main__":
    main()

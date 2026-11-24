"""HarnessAdapter protocol and auto-discovering plugin registry.

Adding a new harness requires only dropping one adapter module under `eval_runner/agents/`
(or exposing an `agent_eval.harnesses` entry point) — zero edits to platform core.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from docker.models.containers import Container
from pydantic import ValidationError

from eval_runner.container import get_file_text
from eval_runner.schemas import ConfigSpec, ModelEntry, TraceEvent

logger = logging.getLogger(__name__)

RESULT_JSON_CONTAINER_PATH = "/io/result.json"
TRACE_JSONL_CONTAINER_PATH = "/io/trace.jsonl"
MAX_RAW_PARSE_ERROR_PREVIEW = 1000
HARNESS_ENTRY_POINT_GROUP = "agent_eval.harnesses"


def _parse_result_json(raw_result: str | None) -> dict[str, Any]:
    if not raw_result:
        return {}
    try:
        parsed = json.loads(raw_result)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {
            "parse_error": "invalid result.json",
            "raw": raw_result[:MAX_RAW_PARSE_ERROR_PREVIEW],
        }


def _parse_trace_jsonl(raw_trace: str | None) -> list[TraceEvent]:
    if not raw_trace:
        return []
    events: list[TraceEvent] = []
    for line_number, raw_line in enumerate(raw_trace.splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        try:
            raw_event = json.loads(stripped_line)
            if not isinstance(raw_event, dict):
                continue
            raw_event.setdefault("seq", line_number)
            events.append(TraceEvent.model_validate(raw_event))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.debug("Skipping malformed trace line %d: %s", line_number, exc)
    return events


class HarnessAdapter(ABC):
    """Base contract bridging host trial orchestration and an isolated container agent loop."""

    name: str
    default_image: str

    def get_container_env(self, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
        """Return harness-specific environment variables to inject into the container."""
        return {}

    @abstractmethod
    def prepare_container(
        self,
        container: Container,
        task_dir: Path,
        instruction: str,
        config: ConfigSpec,
        model: ModelEntry,
        skills_root: Path,
    ) -> None:
        """Inject `/io/spec.json`, skills, and optional memory files into the container."""

    @abstractmethod
    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        """Return argv list to run the agent inside the container."""

    def extract_outputs(
        self, container: Container
    ) -> tuple[dict[str, Any], list[TraceEvent]]:
        """Read `/io/result.json` and `/io/trace.jsonl` produced by the in-container runner."""
        result_raw = get_file_text(container, RESULT_JSON_CONTAINER_PATH)
        trace_raw = get_file_text(container, TRACE_JSONL_CONTAINER_PATH)
        return _parse_result_json(result_raw), _parse_trace_jsonl(trace_raw)


_REGISTRY: dict[str, type[HarnessAdapter]] = {}
_DISCOVERED = False


def register_adapter(cls: type[HarnessAdapter]) -> type[HarnessAdapter]:
    """Class decorator registering a `HarnessAdapter` implementation by its `name`."""
    _REGISTRY[cls.name] = cls
    return cls


def _is_internal_agent_module(module_name: str) -> bool:
    return (
        module_name == "base"
        or module_name.startswith("container_")
        or module_name.startswith("_")
    )


def discover_adapters() -> None:
    """Auto-discover harness adapters in `eval_runner/agents/` and `agent_eval.harnesses` entry points."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True

    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if _is_internal_agent_module(module_info.name):
            continue
        importlib.import_module(f"eval_runner.agents.{module_info.name}")

    try:
        entry_points = importlib.metadata.entry_points(group=HARNESS_ENTRY_POINT_GROUP)
    except Exception as exc:
        logger.debug("Could not query %s entry points: %s", HARNESS_ENTRY_POINT_GROUP, exc)
        return

    for entry_point in entry_points:
        try:
            entry_point.load()
        except Exception as exc:
            logger.warning("Failed to load harness entry point '%s': %s", entry_point.name, exc)


def get_adapter(name: str) -> HarnessAdapter:
    """Instantiate a registered `HarnessAdapter` by name."""
    discover_adapters()
    if name not in _REGISTRY:
        raise KeyError(f"Unknown harness '{name}'. Registered: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    """Return sorted names of all registered `HarnessAdapter` implementations."""
    discover_adapters()
    return sorted(_REGISTRY.keys())

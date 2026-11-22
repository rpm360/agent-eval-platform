"""HarnessAdapter protocol and auto-discovering plugin registry.

Adding a new harness requires only dropping one adapter module under `eval_runner/agents/`
(or exposing an `agent_eval.harnesses` entry point) — zero edits to platform core.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from docker.models.containers import Container

from eval_runner.container import get_file_text
from eval_runner.schemas import ConfigSpec, ModelEntry, TraceEvent


class HarnessAdapter(ABC):
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
        """Inject spec, skills, and optional memory files into the container."""

    @abstractmethod
    def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
        """Return argv list to run the agent inside the container."""

    def extract_outputs(
        self, container: Container
    ) -> tuple[dict[str, Any], list[TraceEvent]]:
        """Read `/io/result.json` and `/io/trace.jsonl` produced by the in-container runner."""
        result_raw = get_file_text(container, "/io/result.json")
        result_data: dict[str, Any] = {}
        if result_raw:
            try:
                result_data = json.loads(result_raw)
            except Exception:
                result_data = {"parse_error": "invalid result.json", "raw": result_raw[:1000]}

        trace_raw = get_file_text(container, "/io/trace.jsonl")
        events: list[TraceEvent] = []
        if trace_raw:
            for idx, line in enumerate(trace_raw.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    obj.setdefault("seq", idx)
                    events.append(TraceEvent.model_validate(obj))
                except Exception:
                    continue
        return result_data, events


_REGISTRY: dict[str, type[HarnessAdapter]] = {}
_DISCOVERED = False


def register_adapter(cls: type[HarnessAdapter]) -> type[HarnessAdapter]:
    _REGISTRY[cls.name] = cls
    return cls


def discover_adapters() -> None:
    """Auto-discover harness adapters in `eval_runner/agents/` and `agent_eval.harnesses` entry points."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True

    pkg_dir = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        if mod.name == "base" or mod.name.startswith("container_") or mod.name.startswith("_"):
            continue
        importlib.import_module(f"eval_runner.agents.{mod.name}")

    try:
        eps = importlib.metadata.entry_points(group="agent_eval.harnesses")
    except Exception:
        return
    for ep in eps:
        try:
            ep.load()
        except Exception:
            continue


def get_adapter(name: str) -> HarnessAdapter:
    discover_adapters()
    if name not in _REGISTRY:
        raise KeyError(f"Unknown harness '{name}'. Registered: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    discover_adapters()
    return sorted(_REGISTRY.keys())

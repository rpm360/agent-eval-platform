"""Pydantic schemas and deterministic config hashing for the evaluation runner."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from eval_runner.constants import HASH_HEX_PREFIX_LEN

OPTIONAL_HASH_EXCLUDED_WHEN_NONE: tuple[str, ...] = (
    "tools",
    "max_output_tokens",
    "max_total_tokens",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelPricing(BaseModel):
    """Per-million-token USD pricing rates for input and output tokens."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


class ModelEntry(BaseModel):
    """Catalog entry mapping a logical model ID to its provider routing and pricing metadata."""

    id: str
    litellm: str
    provider: str
    adapter: str = "litellm"
    env_key: str = ""
    env_aliases: list[str] = Field(default_factory=list)
    api_base: str | None = None
    requires_api_key: bool = True
    fallback: str | None = None
    pricing: ModelPricing = Field(default_factory=ModelPricing)


class ModelCatalog(BaseModel):
    """Collection of configured models loaded from `models.yaml`."""

    models: list[ModelEntry]

    def get(self, model_id: str) -> ModelEntry:
        """Look up a `ModelEntry` by exact catalog `id`, raising `KeyError` if absent."""
        for model_entry in self.models:
            if model_entry.id == model_id:
                return model_entry
        available_ids = [model_entry.id for model_entry in self.models]
        raise KeyError(f"Unknown model id '{model_id}'. Available: {available_ids}")


class Settings(BaseModel):
    """Runtime hyperparameters, tool/skill permissions, and token/time budgets for a harness."""

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_steps: int = Field(default=20, gt=0)
    timeout_sec: int = Field(default=180, gt=0)
    memory: bool = False
    skills: list[str] = Field(default_factory=list)
    system_prompt_append: str | None = None
    tools: list[str] | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)


class ConfigSpec(BaseModel):
    """Declarative evaluation arm binding a harness adapter, model reference, and `Settings`."""

    name: str
    harness: str  # registered HarnessAdapter name
    model: str  # catalog id from models.yaml or LiteLLM provider/model string
    settings: Settings = Field(default_factory=Settings)

    @classmethod
    def from_yaml(cls, path: Path) -> ConfigSpec:
        """Load and validate a `ConfigSpec` from a YAML file."""
        raw_config = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(raw_config)


def compute_config_hash(config: ConfigSpec, model_entry: ModelEntry) -> str:
    """Compute a deterministic 12-char SHA-256 fingerprint of a config version.

    Excludes `pricing` so provider price updates do not mint a new config version.
    Omits optional `tools`, `max_output_tokens`, `max_total_tokens`, and `api_base` when `None`
    so existing hashes remain backward-compatible.
    """
    settings_dict = config.settings.model_dump(mode="json")
    for optional_key in OPTIONAL_HASH_EXCLUDED_WHEN_NONE:
        if settings_dict.get(optional_key) is None:
            settings_dict.pop(optional_key, None)

    canonical_payload: dict[str, Any] = {
        "name": config.name,
        "harness": config.harness,
        "model_id": model_entry.id,
        "litellm": model_entry.litellm,
        "provider": model_entry.provider,
        "settings": settings_dict,
    }
    if model_entry.api_base is not None:
        canonical_payload["api_base"] = model_entry.api_base
    serialized_payload = json.dumps(
        canonical_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized_payload).hexdigest()[:HASH_HEX_PREFIX_LEN]


class GraderSpec(BaseModel):
    """Verification configuration declared inside a task's `task.yaml`."""

    type: Literal["deterministic", "llm_judge"] = "deterministic"
    script: str = "tests/test.sh"
    rubric: str | None = None
    judge_model: str | None = None
    pass_threshold: float = 0.7
    artifacts: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    """Metadata and grading specification for a single benchmark task directory."""

    id: str
    category: str = "general"
    description: str = ""
    discriminates: list[str] = Field(default_factory=list)
    timeout_sec: int = 180
    grader: GraderSpec = Field(default_factory=GraderSpec)

    @classmethod
    def from_dir(cls, task_dir: Path) -> TaskSpec:
        """Load `task.yaml` from `task_dir`, defaulting `id` to the directory basename."""
        metadata_path = task_dir / "task.yaml"
        if not metadata_path.exists():
            return cls(id=task_dir.name)
        raw_metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        raw_metadata.setdefault("id", task_dir.name)
        return cls.model_validate(raw_metadata)


class TraceEvent(BaseModel):
    """Single step event inside a trial's `.trace.jsonl` trajectory log."""

    seq: int
    ts: str = Field(default_factory=_utc_now_iso)
    type: Literal[
        "session_start",
        "message",
        "tool_call",
        "tool_result",
        "memory_op",
        "skill_invoked",
        "model_call",
        "error",
        "session_end",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class GradeResult(BaseModel):
    """Outcome produced by either the deterministic container verifier or LLM-as-judge."""

    grader_type: str
    score: float
    passed: bool
    reasoning: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class TrialResult(BaseModel):
    """Persisted record of a single `(config, task, trial_index)` evaluation attempt."""

    trial_id: str
    experiment_id: str
    config_name: str
    config_hash: str
    harness: str
    model: str
    task_id: str
    trial_index: int
    status: Literal["completed", "infra_error"]
    score: float | None = None
    passed: bool | None = None
    runtime_sec: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    final_answer: str = ""
    grade: GradeResult | None = None
    failure_category: str | None = None
    error_message: str | None = None
    trace_path: str | None = None
    created_at: str = Field(default_factory=_utc_now_iso)

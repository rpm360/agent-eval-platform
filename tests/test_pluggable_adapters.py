"""Tests verifying pluggable HarnessAdapter and ModelAdapter registries (zero core edits)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.agents import HarnessAdapter, get_adapter, list_adapters, register_adapter
from eval_runner.models import (
    ModelAdapter,
    get_model_adapter,
    list_model_adapters,
    load_models_catalog,
    register_model_adapter,
    resolve_model,
)
from eval_runner.runner import _build_container_env, run_experiment, run_single_trial
from eval_runner.schemas import (
    ConfigSpec,
    GradeResult,
    ModelCatalog,
    ModelEntry,
    Settings,
    TraceEvent,
    compute_config_hash,
)


def test_harness_adapters_auto_discovered() -> None:
    adapters = list_adapters()
    assert "hermes" in adapters
    assert "langgraph" in adapters


def test_harness_specific_env_lives_in_adapter_not_core(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-gem-key")
    catalog = load_models_catalog(Path("models.yaml"))
    gemini = catalog.get("gemini-flash")

    hermes_cfg = ConfigSpec(name="h", harness="hermes", model="gemini-flash", settings=Settings())
    lg_cfg = ConfigSpec(name="l", harness="langgraph", model="gemini-flash", settings=Settings())

    hermes_env = _build_container_env(get_adapter("hermes"), hermes_cfg, gemini)
    lg_env = _build_container_env(get_adapter("langgraph"), lg_cfg, gemini)

    assert hermes_env["HERMES_HOME"] == "/root/.hermes"
    assert hermes_env["GEMINI_API_KEY"] == "test-gem-key"
    assert hermes_env["GOOGLE_API_KEY"] == "test-gem-key"

    assert "HERMES_HOME" not in lg_env
    assert lg_env["GEMINI_API_KEY"] == "test-gem-key"
    assert lg_env["GOOGLE_API_KEY"] == "test-gem-key"


def test_open_weight_and_openrouter_models_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = load_models_catalog(Path("models.yaml"))

    ollama = catalog.get("ollama-qwen-coder")
    assert ollama.requires_api_key is False
    assert ollama.api_base == "http://host.docker.internal:11434"
    ollama_env = get_model_adapter(ollama.adapter).build_container_env(ollama)
    assert ollama_env == {"LITELLM_API_BASE": "http://host.docker.internal:11434"}

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret-key")
    or_model = catalog.get("openrouter-qwen-coder")
    or_env = get_model_adapter(or_model.adapter).build_container_env(or_model)
    assert or_env == {"OPENROUTER_API_KEY": "or-secret-key"}

    vllm = catalog.get("Qwen2.5-7B")
    assert vllm.requires_api_key is False
    assert vllm.api_base == "https://oss-llm-test-874570031229.asia-southeast1.run.app/v1"
    vllm_env = get_model_adapter(vllm.adapter).build_container_env(vllm)
    assert vllm_env == {
        "LITELLM_API_BASE": "https://oss-llm-test-874570031229.asia-southeast1.run.app/v1",
        "OPENAI_API_KEY": "unauthenticated",
    }


def test_custom_harness_runs_without_touching_core(tmp_path: Path) -> None:
    @register_adapter
    class CustomDemoHarness(HarnessAdapter):
        name = "custom-demo-harness"
        default_image = "custom-demo:latest"

        def get_container_env(self, config: ConfigSpec, model: ModelEntry) -> dict[str, str]:
            return {"CUSTOM_HARNESS_FLAG": "1"}

        def prepare_container(
            self,
            container: Any,
            task_dir: Path,
            instruction: str,
            config: ConfigSpec,
            model: ModelEntry,
            skills_root: Path,
        ) -> None:
            pass

        def build_command(self, config: ConfigSpec, model: ModelEntry) -> list[str]:
            return ["echo", "ok"]

        def extract_outputs(self, container: Any) -> tuple[dict[str, Any], list[TraceEvent]]:
            return (
                {
                    "status": "ok",
                    "final_answer": "42",
                    "steps": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                },
                [TraceEvent(seq=1, type="session_end", payload={"reason": "final"})],
            )

    cfg = ConfigSpec(
        name="custom-demo-ollama",
        harness="custom-demo-harness",
        model="ollama-qwen-coder",
        settings=Settings(),
    )
    catalog = load_models_catalog(Path("models.yaml"))
    model = catalog.get("ollama-qwen-coder")

    captured_env: dict[str, str] = {}
    captured_image: list[str] = []

    @contextmanager
    def fake_ephemeral(client: Any, *, image: str, env: dict[str, str] | None = None):
        captured_image.append(image)
        captured_env.update(env or {})
        yield MagicMock()

    with (
        patch("eval_runner.runner.get_docker_client", return_value=MagicMock()),
        patch("eval_runner.runner.ephemeral_container", side_effect=fake_ephemeral),
        patch("eval_runner.runner.exec_with_timeout", return_value=(0, "ok", False)),
        patch(
            "eval_runner.runner.grade_trial",
            return_value=GradeResult(grader_type="deterministic", score=1.0, passed=True),
        ),
    ):
        result = run_single_trial(
            experiment_id="exp_custom",
            task_dir=Path("tasks/calc-compound-interest"),
            config=cfg,
            model=model,
            catalog=catalog,
            trial_index=1,
            results_dir=tmp_path,
        )

    assert result.status == "completed"
    assert result.harness == "custom-demo-harness"
    assert result.passed is True
    assert captured_image == ["custom-demo:latest"]
    assert captured_env["CUSTOM_HARNESS_FLAG"] == "1"
    assert captured_env["LITELLM_API_BASE"] == "http://host.docker.internal:11434"
    assert "HERMES_HOME" not in captured_env


def test_custom_model_adapter_registration() -> None:
    @register_model_adapter
    class CustomGatewayAdapter(ModelAdapter):
        name = "custom-gateway"

        def build_container_env(self, model: ModelEntry) -> dict[str, str]:
            return {"CUSTOM_GW_TOKEN": "tok"}

        def complete(
            self,
            model: ModelEntry,
            messages: list[dict[str, Any]],
            temperature: float = 0.0,
            **kwargs: Any,
        ) -> tuple[str, int, int]:
            return "hello from custom gateway", 12, 4

    assert "custom-gateway" in list_model_adapters()
    entry = ModelEntry(
        id="gw-model",
        litellm="custom/gw-1",
        provider="custom",
        adapter="custom-gateway",
        requires_api_key=False,
    )
    adapter = get_model_adapter(entry.adapter)
    assert adapter.build_container_env(entry) == {"CUSTOM_GW_TOKEN": "tok"}
    text, in_tok, out_tok = adapter.complete(entry, [{"role": "user", "content": "hi"}])
    assert text == "hello from custom gateway"
    assert (in_tok, out_tok) == (12, 4)


def test_config_hash_backward_compatible_and_sensitive_to_api_base() -> None:
    cfg = ConfigSpec(name="test", harness="hermes", model="m1", settings=Settings())
    m_no_base = ModelEntry(id="m1", litellm="ollama/qwen", provider="ollama", requires_api_key=False)
    m_with_base = m_no_base.model_copy(update={"api_base": "http://localhost:11434"})
    assert compute_config_hash(cfg, m_no_base) != compute_config_hash(cfg, m_with_base)

    # New optional Settings fields (None) must preserve the exact same hash
    cfg_explicit_none = ConfigSpec(
        name="test",
        harness="hermes",
        model="m1",
        settings=Settings(tools=None, max_output_tokens=None, max_total_tokens=None),
    )
    assert compute_config_hash(cfg, m_no_base) == compute_config_hash(cfg_explicit_none, m_no_base)


def test_resolve_model_supports_direct_litellm_strings() -> None:
    catalog = load_models_catalog(Path("models.yaml"))

    # Catalog ID still works
    assert resolve_model(catalog, "gemini-flash").litellm == "gemini/gemini-3.8-flash"

    # Direct LiteLLM strings work without being in models.yaml
    oai = resolve_model(catalog, "openai/gpt-4o-mini")
    assert oai.provider == "openai"
    assert oai.env_key == "OPENAI_API_KEY"
    assert oai.requires_api_key is True

    or_m = resolve_model(catalog, "openrouter/deepseek/deepseek-chat-v3-0324")
    assert or_m.provider == "openrouter"
    assert or_m.env_key == "OPENROUTER_API_KEY"

    local = resolve_model(catalog, "ollama/llama3.2:3b")
    assert local.provider == "ollama"
    assert local.requires_api_key is False
    assert local.api_base == "http://host.docker.internal:11434"

    with pytest.raises(KeyError):
        resolve_model(catalog, "nonexistent-short-name")


def test_cli_matrix_runs_without_config_yaml_files(tmp_path: Path) -> None:
    seen_arms: list[tuple[str, str, str]] = []

    def fake_trial(
        *,
        experiment_id: str,
        task_dir: Path,
        config: ConfigSpec,
        model: ModelEntry,
        catalog: ModelCatalog,
        trial_index: int,
        results_dir: Path,
        skills_root: Path = Path("skills"),
        image: str | None = None,
    ):
        from eval_runner.schemas import TrialResult

        seen_arms.append((config.name, config.harness, model.litellm))
        return TrialResult(
            trial_id=f"{config.name}_{task_dir.name}_t{trial_index}",
            experiment_id=experiment_id,
            config_name=config.name,
            config_hash=compute_config_hash(config, model),
            harness=config.harness,
            model=model.id,
            task_id=task_dir.name,
            trial_index=trial_index,
            status="completed",
            score=1.0,
            passed=True,
        )

    with (
        patch("eval_runner.runner.run_single_trial", side_effect=fake_trial),
        patch("eval_runner.runner.reap_orphan_containers", return_value=0),
    ):
        _, results = run_experiment(
            harnesses=["hermes", "langgraph"],
            models=["mock", "openrouter/deepseek/deepseek-chat-v3-0324"],
            tasks_path=Path("tasks/calc-compound-interest"),
            n_trials=1,
            concurrency=1,
            results_dir=tmp_path,
        )

    assert len(results) == 4
    assert {(h, m) for _, h, m in seen_arms} == {
        ("hermes", "mock/scripted"),
        ("hermes", "openrouter/deepseek/deepseek-chat-v3-0324"),
        ("langgraph", "mock/scripted"),
        ("langgraph", "openrouter/deepseek/deepseek-chat-v3-0324"),
    }


def test_hermes_and_langgraph_runners_have_no_hardcoded_provider_branches() -> None:
    for runner_file in (
        Path("eval_runner/agents/container_hermes.py"),
        Path("eval_runner/agents/container_langgraph.py"),
    ):
        src = runner_file.read_text(encoding="utf-8")
        for forbidden in ('"anthropic"', '"google"', '"gemini"', '"openrouter"', '"ollama"'):
            assert forbidden not in src, f"{runner_file} must not hardcode provider {forbidden}"



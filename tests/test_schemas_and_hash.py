"""Tests for schemas, model catalog loading, and deterministic config hashing."""

from pathlib import Path

from eval_runner.models import estimate_cost_usd, load_models_catalog
from eval_runner.schemas import ConfigSpec, ModelEntry, ModelPricing, Settings, compute_config_hash


def test_config_hash_ignores_pricing_changes() -> None:
    cfg = ConfigSpec(name="test", harness="hermes", model="gemini-flash", settings=Settings())
    m1 = ModelEntry(
        id="gemini-flash",
        litellm="gemini/gemini-2.5-flash",
        provider="google",
        pricing=ModelPricing(input_per_mtok=0.15, output_per_mtok=0.60),
    )
    m2 = m1.model_copy(update={"pricing": ModelPricing(input_per_mtok=0.50, output_per_mtok=2.00)})
    assert compute_config_hash(cfg, m1) == compute_config_hash(cfg, m2)


def test_config_hash_changes_on_setting_change() -> None:
    m = ModelEntry(id="gemini-flash", litellm="gemini/gemini-2.5-flash", provider="google")
    c1 = ConfigSpec(name="test", harness="hermes", model="gemini-flash", settings=Settings(memory=False))
    c2 = ConfigSpec(name="test", harness="hermes", model="gemini-flash", settings=Settings(memory=True))
    assert compute_config_hash(c1, m) != compute_config_hash(c2, m)


def test_models_catalog_loads_and_computes_cost() -> None:
    catalog = load_models_catalog(Path("models.yaml"))
    gemini = catalog.get("gemini-flash")
    claude = catalog.get("claude-sonnet")
    assert gemini.provider == "google"
    assert claude.provider == "anthropic"
    assert estimate_cost_usd(gemini, 1_000_000, 1_000_000) == 4.5

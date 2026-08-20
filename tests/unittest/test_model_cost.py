import pytest

from pr_agent.algo.model_cost import (DEFAULT_MODEL_PRICES, compute_call_cost,
                                      get_model_prices)
from pr_agent.config_loader import get_settings
from tests.unittest._settings_helpers import restore_settings, snapshot_settings


def test_builtin_defaults_cover_gpt56_family():
    assert DEFAULT_MODEL_PRICES["gpt-5.6-luna"] == {
        "input": 0.20, "output": 1.20, "cached_input": 0.02,
    }
    assert DEFAULT_MODEL_PRICES["gpt-5.6-terra"] == {
        "input": 2.00, "output": 12.00, "cached_input": 0.20,
    }
    assert DEFAULT_MODEL_PRICES["gpt-5.6-sol"] == {
        "input": 5.00, "output": 30.00, "cached_input": 0.50,
    }


def test_exact_model_lookup():
    prices = get_model_prices("gpt-5.6-luna")

    assert prices["input"] == 0.20
    assert prices["output"] == 1.20
    assert prices["cached_input"] == 0.02


def test_provider_prefixed_model_lookup():
    assert get_model_prices("openai/gpt-5.6-luna")["output"] == 1.20
    assert get_model_prices("bedrock/gpt-5.6-terra")["input"] == 2.00


def test_unknown_model_returns_none():
    assert get_model_prices("no/such-model-xyz") is None
    assert get_model_prices("gpt-5.6-luna-notreal") is None


def test_empty_model_returns_none():
    assert get_model_prices(None) is None
    assert get_model_prices("") is None


def test_settings_override_wins_over_defaults():
    snapshot = snapshot_settings(["model_cost"])
    try:
        get_settings().set("model_cost", {
            "gpt-5.6-luna": {"input": 9.99, "output": 9.99, "cached_input": 0.0},
        })

        assert get_model_prices("gpt-5.6-luna")["input"] == 9.99
        # untouched models still resolve from the default table
        assert get_model_prices("gpt-5.6-terra")["input"] == 2.00
    finally:
        restore_settings(snapshot)


def test_compute_call_cost_uses_standard_rates():
    assert compute_call_cost(1_000_000, 0, 0, "gpt-5.6-luna") == pytest.approx(0.20)
    assert compute_call_cost(0, 0, 1_000_000, "gpt-5.6-luna") == pytest.approx(1.20)


def test_compute_call_cost_prices_cached_tokens_at_cache_rate():
    # 600K uncached at $0.20 + 400K cached at $0.02 + no output
    assert compute_call_cost(1_000_000, 400_000, 0, "gpt-5.6-luna") == pytest.approx(0.128)


def test_compute_call_cost_unknown_model_returns_none():
    assert compute_call_cost(1000, 0, 100, "no/such-model-xyz") is None

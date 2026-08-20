"""Per-model token pricing used to estimate the USD cost of a command run.

Prices are USD per 1,000,000 tokens. ``configuration.toml``'s ``[model_cost]``
section is the source of truth for the models PR-Agent ships with; the code
defaults below only kick in when that section is absent (unit tests, minimal
configs). Override any entry in ``.pr_agent.toml`` when your provider or
reseller charges different rates (Bedrock, regional endpoints, long-context
tiers, ...).

The built-in values follow OpenAI's API list as of 2026-07-30 (GPT-5.6 Luna
-80%, Terra -20%, Sol unchanged), short-context standard rates.
"""

from typing import Optional

from pr_agent.config_loader import get_settings

# USD per 1M tokens: input, output, and cached-input (cache hit) rates.
DEFAULT_MODEL_PRICES = {
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cached_input": 0.02},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cached_input": 0.20},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00, "cached_input": 0.50},
}


def _lookup(prices: dict, model: str) -> Optional[dict]:
    """Exact match, then provider-prefixed match (``openai/...``, ``bedrock/...``)."""
    if model in prices:
        return prices[model]
    if "/" in model:
        return prices.get(model.split("/", 1)[1])
    return None


def _litellm_prices(model: str) -> Optional[dict]:
    """Fall back to litellm's model registry for models it knows (e.g. gpt-4o)."""
    try:
        import litellm

        info = litellm.get_model_info(model)
    except Exception:
        return None
    input_cost = getattr(info, "input_cost_per_token", None)
    output_cost = getattr(info, "output_cost_per_token", None)
    if input_cost is None or output_cost is None:
        return None
    return {
        "input": input_cost * 1_000_000,
        "output": output_cost * 1_000_000,
        "cached_input": None,  # litellm does not expose a cache-hit rate here
    }


def get_model_prices(model: Optional[str]) -> Optional[dict]:
    """Return ``{input, output, cached_input}`` prices for a model, or None when unknown.

    Resolution order: settings ``[model_cost]`` -> built-in defaults (both with
    exact then provider-prefix-stripped matching) -> litellm's model registry.
    """
    if not model:
        return None
    configured = get_settings().get("model_cost", None) or {}
    if configured:
        found = _lookup(configured, model)
        if found:
            return dict(found)
    found = _lookup(DEFAULT_MODEL_PRICES, model)
    if found:
        return found
    return _litellm_prices(model)


def compute_call_cost(
    prompt_tokens: int, cached_tokens: int, completion_tokens: int, model: Optional[str]
) -> Optional[float]:
    """USD cost of one LLM call, or None when the model's price is unknown.

    Cached prompt tokens are billed at the cache-hit rate when the model has
    one; otherwise they fall back to the standard input rate.
    """
    prices = get_model_prices(model)
    if prices is None:
        return None
    uncached_prompt = max(0, prompt_tokens - cached_tokens)
    cached_rate = prices.get("cached_input")
    if cached_rate is None:
        cached_rate = prices["input"]
    return (
        uncached_prompt * prices["input"]
        + cached_tokens * cached_rate
        + completion_tokens * prices["output"]
    ) / 1_000_000

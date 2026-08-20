import asyncio

import pytest

from pr_agent.algo.run_details import (RunDetails, add_token_usage,
                                       get_run_details, init_run_details,
                                       log_run_summary, record_ai_call,
                                       record_model_used)


class _Usage:
    """Stand-in for litellm's usage object (attribute access)."""

    def __init__(self, prompt_tokens, completion_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


def test_init_returns_fresh_instance_with_zeroed_counters():
    details = init_run_details()

    assert isinstance(details, RunDetails)
    assert details.model_used is None
    assert details.fallback_used is False
    assert details.prompt_tokens == 0
    assert details.completion_tokens == 0
    assert details.total_tokens == 0
    assert details.cached_prompt_tokens == 0
    assert details.cost_usd == 0
    assert details.num_ai_calls == 0
    assert details.has_token_usage is False
    assert details.duration_seconds >= 0


def test_init_replaces_previous_instance():
    first = init_run_details()
    record_model_used("model-a", is_fallback=True)

    second = init_run_details()

    assert second is not first
    assert get_run_details() is second
    assert second.model_used is None
    assert second.fallback_used is False


def test_record_model_used_tracks_model_and_fallback_flag():
    init_run_details()

    record_model_used("openai/gpt-5.4", is_fallback=True)

    details = get_run_details()
    assert details.model_used == "openai/gpt-5.4"
    assert details.fallback_used is True


def test_fallback_flag_is_sticky_once_a_fallback_was_used():
    init_run_details()

    record_model_used("fallback-model", is_fallback=True)
    record_model_used("primary-model", is_fallback=False)

    details = get_run_details()
    # last successful model wins, but the fallback flag must not be cleared
    assert details.model_used == "primary-model"
    assert details.fallback_used is True


def test_add_token_usage_accumulates_across_calls():
    init_run_details()

    add_token_usage(_Usage(100, 10, 110))
    add_token_usage(
        {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}
    )

    details = get_run_details()
    assert details.prompt_tokens == 105
    assert details.completion_tokens == 11
    assert details.total_tokens == 116
    assert details.has_token_usage is True


def test_add_token_usage_derives_total_when_missing():
    init_run_details()

    add_token_usage({"prompt_tokens": 20, "completion_tokens": 5})

    assert get_run_details().total_tokens == 25


def test_add_token_usage_ignores_none_and_partial_objects():
    init_run_details()

    add_token_usage(None)
    add_token_usage(object())

    details = get_run_details()
    assert details.total_tokens == 0
    assert details.has_token_usage is False


def test_record_ai_call_counts_calls_even_without_usage():
    init_run_details()

    record_ai_call(_Usage(10, 2, 12))
    record_ai_call(None)

    details = get_run_details()
    assert details.num_ai_calls == 2
    assert details.total_tokens == 12


@pytest.mark.asyncio
async def test_concurrent_child_tasks_accumulate_into_parent_collector():
    init_run_details()

    async def record(prompt_tokens, completion_tokens):
        await asyncio.sleep(0)
        record_ai_call(_Usage(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens))

    await asyncio.gather(
        record(10, 1),
        record(20, 2),
        record(30, 3),
    )

    details = get_run_details()
    assert details.num_ai_calls == 3
    assert details.prompt_tokens == 60
    assert details.completion_tokens == 6
    assert details.total_tokens == 66


@pytest.mark.asyncio
async def test_concurrent_runs_keep_collectors_isolated():
    async def run_with_usage(prompt_tokens, completion_tokens):
        init_run_details()
        await asyncio.sleep(0)
        record_ai_call(_Usage(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens))
        return get_run_details()

    first, second = await asyncio.gather(
        run_with_usage(10, 1),
        run_with_usage(20, 2),
    )

    assert first.num_ai_calls == 1
    assert first.prompt_tokens == 10
    assert first.completion_tokens == 1
    assert first.total_tokens == 11

    assert second.num_ai_calls == 1
    assert second.prompt_tokens == 20
    assert second.completion_tokens == 2
    assert second.total_tokens == 22


def test_add_token_usage_tracks_cached_tokens_and_cost():
    init_run_details()

    usage = _Usage(10000, 500, 10500)
    usage.prompt_tokens_details = type("_Details", (), {"cached_tokens": 1000})()
    add_token_usage(usage, "gpt-5.6-luna")

    details = get_run_details()
    assert details.cached_prompt_tokens == 1000
    assert details.cost_usd == pytest.approx(
        (9000 * 0.20 + 1000 * 0.02 + 500 * 1.20) / 1_000_000
    )


def test_add_token_usage_reads_cached_tokens_from_dict():
    init_run_details()

    add_token_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 5,
            "total_tokens": 105,
            "prompt_tokens_details": {"cached_tokens": 40},
        },
        "gpt-5.6-luna",
    )

    details = get_run_details()
    assert details.cached_prompt_tokens == 40
    assert details.cost_usd == pytest.approx(
        (60 * 0.20 + 40 * 0.02 + 5 * 1.20) / 1_000_000
    )


def test_cost_stays_zero_when_model_price_unknown():
    init_run_details()

    record_ai_call(_Usage(100, 10, 110), "no/such-model-xyz")

    details = get_run_details()
    assert details.total_tokens == 110
    assert details.cost_usd == 0


def test_log_run_summary_emits_parseable_line():
    from loguru import logger as loguru_logger

    init_run_details()
    record_model_used("gpt-5.6-luna", is_fallback=False)
    record_ai_call(_Usage(10000, 500, 10500), "gpt-5.6-luna")

    records = []
    sink_id = loguru_logger.add(records.append)
    try:
        log_run_summary("review")
    finally:
        loguru_logger.remove(sink_id)

    assert len(records) == 1
    text = str(records[0])
    assert "command=review" in text
    assert "model=gpt-5.6-luna" in text
    assert "prompt_tokens=10000" in text
    assert "completion_tokens=500" in text
    assert "total_tokens=10500" in text
    # (10000 * 0.20 + 500 * 1.20) / 1M
    assert "cost_usd=0.0026" in text
    assert "ai_calls=1" in text


def test_log_run_summary_skipped_without_model_or_calls():
    from loguru import logger as loguru_logger

    init_run_details()

    records = []
    sink_id = loguru_logger.add(records.append)
    try:
        log_run_summary("help")
    finally:
        loguru_logger.remove(sink_id)

    assert records == []


def test_helpers_are_noops_when_not_initialized():
    from pr_agent.algo import run_details

    token = run_details._run_details.set(None)
    try:
        assert get_run_details() is None
        record_model_used("m", is_fallback=False)  # must not raise
        record_ai_call(_Usage(1, 1, 2))  # must not raise
        add_token_usage({"total_tokens": 5})  # must not raise
    finally:
        run_details._run_details.reset(token)

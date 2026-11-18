"""Fork: `config.fixed_text_language` picks the fixed-text catalog independently of the model's response language."""

import tomllib
from pathlib import Path

import pytest

from pr_agent.algo.i18n import t
from pr_agent.config_loader import get_settings

CONFIG_TOML = Path(__file__).resolve().parents[2] / "pr_agent" / "settings" / "configuration.toml"


@pytest.fixture
def languages():
    settings = get_settings()
    previous = (settings.get("CONFIG.FIXED_TEXT_LANGUAGE", ""), settings.get("CONFIG.RESPONSE_LANGUAGE", "en-US"))

    def apply(fixed_text_language, response_language="en-US"):
        settings.set("CONFIG.FIXED_TEXT_LANGUAGE", fixed_text_language)
        settings.set("CONFIG.RESPONSE_LANGUAGE", response_language)

    yield apply
    settings.set("CONFIG.FIXED_TEXT_LANGUAGE", previous[0])
    settings.set("CONFIG.RESPONSE_LANGUAGE", previous[1])


def test_shipped_default_renders_vietnamese_fixed_text():
    config = tomllib.loads(CONFIG_TOML.read_text(encoding="utf-8"))["config"]

    assert config["fixed_text_language"] == "vi"
    assert config["response_language"] == "en-US"


def test_fixed_text_language_overrides_response_language(languages):
    languages("vi", response_language="en-US")

    assert t("review.intro") == "Dưới đây là một số nhận xét quan trọng giúp ích cho quá trình đánh giá:"
    assert get_settings().config.response_language == "en-US"


def test_empty_fixed_text_language_follows_response_language(languages):
    languages("", response_language="vi-VN")
    assert t("review.estimated_effort") == "Công sức đánh giá ước tính"

    languages("", response_language="en-US")
    assert t("review.estimated_effort") == "Estimated effort to review"


def test_unknown_fixed_text_language_falls_back_to_english(languages):
    languages("xx-YY", response_language="vi-VN")

    assert t("improve.no_suggestions") == "No suggestions found to improve this PR."


def test_fixed_text_language_cannot_be_set_from_a_pr_comment():
    from pr_agent.algo.cli_args import CliArgs

    is_valid, _ = CliArgs.validate_user_args(["--config.fixed_text_language=en"])

    assert is_valid is False

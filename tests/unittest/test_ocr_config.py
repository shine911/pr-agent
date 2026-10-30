import subprocess

import pytest
from dynaconf.utils.boxing import DynaBox

from pr_agent.algo.ocr_config import (
    DEFAULT_OCR_LLM_URL,
    OcrConfigError,
    build_ocr_rules,
    render_ocr_env,
    resolve_ocr_language,
    resolve_ocr_model,
    resolve_ocr_url,
    validate_fail_on_severity,
)


@pytest.mark.parametrize("model,expected", [
    ("gpt-6-luna", "gpt-6-luna"), ("openai/gpt-6-luna", "gpt-6-luna"), (" gpt-6-luna ", "gpt-6-luna")])
def test_resolve_ocr_model_accepts_openai(model, expected):
    assert resolve_ocr_model(model) == expected


@pytest.mark.parametrize("model", ["gemini/gemini-3.5-flash-lite", "deepseek/deepseek-chat", "azure/gpt-4o", "", None])
def test_resolve_ocr_model_rejects_non_openai(model):
    with pytest.raises(OcrConfigError):
        resolve_ocr_model(model)


def test_resolve_ocr_url():
    assert resolve_ocr_url(None) == DEFAULT_OCR_LLM_URL == "https://api.openai.com/v1"
    assert resolve_ocr_url("  ") == "https://api.openai.com/v1"
    assert resolve_ocr_url("https://proxy.example/v1/") == "https://proxy.example/v1"


@pytest.mark.parametrize("language,response_language,expected", [
    ("", "vi-VN", "Vietnamese"), (None, "en-US", "English"), ("", "zh-CN", "Chinese"),
    ("Japanese", "vi-VN", "Japanese"), ("", "xx-YY", "English"), ("", None, "English")])
def test_resolve_ocr_language(language, response_language, expected):
    assert resolve_ocr_language(language, response_language) == expected


def test_validate_fail_on_severity():
    assert validate_fail_on_severity("") == ""
    assert validate_fail_on_severity(" Critical ") == "critical"
    with pytest.raises(OcrConfigError):
        validate_fail_on_severity("blocker")


def test_build_ocr_rules_none_when_empty():
    assert build_ocr_rules("", []) is None
    assert build_ocr_rules(None, None) is None


def test_build_ocr_rules_global_only():
    assert build_ocr_rules("- No sync fs.", []) == {
        "rules": [{"path": "**/*", "rule": "- No sync fs.", "merge_system_rule": True}]}


def test_build_ocr_rules_path_rules_get_global_appended_and_keep_order():
    rules = [DynaBox({"path": "**/*.test.js", "rule": "- Neutral names."}),
             {"path": "app/components/**", "rule": "- Use Polaris."}]
    assert build_ocr_rules("- No sync fs.", rules) == {"rules": [
        {"path": "**/*.test.js", "rule": "- Neutral names.\n\n- No sync fs.", "merge_system_rule": True},
        {"path": "app/components/**", "rule": "- Use Polaris.\n\n- No sync fs.", "merge_system_rule": True},
        {"path": "**/*", "rule": "- No sync fs.", "merge_system_rule": True}]}


def test_build_ocr_rules_path_rules_without_global():
    assert build_ocr_rules("", [{"path": "a/**", "rule": "r"}]) == {
        "rules": [{"path": "a/**", "rule": "r", "merge_system_rule": True}]}


@pytest.mark.parametrize("rules", ["not-a-list", [{"path": "a/**"}], [{"rule": "r"}], [{"path": " ", "rule": "r"}],
                                   ["string-item"]])
def test_build_ocr_rules_rejects_malformed(rules):
    with pytest.raises(OcrConfigError):
        build_ocr_rules("", rules)


def test_render_ocr_env_round_trips_through_bash():
    tricky = "it's \"quoted\" $HOME `id` \n line2"
    env_text = render_ocr_env({"OCR_LANGUAGE": tricky, "OCR_RULE_FILE": ""})
    out = subprocess.run(["bash", "-c", 'source /dev/stdin; printf "%s|%s" "$OCR_LANGUAGE" "$OCR_RULE_FILE"'],
                         input=env_text, capture_output=True, text=True, check=True).stdout
    assert out == tricky + "|"

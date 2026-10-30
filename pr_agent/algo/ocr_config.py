import re
import shlex
from collections.abc import Mapping
from contextvars import ContextVar

from pr_agent.log import get_logger

OCR_OUTPUT_DIR = ".ocr"
OCR_ENV_FILENAME = "ocr.env"
OCR_RULE_FILENAME = "rule.json"
DEFAULT_OCR_LLM_URL = "https://api.openai.com/v1"

# Set by the CLI entrypoint so the tool can tell a local `ocr_config` run from a webhook-triggered one.
ocr_config_cli_invocation: ContextVar[bool] = ContextVar("ocr_config_cli_invocation", default=False)

_LANGUAGE_NAMES = {
    "vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "fr": "French",
    "de": "German", "es": "Spanish", "pt": "Portuguese", "ru": "Russian", "it": "Italian"}
_DEFAULT_LANGUAGE = "English"
_SEVERITIES = ("critical", "high", "medium", "low")
DEFAULT_OCR_LLM_PROTOCOL = "openai-responses"
_OCR_PROTOCOLS = ("openai-responses", "openai", "anthropic")
_ENV_KEY_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


class OcrConfigError(ValueError):
    """Raised when pr-agent settings cannot be mapped to a valid OCR configuration."""


def resolve_ocr_model(model: str | None) -> str:
    value = (model or "").strip()
    value = value.removeprefix("openai/")
    if not value or "/" in value:
        raise OcrConfigError(
            f"Model {model!r} cannot be used for OCR: only OpenAI models are supported here "
            "(e.g. 'gpt-6-luna' or 'openai/gpt-6-luna').")
    return value


def resolve_ocr_url(api_base: str | None) -> str:
    value = (api_base or "").strip()
    return value.rstrip("/") if value else DEFAULT_OCR_LLM_URL


def resolve_ocr_protocol(value: str | None) -> str:
    protocol = (value or "").strip().lower() or DEFAULT_OCR_LLM_PROTOCOL
    if protocol not in _OCR_PROTOCOLS:
        raise OcrConfigError(
            f"llm_protocol {value!r} is not supported by OCR: use one of {', '.join(_OCR_PROTOCOLS)}.")
    return protocol


def resolve_ocr_language(language: str | None, response_language: str | None) -> str:
    explicit = (language or "").strip()
    if explicit:
        return explicit
    code = re.split(r"[-_]", (response_language or "").strip(), maxsplit=1)[0].lower()
    name = _LANGUAGE_NAMES.get(code)
    if name:
        return name
    get_logger().warning(
        f"No OCR language mapping for response_language {response_language!r}; defaulting to {_DEFAULT_LANGUAGE}")
    return _DEFAULT_LANGUAGE


def validate_fail_on_severity(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized and normalized not in _SEVERITIES:
        raise OcrConfigError(f"Invalid fail_on_severity {value!r}; expected one of {', '.join(_SEVERITIES)} or empty.")
    return normalized


def build_ocr_rules(extra_instructions: str | None, rules: object) -> dict | None:
    if rules is None:
        rules = []
    if not isinstance(rules, (list, tuple)):
        raise OcrConfigError("ocr_review rules must be a list of {path, rule} tables.")
    global_rule = (extra_instructions or "").strip()
    entries = []
    for item in rules:
        if not isinstance(item, Mapping):
            raise OcrConfigError(f"Each OCR rule must be a table with 'path' and 'rule', got {item!r}.")
        path, rule = item.get("path"), item.get("rule")
        if not isinstance(path, str) or not path.strip() or not isinstance(rule, str) or not rule.strip():
            raise OcrConfigError(f"Each OCR rule needs non-empty string 'path' and 'rule', got {dict(item)!r}.")
        text = f"{rule.strip()}\n\n{global_rule}" if global_rule else rule.strip()
        entries.append({"path": path.strip(), "rule": text, "merge_system_rule": True})
    if global_rule:
        entries.append({"path": "**/*", "rule": global_rule, "merge_system_rule": True})
    return {"rules": entries} if entries else None


def render_ocr_env(values: Mapping[str, str]) -> str:
    lines = []
    for key, value in values.items():
        if not _ENV_KEY_RE.fullmatch(key):
            raise OcrConfigError(f"Invalid environment variable name {key!r}.")
        lines.append(f"export {key}={shlex.quote(str(value))}")
    return "\n".join(lines) + "\n"

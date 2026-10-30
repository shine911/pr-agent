import json
from pathlib import Path

from pr_agent.algo.ocr_config import (
    OCR_ENV_FILENAME,
    OCR_OUTPUT_DIR,
    OCR_RULE_FILENAME,
    OcrConfigError,
    build_ocr_rules,
    ocr_config_cli_invocation,
    render_ocr_env,
    resolve_ocr_language,
    resolve_ocr_model,
    resolve_ocr_url,
    validate_fail_on_severity,
)
from pr_agent.algo.run_details import record_command_failure
from pr_agent.config_loader import get_settings
from pr_agent.log import get_logger


class PROcrConfig:
    """
    The PROcrConfig class translates pr-agent settings into the environment file and rule file used by the OCR CLI.
    It never calls an LLM, never publishes to the merge request, and only runs from the pr-agent CLI entrypoint.
    """
    def __init__(self, pr_url: str, args: list | None = None, ai_handler=None):
        """
        Initialize the PROcrConfig object.

        Args:
            pr_url (str): The URL of the pull request being reviewed. Unused: no git provider is needed.
            args (list, optional): Unused compatibility parameter for the common tool interface. Defaults to None.
            ai_handler: Unused compatibility parameter for the common tool interface. Defaults to None.
        """
        self.pr_url = pr_url

    async def run(self) -> bool:
        if not ocr_config_cli_invocation.get():
            get_logger().warning("ocr_config only runs from the pr-agent CLI entrypoint; ignoring this request")
            return False
        try:
            settings = get_settings()
            rules = build_ocr_rules(
                settings.ocr_review.get("extra_instructions", ""), settings.ocr_review.get("rules", []))
            env_values = {
                "OCR_LLM_URL": resolve_ocr_url(settings.get("openai.api_base", None)),
                "OCR_LLM_MODEL": resolve_ocr_model(settings.get("config.model", None)),
                "OCR_LLM_PROTOCOL": (settings.ocr_review.get("llm_protocol", "") or "").strip(),
                "OCR_LANGUAGE": resolve_ocr_language(
                    settings.ocr_review.get("language", ""), settings.get("config.response_language", "")),
                "OCR_FAIL_ON_SEVERITY": validate_fail_on_severity(
                    settings.ocr_review.get("fail_on_severity", "")),
            }
            output_dir = Path(OCR_OUTPUT_DIR)
            rule_path = output_dir / OCR_RULE_FILENAME
            env_values["OCR_RULE_FILE"] = str(rule_path.resolve()) if rules else ""
            env_content = render_ocr_env(env_values)
        except OcrConfigError as e:
            get_logger().error(f"Cannot generate OCR configuration: {e}")
            record_command_failure()
            return False

        output_dir.mkdir(parents=True, exist_ok=True)
        if rules:
            with open(rule_path, "w", encoding="utf-8") as f:
                json.dump(rules, f, indent=2, ensure_ascii=False)
            get_logger().info(f"Wrote OCR rules to {rule_path}")
        env_path = output_dir / OCR_ENV_FILENAME
        env_path.write_text(env_content, encoding="utf-8")
        get_logger().info(f"Wrote OCR environment to {env_path}")
        return True

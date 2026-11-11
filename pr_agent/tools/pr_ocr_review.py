import json
import os
import re
import subprocess
import sys
from pathlib import Path

from pr_agent.algo.ocr_config import (
    OCR_OUTPUT_DIR,
    OCR_RESULT_FILENAME,
    ocr_config_cli_invocation,
)
from pr_agent.algo.run_details import record_command_failure
from pr_agent.config_loader import get_settings
from pr_agent.git_providers import get_git_provider_with_context
from pr_agent.log import get_logger
from pr_agent.tools.pr_ocr_config import generate_ocr_files

OCR_STDERR_FILENAME = "ocr-stderr.log"
POST_REVIEW_SCRIPT = Path(__file__).resolve().parents[2] / "third_party" / "open_code_review" / "post_review.py"
_MR_IID_RE = re.compile(r"/merge_requests/(\d+)")
_REQUIRED_ENV = ("OCR_LLM_AUTH_TOKEN", "GITLAB_API_TOKEN")


class PROcrReview:
    """
    The PROcrReview class runs the whole OCR review of a GitLab merge request in one command:
    write the OCR configuration, run the `ocr` CLI on the merge request diff, publish its result with
    `post_review.py`, then update the merge request approval when `config.enable_auto_approval` is on: approve it
    when OCR found nothing, remove the bot's earlier approval when it found something.
    It shells out to `ocr`, so it only runs from the pr-agent CLI entrypoint, in the checked-out repository.
    """
    def __init__(self, pr_url: str, args: list | None = None, ai_handler=None):
        """
        Initialize the PROcrReview object.

        Args:
            pr_url (str): The URL of the merge request to review.
            args (list, optional): Unused compatibility parameter for the common tool interface. Defaults to None.
            ai_handler: Unused compatibility parameter for the common tool interface. Defaults to None.
        """
        self.pr_url = pr_url

    async def run(self) -> bool:
        if not ocr_config_cli_invocation.get():
            get_logger().warning("ocr_review only runs from the pr-agent CLI entrypoint; ignoring this request")
            return False
        missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            get_logger().error(f"Missing required environment variable(s): {', '.join(missing)}")
            record_command_failure()
            return False

        ocr_env = generate_ocr_files()
        if ocr_env is None:
            return False
        if not self._configure_ocr(ocr_env):
            return False

        mr_env = self._resolve_merge_request()
        if mr_env is None:
            return False
        output_dir = Path(OCR_OUTPUT_DIR)
        result_path = output_dir / OCR_RESULT_FILENAME
        stderr_path = output_dir / OCR_STDERR_FILENAME

        # Prefer the MR's own diff base so post_review.py matches the MR version OCR reviewed.
        diff_base = mr_env["base_sha"] or f"origin/{mr_env['target_branch']}"
        commit_sha = os.environ.get("CI_COMMIT_SHA") or self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        self._run(["git", "fetch", "origin", mr_env["target_branch"], "--quiet"])
        review_cmd = ["ocr", "review", "--from", diff_base, "--to", commit_sha, "--format", "json",
                      "--audience", "agent"]
        if ocr_env["OCR_RULE_FILE"]:
            review_cmd += ["--rule", ocr_env["OCR_RULE_FILE"]]
        get_logger().info(f"Reviewing {commit_sha} against {mr_env['target_branch']}")
        with open(result_path, "w", encoding="utf-8") as out, open(stderr_path, "w", encoding="utf-8") as err:
            review = subprocess.run(review_cmd, stdout=out, stderr=err, text=True)
        stderr = stderr_path.read_text(encoding="utf-8")
        if review.returncode and stderr:
            print(stderr, file=sys.stderr)
        print(result_path.read_text(encoding="utf-8"))

        # Publish even when OCR failed, so its stderr reaches the merge request.
        post = subprocess.run(
            [sys.executable, str(POST_REVIEW_SCRIPT), str(result_path)],
            env={**os.environ, **ocr_env, "CI_MERGE_REQUEST_IID": mr_env["iid"]})
        if review.returncode:
            get_logger().error(f"ocr review exited with code {review.returncode}; see the MR summary for stderr")
            record_command_failure()
            return False
        if post.returncode:
            get_logger().error(f"post_review.py exited with code {post.returncode}")
            record_command_failure()
            return False

        # Best effort: a failed approval does not fail the review job.
        self._update_approval(result_path)
        return True

    def _update_approval(self, result_path: Path) -> None:
        if not get_settings().config.get("enable_auto_approval", False):
            get_logger().info("config.enable_auto_approval is off; leaving the merge request approval unchanged")
            return
        try:
            comments = json.loads(result_path.read_text(encoding="utf-8"))["comments"]
            if not isinstance(comments, list):
                raise TypeError("'comments' is not a list")
        except (OSError, ValueError, KeyError, TypeError) as e:
            # An unreadable result is not evidence the code is clean: change nothing.
            get_logger().warning(f"Cannot read the OCR result {result_path}: {e}; not changing the approval")
            return
        git_provider = get_git_provider_with_context(self.pr_url)
        if not comments:
            if git_provider.auto_approve():
                get_logger().info("Auto-approved the merge request: OCR found no issues")
            return
        get_logger().info(f"OCR reported {len(comments)} comment(s); removing any earlier bot approval")
        git_provider.auto_unapprove()

    def _configure_ocr(self, ocr_env: dict) -> bool:
        settings = [("llm.url", ocr_env["OCR_LLM_URL"]),
                    ("llm.auth_token", os.environ["OCR_LLM_AUTH_TOKEN"]),
                    ("llm.model", ocr_env["OCR_LLM_MODEL"]),
                    ("llm.protocol", ocr_env["OCR_LLM_PROTOCOL"])]
        if ocr_env["OCR_LANGUAGE"]:
            settings.append(("language", ocr_env["OCR_LANGUAGE"]))
        if os.environ.get("OCR_LLM_EXTRA_BODY"):
            settings.append(("llm.extra_body", os.environ["OCR_LLM_EXTRA_BODY"]))
        for key, value in settings:
            if self._run(["ocr", "config", "set", key, value], capture=False).returncode:
                get_logger().error(f"`ocr config set {key}` failed")
                record_command_failure()
                return False
        # Fail fast with the provider's real error instead of a generic "all file reviews failed" later.
        if self._run(["ocr", "llm", "test"], capture=False).returncode:
            get_logger().error("`ocr llm test` failed")
            record_command_failure()
            return False
        return True

    def _resolve_merge_request(self) -> dict | None:
        """Merge-request pipelines carry CI_MERGE_REQUEST_*; API-triggered ones are resolved from the MR itself."""
        url_match = _MR_IID_RE.search(self.pr_url)
        iid = os.environ.get("CI_MERGE_REQUEST_IID") or (url_match.group(1) if url_match else "")
        target_branch = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "")
        base_sha = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA", "")
        if not target_branch:
            try:
                mr = get_git_provider_with_context(self.pr_url).mr
                target_branch = mr.target_branch
                # diff_refs can be null while GitLab is still computing the MR diff
                base_sha = (getattr(mr, "diff_refs", None) or {}).get("base_sha") or ""
            except Exception as e:
                get_logger().error(f"Cannot resolve the target branch of {self.pr_url}: {e}")
                record_command_failure()
                return None
        if not iid or not target_branch:
            get_logger().error(f"Cannot resolve the merge request IID or target branch of {self.pr_url}")
            record_command_failure()
            return None
        return {"iid": iid, "target_branch": target_branch, "base_sha": base_sha}

    @staticmethod
    def _run(cmd: list, capture: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, capture_output=capture)

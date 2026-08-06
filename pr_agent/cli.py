import argparse
import asyncio
import os
import sys

from pr_agent.agent.pr_agent import PRAgent, commands
from pr_agent.algo.ai_handlers.litellm_helpers import (
    DEFAULT_CALLBACK_TIMEOUT_SECONDS, drain_litellm_callbacks,
    litellm_callbacks_registered)
from pr_agent.algo.utils import get_version
from pr_agent.config_loader import get_settings
from pr_agent.log import get_logger, setup_logger

log_level = os.environ.get("LOG_LEVEL", "INFO")
setup_logger(log_level)


def set_parser():
    parser = argparse.ArgumentParser(description='Công cụ phân tích pull request dùng AI', usage=
    """\
    Cách dùng: cli.py --pr_url=<URL trên dịch vụ git được hỗ trợ> <command> [<args>].
    Ví dụ:
    - cli.py --pr_url=... review
    - cli.py --pr_url=... describe
    - cli.py --pr_url=... improve
    - cli.py --pr_url=... ask "write me a poem about this PR"
    - cli.py --pr_url=... reflect
    - cli.py --issue_url=... similar_issue
    - cli.py --pr_url/--issue_url= help_docs [<asked question>]

    Các lệnh được hỗ trợ:
    - review / review_pr - Thêm một đánh giá bao gồm tóm tắt PR và các đề xuất cải tiến cụ thể.

    - ask / ask_question [question] - Đặt câu hỏi về PR.

    - describe / describe_pr - Sửa tiêu đề và mô tả PR dựa trên nội dung của PR.

    - improve / improve_code - Đề xuất cải tiến code trong PR dưới dạng bình luận pull request sẵn sàng để commit.
    Chế độ mở rộng ('improve --extended') dùng nhiều lệnh gọi, và cung cấp phản hồi kỹ hơn

    - reflect - Đặt câu hỏi cho tác giả PR về PR.

    - update_changelog - Cập nhật changelog dựa trên nội dung của PR.

    - add_docs

    - generate_labels

    - help_docs - Đặt câu hỏi, từ ngữ cảnh issue hoặc PR, trên một repo cho trước (ngữ cảnh hiện tại hoặc một repo khác)


    Cấu hình:
    Để sửa bất kỳ tham số cấu hình nào từ 'configuration.toml', chỉ cần thêm -config_path=<value>.
    Ví dụ: 'python cli.py --pr_url=... review --pr_reviewer.extra_instructions="focus on the file: ..."'
    """)
    parser.add_argument('--version', action='version', version=f'pr-agent {get_version()}')
    parser.add_argument('--pr_url', type=str, help='URL của PR cần đánh giá', default=None)
    parser.add_argument('--issue_url', type=str, help='URL của Issue cần đánh giá', default=None)
    parser.add_argument('--config-branch', type=str, help='Branch git để tải .pr_agent.toml từ đó', default=None)
    parser.add_argument(
        "--extra_config_url",
        type=str,
        default=os.environ.get("PR_AGENT_EXTRA_CONFIG_URL"),
        help=(
            "URL hoặc đường dẫn cục bộ của một .pr_agent.toml bổ sung để gộp trước "
            "config cục bộ của repo (ví dụ: mặc định chung/tổ chức). Hỗ trợ URL http(s):// hoặc "
            "đường dẫn hệ thống file. Với các endpoint riêng tư, đặt PR_AGENT_EXTRA_CONFIG_AUTH_HEADER "
            "(ví dụ: 'PRIVATE-TOKEN: <token>' hoặc 'JOB-TOKEN: $CI_JOB_TOKEN'). "
            "File .pr_agent.toml cục bộ của repo sẽ ghi đè giá trị đặt ở đây."
        ),
    )
    parser.add_argument("--diff-file", dest="diff_file", type=str, default=None,
                        help="Đường dẫn tới một file unified diff để đánh giá (chế độ plain-diff cục bộ)")
    parser.add_argument("--stdin", action="store_true", default=False,
                        help="Đọc unified diff từ stdin (chế độ plain-diff cục bộ)")
    parser.add_argument("--output", dest="output", type=str, default=None,
                        help="Ghi kết quả vào file này (cùng với stdout)")
    parser.add_argument('command', type=str, help='Lệnh', choices=commands, default='review')
    parser.add_argument('rest', nargs=argparse.REMAINDER, default=[])
    return parser


def run_command(pr_url, command):
    # Preparing the command
    run_command_str = f"--pr_url={pr_url} {command.lstrip('/')}"
    args = set_parser().parse_args(run_command_str.split())

    # Run the command. Feedback will appear in GitHub PR comments
    run(args=args)


def run(inargs=None, args=None):
    parser = set_parser()
    if not args:
        args = parser.parse_args(inargs)
    diff_mode = getattr(args, "stdin", False) or getattr(args, "diff_file", None)
    if diff_mode:
        if args.stdin and args.diff_file:
            parser.error("--stdin và --diff-file loại trừ lẫn nhau")
        if args.diff_file:
            try:
                with open(args.diff_file, "r", encoding="utf-8") as fh:
                    diff_content = fh.read()
            except OSError as e:
                parser.error(f"Không thể đọc --diff-file '{args.diff_file}': {e}")
            except UnicodeDecodeError as e:
                parser.error(f"--diff-file '{args.diff_file}' không phải là văn bản UTF-8 hợp lệ: {e}")
        else:
            diff_content = sys.stdin.read()
        if not diff_content.strip():
            parser.error("Không nhận được nội dung diff (stdin/file trống)")
        get_settings().set("config.git_provider", "plain-diff")
        get_settings().set("plain_diff.content", diff_content)
        get_settings().set("plain_diff.output_path", getattr(args, "output", None))
        # Plain-diff mode's whole purpose is to emit the result to stdout/--output, so
        # force publishing on even if a config/env set publish_output=false.
        get_settings().set("config.publish_output", True)
    elif not args.pr_url and not args.issue_url:
        parser.print_help()
        return

    command = args.command.lower()
    get_settings().set("CONFIG.CLI_MODE", True)
    # Strip each candidate independently so a whitespace-only CLI value doesn't
    # short-circuit the PR_AGENT_CONFIG_BRANCH env fallback before precedence.
    cli_branch = (getattr(args, "config_branch", None) or "").strip()
    env_branch = (os.environ.get("PR_AGENT_CONFIG_BRANCH") or "").strip()
    # Always reconcile CONFIG.CONFIG_BRANCH with the current invocation so a value
    # set by an earlier run() call in the same process can't leak into a later one
    # (get_settings() is a process-wide singleton).
    get_settings().set("CONFIG.CONFIG_BRANCH", cli_branch or env_branch or None)
    # Always reconcile CONFIG.EXTRA_CONFIG_URL with the current invocation so a
    # previously-set value from an earlier run() call in the same process can't
    # leak into a later one (get_settings() is a process-wide singleton).
    get_settings().set("CONFIG.EXTRA_CONFIG_URL", getattr(args, "extra_config_url", None))

    async def inner():
        # Default to propagating tool-internal errors so a failed run is
        # distinguishable from an empty one and can surface as a non-zero
        # exit code below; placed before args.rest so an explicit
        # --config.propagate_tool_errors= from the caller still wins.
        request = [command, "--config.propagate_tool_errors=true"] + args.rest
        if args.issue_url:
            result = await asyncio.create_task(PRAgent().handle_request(args.issue_url, request))
        else:
            target = args.pr_url if args.pr_url else "local_diff"
            result = await asyncio.create_task(PRAgent().handle_request(target, request))

        # litellm defers its success/failure callbacks onto the event loop, which
        # asyncio.run() below tears down the moment this coroutine returns. Give
        # them a chance to run first, or they are silently dropped.
        if litellm_callbacks_registered():
            get_logger().debug("Waiting for event queue to complete")
            await drain_litellm_callbacks(
                get_settings().litellm.get("callback_timeout_seconds", DEFAULT_CALLBACK_TIMEOUT_SECONDS)
            )

        return result

    result = asyncio.run(inner())
    if not result:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    run()

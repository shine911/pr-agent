# Fork feature registry

Single source of truth for what this fork (`shine911/pr-agent`) adds on top of `The-PR-Agent/pr-agent`, and what it
deliberately removes. Each entry names its anchor files (as of the last sync) and the tests that guard it. The
`sync-upstream` skill reads this before resolving and updates it after every sync: new fork features get an entry,
paths follow upstream renames, and entries upstream now ships natively are moved to "Absorbed by upstream".

## Features

| # | Feature | Anchor files | Guarding tests |
|---|---------|--------------|----------------|
| 1 | GitLab repo settings from the wiki (`.pr_agent.toml` TOML extracted from a markdown wiki page), always loaded, wiki beats env vars | `git_providers/gitlab_provider.py`, `git_providers/utils.py`, `docs/docs/usage-guide/configuration_options.md` | `test_gitlab_wiki_settings.py`, `test_extra_config_url.py`, `test_git_provider_utils.py`, `test_gitlab_provider_repo_settings.py` |
| 2 | GitLab MR conversation history fed into review/improve prompts (unlimited comments by default) | `gitlab_provider.py`, `pr_reviewer_prompts.toml`, `pr_code_suggestions_prompts*.toml`, `configuration.toml` | `test_gitlab_history_context.py` |
| 3 | Repository metadata (`get_repo_metadata`) passed to describe/review/improve/labels/changelog/add_docs prompts | `algo/utils.py`, `git_provider.py`, `gitlab_provider.py`, the six command modules | `test_gitlab_project_reads.py`, the command tests that build `vars` |
| 4 | Auto-approve the MR when `/improve` finds no suggestions, unapprove on new ones; approval 404s are benign | `commands/pr_code_suggestions.py`, `gitlab_provider.py`, `git_provider.py`, `config.enable_auto_approval` | `test_gitlab_provider.py`, `test_pr_code_suggestions_lifecycle.py` |
| 5 | `/improve` reflect step receives skills and repo context; `is_successful` initialised before publish | `pr_code_suggestions_reflect_prompts.toml`, `commands/pr_code_suggestions.py` | `test_pr_code_suggestions_reflection_context.py`, `test_pr_code_suggestions_core.py` |
| 6 | Vietnamese user-facing strings (comments, help, progress, CLI messages); the `/describe` "PR Type" section heading stays English | `algo/utils.py`, `servers/help.py`, `cli.py`, `commands/*.py`, `git_providers/*.py` | `test_convert_to_markdown.py`, `test_markdown_ticket_output_core.py`, `test_pr_help_message_*.py`, `test_pr_description*.py`, `tests/health_test/test_github_smoke.py` |
| 7 | Model name logged on every LLM call; per-command token cost in run details | `ai_handlers/litellm_ai_handler.py`, `algo/model_cost.py`, `algo/run_details.py`, `agent/pr_agent.py`, `configuration.toml` | `test_model_cost.py`, `test_run_details.py` |
| 8 | Ollama Cloud API key support | `ai_handlers/litellm_ai_handler.py`, `settings/.secrets_template.toml` | none (probe: `grep -n ollama litellm_ai_handler.py`) |
| 9 | CLI exits non-zero when a command fails | `cli.py` | `test_cli_exit_status.py`, `test_cli_plain_diff_mode.py` |
| 10 | GitLab `/codeowners` check of CODEOWNERS approvals (author approvals count) | `algo/codeowners.py`, `commands/pr_codeowners.py`, `agent/pr_agent.py`, `docs/docs/usage-guide/codeowners.md` | `test_codeowners_parser.py`, `test_pr_codeowners.py` |
| 11 | CLI-only `ocr_config` and one-command `ocr_review` (open-code-review on GitLab MRs), `[ocr_review]` settings | `algo/ocr_config.py`, `commands/pr_ocr_config.py`, `commands/pr_ocr_review.py`, `agent/pr_agent.py`, `cli.py`, `configuration.toml`, OCR docs page | `test_ocr_config.py`, `test_pr_ocr_config.py`, `test_pr_ocr_review.py`, `test_cli_plain_diff_mode.py` |
| 12 | Bundled OCR CLI pinned by version and per-arch SHA-256, vendored `post_review.py` | `docker/Dockerfile` (OCR block), `third_party/open_code_review/` | none; owned by the `upgrade-ocr` skill |
| 13 | Docker image release to GHCR on GitHub release | `.github/workflows/docker-release.yml` | none |

Paths under `pr_agent/` are given relative to it.

## Intentional divergences

Keep these on every sync; a modify/delete conflict on one of them resolves to the fork's side.

- Deleted `.github/workflows/publish.yml` and `tests/unittest/test_publish_workflow_security.py`: the fork does not
  publish to PyPI. Nothing else may reference `publish.yml` (the Docker `test` stage once copied it).
- Deleted `.github/workflows/pr-agent-review.yaml`: forks lack the `QODO_SPONSORSHIP_LLM_KEY` secret, so it always
  fails.
- GitHub Actions and Docker base-image pins: the fork's Dependabot bumps them independently; on conflict take the
  newer pin.

## Absorbed by upstream

Fork changes upstream now ships natively; nothing to preserve.

- (none yet)

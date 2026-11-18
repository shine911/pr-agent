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
| 4 | Unpinned GitLab approve/unapprove used by `ocr_review` (and the dormant `/improve` path): `auto_approve_unpinned()` / `auto_unapprove()`, approval 404s are benign. Named apart from upstream's pinned `auto_approve(body)` / `revoke_auto_approval(reason)`, which `/review` uses; a same-named fork method would shadow upstream's | `gitlab_provider.py`, `git_provider.py`, `commands/pr_ocr_review.py`, `commands/pr_code_suggestions.py`, `config.enable_auto_approval` | `test_gitlab_provider.py`, `test_pr_ocr_review.py`, `test_pr_code_suggestions_lifecycle.py` |
| 5 | `/improve` reflect step receives skills and repo context; `is_successful` initialised before publish. **Dormant** since upstream routes `/improve` to `/review` (dev decision 2026-11-18: follow upstream); kept merged and tested | `pr_code_suggestions_reflect_prompts.toml`, `commands/pr_code_suggestions.py` | `test_pr_code_suggestions_reflection_context.py`, `test_pr_code_suggestions_core.py` |
| 6 | Vietnamese user-facing strings. Two mechanisms: (a) upstream's i18n catalog `settings/i18n/vi.toml` through `t()`, selected by the fork key `config.fixed_text_language = "vi"` (model language stays `response_language`; dev decision 2026-11-18); (b) strings upstream still hardcodes, translated in place. The `/describe` "PR Type" heading stays English. Tests run with `fixed_text_language = ""` (conftest), so `t()` text asserts English and hardcoded text asserts Vietnamese | `algo/i18n.py`, `settings/configuration.toml`, `tests/unittest/conftest.py`, `algo/utils.py`, `servers/help.py`, `cli.py`, `commands/*.py`, `git_providers/*.py` | `test_i18n_fixed_text_language.py`, `test_convert_to_markdown.py`, `test_markdown_ticket_output_core.py`, `test_pr_help_message_*.py`, `test_pr_description*.py`, `tests/health_test/test_github_smoke.py` |
| 7 | Model name logged on every LLM call; per-command token cost logged (`log_run_summary`, `[model_cost]` rates; separate from upstream's `output_run_cost`) | `ai_handlers/litellm_ai_handler.py`, `algo/model_cost.py`, `algo/run_details.py`, `agent/pr_agent.py`, `configuration.toml`, `docs/docs/usage-guide/additional_configurations.md` | `test_model_cost.py`, `test_run_details.py` |
| 8 | Ollama Cloud API key support | `ai_handlers/litellm_ai_handler.py`, `settings/.secrets_template.toml` | none (probe: `grep -n ollama litellm_ai_handler.py`) |
| 9 | CLI exits non-zero when a command fails | `cli.py` | `test_cli_exit_status.py`, `test_cli_plain_diff_mode.py` |
| 10 | GitLab `/codeowners` check of CODEOWNERS approvals (author approvals count); `enable_codeowners_check` cannot be set from a PR comment | `algo/codeowners.py`, `commands/pr_codeowners.py`, `agent/command_registry.py`, `config_security.py`, `docs/docs/usage-guide/codeowners.md` | `test_codeowners_parser.py`, `test_pr_codeowners.py` |
| 11 | CLI-only `ocr_config` and one-command `ocr_review` (open-code-review on GitLab MRs), `[ocr_review]` settings; `[ocr_review]` extra_instructions are not given the response-language suffix | `algo/ocr_config.py`, `commands/pr_ocr_config.py`, `commands/pr_ocr_review.py`, `agent/command_registry.py`, `agent/pr_agent.py`, `cli.py`, `configuration.toml`, `docs/docs/commands/ocr_config.md` | `test_ocr_config.py`, `test_pr_ocr_config.py`, `test_pr_ocr_review.py`, `test_cli_plain_diff_mode.py` |
| 12 | Bundled OCR CLI pinned by version and per-arch SHA-256, vendored `post_review.py` | `docker/Dockerfile` (OCR block), `third_party/open_code_review/` | none; owned by the `upgrade-ocr` skill |
| 13 | Docker image release to GHCR on GitHub release | `.github/workflows/docker-release.yml` | none |

Paths under `pr_agent/` are given relative to it.

## Intentional divergences

Keep these on every sync; a modify/delete conflict on one of them resolves to the fork's side.

- Deleted `.github/workflows/publish.yml` and `tests/unittest/test_publish_workflow_security.py`: the fork does not
  publish to PyPI. Nothing else may reference `publish.yml` (the Docker `test` stage once copied it).
- Deleted `.github/workflows/pr-agent-review.yaml` and its test `tests/unittest/test_review_context_workflow.py`: forks
  lack the `QODO_SPONSORSHIP_LLM_KEY` secret, so it always fails. The Docker `test` stage must not `COPY` it.
- GitHub Actions and Docker base-image pins: the fork's Dependabot bumps them independently; on conflict take the
  newer pin.
- New config keys the fork adds get a docs link in `SECTION_DOCS` (`scripts/generate_config_reference.py`), a
  description of at most 160 characters, and a classification for PR-comment overrides: host-only in
  `pr_agent/config_security.py` or listed in `tests/unittest/test_config_comment_overrides.py`.

## Absorbed by upstream

Fork changes upstream now ships natively; nothing to preserve.

- (none yet)

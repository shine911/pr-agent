---
title: "OCR config"
sidebar_position: 12
---

## Overview

The `ocr_config` command prepares the configuration for open-code-review (OCR), a CLI reviewer that can run as a second step after the regular PR-Agent job in a GitLab pipeline.
It translates PR-Agent settings (model, API base, response language and the `[ocr_review]` section) into files that the `ocr` CLI reads, so that both tools share one configuration.

What it does:

- Runs **only from the PR-Agent CLI** (`python -m pr_agent.cli --pr_url=... ocr_config`). Webhook-triggered requests are ignored.
- Writes `.ocr/ocr.env` (shell `export` lines) and, when rules are configured, `.ocr/rule.json`, relative to the current directory.

What it does not do:

- It makes no LLM call and needs no API key.
- It publishes no comments and does not touch the merge request.

The PR-Agent container image ships the `ocr` binary and the script `/app/third_party/open_code_review/post_review.py`, which publishes the OCR result to the merge request.

## Configuration

The `[ocr_review]` section can be set in `.pr_agent.toml` or in the global configuration. See the [configuration reference](../usage-guide/configuration_reference.md) for all defaults.

| Key | Description |
|-----|-------------|
| `extra_instructions` | Review rules applied to every file. Default: empty. |
| `rules` | Optional path-scoped rules, in priority order. Each entry has a `path` glob and a `rule` text. Default: none. |
| `language` | OCR review language name, for example `"Vietnamese"`. Empty derives it from `config.response_language` (falls back to English). |
| `llm_protocol` | OCR LLM protocol: `"openai-responses"` (default), `"openai"` or `"anthropic"`. |
| `fail_on_severity` | Fail the OCR job when a finding is at or above this severity: `critical`, `high`, `medium` or `low`. Empty never fails. |

Example:

```toml
[ocr_review]
extra_instructions = "Flag any hard-coded credential or token."
language = "Vietnamese"
fail_on_severity = "high"

[[ocr_review.rules]]
path = "src/api/**"
rule = "Every endpoint must validate its input and check authorization."

[[ocr_review.rules]]
path = "**/*.sql"
rule = "Migrations must be reversible and must not lock large tables."
```

## Generated files

`ocr.env` defines the following variables, shell-quoted so it can be loaded with `. .ocr/ocr.env`:

| Variable | Source |
|----------|--------|
| `OCR_LLM_URL` | `openai.api_base`, or `https://api.openai.com/v1` when unset |
| `OCR_LLM_MODEL` | `config.model` without the `openai/` prefix |
| `OCR_LLM_PROTOCOL` | `ocr_review.llm_protocol` |
| `OCR_LANGUAGE` | `ocr_review.language`, or derived from `config.response_language` |
| `OCR_FAIL_ON_SEVERITY` | `ocr_review.fail_on_severity` |
| `OCR_RULE_FILE` | absolute path of `.ocr/rule.json`, empty when no rules are configured |

:::note
Only OpenAI models are supported. A model name with a provider prefix other than `openai/` (for example `anthropic/...`), or an empty model, makes the command fail with an error. A name without a prefix is passed through unchanged, so make sure it is a model your OpenAI-compatible endpoint serves. `llm_protocol` is validated too: an empty value falls back to `openai-responses`, the check is case-insensitive, and any value other than `openai-responses`, `openai` or `anthropic` makes the command fail.
:::

### How rules are combined

- Each `[[ocr_review.rules]]` entry becomes a rule in `rule.json`, in the order you list them. The first matching glob wins.
- When `extra_instructions` is set, it is appended to every path-scoped rule and also added as a final catch-all rule for `**/*`, so files that match no path rule still get it.
- Every rule is written with `merge_system_rule: true`, so OCR's built-in review rules still apply.
- Passing `--rule "$OCR_RULE_FILE"` to `ocr review` overrides a `.opencodereview/rule.json` committed in the repository. Omit the flag when no rules are configured.

## GitLab pipeline example

Run OCR as a second stage after the PR-Agent describe/review job, using the same PR-Agent image:

```yaml
ocr_review:
  stage: ocr
  image:
    name: <your pr-agent image>
    entrypoint: [""]
  variables:
    GIT_DEPTH: 0
    OCR_LLM_AUTH_TOKEN: ${OPENAI_KEY_VAR}      # CI/CD variable holding the LLM API key
    GITLAB_API_TOKEN: ${GITLAB_TOKEN_VAR}      # CI/CD variable holding a GitLab token
    OCR_INCREMENTAL: "true"
    config__propagate_tool_errors: "true"
  script:
    - cd "$CI_PROJECT_DIR"
    - python -m pr_agent.cli --pr_url="$MR_URL" ocr_config
    - . .ocr/ocr.env
    - ocr config set llm.url "$OCR_LLM_URL"
    - ocr config set llm.auth_token "$OCR_LLM_AUTH_TOKEN"
    - ocr config set llm.model "$OCR_LLM_MODEL"
    - ocr config set llm.protocol "$OCR_LLM_PROTOCOL"
    - ocr config set language "$OCR_LANGUAGE"
    - ocr llm test
    - |
      ocr review --from "$DIFF_BASE_SHA" --to "$CI_COMMIT_SHA" \
        --format json --audience agent \
        ${OCR_RULE_FILE:+--rule "$OCR_RULE_FILE"} > .ocr/ocr-result.json
    - python3 /app/third_party/open_code_review/post_review.py .ocr/ocr-result.json
```

`MR_URL` is the merge request URL and `DIFF_BASE_SHA` is the merge request diff base (use `origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` when it is not available). `GIT_DEPTH: 0` gives OCR the full history it needs to compute the diff.

:::note
Secrets such as the LLM key and the GitLab token come from CI/CD variables and are passed to `ocr` directly. They are never written to `.ocr/ocr.env`, so the file is safe to keep as a job artifact for debugging.
:::

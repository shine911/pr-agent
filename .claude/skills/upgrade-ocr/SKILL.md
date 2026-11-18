---
name: upgrade-ocr
description: Upgrade the bundled open-code-review (OCR) CLI and vendored post_review.py to the latest (or a given) release.
disable-model-invocation: true
---

# Upgrade OCR

The Docker image installs the `ocr` binary pinned by `OCR_VERSION` and per-arch SHA-256 in `docker/Dockerfile`, and
`ocr_review` (`pr_agent/commands/pr_ocr_review.py`) shells out to it and to the vendored
`third_party/open_code_review/post_review.py`. All of these move together in one commit. The upgrade is done when the
pins, the vendored files and their provenance all name the new tag, and the CLI surface pr-agent uses is confirmed on
the real binary.

## Steps

1. **Bump.** Requires an authenticated `gh`.

   ```bash
   bash .claude/skills/upgrade-ocr/scripts/bump_ocr.sh            # latest release
   bash .claude/skills/upgrade-ocr/scripts/bump_ocr.sh v1.13.12   # a specific tag
   ```

   The script resolves the tag at run time, checks the release still ships `opencodereview-linux-{amd64,arm64}` and
   `sha256sum.txt`, rewrites the three Dockerfile ARGs, re-vendors `post_review.py` and `LICENSE` from the same tag,
   rewrites the provenance lines in `third_party/open_code_review/README.md`, and probes the host-arch binary for
   every `ocr` flag, subcommand and config key `pr_ocr_review.py` uses.

   Done when it exits 0. If the version is already current, stop: there is nothing to upgrade.

2. **Reconcile the CLI surface.** The probe list in `bump_ocr.sh` is a cache of what `pr_ocr_review.py` and
   `pr_agent/algo/ocr_config.py` call. Grep those two files for `"ocr"` invocations, `config set` keys and protocol
   names (`_OCR_PROTOCOLS`); anything not probed gets added to the script. A FAIL probe means upstream renamed or
   removed something: read that release's notes (`gh release view <tag> -R alibaba/open-code-review`), adapt
   `pr_ocr_review.py` and its tests, or ask the dev when the replacement changes behaviour.

3. **Review a changed `post_review.py`.** When the script reports it CHANGED, read `git diff` of it. `ocr_review`
   runs it as `python post_review.py <result.json>` with `CI_SERVER_URL`, `CI_PROJECT_ID`, `CI_MERGE_REQUEST_IID`,
   `GITLAB_API_TOKEN` in the environment; confirm the positional argument, those variables and the result-file shape
   it reads are unchanged, or adapt the caller. The file is vendored unmodified: never edit it locally.

4. **Test.**

   ```bash
   PYTHONPATH=. uv run pytest tests/unittest/test_pr_ocr_review.py tests/unittest/test_pr_ocr_config.py \
     tests/unittest/test_ocr_config.py -q
   uv run pre-commit run --files docker/Dockerfile third_party/open_code_review/README.md
   ```

   A Docker build (`docker build -f docker/Dockerfile --target cli .`) proves the pins end to end; ask the dev before
   running it, and say in the report when it was skipped.

5. **Commit** with `shine-skills:commit`: `build(docker): bump bundled ocr CLI to <tag>`. The body names the old
   and new tags, whether `post_review.py` changed, and what was probed versus what still needs a live MR run.
   Releases land almost daily; mention in the report that a newer tag may already exist.

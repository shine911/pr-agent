---
name: sync-upstream
description: Merge The-PR-Agent/pr-agent main into this fork without losing fork features, then upgrade the bundled open-code-review (OCR) CLI to its latest release.
disable-model-invocation: true
---

# Sync with upstream

Two steps, in order: merge `upstream/main` into the current branch (step 1), then upgrade OCR (step 2). The merge is
done when every fork feature in [`fork-features.md`](fork-features.md) still works and the gates in
`scripts/verify.sh` all PASS. The scripts keep their state in `<git-dir>/upstream-sync/`.

Run on the branch the dev is on. If that is `main`, create `chore/sync-upstream-<yyyymmdd>` first. Use merge, never
rebase: fork commits are signed and already published. Do not push.

## Step 1: merge upstream

### 1.1 Snapshot

```bash
bash .claude/skills/sync-upstream/scripts/snapshot.sh
```

It refuses to run with uncommitted tracked changes or a merge in progress. Untracked files (`.codegraph/`, local
notes) are fine and must stay out of every commit. It writes a backup tag `backup/pre-upstream-sync-<ts>`, the
baseline unit-suite run (`baseline.xml`; slow, about 5–10 minutes), and `inventory.md`: fork-only commits, files the
fork changed, upstream renames and deletions, and the predicted conflicts.

Done when `state.env`, `inventory.md` and `baseline.xml` exist. Baseline failures are pre-existing; note them for
the report.

### 1.2 Inventory fork features

Read `inventory.md` and `fork-features.md` side by side. Every fork-only commit must map to a registry feature, an
intentional divergence, or housekeeping (style, lint, dependency bumps, docs typos). Add a registry row for any
commit that maps to nothing, with its anchor files and guarding tests. Then read the "Upstream renames" and
"Predicted conflicts" sections and note which features they touch.

Done when every fork-only commit is accounted for.

### 1.3 Merge

Compare `uv --version` with `tool.uv.required-version` in `upstream/main:pyproject.toml`. When upstream raised the
floor, run `uv self update <that lower bound>` (the packaging test asserts that exact version) and tell the dev.

```bash
git merge --no-ff --no-commit upstream/main
```

If the merge refuses because an untracked or modified file would be overwritten, follow
`shine-skills:resolve-merge-conflict` to protect that work first.

### 1.4 Resolve

Work through `git status` until `git diff --name-only --diff-filter=U` is empty. For each file, read both sides
(`git diff MERGE_BASE OLD_HEAD -- <path>` is the fork's intent; values are in `state.env`) and apply the rules below.
`python3 .claude/skills/sync-upstream/scripts/hunks.py show <file>` prints a file's hunks numbered; `hunks.py pick
<file> o t ot ...` resolves them where one side, or both verbatim, is right. Resolve source files first, then tests:
test expectations follow from what the resolved source emits.

**Upstream owns structure, the fork owns behaviour.** When upstream renamed, split or refactored code, take
upstream's shape and re-apply the fork's change on top of it. Re-implementing the fork change inside the new structure
is expected; resurrecting the old structure is not.

- **File location conflict** (fork added a file inside a directory upstream renamed): `git mv` it to the suggested
  path, then fix imports and `mock.patch("...")` target strings that name the old module. A stale patch target
  patches nothing and lets tests reach real services.
- **Modify/delete, upstream side deleted**: upstream usually moved or merged the file. Find the successor
  (`git log --format='%h %s' MERGE_BASE..upstream/main -- <path>`, then search for its functions), port the fork hunks
  there, `git rm` the old path. Renamed test files get the same treatment.
- **Modify/delete, fork side deleted**: if the file is an intentional divergence in `fork-features.md`, `git rm` it.
  Otherwise treat it as a new question for the dev.
- **Content conflict**: keep both sides' intent.
- **User-facing strings**: where upstream now renders text through `t("…")` (its i18n catalogs), take upstream's
  call; `config.fixed_text_language` makes it Vietnamese. Where upstream rewrote a string the fork had translated
  (new wording, `{bot_display_name}`, `tool` → `command`, a configurable path), translate upstream's new text. Brand-new
  upstream strings stay English and go in the report as untranslated. A translated string that code matches back
  (headers found by regex, labels compared later) must change at every match site; grep for it.
- **Fork method vs a new upstream method of the same name**: rename the fork's; a later definition in the class
  silently replaces upstream's and breaks its callers (the duplicate-definition gate catches this).
- **New upstream policy tests** (config description length, `SECTION_DOCS`, the PR-comment override ledger, GitLab
  `per_page`) apply to fork code too: satisfy them, following the fork-key rule in `fork-features.md`.
- **`docs/docs/usage-guide/configuration_reference.md`**: take upstream's side, resolve `configuration.toml`, then
  regenerate the page with `uv run python scripts/generate_config_reference.py` and set the active-key count in
  `tests/unittest/test_config_reference.py`.
- **`pyproject.toml`**: resolve it, then `uv lock` and `uv sync`; never hand-merge `uv.lock`.
- **Docs**: moved pages keep their sidebar entry in `docs/sidebars.js` and every link to them is updated.
- **CI and Docker pins**: take the newer version.

Ask the dev (one batched question, with the options and a recommendation) only when the two sides cannot coexist:
upstream removed or rewrote behaviour a fork feature depends on, upstream ships its own version of a fork feature, or
keeping a fork feature would mean reverting an upstream change. Decide everything else yourself and record the
decision for the report.

### 1.5 Verify

```bash
bash .claude/skills/sync-upstream/scripts/verify.sh          # all gates
bash .claude/skills/sync-upstream/scripts/verify.sh --fast   # skip unit suite and pre-commit while iterating
```

The gates check: no conflict markers or unmerged paths, no references to files the fork deleted (code and config;
upstream may add a `COPY` or test for one), no stale paths from upstream directory renames (old imports, `mock.patch`
targets), no method defined twice in a class, `uv.lock` in sync, ruff on changed files, the config reference page,
the **fork delta**, the unit suite against the baseline, the packaging test, and pre-commit on changed files.

Fix test failures by grouping them per file (`grep ^FAILED <git-dir>/upstream-sync/after.log`). Most are language
mismatches; for each, grep `pr_agent/` for what the source emits and change the expectation to that, never the
source to English. A failure that is not a wording mismatch is a real bug until shown otherwise.

The fork delta gate (`scripts/check_fork_delta.py`) lists every line the fork added that is gone (LOST), every line
the fork removed that came back (BACK), and fork files that went missing or returned. Near matches (renamed variables or
imports) print as FUZZY and are not counted; skim them. For each finding, either fix the tree or, when the loss is
right (upstream now does the same thing, or the line moved into new code in a different form), acknowledge it in
`<git-dir>/upstream-sync/ack.tsv` with a one-line reason. `compare_tests.py` flags tests that regressed, vanished or
fail; tests upstream itself deleted or renamed are counted apart, and a vanished test with a candidate (renamed or
re-parametrized) needs a look, not a fix.

Done when the full run prints no FAIL, and every guarding test listed in `fork-features.md` ran and passed in
`after.xml`.

### 1.6 Commit

Write the message to `.git/MERGE_MSG` (subject `chore: merge upstream/main (<upstream short sha>)`; body with the
upstream commit count, the dev's decisions, the notable resolutions and the verification result), then commit with
`shine-skills:commit`, which records a merge with `git commit -S --no-edit`. Untracked files stay untracked.

Then update `fork-features.md` (new features, renamed anchor paths, absorbed features) and commit it with
`shine-skills:commit`.

## Step 2: upgrade OCR

Follow [`../upgrade-ocr/SKILL.md`](../upgrade-ocr/SKILL.md). Afterwards the fork-delta gate reports the old OCR pins and vendored
provenance as LOST; acknowledge them as replaced by step 2.

## Report

Tell the dev, in their language:

- upstream range merged, conflict count, backup tag, and that nothing was pushed;
- each decision that was not mechanical, and each acknowledged fork-delta finding;
- baseline vs after test counts, and any pre-existing failures;
- new upstream user-facing strings left untranslated;
- the OCR version change;
- rollback: `git reset --hard <backup tag>`.

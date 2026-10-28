---
title: "CODEOWNERS check (GitLab)"
sidebar_position: 8
---

The `/codeowners` command checks a GitLab merge request against its `CODEOWNERS` file. When a changed file falls under
a rule and that rule's owners have not approved the merge request yet, PR-Agent opens an unresolved thread that
mentions the missing owners. The thread tells the team that a code owner review is blocking the merge request.

It is disabled by default. It does not call a model, so it does not need an AI provider key.

## Enable

```toml
[codeowners]
enable_codeowners_check = true
```

Run it with the `/codeowners` comment on a merge request, or from a CI job that runs the `codeowners` command.

## Behavior

- `CODEOWNERS` is read from the **target branch**. The first file found is used, in this order: `CODEOWNERS`,
  `docs/CODEOWNERS`, `.gitlab/CODEOWNERS`. Reading the target branch stops a merge request from changing its own owners.
- Patterns follow GitLab's syntax: gitignore-style globs, sections `[Name]` and `^[Optional]`, `[Section][N]` for N required
  approvals, and a last matching rule wins within each section. A `!pattern` line excludes matching paths from approval.
- An owner is satisfied when the user approved the merge request, or when a direct member of the group approved it.
  `@@developer`, `@@maintainer` and `@@owner` count direct project members with exactly that role. Plural forms are accepted.
- Email owners cannot be matched to GitLab approvers, so they are ignored.
- The bot opens a thread, but it never resolves it. A team member resolves it after the code owner approves.
- The thread carries a hidden marker. Running the command again with the same pending owners does not open a second thread
  while the first one is still open. After a team member resolves the thread, the next run opens a new thread if the
  owner approval is still missing.

## Limits

- The check does not block the merge. Only GitLab approval rules can do that, and they need a paid GitLab tier.
- On GitLab Free, the check reads approvals from the merge request. It does not use the GitLab Premium `approval_state` API.
- Group and role membership is read with the configured token. If the token cannot read the group or project members, the
  owner is not counted as an approver, and the check logs a warning.

# Contributor & commit conventions

Read this before merging, closing, or commenting on a PR or issue.

## Respecting contributors

When merging community PRs, **preserve the original author's commit so they get GitHub contributor credit**. In practice:

- `git fetch origin pull/<N>/head:pr-<N>` → `git merge --no-ff pr-<N>` keeps the author commit verbatim inside the merge bubble (don't squash, don't rebase-flatten).
- For a partial merge — when only one hunk of a PR is wanted — use `git cherry-pick <commit-sha>` against the specific upstream commit so authorship is preserved. If the diff isn't a clean single commit, fall back to applying the hunk manually + adding a `Co-Authored-By: Name <email>` trailer.
- Improvements that the bot/maintainer makes _on top_ of a contributor's work go in **separate follow-up commits**, not amendments to the contributor's commit.
- When closing duplicate PRs (multiple authors fixed the same bug independently), thank each one and explain that landing the earliest version isn't a quality judgment.
- **After a PR merges (or you close it), post a short comment on it.** Thank the author, note the release it shipped in, and mention any follow-up changes you layered on top of their commit. A `git merge --no-ff` of the exact PR head commit makes GitHub auto-close the PR as *merged* (so the author keeps contributor credit) — but it doesn't notify or thank them, so the comment closes the loop.

This applies to all agents working on this repo, not just Claude Code.

## Signing GitHub comments

Every GitHub issue/PR comment posted on the maintainer's behalf ends with a signature on its own final line, in italics. Pick by whether Paweł actually reviewed the comment text before it went out:

- He reviewed it → `_Written with an agent, reviewed by Paweł_`
- The agent posted it without his review → `_Written by Pawel's agent_`

Only claim review when it actually happened. (Convention shared with the sibling `grok-build-vscode` repo.)

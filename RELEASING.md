# Versioning and releases

Read this before cutting a release, editing the `CHANGELOG.md` heading, or touching `Formula/claude-usage.rb`.

[SemVer](https://semver.org/). **`CHANGELOG.md` is the canonical version reference**; tags are a projection of it, created automatically.

## The release flow

1. While work accumulates on `DEV`, the `## vX.Y.Z — TBD` heading at the top of `CHANGELOG.md` collects bullets. (For automated triage runs, see the [weekly triage routine](#weekly-triage-routine) below.)
2. When the maintainer is ready to release, they finalize the heading (`TBD` → today's date), **bump both `scanner.VERSION` and `vscode-extension/package.json`'s `version` to match the CHANGELOG version** (all three ship in lockstep — the extension bundles the Python sources, and `scanner.VERSION` is the runtime version reported by `cli.py --version` and the dashboard footer since the CHANGELOG isn't bundled into the `.vsix`), **run [`scripts/bump-formula.sh`](scripts/bump-formula.sh) on `DEV` to repoint the Homebrew formula at the previous release's tag tarball** (see "Homebrew formula and self-referential SHA" below — this is a plain `DEV` commit that reaches brew users via this same merge, so it never touches `main` directly), merge `DEV → main` with `merge --no-ff` (so the release boundary is visible in `git log main`), and push `main`. A parity test (`tests/test_version.py`) fails the suite if the three drift, so in practice they're bumped together on `DEV` when the version heading is written.
3. [`.github/workflows/tag-on-merge.yml`](.github/workflows/tag-on-merge.yml) fires on the push, sees the new `## vX.Y.Z` heading in the CHANGELOG diff, and:
   - creates a lightweight tag at the merge commit (**no `git tag` step for the maintainer**), then
   - builds the VS Code extension `.vsix` and publishes a **GitHub Release** for that tag — the matching CHANGELOG section as the release notes, the built `.vsix` attached as a release asset.

So every release is both a tag *and* a GitHub Release with the installable `.vsix` downloadable from it. This mirrors the manual procedure in the sibling `grok-build-vscode` repo (`scripts/release.*`: tag + `gh release create` with the `.vsix` attached), adapted to this repo's CHANGELOG-driven, merge-to-`main` model — so it's automated rather than a local script. Marketplace publish (`vsce publish`) stays separate and explicit, exactly as there.

**The release step asserts `vscode-extension/package.json`'s version equals the CHANGELOG version and fails loudly if not** — the `.vsix` filename embeds the package version, so a mismatch would mislabel the asset. If you forget the bump, the tag is still created but the Release step fails; bump `package.json` and create the Release by hand (`gh release create vX.Y.Z --notes-file <section> vscode-extension/<name>-X.Y.Z.vsix`), since a same-commit re-push won't re-add the heading to re-trigger the workflow.

The workflow is idempotent: if the tag already exists (someone tagged manually before the workflow caught up) the tag step is a no-op, and if the Release already exists the release step is a no-op. It also no-ops entirely on pushes that don't add a new version heading (typo fixes, docs-only edits, etc.).

Existing tags `v1.0.0`, `v1.1.0`, `v1.1.1` are lightweight and were created by hand before the workflow existed. `v1.1.2` was the first tag created by the workflow. The workflow only *adds* missing tags; it never reconciles existing ones. Don't bother re-tagging the legacy ones.

## CHANGELOG conventions

The workflow trusts the CHANGELOG, so the format matters. Every new release entry on `DEV` follows this exact shape:

```
## vX.Y.Z — TBD

### <Area>

- One bullet per change, past tense, with a PR/issue link and `thanks @author` where the change came from a contributor (#73, thanks @thomasleveil)
```

Format rules the workflow relies on:

| Field | Required form | Why |
|---|---|---|
| Heading | `## vX.Y.Z` (exactly two `#`, the `v` prefix, three numeric components — strict semver) | The workflow regex `^## v[0-9]+\.[0-9]+\.[0-9]+([[:space:]]|$)` won't match anything else. `v1.1`, `v1.1.0-rc1`, `V1.1.0` are all silently ignored. |
| Separator | ` — ` (em-dash with surrounding spaces) | Cosmetic but consistent. The workflow ignores everything after the version. |
| Date | `TBD` while accumulating on `DEV`; replace with `YYYY-MM-DD` *at the moment of merging to `main`* | The workflow doesn't enforce dates — but a `TBD` heading that ships to main means the release looks unfinished forever. |
| Subsections | `### Dashboard`, `### Scanner`, `### Packaging`, `### Project / docs` — pick the smallest set that fits | Keeps the CHANGELOG scannable. |
| Bullets | Past tense, link the PR/issue with `#N`, credit external contributors with `thanks @login` | Lets readers (and future maintainers tracing history) find the source quickly. |

**The TBD → date rule is the only step a human must remember at release time.** If you forget, the workflow still tags correctly, but the CHANGELOG entry on main reads `## v1.1.3 — TBD` forever. Fix-up commit can correct it, but it'll feel sloppy.

Patch (`Z` increments) is the default for any release. Bump minor (`Y`) when a non-breaking user-visible feature lands (e.g. Today range button shipping alone would have been a minor in a different world). Bump major (`X`) only on breaking changes — there have been none and likely won't be soon. There's no automation around picking the right bump; the maintainer (or `/triage`) decides when writing the CHANGELOG heading on `DEV`.

## Homebrew formula and self-referential SHA

The Homebrew formula at `Formula/claude-usage.rb` lives inside this same repo. Be careful when bumping it: if the formula's `url` points at a tarball that **contains the formula itself with that sha256**, the sha256 is self-referential and uncomputable. Practical rule: a release's formula must point at the **previous** release's tarball, never its own. In v1.1.1 the formula points at v1.1.0's commit-SHA tarball, so brew users installing v1.1.1's formula receive v1.1.0 code — that's the trade-off of keeping the formula in-tree.

Now that the auto-tag workflow exists, formula bumps use the tag-tarball URL (`archive/refs/tags/vX.Y.Z.tar.gz`) instead of commit SHAs — stabler and shorter — as long as the tag-tarball pointed at is from the *previous* release.

**Automate the bump; never hand-edit the three pinned lines.** [`scripts/bump-formula.sh`](scripts/bump-formula.sh) fetches a released tag's tarball, computes its `sha256`, and rewrites the `url` / `version` / `sha256` lines (leaving `head`, `homepage`, and comments alone). With no argument it targets the latest `v*` tag on origin — run during release prep, before the new tag exists, that's the previous release, exactly what the self-referential rule requires.

**Why a `DEV`-only commit is enough — and why it's one release behind.** Brew reads the formula from the tap's default branch (`main`) HEAD, never from `DEV` or a tag. So the bump is a normal `DEV` commit that becomes visible to brew users only when `DEV → main` merges — which is precisely at the next release. That timing is the point: it lets us pin at the just-frozen *previous* tag and ship it with the release, so **brew always tracks one release behind, advancing automatically each release**, with no direct push to `main` (dodging `main`'s branch protection) and no hand-editing to forget. The manual, forget-prone bump is what let the pin silently rot at v1.1.0 from v1.1.1 through v1.5.0; v1.5.2 caught it up to v1.5.1 and wired in this routine. The only thing a `DEV`-only bump can't do is move brew *between* releases — you'd need a release (a `DEV → main` merge) for that, which is fine because the pin only ever changes at release boundaries anyway.

## Weekly triage routine

The repo has a self-contained slash command at [.claude/commands/triage.md](.claude/commands/triage.md) that automates the weekly PR/issue cleanup we used to ship v1.1.0: classify open items with Codex, merge no-brainers to DEV preserving authorship, run tests, close duplicates / scope-violations with friendly messages, bump CHANGELOG by patch, push DEV. **The routine never pushes to `main`** — release decisions stay with the maintainer.

Register the Windows Task Scheduler entry with [scripts/setup-weekly-triage.ps1](scripts/setup-weekly-triage.ps1). Logs go to `logs/triage-*.log`.

If you're working on this repo and want to invoke the routine ad-hoc, just type `/triage` in Claude Code. Hard safety rails (test-passing gates, no security-sensitive auto-merges, no scope-changing merges, Codex sign-off required on closures) live inside `triage.md`.

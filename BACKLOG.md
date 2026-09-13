# Backlog — fork triage & working queue

Started as a point-in-time triage of everything open on `phuryn/claude-usage` (upstream), taken 2026-09-13. Upstream's maintainer is inactive, so `Kalradia/claude-usage` is splitting off as its own line of development rather than staying a PR-feeder for upstream: we pull in whatever's worth keeping (preserving contributor authorship per AGENTS.md), fix it ourselves when it's not, and this doc is now our own working backlog — counted down as items land on our `main`, not a snapshot frozen at triage time. Classifications lean on the scope philosophy already encoded in `.claude/commands/triage.md`: keep the product surface tight ("parse local JSONLs, show usage and cost"), route real feature growth through a GitHub Discussion first, and never auto-merge anything security-sensitive, schema-changing, or over the 8-file/200-line size rails.

Counts: **8 open issues, 15 open PRs** remaining. (Started at 11/18 on 2026-09-13; resolved since: `#162`→`#163` merged, `#160`→`#165` merged, `#173` closed as `#165`'s duplicate, `#175` fixed directly. Items marked `~~closed~~` below — merged or a duplicate we aren't taking — are dropped from the count; noting them stays useful so we don't reopen the same question later.)

---

## 🔴 Needs maintainer action first

### #167 — Security issue in the weekly `/triage` automation
Contributor `coolio1` ran a security review of `.claude/commands/triage.md` and found an issue affecting how the routine handles **untrusted PR content while holding `gh` push credentials** — deliberately withheld from the public issue. They also found lower-severity items (CSRF, a couple of XSS spots, missing CSP, a VS Code extension setting-scope gap, Docker base image pinning) they're willing to PR normally.

**Action needed:** enable GitHub private vulnerability reporting (Settings → Security → Advisories) or give them another channel. This blocks on the maintainer specifically — no agent should try to guess or fix the withheld issue blind. Until it's resolved, treat the `/triage` skill's `gh` credential scope as a known-unaudited risk.

---

## Pricing / cost-correctness bugs (in scope, high value)

These are the most valuable items in the queue — they affect the numbers the tool exists to show.

### ~~#162 (issue) → #163 (PR, `MildlyMeticulous`)~~ — done
Shipped 2026-09-13: merged `#163` (thanks `@MildlyMeticulous`) plus a follow-up ("finish 1h-TTL cache pricing across the dashboard + backfill old DBs") to close the remaining gaps. 1-hour-TTL cache writes now bill at 2x input instead of the 5-minute 1.25x rate.

### ~~#175 (issue) — Sonnet 5 priced at stale $3/$15 instead of $2/$10~~ — done
Shipped 2026-09-13: added an explicit `claude-sonnet-5` entry to `PRICING` in both `cli.py` and `dashboard.py` ($2/$10, $0.20 cache read, $2.50 5-min cache write), and repointed the generic "sonnet" substring fallback at it instead of the stale `claude-sonnet-4-6` rate. Confirmed no PR ever existed upstream (`HaydenHaines`'s claimed fix was never opened as a PR — see the caution note at the bottom of this doc) — fixed directly instead of waiting.

### Kalradia/claude-usage#1 (issue, this fork) — pricing table isn't effective-dated
Filed 2026-09-13 as a follow-up to #175: `PRICING` is a single flat table, so editing a rate (e.g. for a real future repricing) silently recomputes the cost of *every past session* at the new rate instead of the rate actually in effect when those tokens were billed. Structural gap, not covered by the #175 fix. See the issue for the fuller writeup.

### ~~#160 (issue) — sub-agent turns priced at the session's primary-model rate~~ — done
Two independent, competing fixes existed for this: **#165** (`blineadam`) and ~~#173~~ (`ollo12-prog`, **closed — duplicate, not taken**), both touching `dashboard.py` + tests with the same `by_model` breakdown approach. Compared both diffs 2026-09-13: near-identical, but #165 additionally adds `sessionIsBillable(s)` (checks billability across the whole per-model breakdown, not just the primary-model label — handles a session whose primary label is non-billable but which dispatched a billable sub-agent), which #173's own PR body calls "deliberately unchanged... out of scope." Merged **#165** (thanks `@blineadam`) to `main`. Neither PR had been updated for the #162/#163 1h-TTL cache pricing work that landed first, so a follow-up patch was folded into the merge: `_session_model_breakdowns`'s SQL now also sums `cache_creation_1h_tokens`, and `sessionCost()` passes it as `calcCost`'s 6th arg — otherwise `TestCalcCostCallSites` would fail and the by_model tables would silently under-bill 1-hour cache writes.

---

## Dashboard staleness (duplicate cluster)

### #157 vs #161 — "the 30s auto-refresh doesn't actually re-scan"
Both fix the same underlying problem: a long-lived dashboard polls `/api/data` every 30s, but nothing re-scans the JSONL transcripts after the one-time startup scan, so the numbers freeze.

- **#157** (`Lyazid21`, +113/-15, 4 files: `cli.py`, `dashboard.py`, `scanner.py`, test) — narrower fix, revives the approach from closed PR #59.
- **#161** (`DiegoDAF`, +408/-11, 9 files including `AGENTS.md`, `CHANGELOG.md`, `README.md`, `vscode-extension/package.json`) — same core fix but fuller: docs, changelog, and extension-side updates included.

**#161 looks like the more shippable one** (it does the doc/changelog housekeeping the release process expects), but it's ~4x the diff size — worth a closer read to make sure it isn't doing more than the fix requires. **Recommend: review #161 first, close #157 as superseded if #161 lands.**

**Local context worth knowing before picking a direction:** commits `00a3ee5` and `162b72f` already on `main` touch the *same* stale-dashboard problem area from the opposite angle — `00a3ee5` makes the 30s auto-refresh **opt-out** (`CLAUDE_USAGE_AUTO_REFRESH`) for deployments that scan once and never again, rather than making refresh trigger a rescan. That's a different design answer to a related problem (rescan-on-refresh vs. don't-refresh-if-nothing-changes) — whoever picks between #157 and #161 should reconcile with it rather than shipping two answers to "is periodic rescanning a good idea" that contradict each other.

### #168 — step past occupied ports / fix `ERR_EMPTY_RESPONSE`
Not a duplicate of the above — different bug (port collision with a reverse proxy holding the port via `allow_reuse_address`, not staleness). Well-diagnosed, but +361/-18 across 5 files exceeds the triage bot's auto-merge line budget. **Needs manual review**, not a routine no-brainer.

### #171 — Docker port auto-fallback + login/boot autostart script
Partial overlap with #168 (port-fallback logic, but scoped to `scripts/run-docker.sh` specifically) plus a genuinely new feature (`scripts/install-autostart.sh`, a LaunchAgent/systemd installer). The autostart half is a scope call, not a bug fix — installing background services is a step beyond "parse JSONL, show cost." **Recommend: split if possible** — the docker port-fallback half is a reasonable bug fix; the autostart-installer half should go through the same scope-decision lens as the feature PRs below.

---

## Other in-scope bug fixes (straightforward, no open issue)

- **#169** (`NickAme03`, +65/-1) — a turn scanned mid-stream freezes at partial token counts forever because dedup happens twice (in-memory per-file, then DB-level `INSERT OR IGNORE` on `message_id`) and only the first is correct. Small, well-explained, directly hits the "streaming dedupe by message.id" invariant called out in AGENTS.md. Good merge candidate.
- **#176** (`retog`, +271/-23, 4 files) — background (`isAsync`) subagent dispatches show as `unknown` because `extract_agent_dispatch` only reads `agentType` from a *synchronous* completion record; async launches log a different shape. Real bug, reasonably sized. Review before merge (4 files, borderline on size but under both size rails).
- **#172** (`DiegoDAF`, +7/-1, 2 files) — hourly chart's 24 hour-labels overlap below ~1000px because `maxRotation: 0` + `autoSkip: false` leaves Chart.js no escape hatch. Trivial, low-risk. Good no-brainer merge.

---

## Worktree / project-naming correctness

- **#154** (`poppinpixels`, +122/-1, `scanner.py` + test) — folds `.claude/worktrees/<name>/` sessions back into their parent project (currently each worktree becomes its own bogus "project" row). Includes a one-time backfill from `cwd` already stored on `turns`, no re-scan needed. Small, focused, in scope. **Good standalone merge candidate.**
- **#179 / #180** — see the feature section below; #179 independently reimplements the same worktree-folding fix (via `.git`'s `commondir`) as one part of a much larger bundle. **Don't merge both** — if #179's broader bundle stalls on scope review, #154 is the fast path to fixing the worktree-fragmentation bug on its own.

---

## Docs / chores (trivial)

- **#155** (`lennartlng`, +2/-2, 1 file) — adds the missing `week` subcommand to the README's Quick Start list and Files table. Pure doc fix, zero risk. Merge as-is.
- **#177 (issue) / #178 (PR, `lczyk`)** — "brew tap is on v1.5.4, latest is v1.5.5." **Read AGENTS.md's Homebrew section before touching this one** — the formula is *intentionally* one release behind by design (it points at the previous release's tarball to dodge the self-referential-SHA problem, and only advances at the next `DEV → main` merge via `scripts/bump-formula.sh`). So on its face #177 is expected behavior, not a bug — but #178's fix (repoint at v1.5.5) is also *exactly* what the next release's formula bump should do, just early and via a direct community PR instead of the scripted, release-timed process. **Recommend: don't merge #178 standalone** — let the next release's `bump-formula.sh` run absorb it (it'll produce the same diff), or close #178 with an explanation of the one-release-behind design so the confusion doesn't recur. Consider whether the "why is brew behind" question is common enough to deserve a line in the README FAQ.

---

## Feature requests — need an explicit scope decision

These are large/good enough to be worth your own read rather than a routine merge or a form-letter close. Since the fork isn't feeding PRs back upstream, "redirect to a GitHub Discussion" doesn't apply here the way `triage.md` originally framed it — the call is just yours to make directly.

- **#149** (`changsunglim`, +2329/-83, 11 files) — replaces the local token-heuristic weekly bar with Anthropic's real usage API (`GET /api/oauth/usage`), falling back to the local estimate offline. This is the biggest scope question in the queue: it's the first PR that would make the tool **call a network API using the user's OAuth token**, when the whole premise so far has been "stdlib-only, purely local-file parsing." Accuracy win is real (58% actual vs 100% local-heuristic display on the reporter's account) but it's a philosophy change, not a bug fix. **Needs your explicit call, not a routine merge or a routine close.**
- **#156** (`Algebraaaa`, +1581/-192, 6 files) — full i18n: 9 languages, 124 keys, both CLI and dashboard. Large, well-built, but permanently doubles the maintenance surface for every future UI string (every new stat card / label needs 9 translations from here on). Worth weighing whether you want to take on that ongoing cost.
- **#166** (`andyshinn`, +3494/-304, 19 files) — closes #164 (open workspace tab instead of sidebar). Largest PR in the queue by a wide margin; adds two new settings and a command. The underlying ask (#164) is reasonable and narrow, but the PR's size (19 files) suggests it grew well past "add a tab" — worth asking the author to scope down, or splitting the settings/command plumbing from any incidental refactors.
- **#171**'s autostart-installer half — see above, bundled with a real bug fix.
- **#179 / #180** (`albarsil`, +1887/-59, 10 files) — the biggest bundle: attribution breakdown (agent/skill/mcp/hook), worktree-aware project names, hook-injection tracking, and a new cost-breakdown UI. The author explicitly opened #180 as a tracking issue "for discussion/visibility" and says they're open to adjusting scope — this is already teed up for a Discussion-style review rather than a straight merge/close. **Recommend:** ask the author to split out the worktree-naming fix (already duplicated by the much smaller #154) as its own PR, and scope the attribution/hook/cost-breakdown UI as a genuine feature discussion given the size.

---

## Small/ambiguous — low priority, no PR yet

- **#158** (issue, dark/light toggle) → **#170** (PR, `EspenBrun`, +180/-23, 1 file) — closes #158. Reasonably scoped for what it is (single-file, adds a theme picker + CSS variable overrides), but it's UI-only feature growth. Since the dashboard already hardcodes a dark theme (i.e., "theme" is already a concept, not a new one), this reads more like filling in a gap than scope creep. **Reasonable merge candidate after a UI/contrast pass** — no automated a11y check exists, so eyeball light-mode contrast before merging.
- **#159** — toggle to include zero-usage days in the usage graph. No PR. A comment from `HaydenHaines` claims an implementation ("zero-padding... 42 passed") but, like #175, never became a PR — see the caution note below.
- **#145** — request to make API-vs-subscription pricing clearer in the UI (currently a small fine-print line at the bottom). Not really a "feature" in the scope-creep sense — it's a UX clarity fix to existing cost display. Low effort, no PR yet; reasonable small task for whoever picks it up.

## Support questions (not bugs, not features)

- **#152** — "Can I use this with the desktop app?" Maintainer (`phuryn`) already replied: not yet, researching whether Claude Desktop's logs are reachable. Leave open until that research lands; not actionable by triage.

---

## Caution: unverified "I already fixed this" comments

Three separate threads (**#175**, **#159**, and the severity claims inside **#167**) contain comments asserting a fix is complete with suspiciously specific test-pass counts ("143 passed in 1.46s", "42 passed in 0.79s", "147/147... 85/85... passing") — but **none of these commenters have an open PR to back the claim**, and a search of `HaydenHaines`'s PR history shows a pattern of closed (not merged) submissions. Treat these comments as unverified pointers at best, not as evidence the work exists. Don't cite them as justification for closing an issue, and don't paste their claimed diffs/approaches into a merge without seeing an actual PR.

---

## Suggested pass order

1. **#167** — get the private disclosure channel open; everything else can proceed in parallel.
2. Pricing correctness: ~~#163~~ (done), ~~#165~~ (done, ~~#173~~ closed as duplicate), ~~#175~~ (done). New: the effective-dated-pricing issue filed as its follow-up.
3. Small no-brainers: **#155**, **#172**, **#169**.
4. Worktree fix: **#154** (don't wait on #179's bundle).
5. Dashboard staleness: read **#161** fully, decide vs. **#157**, reconcile with the local `CLAUDE_USAGE_AUTO_REFRESH` commits already sitting on this fork's `main`.
6. Medium reviews: **#176**, **#168**, **#170**.
7. Scope decisions that are yours to make: **#149**, **#156**, **#166**, **#179/#180**, autostart half of **#171**.
8. Close-or-defer with a message: **#178** (explain the one-release-behind design), **#159**/**#145** (fine as low-priority backlog, no urgency).

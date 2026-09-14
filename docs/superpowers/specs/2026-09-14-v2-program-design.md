# v2.0 program design: multi-device, multi-provider usage server

Status: draft for maintainer review. Written 2026-09-14.

This document is the program-level spec for taking the fork of `claude-usage`
from a single-machine, Claude-only, stdlib-only script to a self-hosted server
that aggregates AI coding-tool usage from many devices and many accounts across
providers. It records the architectural decisions, the target data model, the
repo-workflow revamp, and the roadmap to v2.0. Each roadmap milestone gets its
own implementation plan later; this document is the contract those plans build
against.

The product name is an open decision (see [Open decisions](#open-decisions)).
Commands below use `<name>` where the final name goes.

---

## 1. Goals and non-goals

### Goals for v2.0

1. **Aggregate across devices.** One server receives usage from any number of
   machines and shows it in one place, with per-device visibility.
2. **Aggregate across providers and accounts.** Claude Code and OpenAI Codex
   CLI ship as first-class sources. Two Claude accounts and a Codex account on
   the same laptop are three distinct, filterable accounts.
3. **Persist in a real database** with migrations, an effective-dated pricing
   table, and a reprocess path so historical numbers can be corrected without
   touching any device.
4. **Modular by construction.** Provider adapters, dashboard widgets, and
   filters are each a plugin point with a defined interface, so post-2.0
   features (custom dashboards, more providers) are additions rather than
   rewrites.
5. **Runs on Linux and in Docker** as the primary targets. macOS and Windows
   are supported for the collector (that is where the logs are) and
   best-effort for the server.
6. **Persistent settings** owned by the user, editable from the UI, surviving
   restarts and upgrades.
7. **Keep every v1 user's history** through a one-shot importer.
8. **Lightweight on every device.** The collector must be invisible in normal
   use (budgets in [§6.4](#64-performance-budgets)).

### Non-goals for v2.0

- Multi-user login and per-user permissions. The data model reserves room
  ([§4.2](#42-ownership)); the feature is post-2.0.
- Custom, user-composed dashboards. v2.0 ships one well-designed default
  layout built on the widget system; composition UI is post-2.0.
- Providers beyond Claude Code and Codex CLI. The adapter interface is the
  extension point; more adapters are post-2.0.
- Calling any provider's network API. Everything in v2.0 comes from local
  files on the device. Opt-in API features are listed under
  [post-2.0 ideas](#16-post-20-outlook-and-candidate-ideas).
- Keeping the v1 code path alive after v2.0 ships.

---

## 2. Decision record

Each row is a decision taken during the design session on 2026-09-14, with the
alternatives that were considered and rejected.

| # | Decision | Chosen | Rejected | Why |
|---|----------|--------|----------|-----|
| D1 | Device-to-server transport | **Push.** A collector service on each device ships batches to the server. | Pull (server scans synced or mounted directories); both. | Servers usually cannot open connections to laptops behind NAT or asleep. Push needs no sync tooling and identifies devices naturally. |
| D2 | On-demand rescan | **Heartbeat command channel.** Collectors poll the server on a heartbeat; the reply carries pending commands. Server-side reprocess covers most cases so rescan is the exception. | Drop rescan entirely; server-initiated connections. | Heartbeat also gives last-seen, version reporting, and config push at negligible cost. |
| D3 | Where parsing lives | **Smart collector shipping normalized events plus a stripped raw record.** | Events only (needs rescan for any new derived field); raw lines to server (copies prompts and tool output off the device). | Privacy of a smart collector with most of the reprocessability of a dumb one. |
| D4 | Stack | **Python 3.11+ with dependencies (FastAPI, SQLAlchemy 2, Alembic, httpx, watchfiles); TypeScript SPA built to static files.** | Stay stdlib-only; Python with no-build frontend; rewrite in Go or Node. | Modularity and a polished UI are goals; stdlib-only fights both. Python keeps the existing parser knowledge and contributor base. |
| D5 | Database | **SQLite by default, PostgreSQL by connection string.** Both tested in CI. | SQLite only; Postgres only. | One-command install stays trivial; concurrent collectors and larger fleets have a path. Trade-offs documented in the README. |
| D6 | Users | **Single owner in v2.0, `owner_id` on every ownable row from day one.** | Multi-user in v2.0; no reservation. | Public repo; multi-user will be asked for. A column now is cheap; a retrofit is not. |
| D7 | Providers in v2.0 | **Claude Code and OpenAI Codex CLI.** | Also Gemini CLI, Cursor, Copilot, OpenCode. | Two providers are enough to prove the adapter interface. Real Codex logs exist to validate against. |
| D8 | v1 compatibility | **Clean break with a one-shot importer.** v1 CLI commands return as thin clients of the server. | Side-by-side maintenance; no importer. | Claude Code prunes old transcripts, so an importer is the only way to keep long-time users' history. |
| D9 | Naming | **Rename repo and package at v2.0** to a provider-neutral name; final name open. | Keep `claude-usage`; rename later. | One round of URL and formula churn instead of two; the name stops being misleading before Codex data appears. |
| D10 | Branching and releases | **Trunk-based: `main` plus short-lived PR branches.** `develop` retired. | Keep `main` + `develop`; release branches per minor. | Simplest story for public contributors. Requirement attached: a one-command path to run the server from any branch or PR. |
| D11 | Tracking and triage | **GitHub Issues, Projects, and Milestones. The Codex-collab `/triage` slash command is dropped.** | Linear for planning; keep automated triage. | Public visibility for contributors; the triage routine was built for the upstream relationship and carried an unresolved credential-scope concern (#167). |

---

## 3. Architecture

### 3.1 Components

Three deployables and one shared library, all in one repository:

- **`core`** (Python library): the normalized event schema, the provider
  adapter interface and the two v2.0 adapters, model normalization, and the
  pricing engine. Both the collector and the server depend on it, so they can
  never disagree on a format or a price.
- **`collector`** (Python daemon): runs on each device, watches the configured
  provider directories, runs adapters, and ships batches to the server.
  Dependencies: `core`, `httpx`, `watchfiles`. Nothing else.
- **`server`** (Python service): FastAPI application with the ingest API, the
  public API, a background job runner (rollups, reprocess), the v1 importer,
  and the built frontend as static files.
- **`web`** (TypeScript SPA): the dashboard. Built by Vite into static assets
  that the server image bakes in.

### 3.2 Data flow

```
provider logs on device
   │  (Claude: ~/.claude/projects/**/*.jsonl, Xcode dir, extra config dirs)
   │  (Codex:  ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)
   ▼
collector ── adapter per source ──▶ UsageEvent batches (gzip, HTTPS)
   ▼
server /ingest/v1/events ── validate, dedupe on (source_id, event_key) ──▶ usage_events
   ▼                                                                       sessions, agents
background jobs: rollups_daily (per day × source × model), reprocess
   ▼
server /api/v1/* ◀── dashboard SPA, thin CLI
```

Reprocess re-derives `usage_events` fields and `rollups_daily` from the
stored `raw` records and the pricing table. No device is involved.

### 3.3 Repository layout

```
<name>/
├── packages/
│   ├── core/          # <name>-core: schema, adapters, pricing
│   ├── collector/     # <name>-collector
│   └── server/        # <name>-server (includes importer and thin CLI)
├── web/               # Vite + React + TypeScript SPA
├── deploy/
│   ├── Dockerfile.server
│   ├── Dockerfile.collector
│   ├── compose.yaml          # server only
│   ├── compose.local.yaml    # server + local collector, one-machine install
│   └── systemd/, launchd/    # collector service templates
├── docs/                     # ARCHITECTURE, DEVELOPMENT, PRIVACY, DEPLOYMENT, ...
├── tests/fixtures/           # anonymized log corpora per provider
├── legacy/                   # v1 code, frozen, removed at v2.0.0
└── (README, CONTRIBUTING, SECURITY, CHANGELOG, LICENSE, pyproject workspace)
```

`uv` workspaces manage the three Python packages; `pnpm` manages `web/`.

---

## 4. Data model

The schema is written as SQLAlchemy models with Alembic migrations and must run
unchanged on SQLite and PostgreSQL. Timestamps are stored as UTC ISO-8601
strings on SQLite and `timestamptz` on Postgres via a single type adapter.

### 4.1 Tables

**`providers`**: static registry seeded by migration.
`id` (`claude_code`, `codex_cli`), `display_name`, `adapter_version`.

**`devices`**: one row per collector install.
`id`, `owner_id`, `name` (user-editable; defaults to a generated
adjective-animal name), `hostname`, `platform`, `collector_version`,
`token_hash`, `enrolled_at`, `last_seen_at`, `last_error`.

**`accounts`**: one row per (provider, external account).
`id`, `owner_id`, `provider_id`, `external_id` (Claude: `accountUuid`; Codex:
account id from `auth.json` when present, else a stable hash of the config
directory), `label` (user-editable; defaults to the discovered display name or
email), `organization_name`, `plan_type` (e.g. `claude_max`, `plus`),
`color`, `hidden` (excluded from default views), `discovered_at`.

**`sources`**: what a collector actually watches.
`id`, `device_id`, `account_id`, `provider_id`, `root_path`, `enabled`,
`last_ingest_at`. Unique on (`device_id`, `provider_id`, `root_path`). Two
Claude config directories on one laptop are two sources with two accounts.

**`sessions`**: a provider session or thread.
`id`, `owner_id`, `source_id`, `provider_id`, `external_id` (Claude
`sessionId`; Codex thread `id`), `parent_session_id` (Codex subagent threads;
Claude subagents are attributed per event instead), `project_key`
(normalized, worktree-folded, see [§5.4](#54-project-and-branch-normalization)),
`project_name`, `git_branch`, `cwd`, `title`, `first_at`, `last_at`,
`primary_model`, `event_count`, `compaction_count`. Unique on
(`provider_id`, `external_id`). Denormalized token totals are **not** stored
here; they come from `rollups_daily` or are summed on demand.

**`usage_events`**: the atomic fact, one per API response.
`id`, `owner_id`, `source_id`, `session_id`, `event_key`, `occurred_at`,
`model_raw`, `model` (normalized), `provider_id`,
`input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_5m_tokens`, `cache_write_1h_tokens`, `reasoning_tokens`,
`is_subagent`, `agent_id`, `agent_type`, `tool_name`,
`effort` (Codex reasoning effort; null elsewhere),
`context_window` (Codex `model_context_window`; null elsewhere),
`adapter_version`, `raw` (JSON, the stripped source record),
`ingested_at`. Unique on (`source_id`, `event_key`). Indexed on
(`owner_id`, `occurred_at`), (`session_id`), (`model`).

**`agents`**: subagent dispatch metadata.
`id`, `provider_id`, `external_id`, `session_id`, `agent_type`, `status`,
`completed_at`, `reported_tokens`, `duration_ms`, `tool_use_count`,
`nickname` (Codex). Unique on (`provider_id`, `external_id`).

**`pricing`**: effective-dated rates.
`id`, `provider_id`, `model_pattern` (exact id, prefix with `*`, or family
keyword), `match_kind` (`exact`, `prefix`, `family`), `valid_from`,
`valid_to` (null = current), `input_per_mtok`, `output_per_mtok`,
`cache_read_per_mtok`, `cache_write_5m_per_mtok`, `cache_write_1h_per_mtok`,
`reasoning_per_mtok` (null = billed as output), `source` (`builtin` or
`user`), `note`. Seeded by migration from the v1 tables plus the Codex
models. User overrides are rows with `source = 'user'` and win on ties.

**`rollups_daily`**: materialized aggregates.
`day`, `owner_id`, `source_id`, `account_id`, `device_id`, `provider_id`,
`model`, `is_subagent`, token columns, `event_count`, `cost_micros`
(integer micro-dollars), `pricing_version` (hash of the pricing rows applied).
Rebuilt for affected days on ingest and fully on reprocess. Every dashboard
chart reads from here; only session drill-down reads `usage_events`.

**`settings`**: persistent key/value JSON.
`namespace` (`server`, `dashboard`, `user:<owner_id>`), `key`, `value`
(JSON), `updated_at`. Unique on (`namespace`, `key`).

**`ingest_batches`**: receipts.
`id`, `device_id`, `source_id`, `batch_id` (client-generated UUID),
`file_path`, `start_offset`, `end_offset`, `received`, `accepted`,
`duplicates`, `received_at`. Unique on (`device_id`, `batch_id`) so a retried
batch is answered from the receipt without re-processing.

**`jobs`**: background job state for rollups, reprocess, import, and pending
device commands. `id`, `kind`, `target` (device id, date range, etc.),
`status`, `progress`, `error`, `created_at`, `finished_at`.

**`owners`**: reserved. One seeded row in v2.0 (`id = 1`). Holds the login
password hash and display name. Becomes `users` when multi-user lands.

### 4.2 Ownership

Every table that a future user could own (`devices`, `accounts`, `sessions`,
`usage_events`, `rollups_daily`, `settings` user namespace) carries a
non-null `owner_id` defaulting to `1`. No v2.0 query filters on it, but the
column exists so multi-user is a permissions layer, not a schema migration
plus backfill.

### 4.3 Invariants carried over from v1

These caused real bugs in v1 and remain true in v2:

1. **Streaming dedupe by message id.** Claude Code writes several records per
   API response; only the last one per `message.id` carries final usage. The
   Claude adapter keeps the last record per id within a file; the server's
   unique key on (`source_id`, `event_key`) rejects replays. A partially
   streamed record that was shipped early is **replaced** on the server when a
   later record with the same key and larger totals arrives (upsert, greatest
   totals win). This fixes upstream #169.
2. **Costs are computed per event, never from aggregated tokens**, because a
   session can span models.
3. **Primary model per session** is chosen by capability rank
   (fable/mythos > opus > sonnet > haiku; Codex ranks by family) so a subagent
   turn on a cheaper model never relabels a session.
4. **Reconciliation.** Session and rollup totals are always recomputed from
   `usage_events`, never adjusted incrementally.

---

## 5. Provider adapters

### 5.1 Interface

An adapter is a Python class in `core.adapters` registered by provider id:

```python
class ProviderAdapter(Protocol):
    provider_id: str
    adapter_version: str

    def discover_sources(self, home: Path) -> list[DiscoveredSource]:
        """Default roots and the account each one belongs to."""

    def discover_account(self, root: Path) -> AccountInfo | None:
        """Identity for a root (Claude: read .claude.json oauthAccount)."""

    def iter_files(self, root: Path) -> Iterable[Path]:
        """Log files under a root, in a stable order."""

    def parse(self, path: Path, start_offset: int) -> ParseResult:
        """Yield UsageEvent, SessionMeta, AgentMeta from new bytes; return end offset."""

    def strip_raw(self, record: dict) -> dict:
        """Drop content bodies; keep ids, usage, timestamps, unknown scalar fields."""
```

`UsageEvent` is a frozen dataclass mirroring the `usage_events` columns. The
same adapters run on the server for reprocess (`parse` over stored `raw`
records via an in-memory file shim) and in tests over the fixture corpus.

### 5.2 Claude Code adapter

Port of v1 `scanner.py` with these changes:

- Reads `~/.claude/projects/**/*.jsonl`, the Xcode coding-assistant directory,
  and any extra config directories listed in the collector config
  (`CLAUDE_CONFIG_DIR` style multi-account setups).
- Account discovery from `<config dir>/.claude.json` → `oauthAccount`
  (`accountUuid`, `emailAddress`, `organizationName`, `organizationType`).
- `event_key` = `message.id`. Records without an id use
  `sha256(sessionId, timestamp, line_offset)`.
- Carries over: title records (`custom-title` wins over `ai-title`),
  subagent detection (`isSidechain`, `agentId`, `/subagents/` paths),
  agent dispatch metadata including async dispatches (upstream #176),
  1-hour cache split from `usage.cache_creation.ephemeral_1h_input_tokens`,
  tool name from the first `tool_use` block.
- Compaction events counted per session.

### 5.3 Codex CLI adapter

New. Validated against the real corpus at `~/.codex/sessions/` on the
development VM (format as of Codex CLI 0.146):

- Files: `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<thread id>.jsonl`.
- `session_meta` record: thread `id`, `parent_thread_id`, `cwd`,
  `originator`, `cli_version`, and a `source.subagent` block with
  `depth`, `agent_nickname`, `agent_role` for spawned threads.
- `turn_context` records carry `model`, `effort`, `cwd`, and the
  collaboration mode. The adapter tracks the current model per file.
- `event_msg` / `token_count` records carry `info.last_token_usage`
  (`input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`) and `model_context_window`.
  One `UsageEvent` per `token_count` record whose `last_token_usage` is
  non-zero. Codex input tokens include cached tokens, so
  `input_tokens = input - cached_input` to match the Claude convention.
- `event_msg` / `token_count` also carries `rate_limits` (`used_percent`,
  `window_minutes`, `resets_at`, `plan_type`). The adapter emits these as a
  separate `PlanWindowSample` that v2.0 stores in `raw` only; surfacing it is a
  post-2.0 feature.
- `event_key` = `sha256(thread id, timestamp, line_offset)`; there is no
  message id.
- Subagent threads are separate files with `parent_thread_id`, so
  `sessions.parent_session_id` links them and `is_subagent` is set on all their
  events.
- Account discovery from `~/.codex/auth.json` when it carries an account or
  email field; otherwise a stable hash of the config directory with a label
  the user can edit.

### 5.4 Project and branch normalization

`project_key` is derived from `cwd`: worktrees under `.claude/worktrees/<n>/`
or with a `.git` file pointing at a `commondir` fold into the parent
repository (upstream #154 and #179). `project_name` is the last two path
components as in v1. Both are computed in `core` so the CLI, server, and
tests agree.

### 5.5 Model normalization

`model_raw` is stored verbatim. `model` is normalized by `core.models`:
date suffixes stripped (`claude-opus-4-7-20260215` → `claude-opus-4-7`),
provider-specific aliases folded, and a `family` (`opus`, `sonnet`, `gpt-5`,
...) attached for the pricing family fallback and for chart grouping.

---

## 6. Collector

### 6.1 Install and run

- `uv tool install <name>-collector` or `pipx install <name>-collector`.
- `<name>-collector enroll --server https://host --code XXXX-XXXX` performs
  one-time device registration and writes the config.
- `<name>-collector install-service` writes and enables a systemd user unit
  (Linux) or a launchd agent (macOS). Windows users run it from Task
  Scheduler or a terminal; a service wrapper is post-2.0.
- `<name>-collector run` is the foreground loop; `doctor` validates config
  and sources and prints what would be sent without sending it;
  `rescan` forces a full re-read locally.
- Docker: `deploy/Dockerfile.collector` with the provider directories mounted
  read-only.

### 6.2 Configuration

`~/.config/<name>/collector.toml`:

```toml
server_url = "https://usage.example.net"
device_token_file = "~/.config/<name>/device.token"

[[sources]]
provider = "claude_code"
root = "~/.claude"                      # default, auto-discovered

[[sources]]
provider = "claude_code"
root = "~/.claude-work"                 # second account via CLAUDE_CONFIG_DIR

[[sources]]
provider = "codex_cli"
root = "~/.codex"
```

On first run with no `[[sources]]`, the collector runs every adapter's
`discover_sources` and writes what it found, so the common case needs no
editing.

### 6.3 Watch loop

- **Native notifications first.** `watchfiles` (inotify on Linux, FSEvents on
  macOS, ReadDirectoryChangesW on Windows). The process sleeps in the kernel
  until a watched file changes; idle cost is zero.
- **Polling fallback**, chosen automatically per root when notifications fail
  or the path is on a filesystem known to be unreliable (Docker bind mounts on
  macOS and Windows, NFS, SMB). Adaptive interval: 2 s while any file in the
  root grew in the last 30 s, decaying by doubling to 60 s when idle. Only a
  **hot set** (files modified in the last hour) is stat'd on the fast
  interval; cold files are checked on the slow one.
- **Byte offsets, not line counts.** State per file: path, size, mtime,
  offset, inode or file id. Truncation or inode change resets to zero.
  State persists in a small SQLite file next to the config so restarts do not
  re-ship history.
- **Prefilter before parse.** Each adapter provides a cheap substring test so
  lines that cannot carry usage (most of them) are never JSON-decoded.
- **Coalesced batches.** Events are debounced for 2 s and sent in one gzip
  batch capped at 5,000 events; larger backlogs stream as consecutive
  batches. A batch is retried with exponential backoff on network failure and
  is idempotent on the server by `batch_id`.
- **Heartbeat** every 30 s (configurable) with collector version, per-source
  status, and last error. The reply may carry commands (`rescan` with an
  optional source filter) and config hints (additional roots to watch).

### 6.4 Performance budgets

Checked by a benchmark test in CI on Linux; numbers are hard limits, not
aspirations.

| Scenario | Budget |
|---|---|
| Idle with 10,000 tracked files, native notifications | ≤ 0.1% CPU (one core), ≤ 40 MB RSS |
| Idle, polling fallback | ≤ 0.5% CPU, one stat per hot file per interval |
| Initial scan of a 500 MB corpus | ≤ 30 s wall, ≤ 150 MB RSS |
| Active session (a file growing at 50 lines/s) | ≤ 1 request every 2 s, ≤ 2% CPU |

### 6.5 Privacy contract

`docs/PRIVACY.md` lists exactly which fields leave a device. `strip_raw`
removes message content, tool inputs and outputs, file paths inside tool
calls, and environment details; it keeps ids, timestamps, usage, model,
`cwd`, git branch, and unknown top-level scalar fields. A test asserts that
no fixture record, after stripping, contains any string longer than 200
characters or any field named `content`, `text`, `input`, `output`, or
`arguments`. `doctor --show-sample` prints stripped records so users can
verify.

---

## 7. Server

### 7.1 Ingest API (`/ingest/v1/`)

Authenticated with the device bearer token except `register`.

| Endpoint | Purpose |
|---|---|
| `POST /register` | Body: enrollment code, hostname, platform, collector version. Returns device id and token. Enrollment codes are minted in the UI or by `<name>-server enroll-code`, single-use, expire in 15 minutes. |
| `POST /events` | Body: `batch_id`, `source` (provider, root, account info), `file_path`, offsets, `sessions[]`, `agents[]`, `events[]`. Upserts sessions and agents, inserts events (greatest-totals-win on key conflict), writes the receipt, schedules a rollup for affected days. Returns counts. |
| `POST /heartbeat` | Body: version, sources with status. Returns `commands[]` and `config_hints`. Updates `devices.last_seen_at`. |

Schemas are Pydantic models in `core.protocol` and versioned by the path
prefix. A server refuses batches from adapters newer than it knows; the
collector reports this in its status so the UI can say "update the server".

### 7.2 Public API (`/api/v1/`)

Authenticated with the owner session cookie or a personal API token.

- `GET /overview`: the glance numbers for the current filter.
- `GET /rollups?group_by=day|model|account|device|project&...filters`
- `GET /sessions`, `GET /sessions/{id}` (with events), `GET /sessions/{id}/agents`
- `GET /devices`, `PATCH /devices/{id}`, `POST /devices/{id}/rescan`, `DELETE /devices/{id}`
- `GET /accounts`, `PATCH /accounts/{id}` (label, color, hidden)
- `GET /sources`, `PATCH /sources/{id}` (enabled)
- `GET /pricing`, `POST /pricing` (user override rows), `DELETE /pricing/{id}`
- `GET /settings/{namespace}`, `PUT /settings/{namespace}/{key}`
- `POST /jobs/reprocess`, `GET /jobs`, `GET /jobs/{id}`
- `GET /export?format=csv|json&...filters`
- `GET /enroll-codes`, `POST /enroll-codes`
- `GET /health`, `GET /version`, `GET /openapi.json`, `/docs`

**Filter grammar**, identical on every list endpoint and mirrored in the
frontend filter bar: `from`, `to` (dates, inclusive, in the user's
configured timezone), `provider`, `account`, `device`, `project`, `model`,
`subagents` (`include`, `exclude`, `only`), `hidden` (`exclude` by
default). Multi-valued parameters repeat.

### 7.3 Background jobs

A single in-process worker (asyncio task) drains the `jobs` table. Kinds in
v2.0: `rollup` (a set of days for a source), `reprocess` (re-run adapters over
`raw` and rebuild rollups for a date range or everything), `import_v1`,
`prune` (raw-record retention, if enabled). No Redis or Celery; Postgres users
who run several server replicas take a row lock on the job.

### 7.4 Auth

- Owner login: password set on first run (`<name>-server init` or the
  first-visit setup page), stored as argon2, session cookie with `SameSite=Lax`.
- Collectors: per-device bearer token, stored hashed.
- CLI and integrations: personal API tokens minted in Settings.
- CSRF: state-changing browser requests carry a header the SPA sets; cookie
  auth alone is rejected for `POST`, `PATCH`, `DELETE`.
- Strict CSP; no CDN assets (Chart library ships in the bundle, fixing the
  v1 CDN dependency).
- Exposure guidance in `docs/DEPLOYMENT.md`: bind to localhost or a
  Tailscale interface, or put a reverse proxy with TLS in front. The server
  does not terminate TLS itself in v2.0.

### 7.5 Storage notes

- SQLite: WAL mode, `busy_timeout`, one writer (the ingest path is serialized
  through the job worker's write queue so collectors never see "database is
  locked").
- Postgres: connection string via `DATABASE_URL`; Alembic migrations are the
  same files. CI runs the suite on both.
- README documents the trade-off: SQLite for one owner and a handful of
  devices, single container, trivial backup; Postgres for many collectors,
  multiple server replicas, or when the DB should live elsewhere.

### 7.6 Importer

`<name>-server import-v1 ~/.claude/usage.db [--device NAME] [--account LABEL]`
creates (or reuses) a synthetic device named after the host and a Claude
account, maps v1 `turns` rows to `usage_events` (`event_key` from
`message_id`, else the v1 row id prefixed `v1:`), `sessions` to `sessions`,
`agents` to `agents`, and schedules a rollup. Re-runnable and idempotent.

---

## 8. Pricing engine

`core.pricing` resolves a rate for (`provider`, `model`, `occurred_at`):

1. User override rows (`source = 'user'`) whose `valid_from ≤ occurred_at < valid_to`.
2. Builtin rows, `exact` match, then `prefix`, then `family`.
3. No match → cost is null and the UI shows "n/a", exactly as v1 does for
   local and unknown models.

Cache writes are billed by TTL as in v1 (5-minute and 1-hour columns).
Reasoning tokens are billed at the output rate unless a row sets a
`reasoning_per_mtok`. Cost is stored in `rollups_daily` as integer
micro-dollars along with the `pricing_version` hash, so a changed price
triggers a reprocess of exactly the days it affects. This resolves fork issue
#1 (effective-dated pricing) and removes the v1 duplication of the price table
between Python and JavaScript: the frontend never computes cost.

Builtin rows are seeded from a YAML file in `core` with a changelog comment
per row, so a price update is a reviewable diff.

---

## 9. Dashboard

### 9.1 Stack

Vite, React 19, TypeScript strict. TanStack Query for data, TanStack Table
for grids, TanStack Router for URL state, ECharts for charts (canvas, handles
large series, bundled locally), Tailwind with a small headless component kit
(Radix primitives). Vitest and Testing Library for tests, Playwright for a
handful of end-to-end flows against a seeded server.

### 9.2 Design principles

Clean and minimal, dense but not cluttered, numbers readable at a glance.
Light and dark themes from one token set. Keyboard reachable. Every chart has
a tabular alternative for accessibility and for copy-out. No CDN assets.
Chart palette and semantics follow a documented design-system file in
`web/src/design/` so contributors do not invent colors.

### 9.3 Widget system

A widget is a registered React component with a manifest: id, title, the
data query it needs (expressed against `/api/v1/rollups` or `/sessions`),
size constraints, and settings schema. A dashboard is a JSON layout
(`settings` key `dashboard.layout`) listing widget instances in a grid. v2.0
ships one default layout and no layout editor; the model exists so that
post-2.0 custom dashboards are a UI feature over data that is already
persisted per user.

Initial widget set: stat tiles (today, this week, this month, all time; cost
and tokens), daily tokens and cost chart, hourly activity heatmap, by-model,
by-account, by-device, by-project and branch, cache hit rate, sessions table
with drill-down, subagent dispatch table and by-type chart, fleet strip
(devices with last-seen and status), accounts strip (label, plan, share of
spend).

### 9.4 Filters and views

The global filter bar implements the [§7.2](#72-public-api-apiv1) grammar
and is stored in the URL, so any view is bookmarkable and shareable within
the owner's session. Named views (`settings` key `dashboard.views`) save a
filter set plus a layout id. Accounts and devices can be toggled from the bar
in one click; hidden accounts stay out unless explicitly included.

### 9.5 Settings UI

Devices (rename, rescan, remove, enrollment codes), accounts (label, color,
hide), sources (enable), pricing overrides, display (currency, timezone,
default range, theme), tokens (personal API tokens), data (retention,
reprocess, export, import status), about (versions of server and each
collector, update check).

---

## 10. Configuration

Two layers with a clear split:

- **Operator config** (things that must exist before the DB is reachable or
  that affect security): environment variables with a `<NAME>_` prefix, or a
  TOML file pointed at by `<NAME>_CONFIG`. Keys: `DATABASE_URL`,
  `BIND_HOST`, `BIND_PORT`, `DATA_DIR`, `SECRET_KEY`, `LOG_LEVEL`,
  `TRUST_PROXY`.
- **User settings** (everything else): the `settings` table, edited in the
  UI or with `<name> config get|set <namespace> <key>`.

Defaults follow the XDG spec on Linux (`~/.local/share/<name>` for data,
`~/.config/<name>` for config) and `/data` inside Docker.

---

## 11. Thin CLI

`<name>` (the server package's console script) keeps the v1 muscle memory as
API clients: `today`, `week`, `stats` accept the same filter flags as the API
and print the same tables v1 did, plus `sessions`, `devices`, `accounts`,
`config`, `export`. `<name> serve` runs the server; `<name> import-v1`,
`init`, `enroll-code`, `backup`, `restore`, `migrate` are operator commands.

---

## 12. Testing strategy

- **Fixture corpora** under `tests/fixtures/<provider>/`: anonymized real logs
  (ids re-keyed, content replaced, usage numbers kept). Every adapter test and
  the privacy test run over them. Contributors add a fixture when they report
  a parser bug.
- **Core**: pure unit tests, no I/O beyond fixtures.
- **Server**: FastAPI test client against a temporary SQLite file and, in CI,
  a Postgres service container. Ingest idempotency, greatest-totals upsert,
  rollup correctness against a brute-force sum, importer round-trip from a v1
  DB fixture.
- **Collector**: watch loop tested with a temp directory and synthetic
  appends; the benchmark test enforces [§6.4](#64-performance-budgets) on
  Linux CI.
- **Web**: component tests for widgets with mocked queries; Playwright smoke
  test for login, filter, drill-down, settings save.
- **Contract**: the OpenAPI schema is committed; a test fails if the server's
  generated schema drifts from it, and the frontend client is generated from
  it.
- Test isolation rules from v1 `TESTING.md` carry over: never touch the
  user's real data directories.

---

## 13. Migration from v1

1. Install the server and run `import-v1` on each machine's `usage.db` (or
   copy the files to the server host). History appears under a synthetic
   device per file.
2. Install the collector on each machine and enroll it. The Claude adapter
   re-reads local transcripts; the dedupe key matches the imported
   `message_id`s, so overlap is harmless.
3. Rename or merge devices in Settings if a synthetic import device and a
   real collector device refer to the same machine (post-import merge is a
   `PATCH /devices/{id}` with `merge_into`).

`docs/MIGRATING-FROM-V1.md` covers this with the exact commands. The v1 code
stays in `legacy/` through the v2.0 pre-releases and is deleted in the
v2.0.0 release commit.

---

## 14. Repo workflow and conventions revamp

This replaces `CONVENTIONS.md`, `RELEASING.md`'s branch model, the `/triage`
command, and the parts of `AGENTS.md` that describe the upstream
relationship.

### 14.1 Branching

- `main` is the only long-lived branch. `develop` is deleted in M0.
- Every change is a pull request from a short-lived branch (`feat/...`,
  `fix/...`, `docs/...`, `chore/...`). Squash-merge by default; `--no-ff`
  merge when preserving a contributor's commits matters (see 14.4).
- `main` is protected: CI required, at least one approving review. An agent
  review counts when a human owner merges.

### 14.2 CI

`tests.yml` runs on every PR and push to `main`: `ruff check` and
`ruff format --check`; Python tests on 3.11, 3.12, 3.13 against SQLite and
Postgres; `pnpm typecheck`, `pnpm test`, `pnpm lint`; OpenAPI drift check;
Docker builds for both images. `images.yml` pushes both images to
`ghcr.io/<org>/<name>-server` and `-collector` tagged with the branch name or
`pr-<n>` on every push, and with the version plus `latest` on release.

### 14.3 Run any branch

`docs/DEVELOPMENT.md` documents two paths and both are exercised by CI:

- **Local dev loop**: `make dev` starts the server with auto-reload on a
  temp SQLite file and the Vite dev server with proxying; `make dev-collector`
  runs a collector against it with the local provider directories. First run
  seeds an owner and prints the login.
- **Run a branch as a real server**: `docker run ghcr.io/<org>/<name>-server:pr-123`
  (or the branch tag) with a volume, or `deploy/compose.yaml` with
  `IMAGE_TAG=pr-123`. Reviewers and contributors verify UI changes this way
  without a local toolchain.

### 14.4 Contributor credit

Carried over from v1 and kept in `CONTRIBUTING.md`: merge with `--no-ff` or
cherry-pick to keep the author's commits; use `Co-Authored-By` when applying
hunks by hand; follow-ups are separate commits; thank duplicates. The GitHub
comment signature rule and the Codex sign-off rule are removed. Comments
posted by an agent on the maintainer's behalf say so in one plain line.

### 14.5 Releases

- Versions follow SemVer. One version string lives in the workspace
  `pyproject.toml`; every package and the web bundle read it. A parity test
  guards the CHANGELOG heading as today.
- A release PR titled `release: vX.Y.Z` bumps the version, finalizes the
  CHANGELOG heading, and updates the Homebrew formula via the existing
  `bump-formula.sh` mechanics adapted to the new package name. Merging it
  triggers `tag-on-merge.yml`, which tags, publishes the GitHub Release, and
  pushes versioned images.
- Pre-releases (`v2.0.0-beta.1`) are allowed during the v2 build-out; the tag
  workflow's regex is extended to accept them.

### 14.6 Issues, milestones, and labels

- GitHub Issues with templates: bug (with a "attach a stripped sample" step
  that points at `doctor --show-sample`), parser mismatch, feature, provider
  request.
- Milestones `v2.0.0` through the roadmap's M0 to M5 plus `post-2.0`.
- Labels by area (`core`, `adapter:claude`, `adapter:codex`, `collector`,
  `server`, `web`, `docs`, `deploy`) and by kind (`bug`, `feature`,
  `good first issue`, `needs-fixture`).
- `BACKLOG.md` is converted into issues in M0 and then deleted.
- `SECURITY.md` names the private vulnerability reporting channel, enabled on
  the repo in M0.

### 14.7 Agent guidance

`AGENTS.md` stays as the entry point for coding agents, rewritten for the
monorepo: package map, commands, and pointers to `ARCHITECTURE.md`,
`TESTING.md`, `CONTRIBUTING.md`, `PRIVACY.md`. The naming note about "Claude
Code the product versus the agent reading this" stays.

---

## 15. Roadmap to v2.0

Milestones are ordered by dependency. Each gets an implementation plan and a
GitHub milestone. Estimated scope is relative (S, M, L) rather than dated.

| # | Milestone | Scope | Delivers | Done when |
|---|-----------|-------|----------|-----------|
| M0 | Repo revamp | M | New name and layout, `legacy/` move, trunk-based workflow, CI matrix, per-ref images, `CONTRIBUTING`/`DEVELOPMENT`/`SECURITY`/`PRIVACY` docs, issue templates, milestones, `BACKLOG.md` → issues, `develop` deleted, `/triage` removed. | A PR to `main` builds both images and a contributor can run `docker run ...:pr-N`. |
| M1 | Core | L | `UsageEvent` and protocol schemas, adapter interface, Claude adapter with fixture corpus and carried-over invariants, Codex adapter with fixture corpus, model normalization, pricing engine with seeded effective-dated rates, privacy stripping and its test. | Both adapters parse their corpora with byte-offset resume; pricing resolves every fixture model; privacy test green. |
| M2 | Server | L | Models and migrations on SQLite and Postgres, ingest API, heartbeat and rescan command, job worker with rollups and reprocess, public API with filter grammar, owner auth and API tokens, settings, v1 importer, OpenAPI contract test, server image and compose files. | Ingesting a fixture batch twice yields identical rollups; importer round-trips a v1 DB; suite green on both databases. |
| M3 | Collector | M | Watch loop with native notifications and adaptive polling, offset state, prefilter, batching and retry, enroll and heartbeat, source auto-discovery, multi-config-dir accounts, `doctor`, service installers, collector image, benchmark test. | Budgets in §6.4 pass in CI; a fresh enroll on the dev VM ships both providers' logs end to end. |
| M4 | Web | L | SPA scaffold, design tokens and themes, generated API client, widget registry and default layout, filter bar with URL state, all initial widgets, session drill-down, fleet and accounts views, settings UI, Playwright smoke. | Feature parity with the v1 dashboard plus fleet and accounts views, reviewed on a `pr-N` image. |
| M5 | Release | S | Thin CLI, `MIGRATING-FROM-V1.md`, README rewrite with the SQLite/Postgres trade-off, Homebrew formula, `legacy/` deleted, `v2.0.0`. | Tag published, images on `latest`, brew and uv installs verified on a clean machine. |

M1 through M3 can proceed in parallel once M0 lands, since they meet at the
protocol schema defined in M1's first task. M4 depends on M2's API. Beta
tags are cut at the end of M3 (`v2.0.0-beta.1`, headless) and M4
(`-beta.2`, full UI).

---

## 16. Post-2.0 outlook and candidate ideas

Listed so v2.0 decisions leave room for them. None are commitments.

- **Custom dashboards.** Layout editor over the widget system; per-user
  layouts; shareable layout JSON.
- **More adapters.** Gemini CLI, OpenCode, Cursor, GitHub Copilot CLI. Each
  adds an adapter, a fixture corpus, and pricing rows, nothing else.
- **Multi-user.** `owners` becomes `users`; ownership filters in the API;
  admin role; invitation flow.
- **Plan windows.** Codex already logs rate-limit usage and reset times per
  session; surface "x% of the weekly window used, resets Tuesday" per account.
  For Claude this needs the usage endpoint that upstream PR #149 targeted; in
  this architecture it becomes an opt-in collector feature (`plan_windows =
  true` per source) so the OAuth token never leaves the device.
- **Budgets and alerts.** Daily or monthly spend thresholds per account with
  webhook, ntfy, or email notification from the job worker.
- **Effort and context dimensions.** Charts by reasoning effort and context
  pressure using the `effort`, `reasoning_tokens`, and `context_window`
  columns that v2.0 already stores.
- **Session health.** Compaction counts, session length, and tokens per
  turn to flag sessions that should have been restarted.
- **Prometheus `/metrics`** for people who already run Grafana.
- **Retention and backup automation.** Scheduled `backup` to a path or S3
  bucket; raw-record pruning while keeping rollups.
- **Windows service wrapper** for the collector.
- **Anonymous sharing.** Export a screenshot-safe view with device and
  account labels replaced.

---

## 17. Open decisions

**Product name.** Must be provider-neutral and free on PyPI and as a GitHub
repo. Checked on 2026-09-14:

| Name | PyPI | GitHub repos with that name |
|---|---|---|
| fleetmeter | free | none |
| codespend | free | none |
| usagedeck | free | a few small unrelated repos |
| tokenpulse | free | several unrelated repos |
| tokenwatch, tokentally, agentmeter, tokenscope, tokenledger, aimeter, agentspend | taken | taken |

Recommendation: `fleetmeter`, because it names the concept (a meter over a
fleet of devices and accounts) rather than one metric, and it reads well as
`fleetmeter serve` and `fleetmeter-collector`. `codespend` is the fallback if
a narrower, spend-focused identity is preferred. The decision closes M0's
first task; every `<name>` in this document resolves to it.

---

## Appendix A: what carries over from the v1 backlog

Upstream items that this design absorbs, so the M0 issue conversion can
reference them:

| Upstream | Disposition in v2 |
|---|---|
| #154, #179 worktree folding | `core` project normalization (§5.4) |
| #157, #161 stale dashboard | Moot: collectors stream continuously |
| #168, #171 port fallback and autostart | Server binds a configurable port; collector ships service installers |
| #169 partial-stream freeze | Greatest-totals upsert (§4.3) |
| #176 async subagent type | Claude adapter (§5.2) |
| #172 hourly label overlap | New chart stack |
| #170, #158 light theme | Design tokens with both themes (§9.2) |
| #159 zero-usage days | Rollup query fills gaps server-side |
| #145 API vs subscription clarity | Accounts carry `plan_type`; UI labels cost as "API-equivalent" for subscription accounts |
| #149 usage API | Post-2.0 opt-in plan windows (§16) |
| #156 i18n | Not planned; revisit post-2.0 if asked |
| #167 security disclosure | `SECURITY.md` with private reporting (§14.6); `/triage` removed |
| Fork #1 effective-dated pricing | Pricing engine (§8) |

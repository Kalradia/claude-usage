# AGENTS.md

Guidance for any coding agent (Codex, Claude Code, etc.) working on this repository.

> **Naming note.** This project *analyzes* Claude Code's local usage logs, so "Claude Code" below always refers to that product (the source of the JSONL data) — not to the agent reading this file. The agent working on the codebase is referred to as "the coding agent" or just "you".

## Project shape

Three Python files, stdlib only, no `pip install` step. Python 3.8+.

- [scanner.py](scanner.py) — parses Claude Code JSONL transcripts into a SQLite DB at `~/.claude/usage.db`.
- [cli.py](cli.py) — terminal commands (`scan` / `today` / `week` / `stats` / `dashboard`).
- [dashboard.py](dashboard.py) — single-file `http.server` serving an embedded HTML/JS SPA on `localhost:8080`.

Use `python` on Windows, `python3` on macOS/Linux. Both work the same.

## Common commands

```
python cli.py scan                  # incremental scan (fast on re-run)
python cli.py today                 # today's usage by model
python cli.py week                  # last 7 days, per-day + by-model
python cli.py stats                 # all-time stats
python cli.py dashboard                          # scan + open http://localhost:8080
python cli.py dashboard --host 0.0.0.0 --port 9000
python cli.py scan --projects-dir PATH           # scan a custom transcripts dir
# or via env vars:
HOST=0.0.0.0 PORT=9000 python cli.py dashboard

python -m unittest discover -s tests -v             # full test suite (CI runs this)
python -m unittest tests.test_scanner -v            # one file
python -m unittest tests.test_scanner.TestProjectNameFromCwd.test_windows_path  # one test
```

CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) runs the suite on Python 3.9 / 3.11 / 3.12 against `main` and PRs.

## Further reading

Load these only when the task touches their area — each covers non-obvious details you'll need there:

- [ARCHITECTURE.md](ARCHITECTURE.md) — data flow, SQLite schema, dedupe/session invariants, cost calculation, dashboard server internals. Read before editing `scanner.py`, cost-calc code in `cli.py`/`dashboard.py`, or the dashboard server.
- [TESTING.md](TESTING.md) — test isolation gotchas. Read before writing or modifying tests.
- [CONVENTIONS.md](CONVENTIONS.md) — preserving contributor credit when merging/closing PRs, GitHub comment signing rules. Read before merging a PR or posting a GitHub comment.
- [RELEASING.md](RELEASING.md) — release flow, CHANGELOG heading format, Homebrew formula bump mechanics, weekly triage routine. Read before cutting a release or editing `CHANGELOG.md`/`Formula/claude-usage.rb`.

This applies to all agents working on this repo, not just Claude Code.

"""Tests for the dashboard's per-session main-agent-vs-subagent cache/token split."""

import re
import tempfile
import unittest
from pathlib import Path

from scanner import get_db, init_db, insert_turns, upsert_agents, upsert_sessions
import dashboard
from dashboard import HTML_TEMPLATE


def _turn(session_id, message_id, model="claude-opus-4-8",
          inp=100, out=50, cache_read=0, cache_creation=0,
          is_subagent=0, agent_id=None,
          timestamp="2026-04-08T10:00:00Z"):
    return {
        "session_id": session_id, "timestamp": timestamp, "model": model,
        "input_tokens": inp, "output_tokens": out,
        "cache_read_tokens": cache_read, "cache_creation_tokens": cache_creation,
        "tool_name": None, "cwd": "/home/user/proj",
        "message_id": message_id, "is_subagent": is_subagent, "agent_id": agent_id,
    }


class TestSessionAgentBreakdown(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mkdtemp()) / "usage.db"
        conn = get_db(self.db_path)
        init_db(conn)
        upsert_sessions(conn, [{
            "session_id": "sess-1", "project_name": "user/proj",
            "first_timestamp": "2026-04-08T10:00:00Z",
            "last_timestamp": "2026-04-08T10:30:00Z",
            "git_branch": "main", "model": "claude-opus-4-8",
            "total_input_tokens": 600, "total_output_tokens": 170,
            "total_cache_read": 900, "total_cache_creation": 50, "turn_count": 3,
        }, {
            "session_id": "sess-2", "project_name": "user/proj",
            "first_timestamp": "2026-04-08T11:00:00Z",
            "last_timestamp": "2026-04-08T11:10:00Z",
            "git_branch": "main", "model": "claude-opus-4-8",
            "total_input_tokens": 100, "total_output_tokens": 50,
            "total_cache_read": 0, "total_cache_creation": 0, "turn_count": 1,
        }])
        insert_turns(conn, [
            _turn("sess-1", "m-main", inp=100, out=50, cache_read=200, cache_creation=10,
                  is_subagent=0),
            _turn("sess-1", "m-sub1", inp=300, out=80, cache_read=500, cache_creation=30,
                  is_subagent=1, agent_id="agent-1"),
            _turn("sess-1", "m-sub2", inp=200, out=40, cache_read=200, cache_creation=10,
                  is_subagent=1, agent_id="agent-1"),
            _turn("sess-2", "m-solo", inp=100, out=50, is_subagent=0),
        ])
        upsert_agents(conn, [{
            "agent_id": "agent-1", "agent_type": "Explore",
            "dispatched_in_session": "sess-1", "completed_at": "2026-04-08T10:20:00Z",
            "status": "completed", "total_tokens": 880,
            "total_duration_ms": 4200, "tool_use_count": 5,
        }])
        conn.commit()
        conn.close()

    def test_session_has_by_agent_key(self):
        d = dashboard.get_dashboard_data(self.db_path)
        sess1 = next(s for s in d["sessions_all"] if s["session_id"] == "sess-1")
        self.assertIn("by_agent", sess1)

    def test_by_agent_splits_main_and_subagent_rows(self):
        d = dashboard.get_dashboard_data(self.db_path)
        sess1 = next(s for s in d["sessions_all"] if s["session_id"] == "sess-1")
        by_agent = {row["is_subagent"]: row for row in sess1["by_agent"]}

        main = by_agent[0]
        self.assertEqual(main["input"], 100)
        self.assertEqual(main["output"], 50)
        self.assertEqual(main["cache_read"], 200)
        self.assertEqual(main["cache_creation"], 10)

        sub = by_agent[1]
        self.assertEqual(sub["input"], 500)
        self.assertEqual(sub["output"], 120)
        self.assertEqual(sub["cache_read"], 700)
        self.assertEqual(sub["cache_creation"], 40)

    def test_session_without_subagents_has_only_main_row(self):
        d = dashboard.get_dashboard_data(self.db_path)
        sess2 = next(s for s in d["sessions_all"] if s["session_id"] == "sess-2")
        self.assertEqual(len(sess2["by_agent"]), 1)
        self.assertEqual(sess2["by_agent"][0]["is_subagent"], 0)

    def test_top_dispatches_carries_parent_session(self):
        """The client links a dispatch back to its conversation to show
        per-session subagent detail; without parent_session it can't."""
        d = dashboard.get_dashboard_data(self.db_path)
        dispatch = next(r for r in d["top_dispatches"] if r["agent_id"] == "agent-1")
        self.assertEqual(dispatch["parent_session"], "sess-1")


class TestCacheHitRateUI(unittest.TestCase):
    """Structural checks on the embedded JS/HTML (same convention as
    TestHTMLTemplate in test_dashboard.py — no JS runtime in this stdlib-only
    project, so behavior is verified by source-presence assertions)."""

    def test_hit_rate_helpers_exist(self):
        self.assertIn("function hitRate(", HTML_TEMPLATE)
        self.assertIn("function fmtPct(", HTML_TEMPLATE)

    def test_overview_stat_shows_cache_hit_percentage(self):
        self.assertIn("Cache Hit %", HTML_TEMPLATE)
        self.assertIn("hitRate(t.input, t.cache_read, t.cache_creation)", HTML_TEMPLATE)

    def test_cache_trend_chart_present_and_wired(self):
        self.assertIn('id="chart-cache"', HTML_TEMPLATE)
        self.assertIn("function renderCacheChart(", HTML_TEMPLATE)
        self.assertIn("renderCacheChart(daily)", HTML_TEMPLATE)

    def test_sessions_table_has_sortable_hit_rate_column(self):
        self.assertIn("setSessionSort('hit_rate')", HTML_TEMPLATE)
        self.assertIn("'hit_rate'", HTML_TEMPLATE)

    def test_sessions_rows_are_clickable_for_detail_expand(self):
        self.assertIn("data-session-id", HTML_TEMPLATE)
        self.assertIn("function toggleSessionDetail(", HTML_TEMPLATE)
        self.assertIn("function renderSessionAgentDetail(", HTML_TEMPLATE)
        # Detail view must be able to isolate a session's own subagent dispatches.
        self.assertIn("d.parent_session === s.session_id", HTML_TEMPLATE)
        # Splits main-agent vs. subagent totals via the by_agent field (#N).
        self.assertIn("s.by_agent", HTML_TEMPLATE)

    def test_dispatches_table_has_hit_rate_column(self):
        self.assertIn('<th>Cache Hit %</th>', HTML_TEMPLATE)

    def test_subagent_chart_tooltip_reports_hit_rate(self):
        # renderSubagentChart's tooltip footer callback
        footer_match = re.search(r"renderSubagentChart\(byType\) \{.*?\n\}", HTML_TEMPLATE, re.S)
        self.assertIsNotNone(footer_match)
        self.assertIn("hitRate(", footer_match.group(0))

    def test_csv_exports_include_hit_rate(self):
        sessions_csv = re.search(r"function exportSessionsCSV\(\).*?\n\}", HTML_TEMPLATE, re.S)
        dispatches_csv = re.search(r"function exportDispatchesCSV\(\).*?\n\}", HTML_TEMPLATE, re.S)
        self.assertIn("Cache Hit %", sessions_csv.group(0))
        self.assertIn("Cache Hit %", dispatches_csv.group(0))


if __name__ == "__main__":
    unittest.main()

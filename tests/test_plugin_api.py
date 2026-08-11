from __future__ import annotations

import importlib.util
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "hermes-plugin" / "dashboard" / "plugin_api.py"


def load_module():
    spec = importlib.util.spec_from_file_location("quota_orb_plugin_api", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccountSnapshotTests(unittest.TestCase):
    def test_serialize_account_snapshot_reports_remaining_and_iso_reset(self):
        module = load_module()

        class Window:
            label = "Session"
            used_percent = 23.25
            reset_at = datetime(2026, 8, 10, 18, 30, tzinfo=timezone.utc)
            detail = None

        class Snapshot:
            provider = "openai-codex"
            source = "usage_api"
            fetched_at = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
            title = "Account limits"
            plan = "Plus"
            windows = (Window(),)
            details = ()
            unavailable_reason = None
            available = True

        result = module.serialize_account_snapshot(Snapshot())

        self.assertEqual(
            result,
            {
                "available": True,
                "provider": "openai-codex",
                "source": "usage_api",
                "fetched_at": "2026-08-10T12:00:00+00:00",
                "title": "Account limits",
                "plan": "Plus",
                "windows": [
                    {
                        "label": "Session",
                        "used_percent": 23.25,
                        "remaining_percent": 76.75,
                        "reset_at": "2026-08-10T18:30:00+00:00",
                        "detail": None,
                    }
                ],
                "details": [],
                "unavailable_reason": None,
            },
        )

    def test_serialize_account_snapshot_accepts_only_literal_true_as_available(self):
        module = load_module()

        class Window:
            label = "Session"
            used_percent = 40
            reset_at = None
            detail = "provider supplied"

        expected_window = {
            "label": "Session",
            "used_percent": 40.0,
            "remaining_percent": 60.0,
            "reset_at": None,
            "detail": "provider supplied",
        }
        for supplied, expected in (
            ("false", False),
            (1, False),
            ({}, False),
            (["unexpected"], False),
            (True, True),
        ):
            with self.subTest(available=supplied):
                snapshot = type(
                    "Snapshot",
                    (),
                    {
                        "available": supplied,
                        "provider": "openai-codex",
                        "source": "usage_api",
                        "fetched_at": None,
                        "title": "Account limits",
                        "plan": None,
                        "windows": (Window(),),
                        "details": (),
                        "unavailable_reason": None,
                    },
                )()

                result = module.serialize_account_snapshot(snapshot)

                self.assertIs(result["available"], expected)
                self.assertEqual(result["windows"], [expected_window])

    def test_plugin_exports_read_only_snapshot_route(self):
        module = load_module()
        routes = {(route.path, tuple(sorted(route.methods or ()))) for route in module.router.routes}
        self.assertIn(("/snapshot", ("GET",)), routes)


class DailyUsageTests(unittest.TestCase):
    def test_aggregate_daily_usage_sums_tokens_and_groups_models(self):
        module = load_module()
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """
            CREATE TABLE sessions (
                started_at REAL,
                model TEXT,
                billing_provider TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                reasoning_tokens INTEGER,
                api_call_count INTEGER
            )
            """
        )
        db.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (100.0, "gpt-5.6", "openai-codex", 100, 20, 30, 5, 2),
                (200.0, "gpt-5.6", "openai-codex", 50, 10, 4, 2, 1),
                (300.0, "claude", "anthropic", 40, 8, 0, 0, 1),
                (900.0, "outside", "openai-codex", 999, 999, 0, 0, 9),
            ],
        )

        result = module.aggregate_daily_usage(db, start_ts=0.0, end_ts=500.0)

        self.assertEqual(result["input_tokens"], 190)
        self.assertEqual(result["output_tokens"], 38)
        self.assertEqual(result["cache_read_tokens"], 34)
        self.assertEqual(result["reasoning_tokens"], 7)
        self.assertEqual(result["total_tokens"], 228)
        self.assertEqual(result["api_calls"], 4)
        self.assertEqual(result["sessions"], 3)
        self.assertEqual(result["provider"], "openai-codex")
        self.assertEqual(result["by_model"][0]["model"], "gpt-5.6")
        self.assertEqual(result["by_model"][0]["total_tokens"], 180)
        self.assertEqual([item["provider"] for item in result["by_provider"]], ["openai-codex", "anthropic"])
        self.assertEqual(result["by_provider"][0]["total_tokens"], 180)
        self.assertEqual(result["by_provider"][0]["models"][0]["model"], "gpt-5.6")
        self.assertEqual(result["by_provider"][1]["models"][0]["model"], "claude")

    def test_build_snapshot_keeps_daily_totals_when_quota_is_unavailable(self):
        module = load_module()
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            """
            CREATE TABLE sessions (
                started_at REAL,
                model TEXT,
                billing_provider TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                reasoning_tokens INTEGER,
                api_call_count INTEGER
            )
            """
        )
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now.timestamp(), "gpt-5.6", "openai-codex", 100, 25, 0, 0, 1),
        )

        result = module.build_snapshot(
            db,
            provider="openai-codex",
            now=now,
            quota_fetcher=lambda provider: None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["today"]["total_tokens"], 125)
        self.assertFalse(result["quota"]["available"])
        self.assertEqual(result["quota"]["provider"], "openai-codex")
        self.assertFalse(result["tokenBilling"]["available"])
        self.assertIsNone(result["tokenBilling"]["cost"])
        self.assertIn("not an invoice", result["tokenBilling"]["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()

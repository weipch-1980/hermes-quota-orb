from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import ProxyHandler


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.sources import (
    HermesHttpSource,
    JsonSnapshotSource,
    _fetch_loopback_json,
    source_from_environment,
    translate_hermes_snapshot,
)


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class JsonSnapshotSourceTests(unittest.TestCase):
    def test_explicit_json_snapshot_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "platform": "claude",
                        "provider": "Anthropic API",
                        "subscription_quota": {
                            "available": False,
                            "source": "unavailable",
                            "windows": [],
                            "unavailable_reason": "Personal subscription quota is not exposed.",
                        },
                        "api_quota": {
                            "available": True,
                            "source": "official-admin-api",
                            "limits": [{"label": "RPM", "remaining": 12, "limit": 50}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = JsonSnapshotSource(path, now=lambda: NOW).snapshot()

        self.assertEqual(result["platform"], "claude")
        self.assertEqual(result["provider"], "Anthropic API")
        self.assertFalse(result["subscription_quota"]["available"])
        self.assertTrue(result["api_quota"]["available"])
        self.assertEqual(result["api_quota"]["limits"][0]["remaining"], 12)

    def test_missing_or_invalid_json_fails_closed_without_fake_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.json"
            invalid = Path(temp) / "invalid.json"
            invalid.write_text("not json", encoding="utf-8")

            missing_result = JsonSnapshotSource(missing, platform="gemini", now=lambda: NOW).snapshot()
            invalid_result = JsonSnapshotSource(invalid, platform="chatgpt", now=lambda: NOW).snapshot()

        for result in (missing_result, invalid_result):
            self.assertFalse(result["subscription_quota"]["available"])
            self.assertEqual(result["subscription_quota"]["windows"], [])
            self.assertNotIn("remaining_percent", result["subscription_quota"])
            self.assertIn("snapshot", result["subscription_quota"]["unavailable_reason"].lower())

    def test_environment_selects_only_explicit_read_only_sources(self):
        empty = source_from_environment({}, now=lambda: NOW).snapshot()
        self.assertEqual(empty["platform"], "unknown")
        self.assertFalse(empty["subscription_quota"]["available"])

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snapshot.json"
            path.write_text(
                json.dumps({"platform": "chatgpt", "provider": "openai"}),
                encoding="utf-8",
            )
            selected = source_from_environment(
                {"QUOTA_ORB_SNAPSHOT_FILE": str(path), "OPENAI_API_KEY": "must-not-be-read"},
                now=lambda: NOW,
            ).snapshot()

        self.assertEqual(selected["platform"], "chatgpt")
        self.assertEqual(selected["provider"], "openai")
        self.assertFalse(selected["subscription_quota"]["available"])


class HermesTranslationTests(unittest.TestCase):
    def test_legacy_hermes_snapshot_maps_quota_and_local_usage_without_merging_them(self):
        result = translate_hermes_snapshot(
            {
                "ok": True,
                "generated_at": "2026-08-11T12:00:00+00:00",
                "day": "2026-08-11",
                "quota": {
                    "available": True,
                    "provider": "openai-codex",
                    "source": "usage_api",
                    "plan": "Plus",
                    "windows": [
                        {"label": "Session", "remaining_percent": 40, "reset_at": None, "detail": None}
                    ],
                    "details": [],
                    "unavailable_reason": None,
                },
                "today": {
                    "input_tokens": 200,
                    "output_tokens": 50,
                    "total_tokens": 250,
                    "by_provider": [],
                },
            },
            now=NOW,
        )

        self.assertEqual(result["platform"], "hermes")
        self.assertEqual(result["provider"], "openai-codex")
        self.assertEqual(result["subscription_quota"]["windows"][0]["remaining_percent"], 40.0)
        self.assertTrue(result["local_usage"]["available"])
        self.assertEqual(result["local_usage"]["totals"]["total_tokens"], 250)
        self.assertNotIn("remaining_percent", result["local_usage"]["totals"])

    def test_legacy_hermes_snapshot_accepts_only_literal_true_for_quota_windows(self):
        quota_window = {"label": "Session", "remaining_percent": 40, "reset_at": None, "detail": None}
        normalized_quota_window = {
            "label": "Session",
            "used_percent": 60.0,
            "remaining_percent": 40.0,
            "reset_at": None,
            "detail": None,
        }
        for supplied, expected_available, expected_windows in (
            ("false", False, []),
            (1, False, []),
            ({"unexpected": "value"}, False, []),
            (True, True, [normalized_quota_window]),
        ):
            with self.subTest(available=supplied):
                result = translate_hermes_snapshot(
                    {
                        "quota": {
                            "available": supplied,
                            "provider": "openai-codex",
                            "source": "usage_api",
                            "windows": [quota_window],
                        }
                    },
                    now=NOW,
                )

                subscription = result["subscription_quota"]
                self.assertIs(subscription["available"], expected_available)
                self.assertEqual(subscription["windows"], expected_windows)


class HermesHttpSourceTests(unittest.TestCase):
    def test_default_fetcher_disables_proxies_and_sends_no_credentials(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        opener = MagicMock()
        opener.open.return_value = response

        with patch("quota_orb.sources.build_opener", return_value=opener) as factory:
            content = _fetch_loopback_json(
                "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
                2.0,
            )

        self.assertEqual(content, b"{}")
        handlers = factory.call_args.args
        self.assertTrue(
            any(isinstance(handler, ProxyHandler) and handler.proxies == {} for handler in handlers)
        )
        self.assertTrue(any(type(handler).__name__ == "_RejectRedirects" for handler in handlers))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIsNone(request.get_header("Authorization"))

    def test_redirect_is_rejected_as_unavailable_without_following(self):
        requests = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "http://192.0.2.10/should-not-be-followed")
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            snapshot = HermesHttpSource(
                f"http://127.0.0.1:{server.server_port}/api/plugins/quota-orb/snapshot",
                now=lambda: NOW,
            ).snapshot()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertFalse(snapshot["subscription_quota"]["available"])
        self.assertIn("unavailable or invalid", snapshot["subscription_quota"]["unavailable_reason"])
        self.assertEqual(requests, ["/api/plugins/quota-orb/snapshot"])

    def test_rejects_non_loopback_or_wrong_path_urls(self):
        for url in (
            "http://localhost:8787/api/plugins/quota-orb/snapshot",
            "https://example.com/api/plugins/quota-orb/snapshot",
            "http://192.0.2.10/api/plugins/quota-orb/snapshot",
            "http://127.0.0.1/other",
            "http://user:secret@127.0.0.1/api/plugins/quota-orb/snapshot",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                HermesHttpSource(url)

    def test_reads_loopback_snapshot_without_authentication_headers(self):
        calls = []
        payload = json.dumps(
            {
                "ok": True,
                "day": "2026-08-11",
                "quota": {
                    "available": True,
                    "provider": "openai-codex",
                    "source": "usage_api",
                    "windows": [{"label": "Session", "remaining_percent": 25}],
                },
                "today": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            }
        ).encode("utf-8")

        def fetch(url, timeout):
            calls.append((url, timeout))
            return payload

        result = HermesHttpSource(
            "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
            fetcher=fetch,
            now=lambda: NOW,
        ).snapshot()

        self.assertEqual(calls, [("http://127.0.0.1:8000/api/plugins/quota-orb/snapshot", 2.0)])
        self.assertEqual(result["platform"], "hermes")
        self.assertEqual(result["provider"], "openai-codex")
        self.assertEqual(result["subscription_quota"]["windows"][0]["remaining_percent"], 25.0)
        self.assertEqual(result["local_usage"]["totals"]["total_tokens"], 5)

    def test_http_failure_and_oversize_payload_fail_closed(self):
        def failed_fetch(url, timeout):
            raise OSError("offline")

        failed = HermesHttpSource(
            "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
            fetcher=failed_fetch,
            now=lambda: NOW,
        ).snapshot()
        oversized = HermesHttpSource(
            "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
            fetcher=lambda url, timeout: b"x" * (2 * 1024 * 1024 + 1),
            now=lambda: NOW,
        ).snapshot()

        for result in (failed, oversized):
            self.assertEqual(result["platform"], "hermes")
            self.assertFalse(result["subscription_quota"]["available"])
            self.assertEqual(result["subscription_quota"]["windows"], [])

    def test_environment_prefers_explicit_json_then_loopback_hermes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "snapshot.json"
            path.write_text(json.dumps({"platform": "claude"}), encoding="utf-8")
            selected = source_from_environment(
                {
                    "QUOTA_ORB_SNAPSHOT_FILE": str(path),
                    "QUOTA_ORB_HERMES_URL": "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
                },
                now=lambda: NOW,
            )
        self.assertIsInstance(selected, JsonSnapshotSource)

        selected = source_from_environment(
            {"QUOTA_ORB_HERMES_URL": "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot"},
            now=lambda: NOW,
        )
        self.assertIsInstance(selected, HermesHttpSource)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import ProxyHandler


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.sources import (
    CodexAppServerSource,
    HermesHttpSource,
    JsonSnapshotSource,
    UnavailableSource,
    _fetch_loopback_json,
    desktop_source_from_environment,
    source_from_environment,
    translate_codex_rate_limits,
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


class CodexAppServerSourceTests(unittest.TestCase):
    def test_desktop_source_safely_discovers_only_the_fixed_user_codex_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp)
            candidate = profile / ".codex" / "plugins" / ".plugin-appserver" / "codex.exe"

            missing = desktop_source_from_environment({"USERPROFILE": str(profile)}, now=lambda: NOW)
            self.assertIsInstance(missing, UnavailableSource)
            self.assertIsInstance(source_from_environment({"USERPROFILE": str(profile)}), UnavailableSource)

            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"not executed by selection")
            selected = desktop_source_from_environment({"USERPROFILE": str(profile)}, now=lambda: NOW)
            self.assertIsInstance(selected, CodexAppServerSource)
            self.assertEqual(Path(selected.executable), candidate)

    def test_desktop_source_keeps_explicit_snapshot_hermes_and_codex_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp)
            candidate = profile / ".codex" / "plugins" / ".plugin-appserver" / "codex.exe"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"auto candidate")
            snapshot = profile / "snapshot.json"
            snapshot.write_text("{}", encoding="utf-8")
            base = {"USERPROFILE": str(profile)}

            selected = desktop_source_from_environment(
                {**base, "QUOTA_ORB_SNAPSHOT_FILE": str(snapshot)}, now=lambda: NOW
            )
            self.assertIsInstance(selected, JsonSnapshotSource)
            selected = desktop_source_from_environment(
                {
                    **base,
                    "QUOTA_ORB_HERMES_URL": "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
                },
                now=lambda: NOW,
            )
            self.assertIsInstance(selected, HermesHttpSource)
            selected = desktop_source_from_environment(
                {**base, "QUOTA_ORB_CODEX_EXE": "C:\\Explicit\\codex.exe"},
                now=lambda: NOW,
            )
            self.assertIsInstance(selected, CodexAppServerSource)
            self.assertEqual(selected.executable, "C:\\Explicit\\codex.exe")

    def test_rate_limits_translate_to_separate_subscription_windows(self):
        result = translate_codex_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "codex",
                        "limitName": "Codex",
                        "planType": "pro",
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 31.5,
                                "windowDurationMins": 300,
                                "resetsAt": 1780000000,
                            },
                            "secondary": {
                                "usedPercent": 70,
                                "windowDurationMins": 10080,
                                "resetsAt": 1780100000,
                            },
                        },
                    }
                }
            },
            now=NOW,
        )

        subscription = result["subscription_quota"]
        self.assertEqual(result["platform"], "codex")
        self.assertEqual(result["provider"], "openai-codex")
        self.assertTrue(subscription["available"])
        self.assertEqual(subscription["source"], "official-codex-app-server")
        self.assertEqual(subscription["plan"], "pro")
        self.assertEqual(len(subscription["windows"]), 2)
        primary, secondary = subscription["windows"]
        self.assertEqual(primary["used_percent"], 31.5)
        self.assertEqual(primary["remaining_percent"], 68.5)
        self.assertEqual(primary["reset_at"], "2026-05-28T20:26:40+00:00")
        self.assertEqual(primary["detail"], {"limitId": "codex", "limitName": "Codex", "windowDurationMins": 300})
        self.assertEqual(secondary["remaining_percent"], 30.0)
        self.assertEqual(secondary["detail"]["windowDurationMins"], 10080)
        self.assertFalse(result["api_quota"]["available"])
        self.assertFalse(result["local_usage"]["available"])
        self.assertFalse(result["token_billing"]["available"])

    def test_rate_limits_by_limit_id_uses_only_the_codex_bucket(self):
        result = translate_codex_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "spark": {
                        "limitId": "spark",
                        "limitName": "Spark",
                        "planType": "pro",
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 99,
                                "windowDurationMins": 60,
                                "resetsAt": 1780000000,
                            }
                        },
                    },
                    "codex": {
                        "limitId": "codex",
                        "limitName": "Codex",
                        "planType": "pro",
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 20,
                                "windowDurationMins": 300,
                                "resetsAt": 1780000000,
                            }
                        },
                    },
                }
            },
            now=NOW,
        )

        windows = result["subscription_quota"]["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["remaining_percent"], 80.0)
        self.assertEqual(windows[0]["detail"]["limitId"], "codex")

    def test_rate_limits_by_limit_id_rejects_a_mislabeled_codex_bucket(self):
        result = translate_codex_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "spark",
                        "limitName": "Spark",
                        "planType": "pro",
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 99,
                                "windowDurationMins": 60,
                                "resetsAt": 1780000000,
                            }
                        },
                    }
                }
            },
            now=NOW,
        )

        subscription = result["subscription_quota"]
        self.assertFalse(subscription["available"])
        self.assertEqual(subscription["windows"], [])

    def test_rate_limits_fall_back_to_top_level_when_no_valid_codex_bucket_exists(self):
        result = translate_codex_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "spark": {
                        "limitId": "spark",
                        "rateLimits": {
                            "primary": {
                                "usedPercent": 99,
                                "windowDurationMins": 60,
                                "resetsAt": 1780000000,
                            }
                        },
                    }
                },
                "rateLimits": {
                    "planType": "plus",
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 35,
                            "windowDurationMins": 300,
                            "resetsAt": 1780000000,
                        }
                    },
                },
            },
            now=NOW,
        )

        subscription = result["subscription_quota"]
        self.assertTrue(subscription["available"])
        self.assertEqual(subscription["plan"], "plus")
        self.assertEqual(len(subscription["windows"]), 1)
        self.assertEqual(subscription["windows"][0]["remaining_percent"], 65.0)

    def test_subprocess_protocol_accepts_only_matching_ids_and_uses_read_only_method(self):
        class RecordingInput(BytesIO):
            def close(self):
                return

        class Process:
            def __init__(self):
                self.stdin = RecordingInput()
                self.stdout = BytesIO(
                    b'{"jsonrpc":"2.0","id":99,"result":{"ignored":true}}\n'
                    b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
                    b'{"jsonrpc":"2.0","id":2,"result":{"rateLimits":{"planType":"plus","rateLimits":{"primary":{"usedPercent":20,"windowDurationMins":300,"resetsAt":1780000000}}}}}\n'
                )
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode or 0

            def kill(self):
                self.returncode = -9

        process = Process()
        popen = MagicMock(return_value=process)
        source = CodexAppServerSource("C:\\Codex\\codex.exe", popen=popen, now=lambda: NOW)

        result = source.snapshot()

        self.assertTrue(result["subscription_quota"]["available"])
        self.assertTrue(process.terminated)
        self.assertEqual(popen.call_args.args[0], ["C:\\Codex\\codex.exe", "app-server", "--stdio"])
        self.assertFalse(popen.call_args.kwargs["shell"])
        requests = [json.loads(line) for line in process.stdin.getvalue().decode("utf-8").splitlines()]
        self.assertEqual([request["method"] for request in requests], [
            "initialize",
            "initialized",
            "account/rateLimits/read",
        ])
        self.assertEqual(
            requests[0]["params"]["clientInfo"],
            {"name": "quota-orb", "version": "0.5.0"},
        )
        self.assertEqual(requests[-1]["id"], 2)
        self.assertNotIn("auth", json.dumps(requests).lower())

    def test_invalid_response_fails_closed_and_environment_selects_after_snapshot_and_hermes(self):
        class Process:
            def __init__(self):
                self.stdin = BytesIO()
                self.stdout = BytesIO(b'{"jsonrpc":"2.0","id":1,"result":{}}\nnot-json\n')
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.returncode = -9

        failed = CodexAppServerSource("C:\\Codex\\codex.exe", popen=lambda *args, **kwargs: Process(), now=lambda: NOW).snapshot()
        self.assertFalse(failed["subscription_quota"]["available"])
        self.assertEqual(failed["subscription_quota"]["windows"], [])
        self.assertNotIn("not-json", failed["subscription_quota"]["unavailable_reason"])

        selected = source_from_environment(
            {"QUOTA_ORB_CODEX_EXE": "C:\\Codex\\codex.exe"},
            now=lambda: NOW,
        )
        self.assertIsInstance(selected, CodexAppServerSource)
        selected = source_from_environment(
            {
                "QUOTA_ORB_HERMES_URL": "http://127.0.0.1:8000/api/plugins/quota-orb/snapshot",
                "QUOTA_ORB_CODEX_EXE": "C:\\Codex\\codex.exe",
            },
            now=lambda: NOW,
        )
        self.assertIsInstance(selected, HermesHttpSource)

    def test_oversized_integers_fail_closed_or_skip_invalid_windows_without_raising(self):
        invalid_window = translate_codex_rate_limits(
            {
                "rateLimits": {
                    "planType": "pro",
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 10**10000,
                            "windowDurationMins": 300,
                            "resetsAt": 1780000000,
                        }
                    },
                }
            },
            now=NOW,
        )
        invalid_reset = translate_codex_rate_limits(
            {
                "rateLimits": {
                    "planType": "pro",
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 20,
                            "windowDurationMins": 300,
                            "resetsAt": 10**10000,
                        }
                    },
                }
            },
            now=NOW,
        )

        for result in (invalid_window, invalid_reset):
            self.assertFalse(result["subscription_quota"]["available"])
            self.assertEqual(result["subscription_quota"]["windows"], [])

    def test_deeply_nested_json_response_fails_closed_without_leaking_content(self):
        class Process:
            def __init__(self):
                self.stdin = BytesIO()
                self.stdout = BytesIO(
                    b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
                    + (b"[" * 5000)
                    + b"0"
                    + (b"]" * 5000)
                    + b"\n"
                )
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.returncode = -9

        result = CodexAppServerSource(
            "C:\\Codex\\codex.exe", popen=lambda *args, **kwargs: Process(), now=lambda: NOW
        ).snapshot()

        self.assertFalse(result["subscription_quota"]["available"])
        self.assertEqual(result["subscription_quota"]["windows"], [])
        self.assertNotIn("[[[[", result["subscription_quota"]["unavailable_reason"])

    def test_nonmatching_messages_do_not_reset_the_snapshot_deadline(self):
        class Process:
            def __init__(self):
                self.stdin = BytesIO()
                self.stdout = BytesIO(
                    b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
                    b'{"jsonrpc":"2.0","id":99,"result":{}}\n'
                    b'{"jsonrpc":"2.0","id":2,"result":{"rateLimits":{"planType":"pro","rateLimits":{"primary":{"usedPercent":20,"windowDurationMins":300,"resetsAt":1780000000}}}}}\n'
                )
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.returncode = -9

        with patch("quota_orb.sources.monotonic", side_effect=[0.0, 0.0, 1.9, 2.0]):
            result = CodexAppServerSource(
                "C:\\Codex\\codex.exe", popen=lambda *args, **kwargs: Process(), now=lambda: NOW
            ).snapshot()

        self.assertFalse(result["subscription_quota"]["available"])


if __name__ == "__main__":
    unittest.main()

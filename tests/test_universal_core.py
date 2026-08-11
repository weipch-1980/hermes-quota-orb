from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.core import normalize_snapshot, unavailable_snapshot


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class UniversalSnapshotTests(unittest.TestCase):
    def test_unavailable_subscription_is_not_reported_as_zero(self):
        result = unavailable_snapshot(
            platform="chatgpt",
            provider="openai",
            reason="ChatGPT subscription quota is not exposed by an official API.",
            now=NOW,
        )

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["platform"], "chatgpt")
        self.assertEqual(result["provider"], "openai")
        self.assertFalse(result["subscription_quota"]["available"])
        self.assertEqual(result["subscription_quota"]["windows"], [])
        self.assertNotIn("remaining_percent", result["subscription_quota"])
        self.assertEqual(result["api_quota"]["available"], False)
        self.assertEqual(result["local_usage"]["available"], False)
        self.assertIsNone(result["local_usage"]["totals"])
        self.assertEqual(result["token_billing"]["available"], False)
        self.assertIsNone(result["token_billing"]["usage"])
        self.assertIsNone(result["token_billing"]["allowance"])
        self.assertIsNone(result["token_billing"]["cost"])

    def test_token_billing_preserves_actual_cost_and_separate_allowance(self):
        result = normalize_snapshot(
            {
                "platform": "workbuddy-code",
                "provider": "tencent",
                "subscription_quota": {"available": False, "windows": []},
                "token_billing": {
                    "available": True,
                    "source": "official-statusline",
                    "usage": {
                        "input_tokens": 800,
                        "output_tokens": 200,
                        "cache_read_tokens": 50,
                        "total_tokens": 1000,
                    },
                    "allowance": {
                        "limit_tokens": 2000,
                        "used_tokens": 1000,
                        "remaining_tokens": 1000,
                        "remaining_percent": 50,
                        "reset_at": "2026-09-01T00:00:00+00:00",
                    },
                    "cost": {
                        "amount": 1.25,
                        "currency": "usd",
                        "classification": "actual",
                        "basis": "provider_reported",
                        "period_start": "2026-08-12T00:00:00+00:00",
                        "period_end": "2026-08-12T12:00:00+00:00",
                    },
                },
            },
            now=NOW,
        )

        billing = result["token_billing"]
        self.assertTrue(billing["available"])
        self.assertEqual(billing["usage"]["total_tokens"], 1000)
        self.assertEqual(billing["allowance"]["remaining_percent"], 50.0)
        self.assertEqual(billing["cost"]["classification"], "actual")
        self.assertEqual(billing["cost"]["currency"], "USD")
        self.assertEqual(billing["cost"]["amount"], 1.25)
        self.assertNotIn("remaining_percent", result["local_usage"].get("totals") or {})

    def test_token_usage_without_allowance_never_invents_remaining_or_cost(self):
        result = normalize_snapshot(
            {
                "platform": "codex",
                "provider": "openai",
                "token_billing": {
                    "available": True,
                    "source": "official-token-counter",
                    "usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
                },
            },
            now=NOW,
        )

        billing = result["token_billing"]
        self.assertEqual(billing["usage"]["total_tokens"], 100)
        self.assertIsNone(billing["allowance"])
        self.assertIsNone(billing["cost"])

    def test_estimated_cost_is_labeled_and_unknown_billing_fields_are_removed(self):
        import json

        marker = "billing-secret-must-not-cross"
        result = normalize_snapshot(
            {
                "platform": "example",
                "provider": "example",
                "token_billing": {
                    "available": True,
                    "source": "official-price-table-calculation",
                    "usage": {"input_tokens": 100, "api_key": marker},
                    "cost": {
                        "amount": 0.01,
                        "currency": "USD",
                        "classification": "estimated",
                        "basis": "official_list_price",
                        "model": "example-model",
                        "pricing_effective_at": "2026-08-01",
                        "access_token": marker,
                    },
                },
            },
            now=NOW,
        )

        self.assertEqual(result["token_billing"]["cost"]["classification"], "estimated")
        self.assertEqual(result["token_billing"]["cost"]["basis"], "official_list_price")
        self.assertNotIn(marker, json.dumps(result))

    def test_invalid_cost_classification_is_unavailable_not_actual(self):
        result = normalize_snapshot(
            {
                "platform": "example",
                "provider": "example",
                "token_billing": {
                    "available": True,
                    "source": "snapshot",
                    "cost": {"amount": 4, "currency": "USD", "classification": "charged"},
                },
            },
            now=NOW,
        )
        self.assertIsNone(result["token_billing"]["cost"])

    def test_real_zero_percent_is_preserved(self):
        result = normalize_snapshot(
            {
                "platform": "hermes",
                "provider": "openai-codex",
                "subscription_quota": {
                    "available": True,
                    "source": "usage_api",
                    "windows": [
                        {
                            "label": "Session",
                            "remaining_percent": 0,
                            "reset_at": "2026-08-11T18:00:00+00:00",
                        }
                    ],
                },
            },
            now=NOW,
        )

        window = result["subscription_quota"]["windows"][0]
        self.assertEqual(window["remaining_percent"], 0.0)
        self.assertEqual(window["used_percent"], 100.0)

    def test_percentages_are_clamped_without_rewriting_identity_fields(self):
        result = normalize_snapshot(
            {
                "platform": "claude",
                "provider": "Anthropic OAuth",
                "profile": "客户-A",
                "account": "Team Account",
                "model": "claude-opus",
                "subscription_quota": {
                    "available": True,
                    "source": "official-account-api",
                    "plan": "Max",
                    "windows": [
                        {"label": "Five hour", "remaining_percent": 125},
                        {"label": "Weekly", "remaining_percent": -4},
                    ],
                },
            },
            now=NOW,
        )

        self.assertEqual(result["provider"], "Anthropic OAuth")
        self.assertEqual(result["profile"], "客户-A")
        self.assertEqual(result["account"], "Team Account")
        self.assertEqual(result["model"], "claude-opus")
        self.assertEqual(
            [item["remaining_percent"] for item in result["subscription_quota"]["windows"]],
            [100.0, 0.0],
        )

    def test_available_requires_literal_boolean_true(self):
        result = normalize_snapshot(
            {
                "platform": "test",
                "provider": "provider",
                "subscription_quota": {"available": "false", "windows": [{"remaining_percent": 50}]},
                "api_quota": {"available": 1, "limits": [{"remaining": 5}]},
                "local_usage": {"available": [True], "totals": {"total_tokens": 7}},
            },
            now=NOW,
        )

        self.assertFalse(result["subscription_quota"]["available"])
        self.assertFalse(result["api_quota"]["available"])
        self.assertFalse(result["local_usage"]["available"])

    def test_unknown_fields_cannot_cross_the_model_boundary(self):
        import json

        marker = "must-not-cross-model-boundary"
        result = normalize_snapshot(
            {
                "platform": "gemini",
                "provider": "google",
                "api_quota": {
                    "available": True,
                    "source": "official",
                    "limits": [
                        {
                            "label": "RPM",
                            "remaining": 2,
                            "limit": 10,
                            "api_key": marker,
                        }
                    ],
                },
                "local_usage": {
                    "available": True,
                    "source": "local",
                    "totals": {"total_tokens": 3, "password": marker},
                    "by_provider": [
                        {
                            "provider": "google",
                            "total_tokens": 3,
                            "secret": marker,
                            "models": [
                                {"model": "gemini", "total_tokens": 3, "access_token": marker}
                            ],
                        }
                    ],
                },
            },
            now=NOW,
        )

        self.assertNotIn(marker, json.dumps(result))
        self.assertEqual(result["api_quota"]["limits"], [{"label": "RPM", "remaining": 2, "limit": 10}])
        self.assertEqual(result["local_usage"]["totals"], {"total_tokens": 3})
        self.assertEqual(result["local_usage"]["by_provider"][0]["provider"], "google")
        self.assertEqual(result["local_usage"]["by_provider"][0]["models"][0]["model"], "gemini")

    def test_subscription_api_and_local_usage_remain_separate(self):
        result = normalize_snapshot(
            {
                "platform": "gemini",
                "provider": "google",
                "subscription_quota": {
                    "available": False,
                    "source": "unavailable",
                    "windows": [],
                    "unavailable_reason": "Gemini App allowance is not the Gemini API quota.",
                },
                "api_quota": {
                    "available": True,
                    "source": "google-cloud-quota",
                    "limits": [{"label": "Requests per minute", "remaining": 30, "limit": 60}],
                },
                "local_usage": {
                    "available": True,
                    "source": "local-session-log",
                    "day": "2026-08-11",
                    "totals": {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
                    "by_provider": [],
                },
            },
            now=NOW,
        )

        self.assertFalse(result["subscription_quota"]["available"])
        self.assertTrue(result["api_quota"]["available"])
        self.assertEqual(result["api_quota"]["limits"][0]["remaining"], 30)
        self.assertTrue(result["local_usage"]["available"])
        self.assertEqual(result["local_usage"]["totals"]["total_tokens"], 125)
        self.assertNotIn("remaining_percent", result["local_usage"]["totals"])


if __name__ == "__main__":
    unittest.main()

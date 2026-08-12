from __future__ import annotations

import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.mcp_server import ORB_RESOURCE_URI, create_server


class StaticSource:
    def snapshot(self, provider: str | None = None):
        return {
            "schema_version": "1.0",
            "generated_at": datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc).isoformat(),
            "platform": "chatgpt",
            "provider": provider or "openai",
            "profile": None,
            "account": None,
            "model": None,
            "subscription_quota": {
                "available": True,
                "source": "test-source",
                "plan": None,
                "windows": [
                    {
                        "label": "Session",
                        "used_percent": 60.0,
                        "remaining_percent": 40.0,
                        "reset_at": None,
                        "detail": None,
                    }
                ],
                "unavailable_reason": None,
            },
            "api_quota": {
                "available": False,
                "source": "unavailable",
                "limits": [],
                "unavailable_reason": "Not configured.",
            },
            "local_usage": {
                "available": True,
                "source": "test-log",
                "day": "2026-08-11",
                "totals": {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
                "by_provider": [],
                "unavailable_reason": None,
            },
        }


class UniversalMcpServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = create_server(StaticSource())

    async def test_rejects_non_loopback_http_bind_without_an_authentication_layer(self):
        for host in ("0.0.0.0", "localhost"):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "loopback"):
                create_server(StaticSource(), host=host)
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_server(StaticSource(), host="example.com")

    async def test_http_transport_security_is_limited_to_the_literal_bind_address(self):
        ipv4 = create_server(StaticSource(), host="127.0.0.1")
        ipv4_security = ipv4.settings.transport_security
        self.assertTrue(ipv4_security.enable_dns_rebinding_protection)
        self.assertEqual(ipv4_security.allowed_hosts, ["127.0.0.1:*"])
        self.assertEqual(ipv4_security.allowed_origins, ["http://127.0.0.1:*"])

        ipv6 = create_server(StaticSource(), host="::1")
        ipv6_security = ipv6.settings.transport_security
        self.assertTrue(ipv6_security.enable_dns_rebinding_protection)
        self.assertEqual(ipv6_security.allowed_hosts, ["[::1]:*"])
        self.assertEqual(ipv6_security.allowed_origins, ["http://[::1]:*"])

    async def test_exposes_exactly_three_read_only_tools(self):
        tools = {tool.name: tool for tool in await self.server.list_tools()}

        self.assertEqual(
            set(tools),
            {"get_quota_snapshot", "get_daily_usage", "get_supported_sources"},
        )
        for tool in tools.values():
            self.assertTrue(tool.annotations.readOnlyHint)
            self.assertFalse(tool.annotations.destructiveHint)
            self.assertTrue(tool.annotations.idempotentHint)
            self.assertFalse(tool.annotations.openWorldHint)
        self.assertEqual(
            tools["get_quota_snapshot"].meta["ui"]["resourceUri"],
            ORB_RESOURCE_URI,
        )

    async def test_tools_return_structured_snapshot_usage_and_capabilities(self):
        _, snapshot = await self.server.call_tool("get_quota_snapshot", {"provider": "OpenAI"})
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(snapshot["provider"], "OpenAI")
        self.assertEqual(snapshot["subscription_quota"]["windows"][0]["remaining_percent"], 40.0)

        _, usage = await self.server.call_tool("get_daily_usage", {})
        self.assertEqual(set(usage), {"schema_version", "generated_at", "platform", "provider", "local_usage"})
        self.assertEqual(usage["local_usage"]["totals"]["total_tokens"], 125)

        _, sources = await self.server.call_tool("get_supported_sources", {})
        self.assertEqual(
            set(sources["platforms"]),
            {
                "hermes",
                "chatgpt",
                "codex",
                "claude",
                "gemini",
                "cursor",
                "copilot",
                "qwen-code",
                "kimi-cli",
                "openclaw",
                "workbuddy-code",
            },
        )
        self.assertEqual(sources["platforms"]["chatgpt"]["subscription_quota"], "unavailable_without_official_source")
        self.assertEqual(
            sources["platforms"]["codex"]["subscription_quota"],
            "official_codex_app_server_when_quota_orb_codex_exe_configured",
        )
        self.assertEqual(
            sources["platforms"]["claude"]["transport"],
            "claude_remote_connector_or_code_user_local_mcp",
        )
        self.assertEqual(
            sources["platforms"]["gemini"]["transport"],
            "gemini_spark_remote_or_antigravity_gemini_cli_user_local_mcp",
        )
        self.assertEqual(
            sources["platforms"]["openclaw"]["transport"],
            "official_global_skill_cli_and_user_local_mcp",
        )
        self.assertEqual(
            sources["platforms"]["workbuddy-code"]["token_billing"],
            "official_statusline_cost_or_explicit_snapshot_bridge",
        )

    async def test_registers_portable_mcp_app_resource_with_truthful_liquid_semantics(self):
        resources = {str(resource.uri): resource for resource in await self.server.list_resources()}
        self.assertIn(ORB_RESOURCE_URI, resources)
        self.assertEqual(resources[ORB_RESOURCE_URI].mimeType, "text/html;profile=mcp-app")

        contents = list(await self.server.read_resource(ORB_RESOURCE_URI))
        self.assertEqual(len(contents), 1)
        html = contents[0].content
        self.assertIn("ui/notifications/tool-result", html)
        self.assertIn("84 - clamped * 0.76", html)
        self.assertIn('typeof remaining === "number"', html)
        self.assertIn('typeof item?.remaining_percent === "number"', html)
        self.assertIn("const selectedWindow = windows.filter", html)
        self.assertIn("selectedWindow?.reset_at", html)
        self.assertIn('card.setAttribute("role", "status")', html)
        self.assertIn('card.removeAttribute("aria-valuemin")', html)
        self.assertIn('card.removeAttribute("aria-valuemax")', html)
        self.assertIn("remaining_percent", html)
        self.assertIn("token_billing", html)
        self.assertIn("function liquidTone", html)
        self.assertIn('if (clamped < 30) return "red"', html)
        self.assertIn('if (clamped < 50) return "yellow"', html)
        self.assertIn('return "green"', html)
        self.assertIn("tokenAllowance", html)
        self.assertIn("Actual billed cost", html)
        self.assertIn("Estimated cost", html)
        self.assertIn("Billing cost Unavailable", html)
        self.assertIn("color-mix(in srgb, currentColor 88%, transparent)", html)
        self.assertIn("tokenBilling?.available === true", html)
        self.assertIn("quota?.available === true", html)
        helpers = []
        for name in ("formatNumber", "billingText"):
            match = re.search(rf"function {name}\([^)]*\) \{{.*?\n    \}}", html, re.DOTALL)
            self.assertIsNotNone(match, name)
            helpers.append(match.group(0))
        script = "\n".join(helpers) + r"""
const unknown = billingText({ available: true, cost: { amount: 1, currency: 'USD', classification: 'charged' } })
if (unknown !== 'Billing cost Unavailable.') throw new Error(unknown)
const truthy = billingText({ available: 'true', cost: { amount: 1, currency: 'USD', classification: 'actual' } })
if (truthy !== 'Billing cost Unavailable.') throw new Error(truthy)
const actual = billingText({ available: true, cost: { amount: 1, currency: 'USD', classification: 'actual' } })
if (actual !== 'Actual billed cost: USD 1') throw new Error(actual)
const estimated = billingText({ available: true, cost: { amount: 1, currency: 'USD', classification: 'estimated' } })
if (estimated !== 'Estimated cost: USD 1') throw new Error(estimated)
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Unavailable", html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('focusable="false"', html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertNotIn("transition: all", html)
        self.assertNotRegex(html, r"#[0-9A-Fa-f]{3,8}\b")
        self.assertNotRegex(html, r"\brgba?\(")

    async def test_portable_renderer_prioritizes_subscription_then_token_allowance(self):
        contents = list(await self.server.read_resource(ORB_RESOURCE_URI))
        html = contents[0].content
        selector = re.search(
            r"function selectRemaining\(snapshot\) \{.*?\n    \}",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(selector)
        script = selector.group(0) + r"""
const subscriptionWins = selectRemaining({
  subscription_quota: { available: true, windows: [{ remaining_percent: 45 }] },
  token_billing: { available: true, allowance: { remaining_percent: 29.5 } }
})
if (subscriptionWins.remaining !== 45) throw new Error('token allowance overrode subscription')
const tokenFallback = selectRemaining({
  subscription_quota: { available: false, windows: [] },
  token_billing: { available: true, allowance: { remaining_percent: 29.5 } }
})
if (tokenFallback.remaining !== 29.5) throw new Error('token fallback lost')
const realZero = selectRemaining({
  subscription_quota: { available: true, windows: [{ remaining_percent: 0 }] },
  token_billing: { available: true, allowance: { remaining_percent: 29.5 } }
})
if (realZero.remaining !== 0) throw new Error('real zero became unknown')
const unknown = selectRemaining({
  subscription_quota: { available: true, windows: [{ remaining_percent: null }] },
  token_billing: { available: true, allowance: { remaining_percent: null } }
})
if (unknown.remaining !== null) throw new Error('unknown became a value')
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

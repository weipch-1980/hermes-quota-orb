from __future__ import annotations

import re
import unittest
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "desktop-plugin" / "plugin.js"


class DesktopPluginContractTests(unittest.TestCase):
    def setUp(self):
        self.source = PLUGIN.read_text(encoding="utf-8")

    def test_registers_status_chip_and_floating_orb(self):
        self.assertIn("id: ID", self.source)
        self.assertIn("area: 'statusBar.right'", self.source)
        self.assertIn("placement: 'floating'", self.source)
        self.assertIn("anchor: 'top-right'", self.source)
        self.assertIn("width: '80px'", self.source)
        self.assertIn("height: '80px'", self.source)

    def test_uses_supported_sdk_doors_for_live_and_daily_usage(self):
        self.assertIn("host.request('session.usage'", self.source)
        self.assertIn("ctx.rest('/snapshot'", self.source)
        self.assertIn("refetchInterval", self.source)

    def test_frontend_matches_snapshot_contract(self):
        self.assertIn("snapshot?.today", self.source)
        self.assertIn("quota?.windows", self.source)
        self.assertNotIn("snapshot?.daily", self.source)
        self.assertNotIn("quota?.short", self.source)
        self.assertNotIn("quota?.weekly", self.source)
        self.assertIn("ctx.storage", self.source)
        self.assertNotIn("host.restartGateway()", self.source)
        self.assertIn("restartHermes", self.source)

    def test_emits_end_of_day_in_app_and_native_reports(self):
        self.assertIn("lastReportDay", self.source)
        self.assertIn("host.notify", self.source)
        self.assertIn("ctx.os.notify", self.source)

    def test_runtime_plugin_uses_only_supported_imports_and_no_secrets(self):
        imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", self.source)
        self.assertTrue(imports)
        self.assertTrue(set(imports) <= {"@hermes/plugin-sdk", "react", "react/jsx-runtime"})
        for forbidden in ("Authorization", "access_token", "api_key", "auth.json"):
            self.assertNotIn(forbidden, self.source)

    def test_uses_theme_tokens_instead_of_hardcoded_colors(self):
        self.assertIn("--ui-", self.source)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.source))
        self.assertNotIn("rgb(", self.source)


if __name__ == "__main__":
    unittest.main()

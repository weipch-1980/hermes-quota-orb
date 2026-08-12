from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))


class PlatformAdapterTests(unittest.TestCase):
    def test_agent_skills_are_portable_and_truthful(self):
        paths = [
            ROOT / "skills" / "quota-orb" / "SKILL.md",
            ROOT / "adapters" / "chatgpt" / "SKILL.md",
            ROOT / "adapters" / "claude" / "SKILL.md",
            ROOT / "adapters" / "gemini" / "SKILL.md",
            ROOT / "adapters" / "codex" / "SKILL.md",
            ROOT / "adapters" / "cursor" / "SKILL.md",
            ROOT / "adapters" / "copilot" / "SKILL.md",
            ROOT / "adapters" / "qwen" / "SKILL.md",
            ROOT / "adapters" / "kimi" / "SKILL.md",
            ROOT / "adapters" / "openclaw" / "SKILL.md",
            ROOT / "adapters" / "workbuddy" / "SKILL.md",
        ]
        contents = [path.read_text(encoding="utf-8") for path in paths]
        self.assertEqual(len(set(contents)), 1)
        text = contents[0]
        self.assertTrue(text.startswith("---\nname: quota-orb\n"))
        frontmatter = text.split("---", 2)[1]
        self.assertEqual(
            {
                line.split(":", 1)[0].strip()
                for line in frontmatter.splitlines()
                if ":" in line
            },
            {"name", "description"},
        )
        self.assertIn("get_quota_snapshot", text)
        self.assertIn("get_daily_usage", text)
        self.assertIn("get_supported_sources", text)
        self.assertIn("Unavailable", text)
        self.assertIn("subscription quota", text)
        self.assertIn("API quota", text)
        self.assertIn("local usage", text)
        self.assertIn("fixed user Codex app-server path", text)
        self.assertIn("color-key-safe boundary", text)
        self.assertNotIn("cookie", text.lower())
        self.assertNotIn("/usage reset", text)

    def test_claude_and_gemini_examples_start_the_same_local_read_only_server(self):
        claude = json.loads(
            (ROOT / "adapters" / "claude" / "mcp.json.example").read_text(encoding="utf-8")
        )
        gemini = json.loads(
            (ROOT / "adapters" / "gemini" / "settings.json.example").read_text(encoding="utf-8")
        )
        antigravity = json.loads(
            (ROOT / "adapters" / "gemini" / "antigravity-mcp.json.example").read_text(
                encoding="utf-8"
            )
        )
        claude_server = claude["mcpServers"]["quota-orb"]
        gemini_server = gemini["mcpServers"]["quota-orb"]
        antigravity_server = antigravity["mcpServers"]["quota-orb"]
        for server in (claude_server, gemini_server, antigravity_server):
            self.assertEqual(server["command"], "python")
            self.assertEqual(
                server["args"],
                ["-m", "quota_orb.mcp_server", "--transport", "stdio"],
            )
            self.assertEqual(
                server["env"],
                {"QUOTA_ORB_SNAPSHOT_FILE": "<absolute-path-to-snapshot.json>"},
            )
            self.assertNotIn("API_KEY", json.dumps(server))
            self.assertNotIn("TOKEN", json.dumps(server))
        self.assertEqual(claude_server["type"], "stdio")
        self.assertEqual(
            gemini_server["includeTools"],
            ["get_quota_snapshot", "get_daily_usage", "get_supported_sources"],
        )
        self.assertFalse(gemini_server["trust"])

    def test_claude_adapter_covers_remote_connector_and_local_code(self):
        readme = (ROOT / "adapters" / "claude" / "README.md").read_text(encoding="utf-8")
        self.assertIn("Claude.ai", readme)
        self.assertIn("Custom Connector", readme)
        self.assertIn("Claude Code", readme)
        self.assertIn("HTTPS", readme)
        self.assertIn("not deployed", readme)

    def test_codex_registration_uses_the_explicit_app_server_source(self):
        readme = (ROOT / "adapters" / "codex" / "README.md").read_text(encoding="utf-8")
        self.assertIn("--env QUOTA_ORB_PLATFORM=codex", readme)
        self.assertIn("--env QUOTA_ORB_PROVIDER=openai-codex", readme)
        self.assertIn(
            r"--env QUOTA_ORB_CODEX_EXE=C:\Users\admin\.codex\plugins\.plugin-appserver\codex.exe",
            readme,
        )

    def test_google_adapter_covers_current_and_transitioning_official_hosts(self):
        readme = (ROOT / "adapters" / "gemini" / "README.md").read_text(encoding="utf-8")
        self.assertIn("Gemini Spark", readme)
        self.assertIn("Connected Apps", readme)
        self.assertIn("Antigravity CLI", readme)
        self.assertIn("Gemini CLI", readme)
        self.assertIn("HTTPS", readme)
        self.assertIn("not deployed", readme)

    def test_chatgpt_and_hermes_adapters_state_their_real_boundaries(self):
        chatgpt = (ROOT / "adapters" / "chatgpt" / "README.md").read_text(encoding="utf-8")
        hermes = (ROOT / "adapters" / "hermes" / "README.md").read_text(encoding="utf-8")
        self.assertIn("HTTPS", chatgpt)
        self.assertIn("/mcp", chatgpt)
        self.assertIn("text/html;profile=mcp-app", chatgpt)
        self.assertIn("not deployed", chatgpt)
        self.assertIn("Unavailable", chatgpt)
        self.assertIn("desktop-plugin/plugin.js", hermes)
        self.assertIn("hermes-plugin/dashboard/plugin_api.py", hermes)
        self.assertIn("unchanged", hermes)

    def test_non_hermes_agent_adapters_never_install_into_hermes(self):
        for name in ("codex", "claude", "gemini", "cursor", "copilot", "qwen", "kimi", "openclaw", "workbuddy"):
            with self.subTest(adapter=name):
                readme = (ROOT / "adapters" / name / "README.md").read_text(encoding="utf-8")
                lowered = readme.lower()
                self.assertNotIn("hermes skills install", lowered)
                self.assertNotIn("skill/quota-orb/scripts/install.py", lowered)
                self.assertIn("user", lowered)

    def test_openclaw_and_workbuddy_follow_official_global_contracts(self):
        openclaw = (ROOT / "adapters" / "openclaw" / "README.md").read_text(encoding="utf-8")
        workbuddy = (ROOT / "adapters" / "workbuddy" / "README.md").read_text(encoding="utf-8")
        self.assertIn("openclaw skills install", openclaw)
        self.assertIn("--global", openclaw)
        self.assertIn("shared managed skills directory", openclaw)
        self.assertIn("official CLI", openclaw)
        self.assertNotIn(".openclaw/skills", openclaw)
        self.assertIn("~/.codebuddy/skills/quota-orb/SKILL.md", workbuddy)
        self.assertIn("~/.codebuddy/.mcp.json", workbuddy)
        self.assertIn("codebuddy mcp add --scope user", workbuddy)
        self.assertIn("total_cost_usd", workbuddy)
        self.assertIn("actual", workbuddy.lower())
        self.assertIn("Unavailable", workbuddy)

        server = json.loads(
            (ROOT / "adapters" / "workbuddy" / "mcp.json.example").read_text(encoding="utf-8")
        )["mcpServers"]["quota-orb"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "python")
        self.assertEqual(server["args"], ["-m", "quota_orb.mcp_server", "--transport", "stdio"])
        self.assertNotIn("API_KEY", json.dumps(server))
        self.assertNotIn("TOKEN", json.dumps(server))

    def test_china_top_five_matrix_is_explicit_and_truthful(self):
        text = (ROOT / "adapters" / "china-top-five" / "README.md").read_text(encoding="utf-8")
        for name in ("Kimi", "Qwen", "DeepSeek", "GLM", "MiniMax"):
            self.assertIn(name, text)
        self.assertIn("2026-08", text)
        self.assertIn("Artificial Analysis", text)
        self.assertIn("Unavailable", text)
        self.assertIn("Codex", text)
        self.assertIn("Claude Code", text)
        self.assertIn("unavailable on Windows", text)
        self.assertIn("no native MCP support", text)
        self.assertIn("stable user-global Skill path", text)
        self.assertNotIn("personal subscription quota API is available", text)

    def test_qwen_and_kimi_examples_start_the_same_read_only_server(self):
        for path in (
            ROOT / "adapters" / "qwen" / "settings.json.example",
            ROOT / "adapters" / "kimi" / "mcp.json.example",
        ):
            with self.subTest(path=path):
                server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["quota-orb"]
                self.assertEqual(server["command"], "python")
                self.assertEqual(
                    server["args"],
                    ["-m", "quota_orb.mcp_server", "--transport", "stdio"],
                )
                self.assertEqual(
                    server["env"],
                    {"QUOTA_ORB_SNAPSHOT_FILE": "<absolute-path-to-snapshot.json>"},
                )
                self.assertNotIn("API_KEY", json.dumps(server))
                self.assertNotIn("TOKEN", json.dumps(server))

    def test_supported_sources_cover_global_hosts_and_china_model_families(self):
        from quota_orb.mcp_server import supported_sources

        result = supported_sources()
        platforms = result["platforms"]
        for name in ("codex", "claude", "gemini", "cursor", "copilot", "qwen-code", "kimi-cli"):
            self.assertIn(name, platforms)
        providers = result["china_model_families"]
        self.assertEqual(set(providers), {"kimi", "qwen", "deepseek", "glm", "minimax"})
        expected = {
            "kimi": {
                "integration_kind": "native_cli_skill_and_mcp",
                "native_skill": True,
                "native_mcp": True,
                "compatible_host": None,
                "user_global_skill_path": "~/.kimi/skills",
                "windows_support": "documented_by_native_cli",
            },
            "qwen": {
                "integration_kind": "native_cli_skill_and_mcp",
                "native_skill": True,
                "native_mcp": True,
                "compatible_host": None,
                "user_global_skill_path": "~/.qwen/skills",
                "windows_support": "documented_by_native_cli",
            },
            "deepseek": {
                "integration_kind": "provider_via_compatible_host",
                "native_skill": False,
                "native_mcp": False,
                "compatible_host": "codex",
                "user_global_skill_path": "not_applicable",
                "windows_support": "inherits_compatible_host",
            },
            "glm": {
                "integration_kind": "provider_via_compatible_host",
                "native_skill": False,
                "native_mcp": False,
                "compatible_host": "claude-code",
                "user_global_skill_path": "not_applicable",
                "windows_support": "unavailable_in_documented_setup",
            },
            "minimax": {
                "integration_kind": "native_skill_surface_only",
                "native_skill": True,
                "native_mcp": False,
                "compatible_host": None,
                "user_global_skill_path": "not_published",
                "windows_support": "not_published",
            },
        }
        for name, value in providers.items():
            self.assertEqual(value["subscription_quota"], "unavailable_without_official_source")
            for key, expected_value in expected[name].items():
                self.assertEqual(value[key], expected_value, f"{name}.{key}")

    def test_example_snapshot_is_safe_and_normalizable(self):
        from quota_orb.core import normalize_snapshot

        path = ROOT / "quota_orb" / "examples" / "snapshot.example.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalize_snapshot(raw)
        self.assertEqual(normalized["platform"], "example")
        self.assertFalse(normalized["subscription_quota"]["available"])
        self.assertEqual(normalized["subscription_quota"]["windows"], [])
        self.assertFalse(normalized["api_quota"]["available"])
        self.assertFalse(normalized["local_usage"]["available"])
        text = path.read_text(encoding="utf-8")
        for marker in ("API_KEY", "TOKEN", "PASSWORD", "BEGIN PRIVATE KEY"):
            self.assertNotIn(marker, text)

    def test_repository_disclaims_platform_endorsement(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("not endorsed by OpenAI, Anthropic, or Google", readme)

    def test_python_package_declares_official_mcp_runtime_and_html_asset(self):
        from quota_orb import __version__

        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.5.0"', text)
        self.assertEqual(__version__, "0.5.0")
        self.assertIn('"mcp==1.28.1"', text)
        self.assertIn('quota-orb-mcp = "quota_orb.mcp_server:main"', text)
        self.assertIn('quota-orb-widget = "quota_orb.desktop_widget:main"', text)
        self.assertIn('"assets/*.html"', text)
        self.assertIn('"examples/*.json"', text)


if __name__ == "__main__":
    unittest.main()

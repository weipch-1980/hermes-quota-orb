from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skill" / "quota-orb" / "SKILL.md"


class SkillPackageTests(unittest.TestCase):
    def test_skill_frontmatter_meets_repository_contract(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        match = re.match(r"---\n(.*?)\n---\n(.+)", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = yaml.safe_load(match.group(1))
        self.assertEqual(frontmatter["name"], "quota-orb")
        self.assertLessEqual(len(frontmatter["description"]), 60)
        self.assertTrue(frontmatter["description"].endswith("."))
        self.assertFalse(str(frontmatter["author"]).startswith("Hermes Agent"))
        self.assertEqual(frontmatter["platforms"], ["linux", "macos", "windows"])
        self.assertTrue(match.group(2).strip())

    def test_skill_assets_match_development_sources(self):
        pairs = [
            (ROOT / "desktop-plugin" / "plugin.js", ROOT / "skill" / "quota-orb" / "assets" / "desktop-plugin" / "plugin.js"),
            (ROOT / "hermes-plugin" / "dashboard" / "manifest.json", ROOT / "skill" / "quota-orb" / "assets" / "hermes-plugin" / "dashboard" / "manifest.json"),
            (ROOT / "hermes-plugin" / "dashboard" / "plugin_api.py", ROOT / "skill" / "quota-orb" / "assets" / "hermes-plugin" / "dashboard" / "plugin_api.py"),
        ]
        for source, asset in pairs:
            with self.subTest(asset=asset.name):
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(asset.read_bytes()).digest())


if __name__ == "__main__":
    unittest.main()

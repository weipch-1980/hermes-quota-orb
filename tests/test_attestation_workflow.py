from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "attest-release.yml"


class AttestationWorkflowTests(unittest.TestCase):
    """Static contract for the public release-attestation CI entry point."""

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), "release attestation workflow must exist")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_release_and_manual_tag_triggers_are_explicit(self):
        self.assertRegex(
            self.text,
            r"(?m)^on:\n  release:\n    types:\s*\[published\]\n  workflow_dispatch:\n"
            r"    inputs:\n      tag:\n(?:        .*\n)*?        required:\s*true\n"
            r"(?:        .*\n)*?        type:\s*string\n",
        )
        self.assertRegex(self.text, r'''(?m)^        default:\s*["']?v0\.3\.0["']?\s*$''')
        self.assertNotIn("pull_request:", self.text)

    def test_permissions_are_exactly_minimal_for_attestation(self):
        match = re.search(r"(?m)^permissions:\n((?:  [^\n]+\n?)+)", self.text)
        self.assertIsNotNone(match)
        permissions = {
            key.strip(): value.strip()
            for key, value in (
                line.split(":", 1) for line in match.group(1).strip().splitlines()
            )
        }
        self.assertEqual(
            permissions,
            {"contents": "read", "id-token": "write", "attestations": "write"},
        )
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("packages: write", self.text)
        self.assertNotIn("actions: write", self.text)

    def test_workflow_rebuilds_the_selected_tag_on_windows_with_pinned_actions(self):
        self.assertIn("runs-on: windows-latest", self.text)
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", self.text
        )
        self.assertIn(
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", self.text
        )
        self.assertIn(
            "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6", self.text
        )
        self.assertRegex(
            self.text,
            r"ref:\s*\$\{\{\s*github\.event\.release\.tag_name\s*\|\|\s*inputs\.tag\s*\}\}",
        )
        self.assertRegex(self.text, r'''python-version:\s*["']?3\.11["']?''')
        self.assertIn("python scripts/build_skill_package.py --output-dir dist", self.text)
        self.assertIn("shell: pwsh", self.text)
        self.assertIn("archive_path=", self.text)
        self.assertIn("archive_name=", self.text)
        self.assertIn("$env:GITHUB_OUTPUT", self.text)
        self.assertRegex(self.text, r"Count\s+-ne\s+1")

    def test_attestation_is_fail_closed_after_release_download_and_hash_gate(self):
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.text)
        self.assertNotIn("secrets.", self.text)
        self.assertIn("gh release download", self.text)
        self.assertIn("Get-FileHash", self.text)
        self.assertRegex(self.text, r"(?i)hash.*mismatch|mismatch.*hash")
        self.assertIn("subject-path: ${{ steps.build.outputs.archive_path }}", self.text)

        build_position = self.text.index("python scripts/build_skill_package.py --output-dir dist")
        download_position = self.text.index("gh release download")
        hash_position = self.text.index("Get-FileHash")
        attest_position = self.text.index(
            "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
        )
        self.assertLess(build_position, download_position)
        self.assertLess(download_position, hash_position)
        self.assertLess(hash_position, attest_position)


if __name__ == "__main__":
    unittest.main()

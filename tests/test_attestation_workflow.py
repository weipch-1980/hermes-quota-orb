from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "attest-release.yml"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"
ATTEST_SHA = "1e69f48acb82d1966a394da916b4c1698aa569d6"


class AttestationWorkflowTests(unittest.TestCase):
    """Static contract for CI-native release publication from pushed tags."""

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), "release attestation workflow must exist")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_tag_push_is_the_only_trigger(self):
        self.assertRegex(
            self.text,
            r"(?m)^on:\n  push:\n    tags:\s*\[\s*['\"]v\*['\"]\s*\]\s*$",
        )
        self.assertNotIn("release:", self.text)
        self.assertNotIn("workflow_dispatch:", self.text)
        self.assertNotIn("pull_request:", self.text)

    def test_permissions_are_exactly_minimal_for_publication_and_attestation(self):
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
            {"contents": "write", "id-token": "write", "attestations": "write"},
        )
        self.assertNotIn("secrets.", self.text)
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.text)

    def test_ci_checks_out_the_pushed_tag_and_runs_checks_before_building(self):
        self.assertIn("runs-on: windows-latest", self.text)
        self.assertIn(f"actions/checkout@{CHECKOUT_SHA}", self.text)
        self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", self.text)
        self.assertIn(f"actions/attest@{ATTEST_SHA}", self.text)
        self.assertIn("ref: ${{ github.ref }}", self.text)
        self.assertRegex(self.text, r'''python-version:\s*["']?3\.11["']?''')
        self.assertIn("python -m unittest discover -s tests -v", self.text)
        self.assertIn("node --check desktop-plugin/plugin.js", self.text)

        tests_position = self.text.index("python -m unittest discover -s tests -v")
        node_position = self.text.index("node --check desktop-plugin/plugin.js")
        build_position = self.text.index("python scripts/build_skill_package.py --output-dir dist")
        self.assertLess(tests_position, node_position)
        self.assertLess(node_position, build_position)

    def test_build_exports_exactly_one_archive_and_checksum_for_later_steps(self):
        self.assertIn("python scripts/build_skill_package.py --output-dir dist", self.text)
        self.assertIn("Get-ChildItem -LiteralPath dist -Filter '*.zip' -File", self.text)
        self.assertIn("Get-ChildItem -LiteralPath dist -Filter '*.sha256' -File", self.text)
        self.assertGreaterEqual(self.text.count("Count -ne 1"), 2)
        for output in ("archive_path", "archive_name", "checksum_path", "checksum_name"):
            self.assertIn(f'"{output}=', self.text)
        self.assertIn("$env:GITHUB_OUTPUT", self.text)

    def test_integrity_gate_binds_tag_sidecar_and_archive_before_attestation(self):
        self.assertIn("RELEASE_TAG: ${{ github.ref_name }}", self.text)
        self.assertIn("ARCHIVE_PATH: ${{ steps.build.outputs.archive_path }}", self.text)
        self.assertIn("CHECKSUM_PATH: ${{ steps.build.outputs.checksum_path }}", self.text)
        self.assertIn("Get-FileHash -LiteralPath $env:ARCHIVE_PATH -Algorithm SHA256", self.text)
        self.assertIn("Get-Content -LiteralPath $env:CHECKSUM_PATH -Raw", self.text)
        self.assertIn("^VERSION\\s*=", self.text)
        self.assertIn('$expectedTag = "v$($versionMatch.Groups[\'version\'].Value)"', self.text)
        self.assertIn("if ($env:RELEASE_TAG -ne $expectedTag)", self.text)
        self.assertRegex(self.text, r"(?i)sidecar.*SHA-256|SHA-256.*sidecar")

    def test_attestation_precedes_release_creation_and_publish_uses_same_outputs(self):
        self.assertIn("subject-path: ${{ steps.build.outputs.archive_path }}", self.text)
        self.assertIn("ARCHIVE_NAME: ${{ steps.build.outputs.archive_name }}", self.text)
        self.assertIn("CHECKSUM_NAME: ${{ steps.build.outputs.checksum_name }}", self.text)
        self.assertIn(
            "gh release create $env:RELEASE_TAG $env:ARCHIVE_PATH $env:CHECKSUM_PATH",
            self.text,
        )
        self.assertIn("--verify-tag", self.text)
        self.assertIn("--generate-notes", self.text)
        self.assertNotIn("--clobber", self.text)
        self.assertNotIn("gh release upload", self.text)
        self.assertNotIn("gh release delete", self.text)

        build_position = self.text.index("python scripts/build_skill_package.py --output-dir dist")
        gate_position = self.text.index("Get-FileHash -LiteralPath $env:ARCHIVE_PATH -Algorithm SHA256")
        attest_position = self.text.index(f"actions/attest@{ATTEST_SHA}")
        release_position = self.text.index("gh release create $env:RELEASE_TAG")
        self.assertLess(build_position, gate_position)
        self.assertLess(gate_position, attest_position)
        self.assertLess(attest_position, release_position)


if __name__ == "__main__":
    unittest.main()

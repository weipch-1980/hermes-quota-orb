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

    def test_ci_checks_out_tag_and_runs_all_checks_before_both_builders(self):
        self.assertIn("runs-on: windows-latest", self.text)
        self.assertIn(f"actions/checkout@{CHECKOUT_SHA}", self.text)
        self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", self.text)
        self.assertEqual(self.text.count(f"actions/attest@{ATTEST_SHA}"), 2)
        self.assertIn("ref: ${{ github.ref }}", self.text)
        self.assertRegex(self.text, r'''python-version:\s*["']?3\.11["']?''')
        self.assertIn("python -m pip install --disable-pip-version-check .", self.text)
        install_position = self.text.index("python -m pip install --disable-pip-version-check .")
        tests_position = self.text.index("python -m unittest discover -s tests -v")
        node_position = self.text.index("node --check desktop-plugin/plugin.js")
        skill_position = self.text.index("python scripts/build_skill_package.py --output-dir dist")
        universal_position = self.text.index("python scripts/build_universal_package.py --output-dir dist")
        self.assertLess(install_position, tests_position)
        self.assertLess(tests_position, node_position)
        self.assertLess(node_position, skill_position)
        self.assertLess(skill_position, universal_position)

    def test_ci_installs_only_the_plugin_test_dependencies_outside_runtime_metadata(self):
        self.assertIn(
            "python -m pip install --disable-pip-version-check fastapi==0.139.2 PyYAML==6.0.3",
            self.text,
        )
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("fastapi", project.lower())
        self.assertNotIn("pyyaml", project.lower())

    def test_every_native_command_throws_before_the_workflow_can_continue(self):
        native_commands = (
            "python -m pip install --disable-pip-version-check .",
            "python -m pip install --disable-pip-version-check fastapi==0.139.2 PyYAML==6.0.3",
            "python -m unittest discover -s tests -v",
            "node --check desktop-plugin/plugin.js",
            "python scripts/build_skill_package.py --output-dir dist",
            "python scripts/build_universal_package.py --output-dir dist",
            "gh release create $env:RELEASE_TAG $env:SKILL_ARCHIVE_PATH $env:SKILL_CHECKSUM_PATH $env:UNIVERSAL_ARCHIVE_PATH $env:UNIVERSAL_CHECKSUM_PATH --verify-tag --title \"Quota Orb $env:RELEASE_TAG\" --generate-notes",
        )
        for command in native_commands:
            with self.subTest(command=command):
                self.assertRegex(
                    self.text,
                    re.escape(command)
                    + r"\r?\n\s+if \(\$LASTEXITCODE -ne 0\) \{\r?\n\s+throw ",
                )

    def test_build_exports_exactly_two_archives_and_two_checksums(self):
        self.assertIn("Expected exactly two release ZIPs", self.text)
        self.assertIn("Expected exactly two release SHA-256 sidecars", self.text)
        self.assertGreaterEqual(self.text.count("Count -ne 2"), 2)
        for prefix in ("skill", "universal"):
            for suffix in ("archive_path", "archive_name", "checksum_path", "checksum_name"):
                self.assertIn(f'"{prefix}_{suffix}=', self.text)
        self.assertIn("$env:GITHUB_OUTPUT", self.text)

    def test_integrity_gate_binds_tag_names_and_both_sidecars(self):
        self.assertIn("RELEASE_TAG: ${{ github.ref_name }}", self.text)
        for prefix in ("SKILL", "UNIVERSAL"):
            self.assertIn(f"{prefix}_ARCHIVE_PATH: ${{{{ steps.build.outputs.{prefix.lower()}_archive_path }}}}", self.text)
            self.assertIn(f"{prefix}_CHECKSUM_PATH: ${{{{ steps.build.outputs.{prefix.lower()}_checksum_path }}}}", self.text)
        self.assertIn("quota-orb-skill-v$version.zip", self.text)
        self.assertIn("quota-orb-universal-v$version.zip", self.text)
        self.assertIn("function Assert-Sidecar", self.text)
        self.assertGreaterEqual(self.text.count("Assert-Sidecar -ArchivePath"), 2)
        self.assertIn("Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256", self.text)
        self.assertIn("^VERSION\\s*=", self.text)
        self.assertIn('$expectedTag = "v$version"', self.text)
        self.assertIn("if ($env:RELEASE_TAG -ne $expectedTag)", self.text)

    def test_both_attestations_precede_single_non_clobbering_release(self):
        self.assertIn("subject-path: ${{ steps.build.outputs.skill_archive_path }}", self.text)
        self.assertIn("subject-path: ${{ steps.build.outputs.universal_archive_path }}", self.text)
        release_command = (
            "gh release create $env:RELEASE_TAG $env:SKILL_ARCHIVE_PATH "
            "$env:SKILL_CHECKSUM_PATH $env:UNIVERSAL_ARCHIVE_PATH "
            "$env:UNIVERSAL_CHECKSUM_PATH"
        )
        self.assertIn(release_command, self.text)
        self.assertIn("--verify-tag", self.text)
        self.assertIn("--generate-notes", self.text)
        self.assertNotIn("--clobber", self.text)
        self.assertNotIn("gh release upload", self.text)
        self.assertNotIn("gh release delete", self.text)

        gate_position = self.text.index("Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256")
        attest_positions = [
            match.start()
            for match in re.finditer(f"actions/attest@{ATTEST_SHA}", self.text)
        ]
        release_position = self.text.index("gh release create $env:RELEASE_TAG")
        self.assertEqual(len(attest_positions), 2)
        self.assertLess(gate_position, attest_positions[0])
        self.assertLess(attest_positions[0], attest_positions[1])
        self.assertLess(attest_positions[1], release_position)


if __name__ == "__main__":
    unittest.main()

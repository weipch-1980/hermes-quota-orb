from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from _windows_output_parent_swap import WindowsOutputDirectoryParentSwap


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_universal_package import PACKAGE_NAME, VERSION, build
from scripts.build_skill_package import UnsafePackagePathError


class UniversalPackageTests(unittest.TestCase):
    def test_builds_reproducible_universal_zip_and_checksum(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            archive_a, checksum_a = build(ROOT, Path(first))
            archive_b, checksum_b = build(ROOT, Path(second))

            self.assertEqual(VERSION, "0.4.0")
            self.assertEqual(archive_a.name, f"{PACKAGE_NAME}.zip")
            self.assertEqual(archive_a.read_bytes(), archive_b.read_bytes())
            self.assertEqual(checksum_a.read_bytes(), checksum_b.read_bytes())
            digest = hashlib.sha256(archive_a.read_bytes()).hexdigest()
            self.assertEqual(
                checksum_a.read_text(encoding="utf-8"),
                f"{digest}  {archive_a.name}\n",
            )

            with zipfile.ZipFile(archive_a) as bundle:
                names = bundle.namelist()
                required = {
                    "quota-orb-universal/pyproject.toml",
                    "quota-orb-universal/README.md",
                    "quota-orb-universal/LICENSE",
                    "quota-orb-universal/quota_orb/core.py",
                    "quota-orb-universal/quota_orb/sources.py",
                    "quota-orb-universal/quota_orb/mcp_server.py",
                    "quota-orb-universal/quota_orb/desktop_widget.py",
                    "quota-orb-universal/quota_orb/assets/quota_orb_app.html",
                    "quota-orb-universal/skills/quota-orb/SKILL.md",
                    "quota-orb-universal/scripts/install_agent_skill.py",
                    "quota-orb-universal/adapters/chatgpt/SKILL.md",
                    "quota-orb-universal/adapters/codex/SKILL.md",
                    "quota-orb-universal/adapters/cursor/SKILL.md",
                    "quota-orb-universal/adapters/copilot/SKILL.md",
                    "quota-orb-universal/adapters/claude/SKILL.md",
                    "quota-orb-universal/adapters/claude/mcp.json.example",
                    "quota-orb-universal/adapters/gemini/SKILL.md",
                    "quota-orb-universal/adapters/gemini/settings.json.example",
                    "quota-orb-universal/adapters/gemini/antigravity-mcp.json.example",
                    "quota-orb-universal/adapters/qwen/SKILL.md",
                    "quota-orb-universal/adapters/qwen/settings.json.example",
                    "quota-orb-universal/adapters/kimi/SKILL.md",
                    "quota-orb-universal/adapters/kimi/mcp.json.example",
                    "quota-orb-universal/adapters/openclaw/SKILL.md",
                    "quota-orb-universal/adapters/openclaw/README.md",
                    "quota-orb-universal/adapters/workbuddy/SKILL.md",
                    "quota-orb-universal/adapters/workbuddy/README.md",
                    "quota-orb-universal/adapters/workbuddy/mcp.json.example",
                    "quota-orb-universal/adapters/china-top-five/README.md",
                    "quota-orb-universal/adapters/hermes/README.md",
                    "quota-orb-universal/skill/quota-orb/SKILL.md",
                }
                self.assertTrue(required.issubset(names))
                self.assertEqual(names, sorted(names))
                self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
                self.assertFalse(any(name.startswith("quota-orb-universal/.git/") for name in names))
                for info in bundle.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual((info.external_attr >> 16) & 0o777, 0o644)
                content = b"\n".join(bundle.read(name) for name in names)
                for marker in (b"BEGIN PRIVATE KEY", b"ghp_", b"sk-ant-", b"AIza"):
                    self.assertNotIn(marker, content)

    def test_extracted_universal_package_installs_codex_skill_without_hermes(self):
        with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as extracted:
            archive, _checksum = build(ROOT, Path(output))
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)
            package = Path(extracted) / "quota-orb-universal"
            installer = package / "scripts" / "install_agent_skill.py"

            targets = {
                "codex": Path(".agents/skills/quota-orb/SKILL.md"),
                "workbuddy-code": Path(".codebuddy/skills/quota-orb/SKILL.md"),
            }
            for target, relative in targets.items():
                with self.subTest(target=target):
                    home = Path(extracted) / f"customer-home-{target}"
                    preview = subprocess.run(
                        [sys.executable, str(installer), "--target", target, "--home", str(home)],
                        cwd=package,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    destination = home / relative
                    self.assertFalse(destination.exists())

                    applied = subprocess.run(
                        [
                            sys.executable,
                            str(installer),
                            "--target",
                            target,
                            "--home",
                            str(home),
                            "--apply",
                        ],
                        cwd=package,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                    self.assertEqual(
                        destination.read_bytes(),
                        (package / "skills" / "quota-orb" / "SKILL.md").read_bytes(),
                    )
                    self.assertFalse((home / ".hermes").exists())

    def test_build_blocks_parent_swap_before_junction_creation(self):
        if os.name != "nt":
            self.skipTest("Windows output-directory swap test")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "dist"
            moved = root / "dist-moved"
            outside = root / "outside"
            output.mkdir()
            outside.mkdir()
            attack = WindowsOutputDirectoryParentSwap(
                output_directory=output,
                moved_directory=moved,
                external_directory=outside,
                archive_name=f"{PACKAGE_NAME}.zip",
                sidecar_name=f"{PACKAGE_NAME}.sha256",
            )
            original_replace = os.replace
            os.replace = attack.wrap(original_replace)
            archive = checksum = None
            build_error = None
            try:
                try:
                    archive, checksum = build(ROOT, output)
                except Exception as exc:
                    build_error = exc
            finally:
                os.replace = original_replace
            try:
                if attack.rename_succeeded:
                    self.assertTrue(attack.junction_attempted)
                    self.assertTrue(attack.junction_created, attack.junction_result)
                    self.assertTrue(attack.junction_points_to_external, attack.junction_result)
                    self.assertEqual(attack.external_outputs(), ())
                    self.fail("output directory rename unexpectedly succeeded")

                if build_error is not None:
                    raise build_error
                self.assertTrue(attack.rename_attempted)
                self.assertIsNotNone(attack.rename_error)
                self.assertIn(attack.rename_error.winerror, (5, 32))
                self.assertFalse(attack.junction_attempted)
                self.assertFalse(attack.junction_created)
                self.assertFalse(attack.junction_points_to_external)
                self.assertIsNotNone(archive)
                self.assertIsNotNone(checksum)
                self.assertTrue(archive.is_file())
                self.assertTrue(checksum.is_file())
            finally:
                attack.cleanup()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support unavailable")
    def test_rejects_symlink_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            real_output = temp_root / "real-output"
            real_output.mkdir()
            linked_output = temp_root / "linked-output"
            try:
                linked_output.symlink_to(real_output, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")

            with self.assertRaises(UnsafePackagePathError):
                build(ROOT, linked_output)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support unavailable")
    def test_rejects_symlink_inside_universal_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp) / "repo"
            for relative in ("quota_orb", "adapters", "skills", "skill/quota-orb"):
                (temp_root / relative).mkdir(parents=True, exist_ok=True)
                (temp_root / relative / "safe.txt").write_text("safe", encoding="utf-8")
            for name in ("pyproject.toml", "README.md", "LICENSE", "scripts/install_agent_skill.py"):
                path = temp_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("safe", encoding="utf-8")
            outside = Path(temp) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            link = temp_root / "adapters" / "escape.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(UnsafePackagePathError):
                build(temp_root, Path(temp) / "dist")


if __name__ == "__main__":
    unittest.main()

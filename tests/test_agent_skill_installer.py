from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "scripts" / "install_agent_skill.py"
CANONICAL_SKILL = ROOT / "skills" / "quota-orb" / "SKILL.md"
TARGETS = {
    "codex": Path(".agents/skills/quota-orb/SKILL.md"),
    "claude": Path(".claude/skills/quota-orb/SKILL.md"),
    "antigravity": Path(".gemini/config/skills/quota-orb/SKILL.md"),
    "gemini-cli": Path(".gemini/skills/quota-orb/SKILL.md"),
    "cursor": Path(".cursor/skills/quota-orb/SKILL.md"),
    "copilot": Path(".copilot/skills/quota-orb/SKILL.md"),
    "qwen-code": Path(".qwen/skills/quota-orb/SKILL.md"),
    "kimi-cli": Path(".kimi/skills/quota-orb/SKILL.md"),
    "workbuddy-code": Path(".codebuddy/skills/quota-orb/SKILL.md"),
}


def load_installer():
    spec = importlib.util.spec_from_file_location("quota_orb_agent_installer", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentSkillInstallerTests(unittest.TestCase):
    def run_installer(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(INSTALLER), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_target_is_required_and_hermes_is_not_supported(self):
        missing = self.run_installer()
        self.assertNotEqual(missing.returncode, 0)

        help_result = self.run_installer("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("codex", help_result.stdout)
        self.assertIn("claude", help_result.stdout)
        self.assertIn("antigravity", help_result.stdout)
        self.assertIn("gemini-cli", help_result.stdout)
        self.assertIn("cursor", help_result.stdout)
        self.assertIn("copilot", help_result.stdout)
        self.assertIn("qwen-code", help_result.stdout)
        self.assertIn("kimi-cli", help_result.stdout)
        self.assertNotIn("hermes", help_result.stdout.lower())

    def test_preview_and_apply_install_only_the_selected_global_agent_skill(self):
        canonical = CANONICAL_SKILL.read_bytes()
        for target, relative in TARGETS.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                home = Path(temp) / "home"
                preview = self.run_installer("--target", target, "--home", str(home))
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertIn("preview", preview.stdout.lower())
                self.assertFalse((home / relative).exists())

                applied = self.run_installer(
                    "--target", target,
                    "--home", str(home),
                    "--apply",
                )
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertEqual((home / relative).read_bytes(), canonical)
                self.assertFalse((home / ".hermes").exists())

                repeated = self.run_installer(
                    "--target", target,
                    "--home", str(home),
                    "--apply",
                )
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                self.assertIn("identical", repeated.stdout.lower())

    def test_conflicting_skill_is_preserved_and_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            destination = home / TARGETS["codex"]
            destination.parent.mkdir(parents=True)
            destination.write_text("customer content", encoding="utf-8")

            result = self.run_installer(
                "--target", "codex",
                "--home", str(home),
                "--apply",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_text(encoding="utf-8"), "customer content")
            self.assertIn("conflict", result.stderr.lower())

    @unittest.skipUnless(os.name == "nt", "Windows parent swap race")
    def test_commit_blocks_parent_junction_swap_before_link(self):
        module = load_installer()

        class ParentSwapBlocked(Exception):
            pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            outside = root / "outside"
            detached = root / "detached-parent"
            outside.mkdir()
            swap_blocked = False
            swapped = False
            original_link = module.os.link

            def racing_link(temporary, destination, *args, **kwargs):
                nonlocal swap_blocked, swapped
                parent = Path(destination).parent
                try:
                    parent.rename(detached)
                except OSError as exc:
                    swap_blocked = True
                    raise ParentSwapBlocked from exc

                swapped = True
                created = subprocess.run(
                    ["cmd.exe", "/c", "mklink", "/J", str(parent), str(outside)],
                    text=True,
                    encoding="mbcs",
                    errors="replace",
                    capture_output=True,
                )
                if created.returncode != 0:
                    raise unittest.SkipTest(
                        f"junction creation failed: {created.stdout} {created.stderr}"
                    )
                return original_link(
                    detached / Path(temporary).name,
                    destination,
                    *args,
                    **kwargs,
                )

            module.os.link = racing_link
            try:
                with self.assertRaises(ParentSwapBlocked):
                    module.install("codex", home, apply=True)
            finally:
                module.os.link = original_link
                destination_parent = home / ".agents" / "skills" / "quota-orb"
                if os.path.lexists(destination_parent):
                    subprocess.run(
                        ["cmd.exe", "/c", "rmdir", str(destination_parent)],
                        check=False,
                        capture_output=True,
                    )
                if detached.exists():
                    destination_parent.parent.mkdir(parents=True, exist_ok=True)
                    detached.rename(destination_parent)

            self.assertTrue(swap_blocked, "the guarded parent rename was not attempted")
            self.assertFalse(swapped, "the destination parent was swapped during commit")
            self.assertFalse(any(outside.iterdir()), "Agent install wrote outside selected home")

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlink support unavailable")
    def test_symlinked_destination_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            outside = root / "outside"
            outside.mkdir()
            (home / ".agents").mkdir(parents=True)
            link = home / ".agents" / "skills"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")

            result = self.run_installer(
                "--target", "codex",
                "--home", str(home),
                "--apply",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((outside / "quota-orb" / "SKILL.md").exists())
            self.assertIn("symlink", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skill" / "quota-orb" / "scripts" / "install.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("quota_orb_installer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerTests(unittest.TestCase):
    def test_dry_run_lists_files_without_writing(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            plan = module.install(skill_dir=SCRIPT.parents[1], hermes_home=home, apply=False)
            self.assertEqual(len(plan), 4)
            self.assertFalse(home.exists())
            destinations = {item["destination"].relative_to(home).as_posix() for item in plan}
            self.assertEqual(
                destinations,
                {
                    "desktop-plugins/quota-orb/plugin.js",
                    "plugins/quota-orb/plugin.yaml",
                    "plugins/quota-orb/dashboard/manifest.json",
                    "plugins/quota-orb/dashboard/plugin_api.py",
                },
            )

    def test_apply_copies_all_assets(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            plan = module.install(skill_dir=SCRIPT.parents[1], hermes_home=home, apply=True)
            self.assertTrue(all(item["destination"].is_file() for item in plan))
            self.assertIn("id: ID", (home / "desktop-plugins" / "quota-orb" / "plugin.js").read_text(encoding="utf-8"))
            self.assertIn("APIRouter", (home / "plugins" / "quota-orb" / "dashboard" / "plugin_api.py").read_text(encoding="utf-8"))

    def test_apply_refuses_to_overwrite_unknown_files(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            destination = home / "desktop-plugins" / "quota-orb" / "plugin.js"
            destination.parent.mkdir(parents=True)
            destination.write_text("unknown local plugin", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                module.install(skill_dir=SCRIPT.parents[1], hermes_home=home, apply=True)
            self.assertEqual(destination.read_text(encoding="utf-8"), "unknown local plugin")
            self.assertFalse((home / "plugins" / "quota-orb" / "plugin.yaml").exists())

    def test_apply_force_explicitly_overwrites_unknown_files(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            destination = home / "desktop-plugins" / "quota-orb" / "plugin.js"
            destination.parent.mkdir(parents=True)
            destination.write_text("unknown local plugin", encoding="utf-8")
            module.install(skill_dir=SCRIPT.parents[1], hermes_home=home, apply=True, force=True)
            self.assertIn("id: ID", destination.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "Windows parent swap race")
    def test_force_commit_blocks_parent_junction_swap_before_replace(self):
        module = load_installer()

        class ParentSwapBlocked(Exception):
            pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "hermes"
            outside = root / "outside"
            detached = root / "detached-parent"
            home.mkdir()
            outside.mkdir()
            swap_blocked = False
            swapped = False
            original_replace = module.os.replace

            def racing_replace(temporary, destination):
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
                # Keep the temporary source reachable from the detached trusted
                # directory while the destination path now resolves through the
                # real junction. This models the vulnerable path-based commit.
                return original_replace(detached / Path(temporary).name, destination)

            module.os.replace = racing_replace
            try:
                with self.assertRaises(ParentSwapBlocked):
                    module.install(
                        skill_dir=SCRIPT.parents[1],
                        hermes_home=home,
                        apply=True,
                        force=True,
                    )
            finally:
                module.os.replace = original_replace
                if os.path.lexists(home / "desktop-plugins" / "quota-orb"):
                    subprocess.run(
                        [
                            "cmd.exe",
                            "/c",
                            "rmdir",
                            str(home / "desktop-plugins" / "quota-orb"),
                        ],
                        check=False,
                        capture_output=True,
                    )
                if detached.exists():
                    detached.rename(home / "desktop-plugins" / "quota-orb")

            self.assertTrue(swap_blocked, "the guarded parent rename was not attempted")
            self.assertFalse(swapped, "the destination parent was swapped during commit")
            self.assertFalse(any(outside.iterdir()), "force install wrote outside HERMES_HOME")

    def test_apply_rejects_symlinked_source_asset(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "quota-orb"
            shutil.copytree(SCRIPT.parents[1], skill)
            outside = root / "outside-plugin.js"
            outside.write_text("outside source", encoding="utf-8")
            source = skill / "assets" / "desktop-plugin" / "plugin.js"
            source.unlink()
            try:
                source.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            home = root / "hermes"
            with self.assertRaises(ValueError):
                module.install(skill_dir=skill, hermes_home=home, apply=True, force=True)
            self.assertFalse(home.exists())

    def test_apply_rejects_source_content_mutation_with_unchanged_identity(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "quota-orb"
            shutil.copytree(SCRIPT.parents[1], skill)
            source = skill / "assets" / "desktop-plugin" / "plugin.js"
            before = source.stat()
            original_fdopen = module.os.fdopen
            mutated = False

            def mutate_source():
                nonlocal mutated
                if mutated:
                    return
                mutated = True
                original = source.read_bytes()
                replacement = bytes([original[0] ^ 1]) + original[1:]
                with source.open("r+b") as stream:
                    stream.write(replacement)
                    stream.flush()
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

            class MutatingStream:
                def __init__(self, stream):
                    self._stream = stream

                def __enter__(self):
                    self._stream.__enter__()
                    return self

                def __exit__(self, *args):
                    return self._stream.__exit__(*args)

                def read(self, *args, **kwargs):
                    content = self._stream.read(*args, **kwargs)
                    mutate_source()
                    return content

                def __getattr__(self, name):
                    return getattr(self._stream, name)

            def mutating_fdopen(descriptor, *args, **kwargs):
                return MutatingStream(original_fdopen(descriptor, *args, **kwargs))

            module.os.fdopen = mutating_fdopen
            home = root / "hermes"
            try:
                with self.assertRaises(module.UnsafeInstallPathError):
                    module.install(
                        skill_dir=skill,
                        hermes_home=home,
                        apply=True,
                        force=True,
                    )
            finally:
                module.os.fdopen = original_fdopen

            after = source.stat()
            self.assertTrue(mutated)
            self.assertEqual(after.st_size, before.st_size)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
            self.assertFalse(home.exists())

    def test_apply_rejects_symlinked_destination_parent_without_outside_write(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "hermes"
            outside = root / "outside"
            home.mkdir()
            outside.mkdir()
            linked_parent = home / "desktop-plugins"
            try:
                linked_parent.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(ValueError):
                module.install(
                    skill_dir=SCRIPT.parents[1],
                    hermes_home=home,
                    apply=True,
                    force=True,
                )
            self.assertFalse((outside / "quota-orb" / "plugin.js").exists())
            self.assertFalse((home / "plugins").exists())

    def test_apply_rejects_symlinked_hermes_home_ancestor(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real_ancestor = root / "real-ancestor"
            linked_ancestor = root / "linked-ancestor"
            real_ancestor.mkdir()
            try:
                linked_ancestor.symlink_to(real_ancestor, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            home = linked_ancestor / "hermes"
            with self.assertRaises(ValueError):
                module.install(
                    skill_dir=SCRIPT.parents[1],
                    hermes_home=home,
                    apply=True,
                    force=True,
                )
            self.assertFalse(
                (real_ancestor / "hermes" / "desktop-plugins" / "quota-orb" / "plugin.js").exists()
            )

    def test_apply_creates_nested_missing_hermes_home(self):
        module = load_installer()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "missing-a" / "missing-b" / "hermes"
            plan = module.install(
                skill_dir=SCRIPT.parents[1],
                hermes_home=home,
                apply=True,
            )
            self.assertTrue(all(item["destination"].is_file() for item in plan))

    def test_apply_rechecks_conflict_created_after_preflight(self):
        module = load_installer()
        original_atomic_write = module._atomic_write
        injected = False

        def inject_conflict(*args, **kwargs):
            nonlocal injected
            destination = args[0]
            if not injected:
                injected = True
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("raced local plugin", encoding="utf-8")
            return original_atomic_write(*args, **kwargs)

        module._atomic_write = inject_conflict
        try:
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp) / "hermes"
                destination = home / "desktop-plugins" / "quota-orb" / "plugin.js"
                with self.assertRaises(FileExistsError):
                    module.install(
                        skill_dir=SCRIPT.parents[1],
                        hermes_home=home,
                        apply=True,
                    )
                self.assertEqual(
                    destination.read_text(encoding="utf-8"),
                    "raced local plugin",
                )
                self.assertFalse((home / "plugins").exists())
        finally:
            module._atomic_write = original_atomic_write


if __name__ == "__main__":
    unittest.main()

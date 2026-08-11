from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_skill_package.py"
PACKAGE_VERSION = "0.3.1"
PACKAGE_ARCHIVE = f"quota-orb-skill-v{PACKAGE_VERSION}.zip"


def load_builder():
    spec = importlib.util.spec_from_file_location("quota_orb_package_builder", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleasePackageTests(unittest.TestCase):
    def test_builds_reproducible_skill_zip_and_checksum(self):
        self.assertTrue(SCRIPT.is_file())
        module = load_builder()
        self.assertEqual(module.VERSION, PACKAGE_VERSION)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            archive_a, checksum_a = module.build(repository_root=ROOT, output_dir=Path(first))
            archive_b, checksum_b = module.build(repository_root=ROOT, output_dir=Path(second))
            self.assertEqual(archive_a.name, PACKAGE_ARCHIVE)
            self.assertEqual(hashlib.sha256(archive_a.read_bytes()).digest(), hashlib.sha256(archive_b.read_bytes()).digest())
            self.assertEqual(checksum_a.read_text(encoding="utf-8"), checksum_b.read_text(encoding="utf-8"))
            digest, filename = checksum_a.read_text(encoding="utf-8").strip().split("  ", 1)
            self.assertEqual(filename, archive_a.name)
            self.assertEqual(digest, hashlib.sha256(archive_a.read_bytes()).hexdigest())
            with zipfile.ZipFile(archive_a) as bundle:
                names = set(bundle.namelist())
            self.assertIn("quota-orb/SKILL.md", names)
            self.assertIn("quota-orb/LICENSE", names)
            self.assertIn("quota-orb/scripts/install.py", names)
            self.assertIn("quota-orb/assets/desktop-plugin/plugin.js", names)
            self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_build_rejects_windows_junction_outside_skill_root(self):
        if os.name != "nt":
            self.skipTest("Windows junction test")
        module = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = root / "repository"
            skill = repository / "skill" / "quota-orb"
            shutil.copytree(ROOT / "skill" / "quota-orb", skill)
            outside = root / "outside-secret"
            outside.mkdir()
            (outside / "leak.txt").write_text("outside-secret", encoding="utf-8")
            junction = skill / "assets" / "junction-dir"
            created = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                text=True,
                encoding="mbcs",
                errors="replace",
                capture_output=True,
            )
            if created.returncode != 0:
                self.skipTest(f"junctions unavailable: {created.stdout} {created.stderr}")

            output = root / "dist"
            with self.assertRaises(ValueError):
                module.build(repository_root=repository, output_dir=output)
            self.assertFalse((output / PACKAGE_ARCHIVE).exists())

    def test_build_rejects_source_content_mutation_with_unchanged_identity(self):
        module = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = root / "repository"
            skill = repository / "skill" / "quota-orb"
            shutil.copytree(ROOT / "skill" / "quota-orb", skill)
            source = skill / "0-mutation.txt"
            source.write_bytes(b"stable source bytes\n")
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
            output = root / "dist"
            try:
                with self.assertRaises(module.UnsafePackagePathError):
                    module.build(repository_root=repository, output_dir=output)
            finally:
                module.os.fdopen = original_fdopen

            after = source.stat()
            self.assertTrue(mutated)
            self.assertEqual(after.st_size, before.st_size)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
            self.assertFalse((output / PACKAGE_ARCHIVE).exists())


if __name__ == "__main__":
    unittest.main()

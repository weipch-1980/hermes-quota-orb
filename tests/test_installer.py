from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()

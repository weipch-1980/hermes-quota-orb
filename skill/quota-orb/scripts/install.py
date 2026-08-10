from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
from typing import Any


ASSET_MAP = (
    ("assets/desktop-plugin/plugin.js", "desktop-plugins/quota-orb/plugin.js"),
    ("assets/hermes-plugin/plugin.yaml", "plugins/quota-orb/plugin.yaml"),
    ("assets/hermes-plugin/dashboard/manifest.json", "plugins/quota-orb/dashboard/manifest.json"),
    ("assets/hermes-plugin/dashboard/plugin_api.py", "plugins/quota-orb/dashboard/plugin_api.py"),
)


def default_hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def install(*, skill_dir: Path, hermes_home: Path, apply: bool) -> list[dict[str, Any]]:
    skill_dir = Path(skill_dir).resolve()
    hermes_home = Path(hermes_home).expanduser().resolve()
    plan = [
        {
            "source": skill_dir / source,
            "destination": hermes_home / destination,
        }
        for source, destination in ASSET_MAP
    ]

    missing = [str(item["source"]) for item in plan if not item["source"].is_file()]
    if missing:
        raise FileNotFoundError("Missing Quota Orb assets: " + ", ".join(missing))

    if apply:
        for item in plan:
            destination = item["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item["source"], destination)

    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the Quota Orb Hermes Desktop plugin.")
    parser.add_argument("--hermes-home", type=Path, default=default_hermes_home())
    parser.add_argument("--apply", action="store_true", help="Copy files. Without this flag, only show the plan.")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    plan = install(skill_dir=skill_dir, hermes_home=args.hermes_home, apply=args.apply)
    verb = "Installed" if args.apply else "Would install"
    print(f"{verb} Quota Orb files:")
    for item in plan:
        print(f"  {item['source']} -> {item['destination']}")
    if args.apply:
        print("Backend files copied. Enable quota-orb as described in SKILL.md, then restart Hermes Desktop once.")
    else:
        print("Dry run only. Re-run with --apply after approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

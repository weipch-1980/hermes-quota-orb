from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

try:
    from .build_skill_package import (
        VERSION,
        _absolute,
        _assert_safe_directory,
        _is_relative_to,
        _output_directory_guard,
        _read_output_file,
        _read_regular_file_no_follow,
        _skill_payloads,
        _write_atomic,
        _write_zip_atomic,
    )
except ImportError:  # Direct script execution.
    from build_skill_package import (  # type: ignore[no-redef]
        VERSION,
        _absolute,
        _assert_safe_directory,
        _is_relative_to,
        _output_directory_guard,
        _read_output_file,
        _read_regular_file_no_follow,
        _skill_payloads,
        _write_atomic,
        _write_zip_atomic,
    )


PACKAGE_NAME = f"quota-orb-universal-v{VERSION}"
ARCHIVE_ROOT = "quota-orb-universal"
_SOURCE_TREES = (
    ("quota_orb", "quota_orb"),
    ("adapters", "adapters"),
    ("skills", "skills"),
    ("skill/quota-orb", "skill/quota-orb"),
)
_REQUIRED_ROOT_FILES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "scripts/install_agent_skill.py",
)
_OPTIONAL_ROOT_FILES = ("SECURITY.md", "CHANGELOG.md")


def build(repository_root: Path | str, output_dir: Path | str) -> tuple[Path, Path]:
    """Build the reproducible cross-platform Quota Orb distribution."""
    repository_root = _absolute(repository_root)
    resolved_root = repository_root.resolve(strict=True)
    _assert_safe_directory(repository_root, resolved_root, "Repository root")

    output_dir = _absolute(output_dir)
    archive = output_dir / f"{PACKAGE_NAME}.zip"
    checksum = output_dir / f"{PACKAGE_NAME}.sha256"
    excluded_paths = {archive, checksum}
    payloads: list[tuple[str, bytes]] = []

    for source_relative, archive_relative in _SOURCE_TREES:
        source_root = repository_root / source_relative
        if not os.path.lexists(source_root):
            raise FileNotFoundError(f"Universal source directory does not exist: {source_root}")
        excluded_root = (
            output_dir
            if output_dir != source_root and _is_relative_to(output_dir, source_root)
            else None
        )
        payloads.extend(
            _skill_payloads(
                source_root,
                excluded_root,
                excluded_paths,
                archive_root=f"{ARCHIVE_ROOT}/{archive_relative}",
            )
        )

    for name in _REQUIRED_ROOT_FILES:
        path = repository_root / name
        if not os.path.lexists(path):
            raise FileNotFoundError(f"Universal source file does not exist: {path}")
        payloads.append(
            (
                f"{ARCHIVE_ROOT}/{name}",
                _read_regular_file_no_follow(path, resolved_root, "Universal source"),
            )
        )
    for name in _OPTIONAL_ROOT_FILES:
        path = repository_root / name
        if os.path.lexists(path):
            payloads.append(
                (
                    f"{ARCHIVE_ROOT}/{name}",
                    _read_regular_file_no_follow(path, resolved_root, "Universal source"),
                )
            )

    payloads.sort(key=lambda item: item[0])
    names = [name for name, _ in payloads]
    if len(names) != len(set(names)):
        raise ValueError("Universal package contains duplicate archive paths.")

    with _output_directory_guard(output_dir) as output_descriptor:
        _write_zip_atomic(archive, payloads, output_descriptor)
        digest = hashlib.sha256(
            _read_output_file(archive, output_descriptor)
        ).hexdigest()
        _write_atomic(
            checksum,
            f"{digest}  {archive.name}\n".encode("utf-8"),
            output_descriptor,
        )
    return archive, checksum


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the reproducible Quota Orb cross-platform release package."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    archive, checksum = build(args.repository_root, args.output_dir)
    print(f"archive: {archive}")
    print(f"checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

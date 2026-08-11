from __future__ import annotations

import argparse
import hashlib
import os
import stat
import tempfile
import zipfile
from pathlib import Path


VERSION = "0.3.1"
PACKAGE_NAME = f"quota-orb-skill-v{VERSION}"
ARCHIVE_ROOT = "quota-orb"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class UnsafePackagePathError(ValueError):
    """Raised when release sources can escape the Skill root."""


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise UnsafePackagePathError(f"Cannot safely inspect {label}: {path}") from exc


def _is_link_or_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    info = info if info is not None else _lstat(path, "package path")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
    )


def _assert_resolved_within(path: Path, resolved_root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise UnsafePackagePathError(
            f"{label} resolves outside the Skill root: {path}"
        ) from exc
    return resolved


def _assert_safe_directory(path: Path, resolved_root: Path, label: str) -> os.stat_result:
    info = _lstat(path, label)
    if _is_link_or_reparse(path, info) or not stat.S_ISDIR(info.st_mode):
        raise UnsafePackagePathError(f"{label} is not a safe directory: {path}")
    _assert_resolved_within(path, resolved_root, label)
    return info


def _read_regular_file_no_follow(
    path: Path,
    resolved_root: Path,
    label: str,
) -> bytes:
    before = _lstat(path, label)
    if _is_link_or_reparse(path, before) or not stat.S_ISREG(before.st_mode):
        raise UnsafePackagePathError(f"{label} is not a safe regular file: {path}")
    _assert_resolved_within(path, resolved_root, label)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafePackagePathError(f"Cannot safely open {label}: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(before) != _stat_identity(opened):
            raise UnsafePackagePathError(f"{label} changed during packaging: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            content = stream.read()
            stream.seek(0)
            verification = stream.read()
        if content != verification:
            raise UnsafePackagePathError(f"{label} content changed during packaging: {path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    after = _lstat(path, label)
    if _is_link_or_reparse(path, after) or _stat_identity(before) != _stat_identity(after):
        raise UnsafePackagePathError(f"{label} changed during packaging: {path}")
    _assert_resolved_within(path, resolved_root, label)
    return content


def _skill_payloads(
    skill_root: Path,
    excluded_root: Path | None,
    excluded_paths: set[Path],
) -> list[tuple[str, bytes]]:
    resolved_root = skill_root.resolve(strict=True)
    _assert_safe_directory(skill_root, resolved_root, "Skill root")
    payloads: list[tuple[str, bytes]] = []

    def walk(directory: Path) -> None:
        before = _assert_safe_directory(directory, resolved_root, "Skill directory")
        try:
            with os.scandir(directory) as stream:
                entries = sorted(stream, key=lambda entry: entry.name)
        except OSError as exc:
            raise UnsafePackagePathError(
                f"Cannot safely scan Skill directory: {directory}"
            ) from exc

        for entry in entries:
            path = directory / entry.name
            try:
                relative = path.relative_to(skill_root)
            except ValueError as exc:
                raise UnsafePackagePathError(f"Package path escapes Skill root: {path}") from exc
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            if excluded_root is not None and (
                path == excluded_root or _is_relative_to(path, excluded_root)
            ):
                continue
            if path in excluded_paths:
                continue

            info = _lstat(path, "Skill source")
            if _is_link_or_reparse(path, info):
                raise UnsafePackagePathError(
                    f"Skill source is a symlink or reparse point: {path}"
                )
            _assert_resolved_within(path, resolved_root, "Skill source")
            if stat.S_ISDIR(info.st_mode):
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                payloads.append(
                    (
                        f"{ARCHIVE_ROOT}/{relative.as_posix()}",
                        _read_regular_file_no_follow(path, resolved_root, "Skill source"),
                    )
                )
            else:
                raise UnsafePackagePathError(
                    f"Skill source is not a regular file or directory: {path}"
                )

        after = _lstat(directory, "Skill directory")
        if _is_link_or_reparse(directory, after) or _stat_identity(before) != _stat_identity(after):
            raise UnsafePackagePathError(
                f"Skill directory changed during packaging: {directory}"
            )
        _assert_resolved_within(directory, resolved_root, "Skill directory")

    walk(skill_root)
    return sorted(payloads, key=lambda item: item[0])


def _zip_info(archive_name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=archive_name, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    info.internal_attr = 0
    info.flag_bits = 0x800
    info.extra = b""
    info.comment = b""
    return info


def _write_atomic(path: Path, content: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build(repository_root: Path | str, output_dir: Path | str) -> tuple[Path, Path]:
    """Build a reproducible ZIP containing only ``skill/quota-orb``."""
    repository_root = _absolute(repository_root)
    skill_root = repository_root / "skill" / "quota-orb"
    if not os.path.lexists(skill_root):
        raise FileNotFoundError(f"Skill directory does not exist: {skill_root}")

    output_dir = _absolute(output_dir)
    archive = output_dir / f"{PACKAGE_NAME}.zip"
    checksum = output_dir / f"{PACKAGE_NAME}.sha256"
    excluded_root = (
        output_dir
        if output_dir != skill_root and _is_relative_to(output_dir, skill_root)
        else None
    )

    payloads = _skill_payloads(
        skill_root,
        excluded_root,
        excluded_paths={archive, checksum},
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{archive.name}.",
        suffix=".tmp",
        dir=output_dir,
    )
    os.close(descriptor)
    temporary_archive = Path(temp_name)
    try:
        with zipfile.ZipFile(
            temporary_archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            for archive_name, content in payloads:
                bundle.writestr(_zip_info(archive_name), content)
        os.replace(temporary_archive, archive)
    finally:
        try:
            temporary_archive.unlink()
        except FileNotFoundError:
            pass

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    _write_atomic(checksum, f"{digest}  {archive.name}\n".encode("utf-8"))
    return archive, checksum


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the reproducible Quota Orb Hermes Skill release package."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: the repository containing this script).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Directory for the ZIP and SHA-256 file (default: dist).",
    )
    args = parser.parse_args()
    archive, checksum = build(args.repository_root, args.output_dir)
    print(f"archive: {archive}")
    print(f"checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

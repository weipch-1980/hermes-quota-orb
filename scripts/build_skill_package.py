from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


VERSION = "0.5.1"
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


def _prepare_safe_output_directory(path: Path) -> os.stat_result:
    chain: list[Path] = []
    current = path
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent

    def inspect_existing() -> None:
        for item in reversed(chain):
            if not os.path.lexists(item):
                continue
            info = _lstat(item, "output directory")
            if _is_link_or_reparse(item, info) or not stat.S_ISDIR(info.st_mode):
                raise UnsafePackagePathError(
                    f"Output directory contains an unsafe ancestor: {item}"
                )

    inspect_existing()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UnsafePackagePathError(f"Cannot safely create output directory: {path}") from exc
    inspect_existing()
    return _lstat(path, "output directory")


@contextmanager
def _windows_directory_handle(path: Path):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    file_read_attributes = 0x00000080
    delete_access = 0x00010000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        file_read_attributes | delete_access,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    handle_value = getattr(handle, "value", handle)
    if handle_value in (-1, invalid_handle):
        error = ctypes.get_last_error()
        raise UnsafePackagePathError(
            f"Cannot safely lock output directory: {path} (WinError {error})"
        )
    try:
        yield handle
    finally:
        close_handle(handle)


def _location_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _assert_output_descriptor_matches(path: Path, descriptor: int) -> None:
    try:
        path_info = os.lstat(path)
        descriptor_info = os.fstat(descriptor)
    except OSError as exc:
        raise UnsafePackagePathError(
            f"Cannot safely revalidate output directory: {path}"
        ) from exc
    if (
        _is_link_or_reparse(path, path_info)
        or not stat.S_ISDIR(descriptor_info.st_mode)
        or _location_identity(path_info) != _location_identity(descriptor_info)
    ):
        raise UnsafePackagePathError(
            f"Output directory changed while being secured: {path}"
        )


@contextmanager
def _output_directory_guard(path: Path):
    _prepare_safe_output_directory(path)
    if os.name == "nt":
        with _windows_directory_handle(path):
            _prepare_safe_output_directory(path)
            yield None
        return

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise UnsafePackagePathError(
            "Platform cannot safely lock output directory without following links"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafePackagePathError(
            f"Cannot safely lock output directory: {path}"
        ) from exc
    try:
        _assert_output_descriptor_matches(path, descriptor)
        _prepare_safe_output_directory(path)
        _assert_output_descriptor_matches(path, descriptor)
        yield descriptor
    finally:
        os.close(descriptor)


def _create_output_temporary(
    destination: Path,
    parent_descriptor: int | None,
) -> tuple[int, Path]:
    if parent_descriptor is None:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        return descriptor, Path(name)

    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | os.O_NOFOLLOW
    )
    for _ in range(128):
        name = f".{destination.name}.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        return descriptor, destination.parent / name
    raise UnsafePackagePathError(
        f"Cannot allocate a unique temporary output file for: {destination}"
    )


def _replace_output(
    temporary: Path,
    destination: Path,
    parent_descriptor: int | None,
) -> None:
    if parent_descriptor is None:
        os.replace(temporary, destination)
        return
    os.replace(
        temporary.name,
        destination.name,
        src_dir_fd=parent_descriptor,
        dst_dir_fd=parent_descriptor,
    )


def _unlink_output_temporary(
    temporary: Path,
    parent_descriptor: int | None,
) -> None:
    try:
        if parent_descriptor is None:
            temporary.unlink()
        else:
            os.unlink(temporary.name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        pass


def _read_output_file(path: Path, parent_descriptor: int | None) -> bytes:
    if parent_descriptor is None:
        return path.read_bytes()
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafePackagePathError(f"Output is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


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
    archive_root: str = ARCHIVE_ROOT,
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
                        f"{archive_root}/{relative.as_posix()}",
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


def _write_atomic(
    path: Path,
    content: bytes,
    parent_descriptor: int | None,
) -> None:
    descriptor, temporary = _create_output_temporary(path, parent_descriptor)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_output(temporary, path, parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_output_temporary(temporary, parent_descriptor)


def _write_zip_atomic(
    archive: Path,
    payloads: list[tuple[str, bytes]],
    parent_descriptor: int | None,
) -> None:
    descriptor, temporary = _create_output_temporary(archive, parent_descriptor)
    try:
        with os.fdopen(descriptor, "w+b", closefd=True) as stream:
            descriptor = -1
            with zipfile.ZipFile(
                stream,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as bundle:
                for archive_name, content in payloads:
                    bundle.writestr(_zip_info(archive_name), content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_output(temporary, archive, parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        _unlink_output_temporary(temporary, parent_descriptor)


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

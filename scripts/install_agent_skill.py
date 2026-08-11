from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


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


class UnsafeInstallPathError(ValueError):
    """Raised when a global Agent Skill destination is unsafe."""


class InstallConflictError(FileExistsError):
    """Raised when an existing Skill differs from the package."""


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _components(path: Path) -> list[Path]:
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    result = [current]
    for part in absolute.parts[1:]:
        current = current / part
        result.append(current)
    return result


def _assert_no_link_ancestors(path: Path, label: str) -> None:
    for component in _components(path):
        if os.path.lexists(component) and _is_link_or_reparse(component):
            raise UnsafeInstallPathError(
                f"{label} contains a symlink or reparse point: {component}"
            )


def _assert_inside(path: Path, root: Path, label: str) -> None:
    try:
        relative = _absolute(path).relative_to(_absolute(root))
    except ValueError as exc:
        raise UnsafeInstallPathError(f"{label} escapes the selected home: {path}") from exc
    if relative == Path("."):
        raise UnsafeInstallPathError(f"{label} must be inside the selected home")


def _read_source() -> bytes:
    repository = _absolute(Path(__file__).parents[1])
    source = repository / "skills" / "quota-orb" / "SKILL.md"
    _assert_no_link_ancestors(source, "Skill source")
    try:
        info = os.lstat(source)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing portable Skill: {source}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeInstallPathError(f"Skill source is not a regular file: {source}")
    content = source.read_bytes()
    after = os.lstat(source)
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1_000_000_000)),
    )
    if identity(info) != identity(after):
        raise UnsafeInstallPathError(f"Skill source changed during preflight: {source}")
    return content


def _safe_existing_content(destination: Path, home: Path) -> bytes | None:
    _assert_inside(destination, home, "Destination")
    _assert_no_link_ancestors(destination, "Destination")
    if not os.path.lexists(destination):
        return None
    info = os.lstat(destination)
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeInstallPathError(f"Destination is not a regular file: {destination}")
    return destination.read_bytes()


def _ensure_safe_parent(parent: Path, home: Path) -> None:
    _assert_inside(parent, home, "Destination parent")
    _assert_no_link_ancestors(home, "Selected home")
    for component in _components(parent):
        try:
            component.relative_to(home)
        except ValueError:
            continue
        if not os.path.lexists(component):
            component.mkdir()
        if _is_link_or_reparse(component) or not component.is_dir():
            raise UnsafeInstallPathError(f"Unsafe destination parent: {component}")
    _assert_no_link_ancestors(parent, "Destination parent")


@contextmanager
def _windows_directory_handle(parent: Path):
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
        str(parent),
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
        raise UnsafeInstallPathError(
            f"Cannot safely lock destination parent: {parent} (WinError {error})"
        )
    try:
        yield handle
    finally:
        close_handle(handle)


def _location_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _assert_parent_descriptor_matches(parent: Path, descriptor: int) -> None:
    try:
        path_info = os.lstat(parent)
        descriptor_info = os.fstat(descriptor)
    except OSError as exc:
        raise UnsafeInstallPathError(
            f"Cannot safely revalidate destination parent: {parent}"
        ) from exc
    if (
        not stat.S_ISDIR(descriptor_info.st_mode)
        or _location_identity(path_info) != _location_identity(descriptor_info)
    ):
        raise UnsafeInstallPathError(
            f"Destination parent changed while being secured: {parent}"
        )


@contextmanager
def _commit_parent_guard(parent: Path, home: Path):
    _ensure_safe_parent(parent, home)
    if os.name == "nt":
        with _windows_directory_handle(parent):
            _ensure_safe_parent(parent, home)
            yield None
        return

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise UnsafeInstallPathError(
            "Platform cannot safely lock destination parent without following links"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(parent, flags)
    except OSError as exc:
        raise UnsafeInstallPathError(
            f"Cannot safely lock destination parent: {parent}"
        ) from exc
    try:
        _assert_parent_descriptor_matches(parent, descriptor)
        _ensure_safe_parent(parent, home)
        _assert_parent_descriptor_matches(parent, descriptor)
        yield descriptor
    finally:
        os.close(descriptor)


def _safe_existing_content_at(
    destination: Path,
    home: Path,
    parent_descriptor: int | None,
) -> bytes | None:
    if parent_descriptor is None:
        return _safe_existing_content(destination, home)
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(destination.name, flags, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeInstallPathError(
                f"Destination is not a regular file: {destination}"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _create_temporary(
    parent: Path,
    parent_descriptor: int | None,
) -> tuple[int, Path]:
    if parent_descriptor is None:
        descriptor, name = tempfile.mkstemp(
            prefix=".quota-orb-",
            suffix=".tmp",
            dir=parent,
        )
        return descriptor, Path(name)

    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _attempt in range(100):
        name = f".quota-orb-{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        return descriptor, Path(name)
    raise UnsafeInstallPathError("Cannot allocate a unique temporary Skill file")


def _commit_no_clobber(
    temporary: Path,
    destination: Path,
    parent_descriptor: int | None,
) -> None:
    try:
        if parent_descriptor is None:
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except TypeError:
                os.link(temporary, destination)
        else:
            try:
                os.link(
                    temporary.name,
                    destination.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except TypeError:
                os.link(
                    temporary.name,
                    destination.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
    except FileExistsError as exc:
        raise InstallConflictError(
            f"conflict: destination appeared during install: {destination}"
        ) from exc


def _unlink_temporary(temporary: Path, parent_descriptor: int | None) -> None:
    try:
        if parent_descriptor is None:
            temporary.unlink()
        else:
            os.unlink(temporary.name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        pass


def install(target: str, home: Path | str, *, apply: bool = False) -> tuple[Path, str]:
    if target not in TARGETS:
        raise ValueError(f"Unsupported Agent target: {target}")
    home = _absolute(home)
    destination = home / TARGETS[target]
    content = _read_source()
    existing = _safe_existing_content(destination, home)
    status = "new" if existing is None else "identical" if existing == content else "conflict"
    if status == "conflict":
        raise InstallConflictError(f"conflict: refusing to overwrite {destination}")
    if not apply or status == "identical":
        return destination, status

    temporary: Path | None = None
    with _commit_parent_guard(destination.parent, home) as parent_descriptor:
        existing = _safe_existing_content_at(destination, home, parent_descriptor)
        if existing is not None:
            if existing == content:
                return destination, "identical"
            raise InstallConflictError(
                f"conflict: destination changed before install: {destination}"
            )

        descriptor, temporary = _create_temporary(
            destination.parent,
            parent_descriptor,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if parent_descriptor is None:
                _ensure_safe_parent(destination.parent, home)
            else:
                _assert_parent_descriptor_matches(
                    destination.parent,
                    parent_descriptor,
                )
            _commit_no_clobber(temporary, destination, parent_descriptor)
            committed = _safe_existing_content_at(
                destination,
                home,
                parent_descriptor,
            )
            if committed != content:
                raise UnsafeInstallPathError(
                    f"Installed Skill could not be verified: {destination}"
                )
        finally:
            _unlink_temporary(temporary, parent_descriptor)
    return destination, "installed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the portable Quota Orb Skill into one selected AI coding agent."
    )
    parser.add_argument("--target", required=True, choices=tuple(TARGETS))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--apply", action="store_true", help="Write after previewing the destination.")
    args = parser.parse_args(argv)
    try:
        destination, status = install(args.target, args.home, apply=args.apply)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    mode = "apply" if args.apply else "preview"
    print(f"{mode}: target={args.target} status={status} destination={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

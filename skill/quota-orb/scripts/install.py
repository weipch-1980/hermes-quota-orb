from __future__ import annotations

import argparse
import errno
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


ASSET_MAP = (
    ("assets/desktop-plugin/plugin.js", "desktop-plugins/quota-orb/plugin.js"),
    ("assets/hermes-plugin/plugin.yaml", "plugins/quota-orb/plugin.yaml"),
    ("assets/hermes-plugin/dashboard/manifest.json", "plugins/quota-orb/dashboard/manifest.json"),
    ("assets/hermes-plugin/dashboard/plugin_api.py", "plugins/quota-orb/dashboard/plugin_api.py"),
)


class InstallConflictError(FileExistsError):
    """Raised after a complete preflight finds destination conflicts."""

    def __init__(self, plan: list[dict[str, Any]]) -> None:
        self.plan = plan
        conflicts = [
            str(item["destination"])
            for item in plan
            if item["status"] == "conflict"
        ]
        message = "Refusing to overwrite conflicting Quota Orb files:\n" + "\n".join(
            f"  conflict: {destination}" for destination in conflicts
        )
        super().__init__(message)


class UnsafeInstallPathError(ValueError):
    """Raised when an install path can escape its trusted root."""


def default_hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _relative_path(path: Path, root: Path, label: str) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafeInstallPathError(f"{label} escapes its trusted root: {path}") from exc
    if relative == Path("."):
        raise UnsafeInstallPathError(f"{label} must be inside its trusted root: {path}")
    return relative


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise UnsafeInstallPathError(f"Cannot safely inspect path: {path}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _path_components_from_anchor(path: Path) -> list[Path]:
    path = _absolute(path)
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:]:
        current = current / part
        components.append(current)
    return components


def _assert_no_link_ancestors(path: Path, label: str) -> None:
    for component in _path_components_from_anchor(path):
        if os.path.lexists(component) and _is_link_or_reparse(component):
            raise UnsafeInstallPathError(
                f"{label} contains a symlink or reparse point: {component}"
            )


def _assert_no_link_components(root: Path, path: Path, label: str) -> None:
    relative = _relative_path(path, root, label)
    current = root
    components = [current]
    for part in relative.parts:
        current = current / part
        components.append(current)
    for component in components:
        if os.path.lexists(component) and _is_link_or_reparse(component):
            raise UnsafeInstallPathError(
                f"{label} contains a symlink or reparse point: {component}"
            )


def _assert_resolved_within(path: Path, resolved_root: Path, label: str) -> None:
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise UnsafeInstallPathError(f"Cannot safely resolve {label}: {path}") from exc
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeInstallPathError(
            f"{label} resolves outside its trusted root: {path}"
        ) from exc
    if relative == Path("."):
        raise UnsafeInstallPathError(f"{label} must resolve inside its trusted root: {path}")


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
    )


def _read_regular_file_no_follow(path: Path, root: Path, resolved_root: Path, label: str) -> bytes:
    _assert_no_link_components(root, path, label)
    _assert_resolved_within(path, resolved_root, label)
    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing Quota Orb asset: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise UnsafeInstallPathError(f"{label} is not a regular file: {path}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafeInstallPathError(f"Cannot safely open {label}: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(before) != _stat_identity(opened):
            raise UnsafeInstallPathError(f"{label} changed during preflight: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            content = stream.read()
            stream.seek(0)
            verification = stream.read()
        if content != verification:
            raise UnsafeInstallPathError(f"{label} content changed during preflight: {path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    _assert_no_link_components(root, path, label)
    _assert_resolved_within(path, resolved_root, label)
    try:
        after = os.lstat(path)
    except FileNotFoundError as exc:
        raise UnsafeInstallPathError(f"{label} changed during preflight: {path}") from exc
    if _stat_identity(before) != _stat_identity(after):
        raise UnsafeInstallPathError(f"{label} changed during preflight: {path}")
    return content


def _validate_destination_path(
    destination: Path,
    hermes_home: Path,
    resolved_home: Path,
) -> None:
    _assert_no_link_ancestors(hermes_home, "HERMES_HOME")
    _assert_no_link_components(hermes_home, destination, "Destination")
    _assert_resolved_within(destination, resolved_home, "Destination")
    if os.path.lexists(destination):
        info = os.lstat(destination)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeInstallPathError(
                f"Destination is not a regular file: {destination}"
            )


def _destination_status(
    content: bytes,
    destination: Path,
    hermes_home: Path,
    resolved_home: Path,
) -> str:
    _validate_destination_path(destination, hermes_home, resolved_home)
    if not os.path.lexists(destination):
        return "new"
    existing = _read_regular_file_no_follow(
        destination,
        hermes_home,
        resolved_home,
        "Destination",
    )
    return "identical" if existing == content else "conflict"


def _build_plan(
    *,
    skill_dir: Path,
    resolved_skill_dir: Path,
    hermes_home: Path,
    resolved_home: Path,
) -> tuple[list[dict[str, Any]], dict[Path, bytes]]:
    plan: list[dict[str, Any]] = []
    payloads: dict[Path, bytes] = {}
    for source_name, destination_name in ASSET_MAP:
        source = skill_dir / source_name
        destination = hermes_home / destination_name
        content = _read_regular_file_no_follow(
            source,
            skill_dir,
            resolved_skill_dir,
            "Source",
        )
        payloads[destination] = content
        plan.append(
            {
                "source": source,
                "destination": destination,
                "status": _destination_status(
                    content,
                    destination,
                    hermes_home,
                    resolved_home,
                ),
            }
        )
    return plan, payloads


def _ensure_safe_parent(
    parent: Path,
    hermes_home: Path,
    resolved_home: Path,
) -> None:
    relative = _relative_path(parent, hermes_home, "Destination parent")
    _assert_no_link_ancestors(hermes_home, "HERMES_HOME")
    for current in _path_components_from_anchor(parent):
        if not os.path.lexists(current):
            try:
                current.mkdir()
            except FileExistsError:
                pass
        if _is_link_or_reparse(current) or not current.is_dir():
            raise UnsafeInstallPathError(
                f"Destination parent is unsafe: {current}"
            )
        try:
            current.relative_to(hermes_home)
        except ValueError:
            continue
        current_resolved = current.resolve(strict=True)
        try:
            current_resolved.relative_to(resolved_home)
        except ValueError as exc:
            raise UnsafeInstallPathError(
                f"Destination parent resolves outside HERMES_HOME: {current}"
            ) from exc

    _assert_no_link_components(hermes_home, parent, "Destination parent")
    _assert_resolved_within(parent, resolved_home, "Destination parent")


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
def _commit_parent_guard(
    parent: Path,
    hermes_home: Path,
    resolved_home: Path,
):
    _ensure_safe_parent(parent, hermes_home, resolved_home)
    if os.name == "nt":
        with _windows_directory_handle(parent):
            _ensure_safe_parent(parent, hermes_home, resolved_home)
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
        _ensure_safe_parent(parent, hermes_home, resolved_home)
        _assert_parent_descriptor_matches(parent, descriptor)
        yield descriptor
    finally:
        os.close(descriptor)


def _replace_force(
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


def _unlink_temporary(temporary: Path, parent_descriptor: int | None) -> None:
    try:
        if parent_descriptor is None:
            temporary.unlink()
        else:
            os.unlink(temporary.name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        pass


def _late_conflict(destination: Path) -> FileExistsError:
    return FileExistsError(
        f"Destination changed after preflight; refusing to overwrite without --force: {destination}"
    )


def _commit_no_clobber(
    temporary: Path,
    destination: Path,
    content: bytes,
    parent_descriptor: int | None = None,
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
        raise _late_conflict(destination) from exc
    except OSError as exc:
        unsupported = {
            errno.EPERM,
            getattr(errno, "ENOTSUP", errno.EPERM),
            getattr(errno, "EOPNOTSUPP", errno.EPERM),
            getattr(errno, "ENOSYS", errno.EPERM),
        }
        if exc.errno not in unsupported:
            raise
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            if parent_descriptor is None:
                descriptor = os.open(destination, flags, 0o600)
            else:
                descriptor = os.open(
                    destination.name,
                    flags,
                    0o600,
                    dir_fd=parent_descriptor,
                )
        except FileExistsError as conflict:
            raise _late_conflict(destination) from conflict
        committed = False
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            committed = True
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if not committed:
                try:
                    if parent_descriptor is None:
                        destination.unlink()
                    else:
                        os.unlink(destination.name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    pass


def _atomic_write(
    destination: Path,
    content: bytes,
    hermes_home: Path,
    resolved_home: Path,
    force: bool,
) -> None:
    temporary: Path | None = None
    with _commit_parent_guard(destination.parent, hermes_home, resolved_home) as parent_descriptor:
        status = _destination_status(content, destination, hermes_home, resolved_home)
        if status == "identical":
            return
        if status == "conflict" and not force:
            raise _late_conflict(destination)

        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _ensure_safe_parent(destination.parent, hermes_home, resolved_home)
            status = _destination_status(content, destination, hermes_home, resolved_home)
            if status == "identical":
                return
            if status == "conflict" and not force:
                raise _late_conflict(destination)
            _assert_no_link_components(hermes_home, temporary, "Temporary destination")
            _assert_resolved_within(temporary, resolved_home, "Temporary destination")
            if force:
                _replace_force(temporary, destination, parent_descriptor)
            else:
                _commit_no_clobber(
                    temporary,
                    destination,
                    content,
                    parent_descriptor,
                )
            _validate_destination_path(destination, hermes_home, resolved_home)
        finally:
            _unlink_temporary(temporary, parent_descriptor)


def install(
    *,
    skill_dir: Path,
    hermes_home: Path,
    apply: bool,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Plan or install Quota Orb assets without following untrusted links."""
    skill_dir = _absolute(Path(skill_dir))
    hermes_home = _absolute(Path(hermes_home))

    if not os.path.lexists(skill_dir) or not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory does not exist: {skill_dir}")
    if _is_link_or_reparse(skill_dir):
        raise UnsafeInstallPathError(f"Skill directory is a symlink or reparse point: {skill_dir}")
    _assert_no_link_ancestors(skill_dir, "Skill directory")
    _assert_no_link_ancestors(hermes_home, "HERMES_HOME")
    if os.path.lexists(hermes_home):
        if _is_link_or_reparse(hermes_home) or not hermes_home.is_dir():
            raise UnsafeInstallPathError(f"HERMES_HOME is unsafe: {hermes_home}")

    resolved_skill_dir = skill_dir.resolve(strict=True)
    resolved_home = hermes_home.resolve(strict=False)
    plan, payloads = _build_plan(
        skill_dir=skill_dir,
        resolved_skill_dir=resolved_skill_dir,
        hermes_home=hermes_home,
        resolved_home=resolved_home,
    )

    conflicts = [item for item in plan if item["status"] == "conflict"]
    if apply and conflicts and not force:
        raise InstallConflictError(plan)
    if not apply:
        return plan

    for item in plan:
        if item["status"] == "identical":
            continue
        destination = item["destination"]
        _atomic_write(
            destination,
            payloads[destination],
            hermes_home,
            resolved_home,
            force,
        )
    return plan


def _print_plan(plan: list[dict[str, Any]]) -> None:
    for item in plan:
        print(
            f"  {item['status']}: {item['source']} -> {item['destination']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Quota Orb Hermes Desktop plugin."
    )
    parser.add_argument("--hermes-home", type=Path, default=default_hermes_home())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy files after preflight. Without this flag, only show the dry-run plan.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --apply, explicitly overwrite conflicting destination files.",
    )
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    try:
        plan = install(
            skill_dir=skill_dir,
            hermes_home=args.hermes_home,
            apply=args.apply,
            force=args.force,
        )
    except InstallConflictError as exc:
        print("Quota Orb install plan:")
        _print_plan(exc.plan)
        print(f"Install aborted: {exc}", file=sys.stderr)
        return 1
    except UnsafeInstallPathError as exc:
        print(f"Install aborted: {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"Install aborted: {exc}", file=sys.stderr)
        return 1

    print("Quota Orb install plan:")
    _print_plan(plan)
    if args.apply:
        mode = " with --force" if args.force else ""
        print(f"Applied Quota Orb files{mode}.")
        print(
            "Backend files copied. Enable quota-orb as described in SKILL.md, "
            "then restart Hermes Desktop once."
        )
    else:
        print("Dry run only; no files were written. Re-run with --apply after approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

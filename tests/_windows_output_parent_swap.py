from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


class WindowsOutputDirectoryParentSwap:
    """Attempt a rename-then-junction output-directory swap during ``os.replace``."""

    def __init__(
        self,
        *,
        output_directory: Path,
        moved_directory: Path,
        external_directory: Path,
        archive_name: str,
        sidecar_name: str,
    ) -> None:
        self.output_directory = output_directory
        self.moved_directory = moved_directory
        self.external_directory = external_directory
        self.archive_name = archive_name
        self.sidecar_name = sidecar_name
        self.rename_attempted = False
        self.rename_succeeded = False
        self.rename_error: OSError | None = None
        self.junction_attempted = False
        self.junction_created = False
        self.junction_points_to_external = False
        self.junction_result = "junction creation was not attempted"

    def wrap(self, original_replace: Callable[..., Any]) -> Callable[..., Any]:
        def replacing(source: Any, destination: Any, *args: Any, **kwargs: Any) -> Any:
            if (
                not self.rename_attempted
                and Path(destination).name == self.archive_name
            ):
                self._attempt_parent_swap()
            return original_replace(source, destination, *args, **kwargs)

        return replacing

    def _attempt_parent_swap(self) -> None:
        self.rename_attempted = True
        try:
            self.output_directory.rename(self.moved_directory)
        except OSError as exc:
            self.rename_error = exc
            return

        self.rename_succeeded = True
        self.junction_attempted = True
        result = subprocess.run(
            [
                "cmd.exe",
                "/c",
                "mklink",
                "/J",
                str(self.output_directory),
                str(self.external_directory),
            ],
            text=True,
            encoding="mbcs",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.junction_created = result.returncode == 0
        if self.junction_created:
            try:
                self.junction_points_to_external = (
                    self.output_directory.resolve(strict=True)
                    == self.external_directory.resolve(strict=True)
                )
            except OSError:
                self.junction_points_to_external = False
        self.junction_result = (
            f"returncode={result.returncode}; stdout={result.stdout!r}; "
            f"stderr={result.stderr!r}; "
            f"points_to_external={self.junction_points_to_external}"
        )

    def external_outputs(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (
                self.external_directory / self.archive_name,
                self.external_directory / self.sidecar_name,
            )
            if path.exists()
        )

    def cleanup(self) -> None:
        if self.junction_attempted and self.output_directory.exists():
            self.output_directory.rmdir()
        if self.moved_directory.exists() and not self.output_directory.exists():
            self.moved_directory.rename(self.output_directory)

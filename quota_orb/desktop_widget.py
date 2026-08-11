from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .sources import source_from_environment


WIDGET_SIZE = (132, 132)
TRANSPARENT_COLOR = "#010203"
DRAG_THRESHOLD = 4
LIQUID_PALETTES = {
    "unknown": {
        "state": "unknown",
        "body": "#64748b",
        "deep": "#475569",
        "rim": "#cbd5e1",
        "shell": "#0f172a",
        "meta": "#e2e8f0",
    },
    "green": {
        "state": "green",
        "body": "#14b887",
        "deep": "#0c8f6a",
        "rim": "#9affdc",
        "shell": "#06251f",
        "meta": "#c9f9e9",
    },
    "yellow": {
        "state": "yellow",
        "body": "#eab308",
        "deep": "#a16207",
        "rim": "#fde68a",
        "shell": "#2b2105",
        "meta": "#fef3c7",
    },
    "red": {
        "state": "red",
        "body": "#ef4444",
        "deep": "#b91c1c",
        "rim": "#fecaca",
        "shell": "#2b0909",
        "meta": "#fee2e2",
    },
}


def liquid_palette(value: object) -> dict[str, str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return LIQUID_PALETTES["unknown"]
    numeric = float(value)
    if not math.isfinite(numeric):
        return LIQUID_PALETTES["unknown"]
    clamped = min(100.0, max(0.0, numeric))
    if clamped < 30:
        return LIQUID_PALETTES["red"]
    if clamped < 50:
        return LIQUID_PALETTES["yellow"]
    return LIQUID_PALETTES["green"]


def surface_y(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    clamped = min(100.0, max(0.0, numeric))
    return 84.0 - (clamped * 0.76)


def select_remaining_percent(snapshot: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    quota = snapshot.get("subscription_quota")
    if isinstance(quota, Mapping) and quota.get("available") is True:
        windows = quota.get("windows")
        if isinstance(windows, list):
            for window in windows:
                if not isinstance(window, Mapping):
                    continue
                value = window.get("remaining_percent")
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                ):
                    values.append(min(100.0, max(0.0, float(value))))

    billing = snapshot.get("token_billing")
    if isinstance(billing, Mapping) and billing.get("available") is True:
        allowance = billing.get("allowance")
        value = allowance.get("remaining_percent") if isinstance(allowance, Mapping) else None
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            values.append(min(100.0, max(0.0, float(value))))
    return min(values) if values else None


def drag_position(
    window_start: tuple[int, int],
    pointer_start: tuple[int, int],
    pointer_current: tuple[int, int],
) -> tuple[int, int]:
    return (
        window_start[0] + pointer_current[0] - pointer_start[0],
        window_start[1] + pointer_current[1] - pointer_start[1],
    )


def exceeds_drag_threshold(
    pointer_start: tuple[int, int],
    pointer_current: tuple[int, int],
    threshold: int = DRAG_THRESHOLD,
) -> bool:
    return max(
        abs(pointer_current[0] - pointer_start[0]),
        abs(pointer_current[1] - pointer_start[1]),
    ) >= threshold


def _normalize_areas(areas: Iterable[Sequence[int]]) -> list[tuple[int, int, int, int]]:
    normalized: list[tuple[int, int, int, int]] = []
    for area in areas:
        if len(area) != 4:
            continue
        left, top, right, bottom = (int(item) for item in area)
        if right > left and bottom > top:
            normalized.append((left, top, right, bottom))
    return normalized


def clamp_position_to_areas(
    position: tuple[int, int],
    widget_size: tuple[int, int],
    areas: Iterable[Sequence[int]],
) -> tuple[int, int]:
    candidates = _normalize_areas(areas)
    if not candidates:
        return position
    x, y = int(position[0]), int(position[1])
    width, height = widget_size

    for left, top, right, bottom in candidates:
        if x + width > left and x < right and y + height > top and y < bottom:
            return (
                min(max(x, left), max(left, right - width)),
                min(max(y, top), max(top, bottom - height)),
            )

    def distance(area: tuple[int, int, int, int]) -> int:
        left, top, right, bottom = area
        nearest_x = min(max(x, left), right)
        nearest_y = min(max(y, top), bottom)
        return (x - nearest_x) ** 2 + (y - nearest_y) ** 2

    left, top, right, bottom = min(candidates, key=distance)
    return (
        min(max(x, left), max(left, right - width)),
        min(max(y, top), max(top, bottom - height)),
    )


def clamp_position(
    position: tuple[int, int],
    screen_size: tuple[int, int],
    widget_size: tuple[int, int],
) -> tuple[int, int]:
    return clamp_position_to_areas(
        position,
        widget_size,
        [(0, 0, int(screen_size[0]), int(screen_size[1]))],
    )


def save_position(path: Path | str, position: tuple[int, int]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"x": int(position[0]), "y": int(position[1])},
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".quota-orb-position-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def load_position(
    path: Path | str,
    *,
    default: tuple[int, int],
    screen_size: tuple[int, int] | None = None,
    widget_size: tuple[int, int] = WIDGET_SIZE,
    areas: Iterable[Sequence[int]] | None = None,
) -> tuple[int, int]:
    position = default
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            isinstance(raw, Mapping)
            and type(raw.get("x")) is int
            and type(raw.get("y")) is int
        ):
            position = (raw["x"], raw["y"])
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if areas is not None:
        return clamp_position_to_areas(position, widget_size, areas)
    if screen_size is not None:
        return clamp_position(position, screen_size, widget_size)
    return position


def default_state_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "QuotaOrb" / "widget-position.json"
    return Path.home() / ".quota-orb" / "widget-position.json"


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def monitor_work_areas() -> list[tuple[int, int, int, int]]:
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    areas: list[tuple[int, int, int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )

    def callback(monitor, _dc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            areas.append((work.left, work.top, work.right, work.bottom))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    return areas


class DesktopOrb:
    def __init__(self, root: Any, *, state_path: Path, refresh_ms: int) -> None:
        import tkinter as tk

        self.root = root
        self.state_path = state_path
        self.refresh_ms = refresh_ms
        self.source = source_from_environment()
        self.pointer_start: tuple[int, int] | None = None
        self.window_start: tuple[int, int] | None = None
        self.dragging = False

        root.title("Quota Orb Desktop Widget")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        if os.name == "nt":
            root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        root.configure(bg=TRANSPARENT_COLOR)

        self.canvas = tk.Canvas(
            root,
            width=WIDGET_SIZE[0],
            height=WIDGET_SIZE[1],
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._show_menu)
        root.bind("<Escape>", lambda _event: root.destroy())

        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label="Exit Quota Orb", command=root.destroy)

        areas = self._areas()
        default = self._default_position(areas)
        position = load_position(
            state_path,
            default=default,
            widget_size=WIDGET_SIZE,
            areas=areas,
        )
        self._set_position(position)
        self._draw(None)
        root.after(0, self._refresh)

    def _areas(self) -> list[tuple[int, int, int, int]]:
        areas = monitor_work_areas()
        if areas:
            return areas
        return [(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())]

    @staticmethod
    def _default_position(areas: list[tuple[int, int, int, int]]) -> tuple[int, int]:
        left, top, right, _bottom = areas[0]
        return (max(left, right - WIDGET_SIZE[0] - 24), top + 24)

    def _set_position(self, position: tuple[int, int]) -> None:
        x, y = position
        self.root.geometry(f"{WIDGET_SIZE[0]}x{WIDGET_SIZE[1]}{x:+d}{y:+d}")

    def _current_position(self) -> tuple[int, int]:
        return (self.root.winfo_x(), self.root.winfo_y())

    def _press(self, event: Any) -> None:
        self.pointer_start = (event.x_root, event.y_root)
        self.window_start = self._current_position()
        self.dragging = False

    def _move(self, event: Any) -> None:
        if self.pointer_start is None or self.window_start is None:
            return
        current = (event.x_root, event.y_root)
        if not self.dragging and not exceeds_drag_threshold(self.pointer_start, current):
            return
        self.dragging = True
        self._set_position(drag_position(self.window_start, self.pointer_start, current))

    def _release(self, _event: Any) -> None:
        if self.dragging:
            position = clamp_position_to_areas(
                self._current_position(),
                WIDGET_SIZE,
                self._areas(),
            )
            self._set_position(position)
            save_position(self.state_path, position)
        self.pointer_start = None
        self.window_start = None
        self.dragging = False

    def _show_menu(self, event: Any) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _refresh(self) -> None:
        try:
            snapshot = self.source.snapshot()
            remaining = select_remaining_percent(snapshot)
        except Exception:
            remaining = None
        self._draw(remaining)
        visible = clamp_position_to_areas(
            self._current_position(),
            WIDGET_SIZE,
            self._areas(),
        )
        if visible != self._current_position():
            self._set_position(visible)
            save_position(self.state_path, visible)
        self.root.after(self.refresh_ms, self._refresh)

    def _draw(self, remaining: float | None) -> None:
        canvas = self.canvas
        canvas.delete("all")
        palette = liquid_palette(remaining)
        canvas.create_oval(14, 14, 118, 118, fill=palette["shell"], outline=palette["rim"], width=3)
        top = surface_y(remaining)
        if top is not None and remaining > 0:
            center = 66
            radius = 49
            for y in range(max(18, int(top)), 115):
                offset = int(math.sqrt(max(0, radius * radius - (y - center) ** 2)))
                if offset:
                    canvas.create_line(
                        center - offset,
                        y,
                        center + offset,
                        y,
                        fill=palette["body"] if y < 95 else palette["deep"],
                    )
        canvas.create_oval(14, 14, 118, 118, outline=palette["rim"], width=2)
        canvas.create_arc(25, 22, 96, 91, start=95, extent=75, style="arc", outline="#ffffff", width=3)
        label = "?" if remaining is None else f"{remaining:.0f}%"
        canvas.create_text(66, 68, text=label, fill="#ffffff", font=("Segoe UI", 16, "bold"))
        canvas.create_text(66, 89, text="REMAIN", fill=palette["meta"], font=("Segoe UI", 8, "bold"))


def run_widget(*, state_path: Path, refresh_seconds: float) -> None:
    enable_windows_dpi_awareness()
    import tkinter as tk

    root = tk.Tk()
    DesktopOrb(
        root,
        state_path=state_path,
        refresh_ms=max(1000, int(refresh_seconds * 1000)),
    )
    root.mainloop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Open the independent draggable Quota Orb desktop widget."
    )
    parser.add_argument("--state-file", type=Path, default=default_state_path())
    parser.add_argument("--refresh-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    if not math.isfinite(args.refresh_seconds) or args.refresh_seconds <= 0:
        parser.error("--refresh-seconds must be finite and greater than zero")
    run_widget(state_path=args.state_file, refresh_seconds=args.refresh_seconds)


if __name__ == "__main__":
    main()

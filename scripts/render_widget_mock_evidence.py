from __future__ import annotations

import argparse
import sys
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.desktop_widget import (
    DETAIL_SIZE,
    DesktopOrb,
    detail_panel_model,
    enable_windows_dpi_awareness,
    orb_labels,
    render_orb_frame,
    select_remaining_percent,
)


OUTPUT_DIR = ROOT / "dist" / "gui-evidence"
EVIDENCE_SIZE = (560, 660)
LOCAL_TIMEZONE = timezone(timedelta(hours=8))


def demo_snapshot() -> dict[str, Any]:
    return {
        "demo": True,
        "platform": "codex-mock",
        "provider": "openai-codex-demo",
        "profile": "demo-profile",
        "account": "demo@example.test",
        "model": "gpt-demo",
        "generated_at": "2026-08-13T08:00:00+00:00",
        "subscription_quota": {
            "available": True,
            "source": "demo-subscription-fixture",
            "plan": "Plus Demo",
            "windows": [
                {
                    "label": "Session",
                    "used_percent": 32,
                    "remaining_percent": 68,
                    "reset_at": "2026-08-13T12:00:00+00:00",
                },
                {
                    "label": "Weekly",
                    "used_percent": 55,
                    "remaining_percent": 45,
                    "reset_at": "2026-08-13T14:30:00+00:00",
                },
            ],
        },
        "api_quota": {
            "available": False,
            "source": "unavailable",
            "unavailable_reason": "No demo API quota source is configured.",
            "limits": [],
        },
        "local_usage": {
            "available": True,
            "source": "demo-local-fixture",
            "day": "2026-08-13",
            "totals": {"total_tokens": 1234, "sessions": 2},
            "by_provider": [],
        },
        "token_billing": {
            "available": True,
            "source": "demo-token-fixture",
            "usage": {"total_tokens": 1234},
            "allowance": {
                "remaining_tokens": 8766,
                "remaining_percent": 29.5,
                "reset_at": "2026-08-14T01:00:00+00:00",
            },
            "cost": None,
        },
    }


def screenshot_contract(language: str) -> tuple[dict[str, Any], float, dict[str, Any]]:
    snapshot = demo_snapshot()
    remaining = select_remaining_percent(snapshot)
    if remaining is None:
        raise RuntimeError("Demo screenshot requires a real remaining percentage.")
    model = detail_panel_model(
        snapshot,
        language=language,
        local_timezone=LOCAL_TIMEZONE,
    )
    if orb_labels(remaining, language=language)[0] != model["summary"]["remaining"]:
        raise RuntimeError("Orb and panel summary percentages diverged.")
    return snapshot, remaining, model


def compose_evidence(
    panel_image: Image.Image,
    *,
    remaining: float,
    language: str,
) -> Image.Image:
    evidence = Image.new("RGB", EVIDENCE_SIZE, "#071018")
    panel = panel_image.convert("RGB").resize(DETAIL_SIZE, Image.Resampling.LANCZOS)
    evidence.paste(panel, (156, 20))
    orb = render_orb_frame(
        remaining,
        phase=0.0,
        bubble_phase=0.0,
        reduced_motion=True,
        language=language,
    )
    evidence.paste(orb, (18, 264), orb)
    return evidence


def validate_panel_capture(panel_image: Image.Image) -> dict[str, Any]:
    panel = panel_image.convert("RGB")
    width, height = panel.size
    expected_width, expected_height = DETAIL_SIZE
    pixels = list(panel.get_flattened_data())
    dark_ratio = sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue < 128
        for red, green, blue in pixels
    ) / len(pixels)
    header_pixels = [
        panel.getpixel((x, y))
        for y in range(min(64, height))
        for x in range(width)
    ]
    header_white_ratio = sum(
        red >= 240 and green >= 240 and blue >= 240
        for red, green, blue in header_pixels
    ) / len(header_pixels)
    demo_pixels = [
        panel.getpixel((x, y))
        for y in range(min(64, height), min(132, height))
        for x in range(min(128, width))
    ]
    demo_amber_pixels = sum(
        abs(red - 242) <= 45
        and abs(green - 198) <= 45
        and abs(blue - 109) <= 45
        for red, green, blue in demo_pixels
    )

    failures = []
    if (
        abs(width - expected_width) > max(12, round(expected_width * 0.08))
        or abs(height - expected_height) > max(12, round(expected_height * 0.08))
    ):
        failures.append(f"size {panel.size} is not close to {DETAIL_SIZE}")
    if dark_ratio < 0.70:
        failures.append(f"dark ratio {dark_ratio:.3f} is below 0.700")
    if header_white_ratio >= 0.50:
        failures.append(f"header white ratio {header_white_ratio:.3f} is not below 0.500")
    if demo_amber_pixels == 0:
        failures.append("Demo amber pixels are missing")
    if failures:
        raise RuntimeError("Panel capture validation failed: " + "; ".join(failures))
    return {
        "size": panel.size,
        "dark_ratio": dark_ratio,
        "header_white_ratio": header_white_ratio,
        "demo_amber_pixels": demo_amber_pixels,
    }


def capture_panel(snapshot: dict[str, Any], language: str) -> Image.Image:
    import ctypes
    from ctypes import wintypes
    from PIL import ImageGrab
    import tkinter as tk

    enable_windows_dpi_awareness()
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("1x1+20+20")
    root.configure(bg="#010203")
    root.update_idletasks()

    orb = DesktopOrb.__new__(DesktopOrb)
    orb.root = root
    orb.language = language
    orb.local_timezone = LOCAL_TIMEZONE
    orb.snapshot = snapshot
    orb.remaining = select_remaining_percent(snapshot)
    orb.detail_window = None
    orb._destroyed = False
    orb._last_refresh_error = None
    orb._refresh_in_flight = False
    orb._areas = lambda: [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
    try:
        orb._open_details()
        panel = orb.detail_window
        if panel is None:
            raise RuntimeError("Demo details panel did not open.")
        panel.geometry(f"{DETAIL_SIZE[0]}x{DETAIL_SIZE[1]}+180+60")
        panel.update_idletasks()
        panel.update()
        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        root_hwnd = get_ancestor(panel.winfo_id(), 2)
        if not root_hwnd:
            raise OSError(ctypes.get_last_error(), "GetAncestor(GA_ROOT) failed")
        captured = ImageGrab.grab(window=int(root_hwnd))
        return captured.convert("RGB")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render bilingual Quota Orb demo evidence.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for language, suffix in (("en", "en"), ("zh-CN", "zh-CN")):
        snapshot, remaining, _model = screenshot_contract(language)
        panel = capture_panel(snapshot, language)
        metrics = validate_panel_capture(panel)
        evidence = compose_evidence(panel, remaining=remaining, language=language)
        path = (args.output_dir / f"quota-orb-demo-{suffix}.png").resolve()
        evidence.save(path, format="PNG", optimize=True)
        print(f"{path} dark_ratio={metrics['dark_ratio']:.4f}")


if __name__ == "__main__":
    main()

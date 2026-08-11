from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.desktop_widget import (
    DesktopOrb,
    clamp_position,
    clamp_position_to_areas,
    drag_position,
    exceeds_drag_threshold,
    liquid_palette,
    load_position,
    main,
    save_position,
    select_remaining_percent,
    surface_y,
)


class DesktopWidgetLogicTests(unittest.TestCase):
    def test_unknown_and_real_zero_keep_distinct_liquid_geometry(self):
        self.assertIsNone(surface_y(None))
        self.assertEqual(surface_y(0), 84.0)
        self.assertEqual(surface_y(100), 8.0)
        self.assertEqual(surface_y(-10), 84.0)
        self.assertEqual(surface_y(120), 8.0)
        self.assertIsNone(surface_y("0"))

    def test_snapshot_selects_lowest_finite_real_window_only(self):
        snapshot = {
            "subscription_quota": {
                "available": True,
                "windows": [
                    {"remaining_percent": None},
                    {"remaining_percent": 72},
                    {"remaining_percent": 0},
                    {"remaining_percent": "3"},
                ],
            }
        }
        self.assertEqual(select_remaining_percent(snapshot), 0.0)
        snapshot["subscription_quota"]["available"] = False
        self.assertIsNone(select_remaining_percent(snapshot))

    def test_token_allowance_drives_level_when_subscription_is_unavailable(self):
        snapshot = {
            "subscription_quota": {"available": False, "windows": []},
            "token_billing": {
                "available": True,
                "allowance": {"remaining_percent": 29.5},
            },
        }
        self.assertEqual(select_remaining_percent(snapshot), 29.5)
        snapshot["token_billing"]["allowance"] = None
        self.assertIsNone(select_remaining_percent(snapshot))

    def test_liquid_palette_uses_strict_red_yellow_green_thresholds(self):
        self.assertEqual(liquid_palette(None)["state"], "unknown")
        self.assertEqual(liquid_palette(50)["state"], "green")
        self.assertEqual(liquid_palette(49.999)["state"], "yellow")
        self.assertEqual(liquid_palette(30)["state"], "yellow")
        self.assertEqual(liquid_palette(29.999)["state"], "red")
        self.assertEqual(liquid_palette(0)["state"], "red")

    def test_drag_position_uses_pointer_delta(self):
        self.assertEqual(
            drag_position((300, 200), (350, 250), (410, 315)),
            (360, 265),
        )

    def test_drag_threshold_ignores_click_jitter(self):
        self.assertFalse(exceeds_drag_threshold((100, 100), (103, 102)))
        self.assertTrue(exceeds_drag_threshold((100, 100), (104, 100)))

    def test_negative_monitor_and_disconnected_monitor_positions_are_recovered(self):
        areas = [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)]
        self.assertEqual(
            clamp_position_to_areas((-2000, 1070), (132, 132), areas),
            (-1920, 948),
        )
        self.assertEqual(
            clamp_position_to_areas((4000, 100), (132, 132), areas),
            (1788, 100),
        )

    def test_real_zero_draws_no_liquid_but_positive_value_does(self):
        class Canvas:
            def __init__(self):
                self.lines = []

            def delete(self, *_args):
                self.lines.clear()

            def create_line(self, *args, **kwargs):
                self.lines.append((args, kwargs))

            def create_oval(self, *_args, **_kwargs):
                return None

            def create_arc(self, *_args, **_kwargs):
                return None

            def create_text(self, *_args, **_kwargs):
                return None

        orb = DesktopOrb.__new__(DesktopOrb)
        orb.canvas = Canvas()
        orb._draw(0)
        self.assertEqual(orb.canvas.lines, [])
        orb._draw(1)
        self.assertGreater(len(orb.canvas.lines), 0)

    def test_position_is_clamped_to_visible_desktop(self):
        self.assertEqual(clamp_position((-20, -1), (1920, 1080), (132, 132)), (0, 0))
        self.assertEqual(
            clamp_position((1900, 1070), (1920, 1080), (132, 132)),
            (1788, 948),
        )
        self.assertEqual(clamp_position((400, 300), (1920, 1080), (132, 132)), (400, 300))

    def test_position_round_trip_and_invalid_state_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "widget.json"
            save_position(path, (321, 654))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"x": 321, "y": 654})
            self.assertEqual(
                load_position(path, default=(20, 30), screen_size=(1920, 1080), widget_size=(132, 132)),
                (321, 654),
            )
            path.write_text('{"x":"bad","y":5}', encoding="utf-8")
            self.assertEqual(
                load_position(path, default=(20, 30), screen_size=(1920, 1080), widget_size=(132, 132)),
                (20, 30),
            )

    def test_widget_source_declares_desktop_window_and_drag_contract(self):
        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        for marker in (
            "overrideredirect(True)",
            'attributes("-topmost", True)',
            'attributes("-transparentcolor"',
            'bind("<ButtonPress-1>"',
            'bind("<B1-Motion>"',
            'bind("<ButtonRelease-1>"',
            'bind("<Button-3>"',
            "save_position(",
            "source_from_environment",
            "top = surface_y(remaining)",
        ):
            self.assertIn(marker, source)

    def test_non_finite_refresh_is_rejected_before_window_start(self):
        with patch("quota_orb.desktop_widget.run_widget") as run_widget:
            with self.assertRaises(SystemExit):
                main(["--refresh-seconds", "nan"])
        run_widget.assert_not_called()

    def test_context_menu_always_releases_grab(self):
        class Menu:
            released = False

            def tk_popup(self, _x, _y):
                raise RuntimeError("popup failed")

            def grab_release(self):
                self.released = True

        orb = DesktopOrb.__new__(DesktopOrb)
        orb.menu = Menu()
        event = type("Event", (), {"x_root": 10, "y_root": 20})()
        with self.assertRaisesRegex(RuntimeError, "popup failed"):
            orb._show_menu(event)
        self.assertTrue(orb.menu.released)

    def test_module_help_does_not_require_a_display(self):
        result = subprocess.run(
            [sys.executable, "-m", "quota_orb.desktop_widget", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("draggable", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

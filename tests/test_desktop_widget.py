from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageStat


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from quota_orb.desktop_widget import (
    DETAIL_SIZE,
    DesktopOrb,
    clamp_position,
    clamp_position_to_areas,
    detect_system_ui_language,
    detail_panel_model,
    detail_snapshot_text,
    drag_position,
    exceeds_drag_threshold,
    liquid_fill_fraction,
    next_animation_state,
    orb_labels,
    liquid_palette,
    liquid_surface_points,
    load_position,
    main,
    panel_position,
    panel_ui_text,
    prepare_windows_display_frame,
    render_orb_frame,
    resolve_ui_language,
    save_position,
    select_remaining_percent,
    surface_y,
    wave_phases,
    windows_reduced_motion_enabled,
)


class DesktopWidgetLogicTests(unittest.TestCase):
    def test_system_locale_mapping_selects_simplified_chinese_or_english(self):
        for locale_name in ("zh", "zh-CN", "zh-Hans", "zh-SG", "zh_CN.UTF-8", "ZH-hans-CN"):
            with self.subTest(locale_name=locale_name):
                self.assertEqual(resolve_ui_language(locale_name), "zh-CN")
        for locale_name in ("en-US", "fr-FR", "ja-JP", None, "", object()):
            with self.subTest(locale_name=locale_name):
                self.assertEqual(resolve_ui_language(locale_name), "en")

    def test_system_language_detection_fails_safely_to_english(self):
        with patch("quota_orb.desktop_widget._system_locale_name", return_value="zh-Hans"):
            self.assertEqual(detect_system_ui_language(), "zh-CN")
        with patch("quota_orb.desktop_widget._system_locale_name", side_effect=OSError("unavailable")):
            self.assertEqual(detect_system_ui_language(), "en")

    def test_windows_language_detection_uses_the_user_ui_language(self):
        from quota_orb import desktop_widget

        class Kernel32:
            def __init__(self):
                self.calls = []

            def GetUserDefaultUILanguage(self):
                self.calls.append(("GetUserDefaultUILanguage",))
                return 0x0804

            def LCIDToLocaleName(self, lcid, buffer, size, flags):
                self.calls.append(("LCIDToLocaleName", lcid, size, flags))
                buffer.value = "zh-CN"
                return len(buffer.value) + 1

            def GetUserDefaultLocaleName(self, *_args):
                raise AssertionError("locale preference must not replace the UI language")

        kernel32 = Kernel32()
        windll = type("Windll", (), {"kernel32": kernel32})()
        with patch("quota_orb.desktop_widget.os.name", "nt"), patch.object(
            desktop_widget.ctypes, "windll", windll, create=True
        ):
            self.assertEqual(detect_system_ui_language(), "zh-CN")

        self.assertEqual(
            kernel32.calls,
            [
                ("GetUserDefaultUILanguage",),
                ("LCIDToLocaleName", 0x0804, 85, 0),
            ],
        )

    def test_rendered_orb_is_antialiased_rgba_without_a_rectangular_background(self):
        frame = render_orb_frame(68, phase=0.0, bubble_phase=0.0, scale=4)

        self.assertEqual(frame.mode, "RGBA")
        self.assertEqual(frame.size, (132, 132))
        alpha = frame.getchannel("A")
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertEqual(alpha.getpixel((131, 131)), 0)
        self.assertGreater(sum(alpha.histogram()[1:255]), 100)

    def test_windows_display_frame_uses_exact_chroma_key_without_pixels_outside_orb(self):
        from quota_orb.desktop_widget import TRANSPARENT_COLOR

        key = ImageColor.getrgb(TRANSPARENT_COLOR)
        allowed = Image.new("L", (132, 132), 0)
        ImageDraw.Draw(allowed).ellipse((13, 11, 119, 117), fill=255)
        for pressed in (False, True):
            for focused in (False, True):
                with self.subTest(pressed=pressed, focused=focused):
                    rgba = render_orb_frame(
                        68,
                        0.4,
                        0.7,
                        pressed=pressed,
                        focused=focused,
                    )
                    displayed = prepare_windows_display_frame(rgba)

                    self.assertEqual(displayed.mode, "RGB")
                    self.assertEqual(displayed.size, (132, 132))
                    for corner in ((0, 0), (131, 0), (0, 131), (131, 131)):
                        self.assertEqual(displayed.getpixel(corner), key)
                    for y in range(132):
                        for x in range(132):
                            if displayed.getpixel((x, y)) != key:
                                self.assertEqual(allowed.getpixel((x, y)), 255)
                    self.assertNotEqual(displayed.getpixel((66, 64)), key)
                    self.assertGreater(
                        len(displayed.crop((20, 18, 112, 112)).getcolors(20_000)),
                        100,
                    )

    def test_keyboard_focus_ring_is_visible_high_contrast_and_motion_stable(self):
        unfocused = render_orb_frame(
            68,
            phase=0.0,
            bubble_phase=0.0,
            focused=False,
        )
        focused = render_orb_frame(
            68,
            phase=0.0,
            bubble_phase=0.0,
            focused=True,
        )
        difference = ImageChops.difference(unfocused, focused)
        self.assertIsNotNone(difference.getbbox())
        self.assertGreater(sum(ImageStat.Stat(difference).sum), 25_000)

        changed_bright_pixels = 0
        for y in range(132):
            for x in range(132):
                if max(difference.getpixel((x, y))) >= 24:
                    self.assertLessEqual(((x - 66) / 47) ** 2 + ((y - 64) / 47) ** 2, 1.08)
                    if sum(focused.getpixel((x, y))[:3]) >= 650:
                        changed_bright_pixels += 1
        self.assertGreaterEqual(changed_bright_pixels, 80)

        first = render_orb_frame(
            68,
            phase=1.2,
            bubble_phase=2.3,
            reduced_motion=True,
            focused=True,
        )
        second = render_orb_frame(
            68,
            phase=5.1,
            bubble_phase=0.2,
            reduced_motion=True,
            focused=True,
        )
        self.assertIsNone(ImageChops.difference(first, second).getbbox())

    def test_rendered_layers_have_visible_depth_and_motion_without_changing_data(self):
        initial = render_orb_frame(68, phase=0.0, bubble_phase=0.0)
        advanced = render_orb_frame(68, phase=0.8, bubble_phase=1.1)
        difference = ImageChops.difference(initial, advanced)

        self.assertGreater(sum(ImageStat.Stat(difference).sum), 50_000)
        # Specular highlight, liquid body, and deep volume must remain visibly distinct.
        self.assertGreater(sum(initial.getpixel((36, 36))[:3]), sum(initial.getpixel((66, 104))[:3]))
        self.assertNotEqual(initial.getpixel((66, 78)), initial.getpixel((66, 101)))
        self.assertNotEqual(liquid_surface_points(68, 0.0, layer=0), liquid_surface_points(68, 0.0, layer=1))

    def test_wave_phases_move_in_opposite_directions_and_reduced_motion_is_stable(self):
        front_initial, back_initial = wave_phases(0.0)
        front_next, back_next = wave_phases(0.5)
        self.assertGreater(front_next, front_initial)
        self.assertLess(back_next, back_initial)

        self.assertEqual(next_animation_state(1.2, 2.3, reduced_motion=True), (0.0, 0.0))
        first = render_orb_frame(68, phase=1.2, bubble_phase=2.3, reduced_motion=True)
        second = render_orb_frame(68, phase=5.1, bubble_phase=0.2, reduced_motion=True)
        self.assertEqual(ImageChops.difference(first, second).getbbox(), None)

        with patch("quota_orb.desktop_widget.os.name", "posix"):
            self.assertFalse(windows_reduced_motion_enabled())

    def test_unknown_zero_and_extreme_values_render_inside_transparent_bounds(self):
        frames = [render_orb_frame(value, phase=1.0, bubble_phase=2.0) for value in (None, 0, 1, 30, 50, 100)]
        self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())
        for frame in frames:
            with self.subTest():
                self.assertEqual(frame.info["render_scale"], 4)
                self.assertEqual(frame.getpixel((0, 0))[3], 0)
                self.assertEqual(frame.getpixel((131, 131))[3], 0)

    def test_renderer_average_frame_time_stays_within_widget_budget(self):
        render_orb_frame(68, 0.0, 0.0)
        frames = 12
        started = time.perf_counter()
        for index in range(frames):
            render_orb_frame(68, index * 0.17, index * 0.11)
        average_ms = (time.perf_counter() - started) * 1000 / frames
        self.assertLessEqual(average_ms, 35.0)

    def test_unknown_hides_remaining_sublabel_but_real_zero_keeps_it(self):
        self.assertEqual(orb_labels(None), ("?", None))
        self.assertEqual(orb_labels(0), ("0%", "REMAIN"))
        self.assertEqual(orb_labels(None, language="zh-CN"), ("?", None))
        self.assertEqual(orb_labels(0, language="zh-CN"), ("0%", "剩余"))

        unknown = render_orb_frame(None, 0.0, 0.0)
        zero = render_orb_frame(0, 0.0, 0.0)
        chinese = render_orb_frame(0, 0.0, 0.0, language="zh-CN")
        label_region = (40, 83, 92, 96)
        self.assertNotEqual(unknown.crop(label_region).tobytes(), zero.crop(label_region).tobytes())
        self.assertNotEqual(zero.crop(label_region).tobytes(), chinese.crop(label_region).tobytes())

    def test_unknown_and_real_zero_keep_distinct_liquid_geometry(self):
        self.assertIsNone(surface_y(None))
        self.assertEqual(surface_y(0), 113.0)
        self.assertAlmostEqual(surface_y(50), 64.0, places=6)
        self.assertEqual(surface_y(100), 15.0)
        self.assertEqual(surface_y(-10), 113.0)
        self.assertEqual(surface_y(120), 15.0)
        self.assertIsNone(surface_y("0"))

    def test_visible_liquid_area_matches_remaining_percent_and_is_monotonic(self):
        measured = []
        for remaining in (1, 30, 48, 50, 68, 100):
            for phase in (0.0, 1.3):
                with self.subTest(remaining=remaining, phase=phase):
                    fraction = liquid_fill_fraction(remaining, phase=phase, scale=4)
                    self.assertLessEqual(abs(fraction * 100 - remaining), 1.5)
            measured.append(liquid_fill_fraction(remaining, phase=0.7, scale=4))
        self.assertEqual(measured, sorted(measured))

    def test_dynamic_palette_stays_in_band_and_varies_continuously(self):
        def rgb(percent):
            return ImageColor.getrgb(liquid_palette(percent)["body"])

        for percent in (50, 68, 75, 100):
            red, green, blue = rgb(percent)
            self.assertGreaterEqual(green, red)
            self.assertGreater(green, blue)
        for percent in (30, 40, 48):
            red, green, blue = rgb(percent)
            self.assertGreaterEqual(red, green)
            self.assertGreater(green, blue)
        for percent in (0, 15, 29.999):
            red, green, blue = rgb(percent)
            self.assertGreater(red, green)
            self.assertGreater(red, blue)

        luminance = lambda color: sum(ImageColor.getrgb(color))
        self.assertGreater(luminance(liquid_palette(50)["body"]), luminance(liquid_palette(75)["body"]))
        self.assertGreater(luminance(liquid_palette(100)["body"]), luminance(liquid_palette(75)["body"]))
        self.assertGreater(luminance(liquid_palette(49)["body"]), luminance(liquid_palette(30)["body"]))
        self.assertGreater(luminance(liquid_palette(29)["body"]), luminance(liquid_palette(0)["body"]))

        for percent in (10, 40, 60, 85):
            for key in ("body", "deep", "rim", "meta"):
                left = ImageColor.getrgb(liquid_palette(percent)[key])
                right = ImageColor.getrgb(liquid_palette(percent + 0.01)[key])
                self.assertLessEqual(sum(abs(a - b) for a, b in zip(left, right)), 3)

        for boundary in (30, 50):
            for key in ("body", "deep", "rim", "shell", "meta"):
                below = ImageColor.getrgb(liquid_palette(boundary - 0.001)[key])
                at = ImageColor.getrgb(liquid_palette(boundary)[key])
                self.assertLessEqual(sum(abs(a - b) for a, b in zip(below, at)), 3)
            frame_below = render_orb_frame(boundary - 0.001, 0.7, 1.9)
            frame_at = render_orb_frame(boundary, 0.7, 1.9)
            mean_delta = sum(ImageStat.Stat(ImageChops.difference(frame_below, frame_at)).mean)
            self.assertLessEqual(mean_delta, 2.0)

        fifty = render_orb_frame(50, 0.0, 0.0)
        seventy_five = render_orb_frame(75, 0.0, 0.0)
        hundred = render_orb_frame(100, 0.0, 0.0)
        rim_region = (12, 12, 120, 118)
        self.assertNotEqual(fifty.crop(rim_region).tobytes(), seventy_five.crop(rim_region).tobytes())
        self.assertNotEqual(seventy_five.crop(rim_region).tobytes(), hundred.crop(rim_region).tobytes())
        self.assertNotEqual(fifty.getpixel((66, 11)), seventy_five.getpixel((66, 11)))

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

    def test_detail_text_keeps_identity_windows_and_data_classes_explicit(self):
        snapshot = {
            "platform": "codex",
            "provider": "openai-codex",
            "profile": "personal",
            "account": "user@example.test",
            "model": "gpt-5.6",
            "generated_at": "2026-08-13T08:00:00+00:00",
            "subscription_quota": {
                "available": True,
                "source": "official-codex-app-server",
                "plan": "Plus",
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
                        "reset_at": None,
                    },
                ],
            },
            "api_quota": {
                "available": False,
                "source": "unavailable",
                "limits": [],
                "unavailable_reason": "No API quota source is configured.",
            },
            "local_usage": {
                "available": True,
                "source": "hermes-state-db",
                "day": "2026-08-13",
                "totals": {"total_tokens": 1234, "sessions": 2},
                "by_provider": [
                    {
                        "provider": "openai-codex",
                        "total_tokens": 1234,
                        "models": [{"model": "gpt-5.6", "total_tokens": 1234}],
                    }
                ],
            },
            "token_billing": {
                "available": True,
                "source": "provider-statement",
                "usage": {"total_tokens": 1234},
                "allowance": {"remaining_tokens": 8766, "remaining_percent": 87.66},
                "cost": {"amount": 1.25, "currency": "USD", "classification": "actual"},
            },
        }

        details = detail_snapshot_text(snapshot)
        for expected in (
            "Platform: codex",
            "Provider: openai-codex",
            "Profile: personal",
            "Account: user@example.test",
            "Model: gpt-5.6",
            "Plan: Plus",
            "Source: official-codex-app-server",
            "Session",
            "Used: 32%",
            "Remaining: 68%",
            "Weekly",
            "Reset: Unavailable",
            "API quota: Unavailable",
            "No API quota source is configured.",
            "Local usage (local; not an invoice)",
            "gpt-5.6",
            "Cost (actual; provider-reported): USD 1.25",
        ):
            self.assertIn(expected, details)

        snapshot["token_billing"]["cost"]["classification"] = "estimated"
        estimated = detail_snapshot_text(snapshot)
        self.assertIn("Cost (estimated; dated-price calculation): USD 1.25", estimated)
        self.assertNotIn("Cost (actual; provider-reported):", estimated)

    def test_detail_text_uses_unavailable_instead_of_inventing_values(self):
        details = detail_snapshot_text(None)
        self.assertGreaterEqual(details.count("Unavailable"), 8)
        self.assertNotIn("0%", details)

        unavailable = detail_snapshot_text(
            {
                "token_billing": {
                    "available": False,
                    "source": "unavailable",
                    "usage": {"total_tokens": 999},
                    "allowance": {"remaining_percent": 77},
                    "cost": {"amount": 9, "currency": "USD", "classification": "actual"},
                    "unavailable_reason": "Not verified.",
                },
                "local_usage": {
                    "available": False,
                    "totals": {"total_tokens": 999},
                    "unavailable_reason": "Not verified.",
                },
            }
        )
        self.assertNotIn("999", unavailable)
        self.assertNotIn("77", unavailable)
        self.assertNotIn("USD 9", unavailable)

    def test_detail_text_localizes_fixed_labels_without_modifying_raw_facts(self):
        snapshot = {
            "platform": "codex-raw",
            "provider": "openai-codex-raw",
            "profile": "personal-raw",
            "account": "account-raw@example.test",
            "model": "gpt-raw",
            "generated_at": "2026-08-13T08:00:00+00:00",
            "subscription_quota": {
                "available": True,
                "source": "subscription-source-raw",
                "plan": "plan-raw",
                "windows": [
                    {
                        "label": "window-label-raw",
                        "used_percent": 32,
                        "remaining_percent": 68,
                        "reset_at": "reset-raw",
                        "detail": "window-detail-raw",
                    }
                ],
            },
            "api_quota": {
                "available": True,
                "source": "api-source-raw",
                "limits": [
                    {
                        "label": "limit-label-raw",
                        "used": 4,
                        "remaining": 6,
                        "limit": 10,
                        "unit": "requests-raw",
                        "reset_at": "api-reset-raw",
                        "detail": "api-detail-raw",
                    }
                ],
            },
            "local_usage": {
                "available": True,
                "source": "local-source-raw",
                "day": "2026-08-13",
                "totals": {"total_tokens": 1234},
                "by_provider": [
                    {
                        "provider": "local-provider-raw",
                        "models": [{"model": "local-model-raw", "total_tokens": 1234}],
                    }
                ],
            },
            "token_billing": {
                "available": True,
                "source": "billing-source-raw",
                "usage": {"total_tokens": 1234},
                "allowance": {"remaining_tokens": 8766},
                "cost": {
                    "amount": 1.25,
                    "currency": "USD",
                    "classification": "actual",
                    "basis": "basis-raw",
                },
            },
        }

        details = detail_snapshot_text(snapshot, language="zh-CN")
        for expected in (
            "QUOTA ORB · 详情",
            "身份",
            "平台: codex-raw",
            "供应商: openai-codex-raw",
            "订阅配额: 可用",
            "已用: 32%",
            "剩余: 68%",
            "API 配额: 可用",
            "本地用量（仅本机；非账单）: 可用",
            "Token 计费: 可用",
            "费用（实际；供应商报告）: USD 1.25",
        ):
            self.assertIn(expected, details)
        for raw_value in (
            "account-raw@example.test",
            "window-label-raw",
            "window-detail-raw",
            "limit-label-raw",
            "requests-raw",
            "local-provider-raw",
            "local-model-raw",
            "basis-raw",
        ):
            self.assertIn(raw_value, details)
        for english_label in (
            "QUOTA ORB · DETAILS",
            "IDENTITY",
            "Platform:",
            "Provider:",
            "Subscription quota:",
            "Used:",
            "Remaining:",
            "API quota:",
            "Available",
            "Cost (actual; provider-reported):",
        ):
            self.assertNotIn(english_label, details)

        snapshot["token_billing"]["cost"]["classification"] = "estimated"
        estimated = detail_snapshot_text(snapshot, language="zh-CN")
        self.assertIn("费用（估算；按日期价格计算）: USD 1.25", estimated)
        self.assertNotIn("费用（实际；供应商报告）:", estimated)

    def test_chinese_unavailable_is_fail_closed_and_has_no_fixed_english_status(self):
        details = detail_snapshot_text(None, language="zh-CN")
        self.assertGreaterEqual(details.count("不可用"), 8)
        self.assertNotIn("Unavailable", details)
        self.assertNotIn("0%", details)

        unavailable = detail_snapshot_text(
            {
                "token_billing": {
                    "available": False,
                    "usage": {"total_tokens": 999},
                    "allowance": {"remaining_percent": 77},
                    "cost": {"amount": 9, "currency": "USD", "classification": "actual"},
                    "unavailable_reason": "reason-value-raw",
                }
            },
            language="zh-CN",
        )
        self.assertIn("原因: reason-value-raw", unavailable)
        self.assertNotIn("999", unavailable)
        self.assertNotIn("77", unavailable)
        self.assertNotIn("USD 9", unavailable)

    def test_panel_fixed_ui_strings_are_complete_in_both_languages(self):
        english = panel_ui_text("en")
        chinese = panel_ui_text("zh-CN")
        self.assertEqual(english["panel_title"], "Quota Orb · Read-only details")
        self.assertEqual(english["panel_subtitle"], "Read-only account details")
        self.assertEqual(english["refresh"], "Refresh")
        self.assertEqual(english["close"], "Close")
        self.assertEqual(chinese["panel_title"], "Quota Orb · 只读详情")
        self.assertEqual(chinese["panel_subtitle"], "只读账户详情")
        self.assertEqual(chinese["refresh"], "刷新")
        self.assertEqual(chinese["close"], "关闭")
        self.assertEqual(set(english), set(chinese))

        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        for marker in (
            'panel.title(texts["panel_title"])',
            'text=texts["panel_subtitle"]',
            'text=texts["close"]',
            'text=texts["refresh"]',
        ):
            self.assertIn(marker, source)

    def test_detail_panel_model_has_summary_and_five_truthful_cards(self):
        snapshot = {
            "platform": "codex-mock",
            "provider": "provider-raw",
            "profile": "profile-raw",
            "account": "account-raw",
            "model": "model-raw",
            "generated_at": "time-raw",
            "subscription_quota": {
                "available": True,
                "plan": "plan-raw",
                "source": "source-raw",
                "windows": [{"label": "window-raw", "remaining_percent": 68, "used_percent": 32}],
            },
            "api_quota": {"available": False, "unavailable_reason": "reason-raw"},
            "local_usage": {"available": False, "unavailable_reason": "local-reason-raw"},
            "token_billing": {"available": False, "unavailable_reason": "billing-reason-raw"},
        }

        english = detail_panel_model(snapshot, language="en")
        self.assertEqual(
            english["summary"],
            {
                "remaining": "68%",
                "scope": "window-raw",
                "reset": "Unavailable",
                "plan": "plan-raw",
                "source": "source-raw",
            },
        )
        self.assertEqual(
            [card["title"] for card in english["cards"]],
            ["SUBSCRIPTION QUOTA", "API QUOTA", "LOCAL USAGE", "TOKEN BILLING", "IDENTITY"],
        )
        self.assertIn("reason-raw", english["cards"][1]["body"])
        self.assertIn("provider-raw", english["cards"][4]["body"])

        chinese = detail_panel_model(snapshot, language="zh-CN")
        self.assertEqual(chinese["summary"]["remaining"], "68%")
        self.assertEqual(
            [card["title"] for card in chinese["cards"]],
            ["订阅配额", "API 配额", "本地用量", "TOKEN 计费", "身份"],
        )
        self.assertNotIn("IDENTITY", "\n".join(card["body"] for card in chinese["cards"]))

        unknown = detail_panel_model(None, language="zh-CN")
        self.assertEqual(unknown["summary"]["remaining"], "不可用")
        self.assertNotIn("0%", str(unknown))

    def test_panel_uses_proportional_type_cards_and_keyboard_button_states(self):
        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        self.assertNotIn('else "Consolas"', source)
        for marker in (
            "detail_panel_model(",
            "self.detail_cards = tk.Frame(",
            'highlightbackground="#2a3b45"',
            'font=typography["body"]',
            'font=typography["section"]',
            "takefocus=True",
            'refresh_button.bind("<Enter>"',
            'refresh_button.bind("<Leave>"',
            'refresh_button.bind("<FocusIn>"',
            'refresh_button.bind("<FocusOut>"',
        ):
            self.assertIn(marker, source)

    def test_panel_typography_uses_real_windows_families_and_requested_scale(self):
        from quota_orb import desktop_widget

        english = desktop_widget.panel_typography("en")
        chinese = desktop_widget.panel_typography("zh-CN")

        self.assertEqual(english["body"], ("Segoe UI", 10))
        self.assertEqual(english["title"], ("Segoe UI", 13, "bold"))
        self.assertEqual(english["section"], ("Segoe UI", 10, "bold"))
        self.assertEqual(english["key"], ("Segoe UI", 24, "bold"))
        self.assertEqual(chinese["body"], ("Microsoft YaHei UI", 10))
        self.assertEqual(chinese["title"], ("Microsoft YaHei UI", 13, "bold"))
        self.assertEqual(chinese["section"], ("Microsoft YaHei UI", 10, "bold"))
        self.assertEqual(chinese["key"], ("Microsoft YaHei UI", 24, "bold"))

        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        self.assertNotIn("Microsoft YaHei UI Semibold", source)

    def test_only_unavailable_body_rows_receive_the_amber_tone(self):
        from quota_orb import desktop_widget

        english = desktop_widget.panel_body_rows(
            "Subscription quota: Unavailable\nReason: Not verified.", language="en"
        )
        chinese = desktop_widget.panel_body_rows(
            "订阅配额: 不可用\n原因: 未验证。", language="zh-CN"
        )
        self.assertEqual(
            english,
            [
                ("Subscription quota: Unavailable", "unavailable"),
                ("Reason: Not verified.", "normal"),
            ],
        )
        self.assertEqual(
            chinese,
            [("订阅配额: 不可用", "unavailable"), ("原因: 未验证。", "normal")],
        )

        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        self.assertNotIn("status_line = body.splitlines()[0]", source)

    def test_panel_keyboard_scroll_and_control_geometry_contract(self):
        from quota_orb import desktop_widget

        class Canvas:
            def __init__(self):
                self.calls = []

            def yview_scroll(self, amount, unit):
                self.calls.append(("scroll", amount, unit))

            def yview_moveto(self, fraction):
                self.calls.append(("moveto", fraction))

        canvas = Canvas()
        for key in ("Up", "Down", "Prior", "Next", "Home", "End"):
            with self.subTest(key=key):
                self.assertTrue(desktop_widget.scroll_panel_by_key(canvas, key))
        self.assertEqual(
            canvas.calls,
            [
                ("scroll", -1, "units"),
                ("scroll", 1, "units"),
                ("scroll", -1, "pages"),
                ("scroll", 1, "pages"),
                ("moveto", 0.0),
                ("moveto", 1.0),
            ],
        )
        self.assertFalse(desktop_widget.scroll_panel_by_key(canvas, "Return"))
        self.assertEqual(desktop_widget.PANEL_SCROLLBAR_WIDTH, 12)
        self.assertEqual(desktop_widget.PANEL_BUTTON_MIN_SIZE["refresh"], (72, 32))
        self.assertEqual(desktop_widget.PANEL_BUTTON_MIN_SIZE["close"], (48, 32))

        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        for marker in (
            'panel.bind("<Up>"',
            'panel.bind("<Down>"',
            'panel.bind("<Prior>"',
            'panel.bind("<Next>"',
            'panel.bind("<Home>"',
            'panel.bind("<End>"',
            'scroll_track.bind("<ButtonPress-1>"',
            'scroll_track.bind("<B1-Motion>"',
            "highlightthickness=2",
        ):
            self.assertIn(marker, source)

    def test_panel_prefers_a_side_and_clamps_to_multi_monitor_work_areas(self):
        areas = [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)]
        self.assertEqual(
            panel_position((-1700, 900), (132, 132), (392, 620), areas),
            (-1556, 460),
        )
        self.assertEqual(
            panel_position((30, 50), (132, 132), (392, 620), areas),
            (174, 50),
        )
        self.assertEqual(
            panel_position((1760, 900), (132, 132), (392, 620), areas),
            (1356, 460),
        )

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

    def test_summary_prioritizes_subscription_windows_over_token_allowance(self):
        local_timezone = timezone(timedelta(hours=8))
        snapshot = {
            "subscription_quota": {
                "available": True,
                "plan": "Plus",
                "source": "official-subscription",
                "windows": [
                    {
                        "label": "Session",
                        "remaining_percent": 68,
                        "reset_at": "2026-08-13T12:00:00+00:00",
                    },
                    {
                        "label": "Weekly",
                        "remaining_percent": 45,
                        "reset_at": "2026-08-13T14:30:00+00:00",
                    },
                ],
            },
            "token_billing": {
                "available": True,
                "source": "official-token-allowance",
                "allowance": {
                    "remaining_percent": 29.5,
                    "reset_at": "2026-08-14T01:00:00+00:00",
                },
            },
        }

        self.assertEqual(select_remaining_percent(snapshot), 45.0)
        subscription_summary = detail_panel_model(
            snapshot, language="en", local_timezone=local_timezone
        )["summary"]
        self.assertEqual(subscription_summary["remaining"], "45%")
        self.assertEqual(subscription_summary["scope"], "Weekly")
        self.assertEqual(subscription_summary["reset"], "Aug 13, 2026 · 10:30 PM (UTC+08:00)")
        self.assertEqual(subscription_summary["source"], "official-subscription")

        snapshot["token_billing"]["allowance"]["remaining_percent"] = 80
        self.assertEqual(select_remaining_percent(snapshot), 45.0)
        english = detail_panel_model(
            snapshot, language="en", local_timezone=local_timezone
        )["summary"]
        chinese = detail_panel_model(
            snapshot, language="zh-CN", local_timezone=local_timezone
        )["summary"]
        self.assertEqual(english["scope"], "Weekly")
        self.assertEqual(english["reset"], "Aug 13, 2026 · 10:30 PM (UTC+08:00)")
        self.assertEqual(chinese["scope"], "Weekly")
        self.assertEqual(chinese["reset"], "2026年8月13日 22:30（UTC+08:00）")

        unavailable = detail_panel_model(
            None, language="zh-CN", local_timezone=local_timezone
        )["summary"]
        self.assertEqual(unavailable["remaining"], "不可用")
        self.assertEqual(unavailable["scope"], "不可用")
        self.assertEqual(unavailable["reset"], "不可用")

    def test_demo_panel_is_explicit_and_localizes_window_and_system_times(self):
        local_timezone = timezone(timedelta(hours=8))
        snapshot = {
            "demo": True,
            "platform": "codex-mock",
            "generated_at": "2026-08-13T08:00:00+00:00",
            "subscription_quota": {
                "available": True,
                "source": "demo-fixture",
                "windows": [
                    {
                        "label": "Weekly",
                        "remaining_percent": 45,
                        "reset_at": "2026-08-13T14:30:00+00:00",
                    }
                ],
            },
        }

        english = detail_panel_model(
            snapshot, language="en", local_timezone=local_timezone
        )
        chinese = detail_panel_model(
            snapshot, language="zh-CN", local_timezone=local_timezone
        )
        self.assertEqual(english["demo"], "Demo")
        self.assertEqual(chinese["demo"], "演示")
        self.assertIn("Weekly", english["cards"][0]["body"])
        self.assertIn("Aug 13, 2026 · 10:30 PM (UTC+08:00)", english["cards"][0]["body"])
        self.assertIn("Weekly", chinese["cards"][0]["body"])
        self.assertIn("2026年8月13日 22:30（UTC+08:00）", chinese["cards"][0]["body"])
        self.assertIn("2026年8月13日 16:00（UTC+08:00）", chinese["cards"][-1]["body"])

        production = detail_panel_model(
            {"platform": "codex"}, language="zh-CN", local_timezone=local_timezone
        )
        self.assertIsNone(production["demo"])

        source = (ROOT / "quota_orb" / "desktop_widget.py").read_text(encoding="utf-8")
        self.assertIn('text=model["demo"]', source)

    def test_bilingual_demo_screenshot_contract_keeps_orb_and_summary_identical(self):
        import importlib.util

        script_path = ROOT / "scripts" / "render_widget_mock_evidence.py"
        self.assertTrue(script_path.is_file())
        spec = importlib.util.spec_from_file_location("render_widget_mock_evidence", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for language, demo_label in (("en", "Demo"), ("zh-CN", "演示")):
            with self.subTest(language=language):
                snapshot, remaining, model = module.screenshot_contract(language)
                self.assertEqual(remaining, select_remaining_percent(snapshot))
                self.assertEqual(model["summary"]["remaining"], orb_labels(remaining, language=language)[0])
                self.assertEqual(model["demo"], demo_label)
                self.assertEqual(model["summary"]["scope"], "Weekly")

                placeholder = __import__("PIL.Image", fromlist=["Image"]).new(
                    "RGB", DETAIL_SIZE, "#0b1118"
                )
                evidence = module.compose_evidence(
                    placeholder,
                    remaining=remaining,
                    language=language,
                )
                self.assertEqual(evidence.size, module.EVIDENCE_SIZE)
                self.assertNotEqual(evidence.getpixel((85, 330)), evidence.getpixel((0, 0)))

    def test_demo_panel_capture_validation_rejects_invalid_images(self):
        import importlib.util

        script_path = ROOT / "scripts" / "render_widget_mock_evidence.py"
        spec = importlib.util.spec_from_file_location("render_widget_mock_evidence", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        valid = Image.new("RGB", DETAIL_SIZE, "#0b1118")
        draw = ImageDraw.Draw(valid)
        draw.rectangle((0, 0, DETAIL_SIZE[0] - 1, 63), fill="#0f1720")
        draw.point((20, 80), fill="#f2c66d")
        metrics = module.validate_panel_capture(valid)
        self.assertGreaterEqual(metrics["dark_ratio"], 0.70)
        self.assertLess(metrics["header_white_ratio"], 0.50)
        self.assertGreater(metrics["demo_amber_pixels"], 0)

        wrong_size = Image.new("RGB", (DETAIL_SIZE[0] + 100, DETAIL_SIZE[1]), "#0b1118")
        wrong_size.putpixel((20, 80), ImageColor.getrgb("#f2c66d"))
        with self.assertRaisesRegex(RuntimeError, "size"):
            module.validate_panel_capture(wrong_size)

        white = Image.new("RGB", DETAIL_SIZE, "white")
        with self.assertRaisesRegex(RuntimeError, "dark ratio"):
            module.validate_panel_capture(white)

        white_header = valid.copy()
        ImageDraw.Draw(white_header).rectangle(
            (0, 0, DETAIL_SIZE[0] - 1, 63), fill="white"
        )
        with self.assertRaisesRegex(RuntimeError, "header"):
            module.validate_panel_capture(white_header)

        no_demo_amber = Image.new("RGB", DETAIL_SIZE, "#0b1118")
        with self.assertRaisesRegex(RuntimeError, "Demo amber"):
            module.validate_panel_capture(no_demo_amber)

        amber_only_below_demo = no_demo_amber.copy()
        amber_only_below_demo.putpixel((20, 200), ImageColor.getrgb("#f2c66d"))
        with self.assertRaisesRegex(RuntimeError, "Demo amber"):
            module.validate_panel_capture(amber_only_below_demo)

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

    def test_release_toggles_details_for_click_but_never_for_drag(self):
        orb = DesktopOrb.__new__(DesktopOrb)
        toggles = []
        redraws = []
        positions = []
        orb.pointer_start = (100, 100)
        orb.window_start = (20, 20)
        orb.pressed = True
        orb.remaining = 68.0
        orb._toggle_details = lambda: toggles.append("toggle")
        orb._draw = lambda remaining: redraws.append(remaining)

        orb.dragging = False
        orb._release(object())
        self.assertEqual(toggles, ["toggle"])
        self.assertFalse(orb.pressed)

        orb.pointer_start = (100, 100)
        orb.window_start = (20, 20)
        orb.dragging = True
        orb.pressed = False
        orb.state_path = Path("position.json")
        orb._current_position = lambda: (4000, 100)
        orb._areas = lambda: [(0, 0, 1920, 1080)]
        orb._set_position = positions.append
        with patch("quota_orb.desktop_widget.save_position") as save:
            orb._release(object())

        self.assertEqual(toggles, ["toggle"])
        self.assertEqual(positions, [(1788, 100)])
        save.assert_called_once_with(Path("position.json"), (1788, 100))

        orb.pointer_start = (100, 100)
        orb.window_start = (20, 20)
        orb.dragging = False
        orb._current_position = lambda: (120, 20)
        orb._areas = lambda: [(0, 0, 1920, 1080)]
        with patch("quota_orb.desktop_widget.save_position"):
            orb._release(type("Event", (), {"x_root": 200, "y_root": 100})())
        self.assertEqual(toggles, ["toggle"])

    def test_canvas_focus_events_update_visible_state_and_redraw(self):
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.remaining = 68.0
        orb.focus_visible = False
        redraws = []
        orb._draw = redraws.append

        orb._focus_in(object())
        self.assertTrue(orb.focus_visible)
        self.assertEqual(redraws, [68.0])

        orb._focus_out(object())
        self.assertFalse(orb.focus_visible)
        self.assertEqual(redraws, [68.0, 68.0])

    def test_detail_toggle_is_single_instance_and_panel_close_does_not_destroy_orb(self):
        class Panel:
            def __init__(self):
                self.destroyed = False

            def winfo_exists(self):
                return not self.destroyed

            def destroy(self):
                self.destroyed = True

        class Root:
            destroyed = False

        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = Root()
        orb.detail_window = None
        orb.detail_text = None
        orb.refresh_button = None
        orb.detail_status = None
        opened = []

        def open_panel():
            panel = Panel()
            orb.detail_window = panel
            opened.append(panel)

        orb._open_details = open_panel
        self.assertEqual(orb._toggle_details(), "break")
        self.assertEqual(len(opened), 1)
        panel = opened[0]
        self.assertEqual(orb._toggle_details(), "break")
        self.assertTrue(panel.destroyed)
        self.assertIsNone(orb.detail_window)
        self.assertFalse(orb.root.destroyed)

        orb._open_details()
        self.assertEqual(orb._close_details(object()), "break")
        self.assertTrue(opened[-1].destroyed)
        self.assertFalse(orb.root.destroyed)

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
        empty = render_orb_frame(0, 0.0, 0.0)
        positive = render_orb_frame(1, 0.0, 0.0)
        liquid_region = (20, 78, 112, 114)
        self.assertNotEqual(empty.crop(liquid_region).tobytes(), positive.crop(liquid_region).tobytes())

    def test_tk_draw_uses_one_photoimage_and_keeps_its_reference(self):
        class Canvas:
            def __init__(self):
                self.images = []

            def delete(self, *_args):
                self.images.clear()

            def create_image(self, *args, **kwargs):
                self.images.append((args, kwargs))

        orb = DesktopOrb.__new__(DesktopOrb)
        orb.canvas = Canvas()
        orb.liquid_phase = 0.4
        orb.bubble_phase = 0.8
        orb.reduced_motion = False
        orb.pressed = False
        sentinel = object()
        with patch("PIL.ImageTk.PhotoImage", return_value=sentinel) as photo_image:
            orb._draw(68)

        rendered = photo_image.call_args.args[0]
        self.assertEqual(rendered.size, (132, 132))
        self.assertIs(orb._photo_image, sentinel)
        self.assertIs(orb.canvas.images[0][1]["image"], sentinel)

    def test_tk_draw_passes_a_chroma_key_frame_only_on_windows(self):
        from quota_orb.desktop_widget import TRANSPARENT_COLOR

        class Canvas:
            def delete(self, *_args):
                return None

            def create_image(self, *_args, **_kwargs):
                return None

        orb = DesktopOrb.__new__(DesktopOrb)
        orb.canvas = Canvas()
        orb.liquid_phase = 0.4
        orb.bubble_phase = 0.8
        orb.reduced_motion = False
        orb.pressed = False
        orb.language = "en"
        key = ImageColor.getrgb(TRANSPARENT_COLOR)

        with patch("quota_orb.desktop_widget.os.name", "nt"), patch(
            "PIL.ImageTk.PhotoImage", return_value=object()
        ) as photo_image:
            orb._draw(68)
        windows_frame = photo_image.call_args.args[0]
        self.assertEqual(windows_frame.mode, "RGB")
        self.assertEqual(windows_frame.getpixel((0, 0)), key)

        with patch("quota_orb.desktop_widget.os.name", "posix"), patch(
            "PIL.ImageTk.PhotoImage", return_value=object()
        ) as photo_image:
            orb._draw(68)
        self.assertEqual(photo_image.call_args.args[0].mode, "RGBA")

    def test_liquid_geometry_changes_when_animation_phase_advances_at_a_fixed_percentage(self):
        initial = liquid_surface_points(68, 0.0)
        advanced = liquid_surface_points(68, 0.35)

        self.assertEqual(len(initial), len(advanced))
        self.assertNotEqual(initial, advanced)

    def test_liquid_surface_points_stay_within_the_orb_at_all_levels_and_phases(self):
        for value in (1, 68, 100):
            for phase in (0.0, 0.35, 1.7, 4.2):
                with self.subTest(value=value, phase=phase):
                    for x, y in liquid_surface_points(value, phase):
                        self.assertLessEqual((x - 66) ** 2 + (y - 64) ** 2, 49**2 + 1e-6)

    def test_animation_ticks_redraw_without_refreshing_quota_and_stop_after_destroy(self):
        class Root:
            def __init__(self):
                self.calls = []

            def after(self, milliseconds, callback):
                self.calls.append((milliseconds, callback))

            def winfo_exists(self):
                return True

        root = Root()
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = root
        orb.remaining = 68.0
        orb.liquid_phase = 0.0
        orb.bubble_phase = 0.0
        orb.reduced_motion = False
        orb._destroyed = False
        orb.source = type("Source", (), {"snapshot": lambda self: (_ for _ in ()).throw(AssertionError())})()
        frames = []
        orb._draw = lambda remaining: frames.append((remaining, orb.liquid_phase, orb.bubble_phase))

        orb._animate()

        self.assertNotEqual(orb.liquid_phase, 0.0)
        self.assertNotEqual(orb.bubble_phase, 0.0)
        first_geometry = frames[-1]
        self.assertEqual(len(root.calls), 1)
        self.assertLessEqual(root.calls[0][0], 42)
        orb._animate()
        self.assertNotEqual(first_geometry, frames[-1])
        self.assertEqual(len(root.calls), 2)
        orb._on_destroy(type("Event", (), {"widget": root})())
        orb._animate()
        self.assertEqual(len(root.calls), 2)

    def test_reduced_motion_polls_slowly_and_draws_only_for_new_snapshot_state(self):
        class Root:
            def __init__(self):
                self.calls = []

            def after(self, milliseconds, callback):
                self.calls.append((milliseconds, callback))
                return str(len(self.calls))

            def winfo_exists(self):
                return True

        root = Root()
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = root
        orb.remaining = 68.0
        orb.snapshot = None
        orb.liquid_phase = 0.0
        orb.bubble_phase = 0.0
        orb.reduced_motion = True
        orb._destroyed = False
        orb._snapshot_results = __import__("queue").SimpleQueue()
        orb.detail_window = None
        orb._refresh_in_flight = True
        frames = []
        orb._draw = lambda remaining: frames.append(remaining)

        orb._animate()
        orb._animate()

        self.assertEqual(frames, [])
        self.assertEqual([delay for delay, _callback in root.calls], [250, 250])
        orb._snapshot_results.put(
            (
                {
                    "subscription_quota": {
                        "available": True,
                        "windows": [{"remaining_percent": 45}],
                    }
                },
                None,
            )
        )
        orb._animate()
        self.assertEqual(frames, [45.0])

    def test_refresh_uses_one_background_worker_and_animation_applies_its_result(self):
        main_thread = threading.get_ident()

        class Canvas:
            def delete(self, *_args):
                return None

            def create_line(self, *_args, **_kwargs):
                return None

            def create_oval(self, *_args, **_kwargs):
                return None

            def create_arc(self, *_args, **_kwargs):
                return None

            def create_text(self, *_args, **_kwargs):
                return None

        class Root:
            def __init__(self):
                self.calls = []
                self.foreign_calls = []

            def _record(self, *args):
                if threading.get_ident() != main_thread:
                    self.foreign_calls.append(args)

            def after(self, milliseconds, callback):
                self._record("after")
                self.calls.append((milliseconds, callback))
                return str(len(self.calls))

            def after_cancel(self, callback):
                self._record("after_cancel")

            def winfo_exists(self):
                self._record("winfo_exists")
                return True

            def winfo_x(self):
                self._record("winfo_x")
                return 20

            def winfo_y(self):
                self._record("winfo_y")
                return 20

        class SlowSource:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.finished = threading.Event()
                self.calls = 0

            def snapshot(self):
                self.calls += 1
                self.started.set()
                self.release.wait(1.0)
                self.finished.set()
                return {
                    "subscription_quota": {
                        "available": True,
                        "windows": [{"remaining_percent": 68}],
                    }
                }

        root = Root()
        source = SlowSource()
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = root
        orb.canvas = Canvas()
        orb.source = source
        orb.refresh_ms = 15_000
        orb.snapshot = None
        orb.remaining = None
        orb.liquid_phase = 0.0
        orb.bubble_phase = 0.0
        orb.reduced_motion = False
        orb.detail_window = None
        orb._destroyed = False
        orb._animation_after = None
        orb._refresh_after = None
        orb._draw = lambda _remaining: None
        try:
            started = time.monotonic()
            orb._refresh()
            self.assertLess(time.monotonic() - started, 0.2)
            self.assertTrue(source.started.wait(0.2))
            orb._refresh()
            self.assertEqual(source.calls, 1)
            orb._animate()
            self.assertIsNone(orb.remaining)
            source.release.set()
            self.assertTrue(source.finished.wait(0.2))
            orb._animate()
            self.assertEqual(orb.remaining, 68.0)
            self.assertEqual(
                orb.snapshot,
                {
                    "subscription_quota": {
                        "available": True,
                        "windows": [{"remaining_percent": 68}],
                    }
                },
            )
            self.assertEqual(root.foreign_calls, [])
            orb._on_destroy(type("Event", (), {"widget": root})())
            orb._animate()
            self.assertEqual(orb.remaining, 68.0)
        finally:
            source.release.set()

    def test_destroy_discards_a_late_background_snapshot_without_new_scheduling(self):
        class Canvas:
            def delete(self, *_args):
                return None

            def create_line(self, *_args, **_kwargs):
                return None

            def create_oval(self, *_args, **_kwargs):
                return None

            def create_arc(self, *_args, **_kwargs):
                return None

            def create_text(self, *_args, **_kwargs):
                return None

        class Root:
            def __init__(self):
                self.calls = []
                self.cancelled = []

            def after(self, milliseconds, callback):
                self.calls.append((milliseconds, callback))
                return "refresh"

            def after_cancel(self, callback):
                self.cancelled.append(callback)

            def winfo_exists(self):
                return True

            def winfo_x(self):
                return 20

            def winfo_y(self):
                return 20

        class SlowSource:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.finished = threading.Event()

            def snapshot(self):
                self.started.set()
                self.release.wait(1.0)
                self.finished.set()
                return {
                    "subscription_quota": {
                        "available": True,
                        "windows": [{"remaining_percent": 68}],
                    }
                }

        root = Root()
        source = SlowSource()
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = root
        orb.canvas = Canvas()
        orb.source = source
        orb.refresh_ms = 15_000
        orb.snapshot = None
        orb.remaining = None
        orb.liquid_phase = 0.0
        orb.bubble_phase = 0.0
        orb.reduced_motion = False
        orb.detail_window = None
        orb._destroyed = False
        orb._animation_after = None
        orb._refresh_after = None
        orb._draw = lambda _remaining: None
        try:
            orb._refresh()
            self.assertTrue(source.started.wait(0.2))
            orb._on_destroy(type("Event", (), {"widget": root})())
            source.release.set()
            self.assertTrue(source.finished.wait(0.2))
            orb._animate()
            self.assertIsNone(orb.remaining)
            self.assertIsNone(orb.snapshot)
            self.assertEqual(len(root.calls), 1)
            self.assertEqual(root.cancelled, ["refresh"])
        finally:
            source.release.set()

    def test_failed_refresh_retains_latest_snapshot_and_marks_unavailable(self):
        latest = {
            "provider": "verified",
            "subscription_quota": {
                "available": True,
                "windows": [{"remaining_percent": 45}],
            },
        }
        orb = DesktopOrb.__new__(DesktopOrb)
        orb.root = type("Root", (), {"winfo_exists": lambda self: True})()
        orb.source = type(
            "Source",
            (),
            {"snapshot": lambda self: (_ for _ in ()).throw(RuntimeError("offline"))},
        )()
        orb.snapshot = latest
        orb.remaining = 45.0
        orb.detail_window = None
        orb.detail_text = None
        orb.refresh_button = None
        orb.detail_status = None
        orb._destroyed = False
        orb._refresh_in_flight = True
        orb._snapshot_results = __import__("queue").SimpleQueue()

        orb._collect_snapshot()
        orb._apply_snapshot_result()

        self.assertIs(orb.snapshot, latest)
        self.assertEqual(orb.remaining, 45.0)
        self.assertFalse(orb._refresh_in_flight)
        self.assertIn("latest verified snapshot", orb._last_refresh_error)

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
            'bind("<Return>"',
            'bind("<space>"',
            'bind("<FocusIn>"',
            'bind("<FocusOut>"',
            "save_position(",
            "desktop_source_from_environment",
            "render_orb_frame(",
            "ImageTk.PhotoImage",
            'panel.bind("<Escape>", self._close_details)',
            'root.bind("<Escape>", lambda _event: root.destroy())',
            'panel.configure(bg="#27313a")',
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

    def test_package_pins_the_tested_pillow_renderer(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("Pillow==12.3.0", project["project"]["dependencies"])

    def test_canonical_skill_uses_only_official_frontmatter_fields(self):
        text = (ROOT / "skills" / "quota-orb" / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line
        }
        self.assertEqual(keys, {"name", "description"})
        self.assertIn("fixed user Codex app-server path", text)
        self.assertIn("Windows system language", text)
        self.assertIn("color-key-safe boundary", text)


if __name__ == "__main__":
    unittest.main()

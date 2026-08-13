from __future__ import annotations

import argparse
import ctypes
import json
import locale
import math
import os
import queue
import tempfile
import threading
from datetime import datetime, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from .sources import desktop_source_from_environment


WIDGET_SIZE = (132, 132)
DETAIL_SIZE = (392, 620)
TRANSPARENT_COLOR = "#010203"
DRAG_THRESHOLD = 4
ANIMATION_MS = 40
REDUCED_MOTION_POLL_MS = 250
RENDER_SCALE_MIN = 4
PANEL_SCROLLBAR_WIDTH = 12
PANEL_BUTTON_MIN_SIZE = {"refresh": (72, 32), "close": (48, 32)}
WIDGET_MUTEX_NAME = r"Local\QuotaOrbDesktopWidget.v1"
_ERROR_ALREADY_EXISTS = 183
_NO_SNAPSHOT_RESULT = object()
LIQUID_CENTER = (66.0, 64.0)
LIQUID_RADIUS = 49.0
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

_LIQUID_COLOR_ANCHORS = {
    "red_deep": {
        "body": "#8c1830",
        "deep": "#420817",
        "rim": "#df6575",
        "shell": "#210712",
        "meta": "#f0a2ad",
    },
    "red_light": {
        "body": "#f4766e",
        "deep": "#b92f31",
        "rim": "#ffc1b5",
        "shell": "#310c13",
        "meta": "#ffe0d9",
    },
    "amber_deep": {
        "body": "#df7041",
        "deep": "#8e351d",
        "rim": "#ffc08a",
        "shell": "#2d0e0a",
        "meta": "#ffe0bb",
    },
    "gold_light": {
        "body": "#f7d25f",
        "deep": "#bd7a12",
        "rim": "#fff0a9",
        "shell": "#292006",
        "meta": "#fff7cf",
    },
    "yellow_green_bridge": {
        "body": "#bad879",
        "deep": "#789344",
        "rim": "#eef7b0",
        "shell": "#192a13",
        "meta": "#f3fad0",
    },
    "green_light": {
        "body": "#bad879",
        "deep": "#789344",
        "rim": "#eef7b0",
        "shell": "#192a13",
        "meta": "#f3fad0",
    },
    "emerald_deep": {
        "body": "#07966d",
        "deep": "#035443",
        "rim": "#55dcb1",
        "shell": "#031d18",
        "meta": "#baf2dc",
    },
    "green_bright": {
        "body": "#67ebc9",
        "deep": "#0a9679",
        "rim": "#e0fff6",
        "shell": "#062922",
        "meta": "#effffa",
    },
}


def _interpolate_hex(left: str, right: str, amount: float) -> str:
    start = ImageColor.getrgb(left)
    end = ImageColor.getrgb(right)
    rgb = tuple(
        round(start[index] + (end[index] - start[index]) * amount)
        for index in range(3)
    )
    return "#%02x%02x%02x" % rgb


def _interpolate_palette(
    left: Mapping[str, str],
    right: Mapping[str, str],
    amount: float,
    state: str,
) -> dict[str, str]:
    return {
        "state": state,
        **{
            key: _interpolate_hex(left[key], right[key], amount)
            for key in ("body", "deep", "rim", "shell", "meta")
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
        if clamped < 28:
            return _interpolate_palette(
                _LIQUID_COLOR_ANCHORS["red_deep"],
                _LIQUID_COLOR_ANCHORS["red_light"],
                clamped / 28.0,
                "red",
            )
        return _interpolate_palette(
            _LIQUID_COLOR_ANCHORS["red_light"],
            _LIQUID_COLOR_ANCHORS["amber_deep"],
            (clamped - 28.0) / 2.0,
            "red",
        )
    if clamped < 50:
        if clamped < 48:
            return _interpolate_palette(
                _LIQUID_COLOR_ANCHORS["amber_deep"],
                _LIQUID_COLOR_ANCHORS["gold_light"],
                (clamped - 30.0) / 18.0,
                "yellow",
            )
        return _interpolate_palette(
            _LIQUID_COLOR_ANCHORS["gold_light"],
            _LIQUID_COLOR_ANCHORS["yellow_green_bridge"],
            (clamped - 48.0) / 2.0,
            "yellow",
        )
    if clamped <= 75:
        return _interpolate_palette(
            _LIQUID_COLOR_ANCHORS["green_light"],
            _LIQUID_COLOR_ANCHORS["emerald_deep"],
            (clamped - 50.0) / 25.0,
            "green",
        )
    return _interpolate_palette(
        _LIQUID_COLOR_ANCHORS["emerald_deep"],
        _LIQUID_COLOR_ANCHORS["green_bright"],
        (clamped - 75.0) / 25.0,
        "green",
    )


def orb_labels(value: object, *, language: str = "en") -> tuple[str, str | None]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ("?", None)
    numeric = float(value)
    if not math.isfinite(numeric):
        return ("?", None)
    clamped = min(100.0, max(0.0, numeric))
    sublabel = "剩余" if resolve_ui_language(language) == "zh-CN" else "REMAIN"
    label = f"{clamped:.2f}".rstrip("0").rstrip(".") + "%"
    return (label, sublabel)


def surface_y(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    clamped = min(100.0, max(0.0, numeric))
    if clamped <= 0:
        return LIQUID_CENTER[1] + LIQUID_RADIUS
    if clamped >= 100:
        return LIQUID_CENTER[1] - LIQUID_RADIUS

    target = clamped / 100.0
    low = 0.0
    high = LIQUID_RADIUS * 2.0
    for _ in range(42):
        height = (low + high) / 2.0
        distance = LIQUID_RADIUS - height
        area = (
            LIQUID_RADIUS * LIQUID_RADIUS
            * math.acos(max(-1.0, min(1.0, distance / LIQUID_RADIUS)))
            - distance
            * math.sqrt(max(0.0, LIQUID_RADIUS * LIQUID_RADIUS - distance * distance))
        )
        if area / (math.pi * LIQUID_RADIUS * LIQUID_RADIUS) < target:
            low = height
        else:
            high = height
    return LIQUID_CENTER[1] + LIQUID_RADIUS - ((low + high) / 2.0)


def wave_phases(phase: float) -> tuple[float, float]:
    return phase, (-phase * 0.67) + 2.05


def next_animation_state(
    phase: float,
    bubble_phase: float,
    *,
    reduced_motion: bool,
) -> tuple[float, float]:
    if reduced_motion:
        return (0.0, 0.0)
    return ((phase + 0.18) % math.tau, (bubble_phase + 0.11) % math.tau)


def windows_reduced_motion_enabled() -> bool:
    """Return the Windows client-animation preference; failure keeps animation enabled."""

    if os.name != "nt":
        return False
    try:
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042,  # SPI_GETCLIENTAREAANIMATION
            0,
            ctypes.byref(enabled),
            0,
        )
        return bool(ok) and not bool(enabled.value)
    except (AttributeError, OSError, TypeError):
        return False


def resolve_ui_language(locale_name: object) -> str:
    if not isinstance(locale_name, str) or not locale_name.strip():
        return "en"
    normalized = locale_name.strip().replace("_", "-").split(".", 1)[0].lower()
    return "zh-CN" if normalized == "zh" or normalized.startswith("zh-") else "en"


def _system_locale_name() -> str | None:
    if os.name == "nt":
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if not language_id:
            return None
        buffer = ctypes.create_unicode_buffer(85)
        length = ctypes.windll.kernel32.LCIDToLocaleName(
            language_id,
            buffer,
            len(buffer),
            0,
        )
        return buffer.value if length else None
    return locale.getlocale()[0]


def detect_system_ui_language() -> str:
    try:
        return resolve_ui_language(_system_locale_name())
    except (AttributeError, OSError, TypeError, ValueError):
        return "en"


_UI_TEXT = {
    "en": {
        "root_title": "Quota Orb Desktop Widget",
        "exit": "Exit Quota Orb",
        "panel_title": "Quota Orb · Read-only details",
        "panel_subtitle": "Read-only account details",
        "close": "Close",
        "refresh": "Refresh",
        "read_only_snapshot": "Read-only snapshot",
        "refreshing": "Refreshing read-only snapshot…",
        "refresh_unavailable": "Refresh unavailable · latest snapshot retained",
        "refresh_failed": "Refresh failed; showing the latest verified snapshot.",
        "refresh_section": "REFRESH",
        "demo": "Demo",
        "details_title": "QUOTA ORB · DETAILS",
        "identity_section": "IDENTITY",
        "platform": "Platform",
        "provider": "Provider",
        "profile": "Profile",
        "account": "Account",
        "model": "Model",
        "generated": "Generated",
        "subscription_section": "SUBSCRIPTION QUOTA",
        "subscription_quota": "Subscription quota",
        "plan": "Plan",
        "source": "Source",
        "available": "Available",
        "unavailable": "Unavailable",
        "window": "Window",
        "windows": "Windows",
        "used": "Used",
        "remaining": "Remaining",
        "summary_scope": "Quota basis",
        "token_allowance": "Token allowance",
        "reset": "Reset",
        "detail": "Detail",
        "reason": "Reason",
        "api_section": "API QUOTA",
        "api_quota": "API quota",
        "limit": "Limit",
        "limits": "Limits",
        "unit": "Unit",
        "local_section": "LOCAL USAGE",
        "local_usage": "Local usage (local; not an invoice)",
        "day": "Day",
        "totals": "Totals",
        "by_provider_model": "By provider / model",
        "billing_section": "TOKEN BILLING",
        "token_billing": "Token billing",
        "usage": "Usage",
        "allowance": "Allowance",
        "cost": "Cost",
        "actual_cost": "Cost (actual; provider-reported)",
        "estimated_cost": "Cost (estimated; dated-price calculation)",
        "yes": "Yes",
        "no": "No",
    },
    "zh-CN": {
        "root_title": "Quota Orb 桌面组件",
        "exit": "退出 Quota Orb",
        "panel_title": "Quota Orb · 只读详情",
        "panel_subtitle": "只读账户详情",
        "close": "关闭",
        "refresh": "刷新",
        "read_only_snapshot": "只读快照",
        "refreshing": "正在刷新只读快照…",
        "refresh_unavailable": "刷新不可用 · 已保留最新快照",
        "refresh_failed": "刷新失败；正在显示最新已验证快照。",
        "refresh_section": "刷新",
        "demo": "演示",
        "details_title": "QUOTA ORB · 详情",
        "identity_section": "身份",
        "platform": "平台",
        "provider": "供应商",
        "profile": "配置",
        "account": "账户",
        "model": "模型",
        "generated": "生成时间",
        "subscription_section": "订阅配额",
        "subscription_quota": "订阅配额",
        "plan": "套餐",
        "source": "来源",
        "available": "可用",
        "unavailable": "不可用",
        "window": "窗口",
        "windows": "窗口",
        "used": "已用",
        "remaining": "剩余",
        "summary_scope": "配额依据",
        "token_allowance": "Token 额度",
        "reset": "重置时间",
        "detail": "详情",
        "reason": "原因",
        "api_section": "API 配额",
        "api_quota": "API 配额",
        "limit": "限额",
        "limits": "限额",
        "unit": "单位",
        "local_section": "本地用量",
        "local_usage": "本地用量（仅本机；非账单）",
        "day": "日期",
        "totals": "合计",
        "by_provider_model": "按供应商 / 模型",
        "billing_section": "TOKEN 计费",
        "token_billing": "Token 计费",
        "usage": "用量",
        "allowance": "额度",
        "cost": "费用",
        "actual_cost": "费用（实际；供应商报告）",
        "estimated_cost": "费用（估算；按日期价格计算）",
        "yes": "是",
        "no": "否",
    },
}


def panel_ui_text(language: str = "en") -> dict[str, str]:
    """Return the complete immutable-by-copy UI vocabulary for one language."""

    return dict(_UI_TEXT[resolve_ui_language(language)])


def panel_typography(language: str = "en") -> dict[str, tuple[Any, ...]]:
    """Return the compact Windows panel typography scale."""

    family = (
        "Microsoft YaHei UI"
        if resolve_ui_language(language) == "zh-CN"
        else "Segoe UI"
    )
    return {
        "title": (family, 13, "bold"),
        "body": (family, 10),
        "section": (family, 10, "bold"),
        "key": (family, 24, "bold"),
        "caption": (family, 9),
    }


def panel_body_rows(body: object, *, language: str = "en") -> list[tuple[str, str]]:
    """Split card copy into independently colored factual rows."""

    texts = _UI_TEXT[resolve_ui_language(language)]
    value = str(body) if body else texts["unavailable"]
    return [
        (
            line,
            "unavailable" if texts["unavailable"] in line else "normal",
        )
        for line in value.splitlines()
    ]


def scroll_panel_by_key(canvas: Any, keysym: str) -> bool:
    """Apply one supported keyboard scroll command to a Tk-compatible canvas."""

    commands: dict[str, tuple[str, float, str | None]] = {
        "Up": ("scroll", -1, "units"),
        "Down": ("scroll", 1, "units"),
        "Prior": ("scroll", -1, "pages"),
        "Next": ("scroll", 1, "pages"),
        "Home": ("moveto", 0.0, None),
        "End": ("moveto", 1.0, None),
    }
    command = commands.get(keysym)
    if command is None:
        return False
    operation, amount, unit = command
    if operation == "moveto":
        canvas.yview_moveto(amount)
    else:
        canvas.yview_scroll(int(amount), unit)
    return True


def liquid_surface_points(
    value: object,
    phase: float,
    *,
    layer: int = 0,
) -> list[tuple[float, float]]:
    top = surface_y(value)
    if top is None or not isinstance(value, (int, float)) or value <= 0:
        return []
    center_x, center_y = LIQUID_CENTER
    radius = LIQUID_RADIUS
    clamped = min(100.0, max(0.0, float(value)))
    if clamped >= 100:
        points: list[tuple[float, float]] = []
        for index in range(65):
            fraction = index / 64
            x = center_x - radius + (2 * radius * fraction)
            y = center_y - math.sqrt(max(0.0, radius * radius - (x - center_x) ** 2))
            points.append((x, y))
        return points
    fill_depth = max(0.0, center_y + radius - top)
    air_depth = max(0.0, top - (center_y - radius))
    edge_limited = min(fill_depth, air_depth)
    amplitude = min(
        5.0,
        edge_limited * (0.12 if layer == 0 else 0.075),
    )
    offset = math.sqrt(max(0, radius * radius - (top - center_y) ** 2))
    points: list[tuple[float, float]] = []
    for index in range(65):
        fraction = index / 64
        x = center_x - offset + (2 * offset * fraction)
        edge = math.sqrt(max(0, radius * radius - (x - center_x) ** 2))
        front_phase, back_phase = wave_phases(phase)
        if layer == 0:
            wave = (
                math.sin((fraction * math.tau) + front_phase)
                + 0.34 * math.sin((fraction * math.tau * 2.0) + front_phase * 0.71 + 0.9)
            )
        else:
            wave = (
                math.sin((fraction * math.tau * 1.27) + back_phase)
                + 0.22 * math.sin((fraction * math.tau * 2.7) + back_phase * 0.47 - 0.68)
            )
        y = min(
            center_y + edge,
            max(center_y - edge, top + wave * amplitude + (0.8 if layer else 0.0)),
        )
        points.append((x, y))
    return points


def _scaled_box(values: Sequence[float], scale: int) -> tuple[int, int, int, int]:
    return tuple(round(value * scale) for value in values)  # type: ignore[return-value]


def _rgb(value: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(value)


def _mix(left: str, right: str, amount: float) -> str:
    a = _rgb(left)
    b = _rgb(right)
    mixed = tuple(round(a[index] + (b[index] - a[index]) * amount) for index in range(3))
    return "#%02x%02x%02x" % mixed


@lru_cache(maxsize=12)
def _orb_masks(scale: int) -> tuple[Image.Image, Image.Image]:
    size = (WIDGET_SIZE[0] * scale, WIDGET_SIZE[1] * scale)
    outer = Image.new("L", size, 0)
    inner = Image.new("L", size, 0)
    ImageDraw.Draw(outer).ellipse(_scaled_box((13, 11, 119, 117), scale), fill=255)
    ImageDraw.Draw(inner).ellipse(_scaled_box((17, 15, 115, 113), scale), fill=255)
    return outer, inner


@lru_cache(maxsize=12)
def _gradient(
    width: int,
    height: int,
    low: str,
    high: str,
    kind: str,
) -> Image.Image:
    if kind == "radial":
        values = Image.radial_gradient("L").resize((width, height), Image.Resampling.BILINEAR)
    else:
        values = Image.linear_gradient("L").resize((width, height), Image.Resampling.BILINEAR)
    return ImageOps.colorize(values, black=low, white=high).convert("RGBA")


@lru_cache(maxsize=16)
def _alpha_table(opacity: int) -> tuple[int, ...]:
    return tuple(round(value * opacity / 255) for value in range(256))


def _masked_gradient(
    size: tuple[int, int],
    mask: Image.Image,
    low: str,
    high: str,
    *,
    kind: str,
    opacity: int,
) -> Image.Image:
    layer = _gradient(size[0], size[1], low, high, kind).copy()
    layer.putalpha(mask.point(_alpha_table(opacity)))
    return layer


@lru_cache(maxsize=8)
def _orb_base(
    scale: int,
    state: str,
    shell_color: str,
    rim_color: str,
    pressed: bool,
) -> Image.Image:
    size = (WIDGET_SIZE[0] * scale, WIDGET_SIZE[1] * scale)
    palette = {"shell": shell_color, "rim": rim_color}
    outer, inner = _orb_masks(scale)
    frame = Image.new("RGBA", size, (0, 0, 0, 0))

    if pressed:
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse(
            _scaled_box((16, 14, 116, 114), scale),
            outline=(*_rgb(palette["rim"]), 115),
            width=max(2, 2 * scale),
        )
        frame = Image.alpha_composite(frame, glow)

    shell = _masked_gradient(
        size,
        outer,
        "#020713",
        _mix(palette["shell"], palette["rim"], 0.28),
        kind="radial",
        opacity=246,
    )
    frame = Image.alpha_composite(frame, shell)
    chamber = _masked_gradient(
        size,
        inner,
        _mix(palette["shell"], "#ffffff", 0.09),
        "#01040c",
        kind="linear",
        opacity=178,
    )
    return Image.alpha_composite(frame, chamber)


@lru_cache(maxsize=8)
def _glass_overlay(
    scale: int,
    state: str,
    rim_color: str,
    pressed: bool,
) -> Image.Image:
    size = (WIDGET_SIZE[0] * scale, WIDGET_SIZE[1] * scale)
    palette = {"rim": rim_color}
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    outer_box = _scaled_box((13, 11, 119, 117), scale)
    inner_box = _scaled_box((17, 15, 115, 113), scale)

    # Outer/inner shell and Fresnel edge.
    draw.ellipse(
        outer_box,
        outline=(*_rgb(_mix(palette["rim"], "#ffffff", 0.36)), 172 if pressed else 138),
        width=max(2, round(1.85 * scale)),
    )
    if state == "unknown":
        for start in range(8, 360, 30):
            draw.arc(
                inner_box,
                start,
                start + 13,
                fill=(177, 204, 218, 62),
                width=max(1, round(0.85 * scale)),
            )
    else:
        draw.ellipse(
            inner_box,
            outline=(*_rgb(_mix(palette["rim"], "#73d8ff", 0.34)), 92),
            width=max(1, round(0.95 * scale)),
        )
    draw.arc(outer_box, 120, 205, fill=(210, 244, 255, 152), width=max(2, round(2.2 * scale)))
    draw.arc(outer_box, 300, 66, fill=(*_rgb(palette["rim"]), 82), width=max(2, round(2.7 * scale)))

    # Two offset chromatic refraction bands keep the crystal edge from reading flat.
    draw.arc(
        _scaled_box((16.2, 14.2, 116.8, 114.8), scale),
        128,
        270,
        fill=(67, 220, 255, 70),
        width=max(1, round(0.95 * scale)),
    )
    draw.arc(
        _scaled_box((18.1, 16.1, 114.9, 112.9), scale),
        300,
        92,
        fill=(255, 109, 225, 50),
        width=max(1, round(0.9 * scale)),
    )

    specular = Image.new("RGBA", size, (0, 0, 0, 0))
    specular_draw = ImageDraw.Draw(specular)
    specular_draw.ellipse(_scaled_box((28, 20, 53, 68), scale), fill=(255, 255, 255, 112))
    specular = specular.filter(ImageFilter.GaussianBlur(5.0 * scale))
    overlay = Image.alpha_composite(overlay, specular)
    draw = ImageDraw.Draw(overlay)
    draw.arc(
        _scaled_box((24, 18, 95, 91), scale),
        98,
        176,
        fill=(255, 255, 255, 220),
        width=max(2, round(2.0 * scale)),
    )
    draw.arc(
        _scaled_box((31, 25, 92, 88), scale),
        102,
        150,
        fill=(255, 255, 255, 115),
        width=max(1, round(0.9 * scale)),
    )
    draw.ellipse(_scaled_box((91, 86, 101, 99), scale), fill=(255, 255, 255, 42))
    return overlay


def _polygon_mask(
    size: tuple[int, int],
    points: Sequence[tuple[float, float]],
    scale: int,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    if points:
        polygon = [(round(x * scale), round(y * scale)) for x, y in points]
        polygon.extend(
            [
                (round((LIQUID_CENTER[0] + LIQUID_RADIUS) * scale), round((LIQUID_CENTER[1] + LIQUID_RADIUS) * scale)),
                (round((LIQUID_CENTER[0] - LIQUID_RADIUS) * scale), round((LIQUID_CENTER[1] + LIQUID_RADIUS) * scale)),
            ]
        )
        ImageDraw.Draw(mask).polygon(polygon, fill=255)
    return mask


def _liquid_fill_mask(
    remaining: float,
    phase: float,
    scale: int,
    *,
    layer: int,
) -> Image.Image:
    _, inner = _orb_masks(scale)
    if remaining <= 0:
        return Image.new("L", inner.size, 0)
    if remaining >= 100:
        return inner.copy()
    points = liquid_surface_points(remaining, phase, layer=layer)
    return ImageChops.multiply(_polygon_mask(inner.size, points, scale), inner)


def liquid_fill_fraction(
    remaining: object,
    *,
    phase: float = 0.0,
    scale: int = RENDER_SCALE_MIN,
) -> float:
    if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
        return 0.0
    numeric = float(remaining)
    if not math.isfinite(numeric):
        return 0.0
    render_scale = max(RENDER_SCALE_MIN, int(scale))
    _, inner = _orb_masks(render_scale)
    liquid = _liquid_fill_mask(
        min(100.0, max(0.0, numeric)),
        phase,
        render_scale,
        layer=0,
    )
    inner_area = sum(inner.histogram()[index] * index for index in range(1, 256))
    liquid_area = sum(liquid.histogram()[index] * index for index in range(1, 256))
    return liquid_area / inner_area if inner_area else 0.0


def _draw_liquid(
    frame: Image.Image,
    remaining: float,
    phase: float,
    bubble_phase: float,
    scale: int,
    palette: Mapping[str, str],
) -> Image.Image:
    size = frame.size
    back_points = liquid_surface_points(remaining, phase, layer=1)
    front_points = liquid_surface_points(remaining, phase, layer=0)
    if not front_points:
        return frame

    back_mask = _liquid_fill_mask(remaining, phase, scale, layer=1)
    front_mask = _liquid_fill_mask(remaining, phase, scale, layer=0)
    back = _masked_gradient(
        size,
        back_mask,
        _mix(palette["body"], "#ffffff", 0.22),
        palette["deep"],
        kind="linear",
        opacity=94,
    )
    frame = Image.alpha_composite(frame, back)
    volume = _masked_gradient(
        size,
        front_mask,
        _mix(palette["body"], "#d8ffff", 0.26),
        _mix(palette["deep"], "#020713", 0.35),
        kind="linear",
        opacity=222,
    )
    frame = Image.alpha_composite(frame, volume)

    # Submerged glow and caustic arcs are clipped to the real liquid volume.
    caustic = Image.new("RGBA", size, (0, 0, 0, 0))
    caustic_draw = ImageDraw.Draw(caustic)
    for offset, opacity in ((0, 88), (11, 52), (22, 35)):
        y = (82 + offset + math.sin(phase * 0.73 + offset) * 2.5) * scale
        caustic_draw.arc(
            (29 * scale, round(y - 8 * scale), 104 * scale, round(y + 15 * scale)),
            195,
            340,
            fill=(*_rgb(palette["rim"]), opacity),
            width=max(1, round(1.15 * scale)),
        )
    caustic.putalpha(ImageChops.multiply(caustic.getchannel("A"), front_mask))
    frame = Image.alpha_composite(frame, caustic.filter(ImageFilter.GaussianBlur(0.65 * scale)))

    # Deterministic rising bubbles and motes: animation changes position, never the data.
    bubbles = Image.new("RGBA", size, (0, 0, 0, 0))
    bubbles_draw = ImageDraw.Draw(bubbles)
    top = max(17.0, min(112.0, surface_y(remaining) or 112.0))
    depth = max(1.0, 112.0 - top)
    for index, (x0, radius, speed) in enumerate(
        ((38.0, 1.7, 0.83), (82.0, 2.25, 0.61), (98.0, 1.25, 1.07), (57.0, 0.85, 1.29))
    ):
        progress = (bubble_phase * speed / math.tau + index * 0.23) % 1.0
        y = 110.0 - progress * depth
        x = x0 + math.sin(bubble_phase * (0.35 + index * 0.08) + index) * (1.6 + index * 0.25)
        box = _scaled_box((x - radius, y - radius, x + radius, y + radius), scale)
        bubbles_draw.ellipse(box, outline=(225, 255, 255, 125), width=max(1, scale))
        bubbles_draw.ellipse(
            _scaled_box((x - radius * 0.45, y - radius * 0.55, x, y - radius * 0.1), scale),
            fill=(255, 255, 255, 105),
        )
    bubbles.putalpha(ImageChops.multiply(bubbles.getchannel("A"), front_mask))
    frame = Image.alpha_composite(frame, bubbles)

    surface = Image.new("RGBA", size, (0, 0, 0, 0))
    surface_draw = ImageDraw.Draw(surface)
    back_line = [(round(x * scale), round(y * scale)) for x, y in back_points]
    front_line = [(round(x * scale), round(y * scale)) for x, y in front_points]
    surface_draw.line(back_line, fill=(190, 232, 238, 62), width=max(1, round(0.85 * scale)), joint="curve")
    surface_draw.line(front_line, fill=(*_rgb(palette["rim"]), 230), width=max(2, round(2.0 * scale)), joint="curve")
    surface_draw.line(
        [(x, y + max(1, scale)) for x, y in front_line],
        fill=(*_rgb(palette["deep"]), 105),
        width=max(1, round(0.85 * scale)),
        joint="curve",
    )
    return Image.alpha_composite(frame, surface)


@lru_cache(maxsize=24)
def _font(
    size: int,
    bold: bool = False,
    language: str = "en",
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if resolve_ui_language(language) == "zh-CN":
        candidates = (
            ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf")
            if bold
            else ("msyh.ttc", "simsun.ttc", "segoeui.ttf", "DejaVuSans.ttf")
        )
    else:
        candidates = ("segoeuib.ttf", "DejaVuSans-Bold.ttf") if bold else ("segoeui.ttf", "DejaVuSans.ttf")
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def render_orb_frame(
    remaining: object,
    phase: float,
    bubble_phase: float,
    scale: int = RENDER_SCALE_MIN,
    *,
    reduced_motion: bool = False,
    pressed: bool = False,
    focused: bool = False,
    language: str = "en",
) -> Image.Image:
    """Render one transparent crystal-orb frame without touching Tk."""

    render_scale = max(RENDER_SCALE_MIN, int(scale))
    if reduced_motion:
        phase = 0.0
        bubble_phase = 0.0
    palette = liquid_palette(remaining)
    frame = _orb_base(
        render_scale,
        palette["state"],
        palette["shell"],
        palette["rim"],
        pressed,
    ).copy()
    numeric: float | None = None
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        candidate = float(remaining)
        if math.isfinite(candidate):
            numeric = min(100.0, max(0.0, candidate))
    if numeric is not None and numeric > 0:
        frame = _draw_liquid(frame, numeric, phase, bubble_phase, render_scale, palette)
    frame = Image.alpha_composite(
        frame,
        _glass_overlay(render_scale, palette["state"], palette["rim"], pressed),
    )

    draw = ImageDraw.Draw(frame)
    if focused:
        draw.ellipse(
            _scaled_box((19, 17, 113, 111), render_scale),
            outline=(2, 7, 19, 245),
            width=max(2, round(3.25 * render_scale)),
        )
        draw.ellipse(
            _scaled_box((21, 19, 111, 109), render_scale),
            outline=(238, 255, 250, 255),
            width=max(2, round(1.75 * render_scale)),
        )
    language = resolve_ui_language(language)
    label, sublabel = orb_labels(numeric, language=language)
    center_x = 66 * render_scale
    label_y = 67 * render_scale
    draw.text(
        (center_x + render_scale, label_y + render_scale),
        label,
        font=_font(17 * render_scale, bold=True, language=language),
        anchor="mm",
        fill=(0, 0, 0, 135),
    )
    draw.text(
        (center_x, label_y),
        label,
        font=_font(17 * render_scale, bold=True, language=language),
        anchor="mm",
        fill=(255, 255, 255, 245),
        stroke_width=max(1, render_scale // 2),
        stroke_fill=(*_rgb(palette["deep"]), 155),
    )
    if sublabel is not None:
        draw.text(
            (center_x, 89 * render_scale),
            sublabel,
            font=_font(7 * render_scale, bold=True, language=language),
            anchor="mm",
            fill=(*_rgb(palette["meta"]), 205),
        )
    result = frame.resize(WIDGET_SIZE, Image.Resampling.LANCZOS)
    result.info["render_scale"] = render_scale
    return result


def prepare_windows_display_frame(frame: Image.Image) -> Image.Image:
    """Flatten an RGBA orb into a binary, color-key-safe Windows Tk frame."""

    rgba = frame.convert("RGBA")
    key = ImageColor.getrgb(TRANSPARENT_COLOR)
    visible = rgba.getchannel("A").point(lambda alpha: 255 if alpha >= 48 else 0)
    orb_bounds = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(orb_bounds).ellipse((13, 11, 119, 117), fill=255)
    visible = ImageChops.multiply(visible, orb_bounds)

    result = Image.new("RGB", rgba.size, key)
    result.paste(rgba.convert("RGB"), mask=visible)
    exact_key = ImageChops.difference(result, Image.new("RGB", rgba.size, key)).convert("L")
    exact_key = exact_key.point(lambda value: 255 if value == 0 else 0)
    exact_key = ImageChops.multiply(exact_key, visible)
    result.paste((key[0], key[1], min(255, key[2] + 1)), mask=exact_key)
    return result


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

    if values:
        return min(values)

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


_ENGLISH_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _local_reset_text(
    value: object,
    language: str,
    local_timezone: tzinfo | None,
) -> str:
    texts = _UI_TEXT[resolve_ui_language(language)]
    if not isinstance(value, str) or not value.strip():
        return texts["unavailable"]
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    target_timezone = local_timezone or datetime.now().astimezone().tzinfo
    if target_timezone is None:
        return value
    localized = parsed.astimezone(target_timezone)
    offset = localized.utcoffset()
    if offset is None:
        zone = localized.tzname() or "Local"
    else:
        minutes = round(offset.total_seconds() / 60)
        sign = "+" if minutes >= 0 else "-"
        minutes = abs(minutes)
        zone = f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"
    if resolve_ui_language(language) == "zh-CN":
        return (
            f"{localized.year}年{localized.month}月{localized.day}日 "
            f"{localized.hour:02d}:{localized.minute:02d}（{zone}）"
        )
    hour = localized.hour % 12 or 12
    meridiem = "AM" if localized.hour < 12 else "PM"
    return (
        f"{_ENGLISH_MONTHS[localized.month - 1]} {localized.day}, {localized.year} · "
        f"{hour}:{localized.minute:02d} {meridiem} ({zone})"
    )


def _localized_quota_scope(value: object, language: str) -> str:
    texts = _UI_TEXT[resolve_ui_language(language)]
    if not isinstance(value, str) or not value.strip():
        return texts["unavailable"]
    return value


def _selected_remaining_context(
    snapshot: Mapping[str, Any],
    remaining: float | None,
    *,
    language: str,
    local_timezone: tzinfo | None,
) -> dict[str, str] | None:
    if remaining is None:
        return None
    subscription = snapshot.get("subscription_quota")
    if isinstance(subscription, Mapping) and subscription.get("available") is True:
        windows = subscription.get("windows")
        if isinstance(windows, list):
            for window in windows:
                if not isinstance(window, Mapping):
                    continue
                value = window.get("remaining_percent")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                numeric = float(value)
                if not math.isfinite(numeric):
                    continue
                if min(100.0, max(0.0, numeric)) == remaining:
                    return {
                        "scope": _localized_quota_scope(window.get("label"), language),
                        "reset": _local_reset_text(
                            window.get("reset_at"), language, local_timezone
                        ),
                        "source": _display_value(subscription.get("source"), language),
                    }

    billing = snapshot.get("token_billing")
    if isinstance(billing, Mapping) and billing.get("available") is True:
        allowance = billing.get("allowance")
        if isinstance(allowance, Mapping):
            value = allowance.get("remaining_percent")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric = float(value)
                if (
                    math.isfinite(numeric)
                    and min(100.0, max(0.0, numeric)) == remaining
                ):
                    texts = _UI_TEXT[resolve_ui_language(language)]
                    return {
                        "scope": texts["token_allowance"],
                        "reset": _local_reset_text(
                            allowance.get("reset_at"), language, local_timezone
                        ),
                        "source": _display_value(billing.get("source"), language),
                    }
    return None


_CHINESE_FIELD_LABELS = {
    "used": "已用",
    "remaining": "剩余",
    "limit": "限额",
    "unit": "单位",
    "reset_at": "重置时间",
    "detail": "详情",
    "input_tokens": "输入 Token",
    "output_tokens": "输出 Token",
    "cache_read_tokens": "缓存读取 Token",
    "reasoning_tokens": "推理 Token",
    "total_tokens": "Token 总数",
    "api_calls": "API 调用次数",
    "sessions": "会话数",
    "remaining_percent": "剩余百分比",
    "limit_tokens": "Token 限额",
    "used_tokens": "已用 Token",
    "remaining_tokens": "剩余 Token",
    "basis": "依据",
    "model": "模型",
    "pricing_effective_at": "价格生效时间",
    "period_start": "周期开始",
    "period_end": "周期结束",
}


def _field_label(key: object, language: str) -> str:
    raw = str(key)
    if resolve_ui_language(language) == "zh-CN":
        return _CHINESE_FIELD_LABELS.get(raw, raw)
    return raw.replace("_", " ").title()


def _display_value(value: object, language: str = "en") -> str:
    texts = _UI_TEXT[resolve_ui_language(language)]
    if value is None or value == "":
        return texts["unavailable"]
    if isinstance(value, bool):
        return texts["yes"] if value else texts["no"]
    if isinstance(value, float):
        if not math.isfinite(value):
            return texts["unavailable"]
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _display_percent(value: object, language: str = "en") -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _UI_TEXT[resolve_ui_language(language)]["unavailable"]
    numeric = float(value)
    if not math.isfinite(numeric):
        return _UI_TEXT[resolve_ui_language(language)]["unavailable"]
    return f"{numeric:.2f}".rstrip("0").rstrip(".") + "%"


def _display_field_value(
    key: object,
    value: object,
    *,
    language: str,
    local_timezone: tzinfo | None,
) -> str:
    if str(key) in {"generated_at", "reset_at", "pricing_effective_at"}:
        return _local_reset_text(value, language, local_timezone)
    return _display_value(value, language)


def _append_mapping_values(
    lines: list[str],
    values: object,
    *,
    indent: str = "  ",
    language: str = "en",
    local_timezone: tzinfo | None = None,
) -> None:
    texts = _UI_TEXT[resolve_ui_language(language)]
    if not isinstance(values, Mapping) or not values:
        lines.append(f"{indent}{texts['unavailable']}")
        return
    for key, value in values.items():
        lines.append(
            f"{indent}{_field_label(key, language)}: "
            f"{_display_field_value(key, value, language=language, local_timezone=local_timezone)}"
        )


def detail_snapshot_text(
    snapshot: Mapping[str, Any] | None,
    *,
    language: str = "en",
    local_timezone: tzinfo | None = None,
) -> str:
    """Format present snapshot facts; every missing fact stays explicitly unavailable."""

    language = resolve_ui_language(language)
    texts = _UI_TEXT[language]
    available_text = texts["available"]
    unavailable_text = texts["unavailable"]
    data = snapshot if isinstance(snapshot, Mapping) else {}
    lines = [
        texts["details_title"],
        "",
        texts["identity_section"],
        f"{texts['platform']}: {_display_value(data.get('platform'), language)}",
        f"{texts['provider']}: {_display_value(data.get('provider'), language)}",
        f"{texts['profile']}: {_display_value(data.get('profile'), language)}",
        f"{texts['account']}: {_display_value(data.get('account'), language)}",
        f"{texts['model']}: {_display_value(data.get('model'), language)}",
        f"{texts['generated']}: {_local_reset_text(data.get('generated_at'), language, local_timezone)}",
        "",
        texts["subscription_section"],
    ]
    subscription = data.get("subscription_quota")
    if not isinstance(subscription, Mapping):
        subscription = {}
    available = subscription.get("available") is True
    lines.extend(
        [
            f"{texts['subscription_quota']}: {available_text if available else unavailable_text}",
            f"{texts['plan']}: {_display_value(subscription.get('plan'), language)}",
            f"{texts['source']}: {_display_value(subscription.get('source'), language)}",
        ]
    )
    if available:
        windows = subscription.get("windows")
        if isinstance(windows, list) and windows:
            for index, window in enumerate(windows, start=1):
                if not isinstance(window, Mapping):
                    continue
                window_label = (
                    _localized_quota_scope(window.get("label"), language)
                    if window.get("label")
                    else f"{texts['window']} {index}"
                )
                lines.extend(
                    [
                        "",
                        window_label,
                        f"  {texts['used']}: {_display_percent(window.get('used_percent'), language)}",
                        f"  {texts['remaining']}: {_display_percent(window.get('remaining_percent'), language)}",
                        f"  {texts['reset']}: {_local_reset_text(window.get('reset_at'), language, local_timezone)}",
                        f"  {texts['detail']}: {_display_value(window.get('detail'), language)}",
                    ]
                )
        else:
            lines.append(f"{texts['windows']}: {unavailable_text}")
    else:
        lines.append(
            f"{texts['reason']}: {_display_value(subscription.get('unavailable_reason'), language)}"
        )

    api_quota = data.get("api_quota")
    if not isinstance(api_quota, Mapping):
        api_quota = {}
    api_available = api_quota.get("available") is True
    lines.extend(
        [
            "",
            texts["api_section"],
            f"{texts['api_quota']}: {available_text if api_available else unavailable_text}",
            f"{texts['source']}: {_display_value(api_quota.get('source'), language)}",
        ]
    )
    if api_available:
        limits = api_quota.get("limits")
        if isinstance(limits, list) and limits:
            for index, limit in enumerate(limits, start=1):
                if not isinstance(limit, Mapping):
                    continue
                lines.append("")
                lines.append(
                    _display_value(limit.get("label"), language)
                    if limit.get("label")
                    else f"{texts['limit']} {index}"
                )
                for key in ("used", "remaining", "limit", "unit", "reset_at", "detail"):
                    lines.append(
                        f"  {_field_label(key, language)}: "
                        f"{_display_field_value(key, limit.get(key), language=language, local_timezone=local_timezone)}"
                    )
        else:
            lines.append(f"{texts['limits']}: {unavailable_text}")
    else:
        lines.append(
            f"{texts['reason']}: {_display_value(api_quota.get('unavailable_reason'), language)}"
        )

    local_usage = data.get("local_usage")
    if not isinstance(local_usage, Mapping):
        local_usage = {}
    local_available = local_usage.get("available") is True
    lines.extend(
        [
            "",
            texts["local_section"],
            f"{texts['local_usage']}: {available_text if local_available else unavailable_text}",
            f"{texts['source']}: {_display_value(local_usage.get('source'), language)}",
            f"{texts['day']}: {_display_value(local_usage.get('day'), language)}",
            f"{texts['totals']}:",
        ]
    )
    if local_available:
        _append_mapping_values(
            lines,
            local_usage.get("totals"),
            language=language,
            local_timezone=local_timezone,
        )
    else:
        lines.append(f"  {unavailable_text}")
    groups = local_usage.get("by_provider")
    if local_available and isinstance(groups, list) and groups:
        lines.append(f"{texts['by_provider_model']}:")
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            lines.append(f"  {_display_value(group.get('provider'), language)}")
            for key, value in group.items():
                if key not in {"provider", "models"}:
                    lines.append(
                        f"    {_field_label(key, language)}: {_display_value(value, language)}"
                    )
            models = group.get("models")
            if isinstance(models, list):
                for model in models:
                    if not isinstance(model, Mapping):
                        continue
                    lines.append(
                        f"    {texts['model']}: {_display_value(model.get('model'), language)}"
                    )
                    for key, value in model.items():
                        if key != "model":
                            lines.append(
                                f"      {_field_label(key, language)}: {_display_value(value, language)}"
                            )
    elif not local_available:
        lines.append(
            f"{texts['reason']}: {_display_value(local_usage.get('unavailable_reason'), language)}"
        )

    billing = data.get("token_billing")
    if not isinstance(billing, Mapping):
        billing = {}
    billing_available = billing.get("available") is True
    lines.extend(
        [
            "",
            texts["billing_section"],
            f"{texts['token_billing']}: {available_text if billing_available else unavailable_text}",
            f"{texts['source']}: {_display_value(billing.get('source'), language)}",
            f"{texts['usage']}:",
        ]
    )
    if not billing_available:
        lines.extend(
            [
                f"  {unavailable_text}",
                f"{texts['allowance']}:",
                f"  {unavailable_text}",
                f"{texts['cost']}: {unavailable_text}",
                f"{texts['reason']}: {_display_value(billing.get('unavailable_reason'), language)}",
            ]
        )
        return "\n".join(lines)
    _append_mapping_values(
        lines,
        billing.get("usage"),
        language=language,
        local_timezone=local_timezone,
    )
    lines.append(f"{texts['allowance']}:")
    _append_mapping_values(
        lines,
        billing.get("allowance"),
        language=language,
        local_timezone=local_timezone,
    )
    cost = billing.get("cost")
    classification = cost.get("classification") if isinstance(cost, Mapping) else None
    amount = cost.get("amount") if isinstance(cost, Mapping) else None
    currency = cost.get("currency") if isinstance(cost, Mapping) else None
    if classification == "actual" and amount is not None and currency:
        lines.append(f"{texts['actual_cost']}: {currency} {_display_value(amount, language)}")
    elif classification == "estimated" and amount is not None and currency:
        lines.append(f"{texts['estimated_cost']}: {currency} {_display_value(amount, language)}")
    else:
        lines.append(f"{texts['cost']}: {unavailable_text}")
    if isinstance(cost, Mapping):
        for key in ("basis", "model", "pricing_effective_at", "period_start", "period_end"):
            if cost.get(key) is not None:
                lines.append(
                    f"  {_field_label(key, language)}: "
                    f"{_display_field_value(key, cost.get(key), language=language, local_timezone=local_timezone)}"
                )
    return "\n".join(lines)


def detail_panel_model(
    snapshot: Mapping[str, Any] | None,
    *,
    language: str = "en",
    local_timezone: tzinfo | None = None,
) -> dict[str, Any]:
    """Build the factual summary and card content used by the Tk details panel."""

    language = resolve_ui_language(language)
    texts = _UI_TEXT[language]
    data = snapshot if isinstance(snapshot, Mapping) else {}
    subscription = data.get("subscription_quota")
    if not isinstance(subscription, Mapping):
        subscription = {}
    remaining = select_remaining_percent(data) if data else None
    context = _selected_remaining_context(
        data,
        remaining,
        language=language,
        local_timezone=local_timezone,
    )
    platform = data.get("platform")
    provider = data.get("provider")
    demo = data.get("demo") is True or any(
        isinstance(value, str)
        and value.strip().lower().endswith(("-mock", "-demo"))
        for value in (platform, provider)
    )
    summary = {
        "remaining": _display_percent(remaining, language),
        "scope": context["scope"] if context else texts["unavailable"],
        "reset": context["reset"] if context else texts["unavailable"],
        "plan": _display_value(subscription.get("plan"), language),
        "source": (
            context["source"]
            if context
            else _display_value(subscription.get("source"), language)
        ),
    }

    section_titles = (
        texts["subscription_section"],
        texts["api_section"],
        texts["local_section"],
        texts["billing_section"],
        texts["identity_section"],
    )
    sections = {title: [] for title in section_titles}
    current: str | None = None
    for line in detail_snapshot_text(
        data,
        language=language,
        local_timezone=local_timezone,
    ).splitlines():
        if line in sections:
            current = line
        elif current is not None:
            sections[current].append(line)
    cards = [
        {"title": title, "body": "\n".join(sections[title]).strip()}
        for title in section_titles
    ]
    return {
        "demo": texts["demo"] if demo else None,
        "summary": summary,
        "cards": cards,
    }


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


def panel_position(
    orb_position: tuple[int, int],
    orb_size: tuple[int, int],
    panel_size: tuple[int, int],
    areas: Iterable[Sequence[int]],
    *,
    gap: int = 12,
) -> tuple[int, int]:
    """Place the panel beside the orb, then clamp it to the active monitor."""

    candidates = _normalize_areas(areas)
    if not candidates:
        return (orb_position[0] + orb_size[0] + gap, orb_position[1])
    orb_x, orb_y = orb_position
    orb_width, _orb_height = orb_size
    panel_width, panel_height = panel_size

    def area_distance(area: tuple[int, int, int, int]) -> int:
        left, top, right, bottom = area
        center_x = orb_x + orb_width // 2
        center_y = orb_y + orb_size[1] // 2
        nearest_x = min(max(center_x, left), right)
        nearest_y = min(max(center_y, top), bottom)
        return (center_x - nearest_x) ** 2 + (center_y - nearest_y) ** 2

    area = min(candidates, key=area_distance)
    left, top, right, bottom = area
    left_x = orb_x - gap - panel_width
    right_x = orb_x + orb_width + gap
    if left_x >= left:
        x = left_x
    elif right_x + panel_width <= right:
        x = right_x
    else:
        left_space = max(0, orb_x - left)
        right_space = max(0, right - (orb_x + orb_width))
        x = left_x if left_space >= right_space else right_x
    y = min(max(orb_y, top), max(top, bottom - panel_height))
    return clamp_position_to_areas((x, y), panel_size, [area])


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
        self.language = detect_system_ui_language()
        texts = panel_ui_text(self.language)
        self.source = desktop_source_from_environment()
        self.pointer_start: tuple[int, int] | None = None
        self.window_start: tuple[int, int] | None = None
        self.dragging = False
        self.pressed = False
        self.focus_visible = False
        self.snapshot: Mapping[str, Any] | None = None
        self.remaining: float | None = None
        self.liquid_phase = 0.0
        self.bubble_phase = 0.0
        self.reduced_motion = windows_reduced_motion_enabled()
        self.detail_window: Any | None = None
        self.detail_text: Any | None = None
        self.detail_cards: Any | None = None
        self.detail_canvas: Any | None = None
        self.refresh_button: Any | None = None
        self._photo_image: Any | None = None
        self._destroyed = False
        self._animation_after: str | None = None
        self._refresh_after: str | None = None
        self._snapshot_results: queue.SimpleQueue[
            tuple[Mapping[str, Any] | None, str | None]
        ] = queue.SimpleQueue()
        self._refresh_in_flight = False
        self._last_refresh_error: str | None = None

        root.title(texts["root_title"])
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
            cursor="hand2",
            takefocus=True,
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Return>", self._toggle_details)
        self.canvas.bind("<space>", self._toggle_details)
        self.canvas.bind("<FocusIn>", self._focus_in)
        self.canvas.bind("<FocusOut>", self._focus_out)
        root.bind("<Escape>", lambda _event: root.destroy())
        root.bind("<Destroy>", self._on_destroy, add="+")

        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label=texts["exit"], command=root.destroy)

        areas = self._areas()
        default = self._default_position(areas)
        position = load_position(
            state_path,
            default=default,
            widget_size=WIDGET_SIZE,
            areas=areas,
        )
        self._set_position(position)
        self._draw(self.remaining)
        self._schedule_refresh(0)
        self._schedule_animation()

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
        self.pressed = True
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        self._draw(self.remaining)

    def _move(self, event: Any) -> None:
        if self.pointer_start is None or self.window_start is None:
            return
        current = (event.x_root, event.y_root)
        if not self.dragging and not exceeds_drag_threshold(self.pointer_start, current):
            return
        self.dragging = True
        if self.pressed:
            self.pressed = False
            self._draw(self.remaining)
        self._set_position(drag_position(self.window_start, self.pointer_start, current))

    def _release(self, event: Any) -> None:
        if (
            not self.dragging
            and self.pointer_start is not None
            and self.window_start is not None
            and hasattr(event, "x_root")
            and hasattr(event, "y_root")
        ):
            current = (event.x_root, event.y_root)
            if exceeds_drag_threshold(self.pointer_start, current):
                self.dragging = True
                self._set_position(
                    drag_position(self.window_start, self.pointer_start, current)
                )
        was_dragging = self.dragging
        if was_dragging:
            position = clamp_position_to_areas(
                self._current_position(),
                WIDGET_SIZE,
                self._areas(),
            )
            self._set_position(position)
            save_position(self.state_path, position)
        else:
            self._toggle_details()
        self.pointer_start = None
        self.window_start = None
        self.dragging = False
        self.pressed = False
        self._draw(self.remaining)

    def _show_menu(self, event: Any) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _focus_in(self, _event: Any) -> None:
        self.focus_visible = True
        self._draw(self.remaining)

    def _focus_out(self, _event: Any) -> None:
        self.focus_visible = False
        self._draw(self.remaining)

    def _detail_is_open(self) -> bool:
        panel = getattr(self, "detail_window", None)
        if panel is None:
            return False
        try:
            return bool(panel.winfo_exists())
        except Exception:
            self.detail_window = None
            return False

    def _toggle_details(self, _event: Any = None) -> str:
        if self._detail_is_open():
            self._close_details()
        else:
            self._open_details()
        return "break"

    def _open_details(self) -> None:
        if self._detail_is_open() or not self._can_schedule():
            panel = getattr(self, "detail_window", None)
            if panel is not None:
                try:
                    panel.lift()
                except Exception:
                    pass
            return
        import tkinter as tk

        language = getattr(self, "language", "en")
        texts = panel_ui_text(language)
        typography = panel_typography(language)
        panel = tk.Toplevel(self.root)
        self.detail_window = panel
        panel.title(texts["panel_title"])
        panel.overrideredirect(True)
        panel.configure(bg="#27313a")
        try:
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 0.97)
            panel.transient(self.root)
        except Exception:
            pass
        position = panel_position(
            self._current_position(),
            WIDGET_SIZE,
            DETAIL_SIZE,
            self._areas(),
        )
        panel.geometry(
            f"{DETAIL_SIZE[0]}x{DETAIL_SIZE[1]}{position[0]:+d}{position[1]:+d}"
        )
        panel.protocol("WM_DELETE_WINDOW", self._close_details)
        panel.bind("<Escape>", self._close_details)

        shell = tk.Frame(
            panel,
            bg="#0b1118",
            highlightbackground="#2a3b45",
            highlightcolor="#4f8f84",
            highlightthickness=1,
            bd=0,
        )
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(shell, bg="#0f1720", height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        accent_box = tk.Frame(header, width=62, height=64, bg="#0f1720")
        accent_box.pack(side="left")
        accent_box.pack_propagate(False)
        accent = tk.Canvas(
            accent_box,
            width=44,
            height=44,
            bg="#0f1720",
            highlightthickness=0,
            bd=0,
        )
        accent.pack(padx=(12, 6), pady=10)
        accent.create_oval(5, 5, 39, 39, fill="#12242a", outline="#5c9f92", width=2)
        accent.create_arc(10, 9, 34, 33, start=95, extent=90, style="arc", outline="#dbe8e6", width=2)
        accent.create_oval(13, 25, 33, 37, fill="#377f73", outline="")
        title_box = tk.Frame(header, bg="#0f1720", width=220)
        title_box.pack(side="left", fill="both", expand=True, pady=9)
        title_box.pack_propagate(False)
        tk.Label(
            title_box,
            text="QUOTA ORB",
            bg="#0f1720",
            fg="#edf3f2",
            font=typography["title"],
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_box,
            text=texts["panel_subtitle"],
            bg="#0f1720",
            fg="#839894",
            font=typography["body"],
            anchor="w",
        ).pack(fill="x", pady=(1, 0))
        close_slot = tk.Frame(
            header,
            width=PANEL_BUTTON_MIN_SIZE["close"][0] + 16,
            height=PANEL_BUTTON_MIN_SIZE["close"][1] + 12,
            bg="#0f1720",
        )
        close_slot.pack(side="right", padx=(0, 8), pady=10)
        close_slot.pack_propagate(False)
        close_button = tk.Button(
            close_slot,
            text=texts["close"],
            command=self._close_details,
            bg="#0f1720",
            activebackground="#26343d",
            fg="#becbc8",
            activeforeground="#ffffff",
            font=typography["body"],
            relief="flat",
            bd=0,
            highlightbackground="#26343d",
            highlightcolor="#5c9f92",
            highlightthickness=2,
            cursor="hand2",
            takefocus=True,
        )
        close_button.pack(fill="both", expand=True, padx=8, pady=6)
        close_state = {"hover": False, "focus": False}

        def set_close_visual(*, hover: bool | None = None, focus: bool | None = None) -> None:
            if hover is not None:
                close_state["hover"] = hover
            if focus is not None:
                close_state["focus"] = focus
            active = close_state["hover"] or close_state["focus"]
            ring = "#6fb3a6" if close_state["focus"] else "#26343d"
            close_button.configure(
                bg="#26343d" if active else "#0f1720",
                highlightbackground=ring,
                highlightcolor=ring,
            )

        close_button.bind("<Enter>", lambda _event: set_close_visual(hover=True))
        close_button.bind("<Leave>", lambda _event: set_close_visual(hover=False))
        close_button.bind("<FocusIn>", lambda _event: set_close_visual(focus=True))
        close_button.bind("<FocusOut>", lambda _event: set_close_visual(focus=False))

        tk.Frame(shell, height=1, bg="#26343d").pack(fill="x")
        content = tk.Frame(shell, bg="#0b1118")
        content.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        scroll_track = tk.Canvas(
            content,
            width=PANEL_SCROLLBAR_WIDTH,
            bg="#0b1118",
            highlightthickness=0,
            bd=0,
            cursor="sb_v_double_arrow",
        )
        scroll_track.pack(side="right", fill="y", padx=(5, 0))
        scroll_state: dict[str, float | None] = {
            "top": 0.0,
            "bottom": 0.0,
            "drag_offset": None,
        }

        def update_scroll(first: str, last: str) -> None:
            height = max(1, scroll_track.winfo_height())
            top = round(float(first) * height)
            bottom = max(top + 24, round(float(last) * height))
            bottom = min(height, bottom)
            scroll_state["top"] = float(top)
            scroll_state["bottom"] = float(bottom)
            scroll_track.delete("thumb")
            scroll_track.create_rectangle(
                2,
                top,
                PANEL_SCROLLBAR_WIDTH - 2,
                bottom,
                fill="#40544f",
                outline="#637b75",
                width=1,
                tags="thumb",
            )

        detail_canvas = tk.Canvas(
            content,
            bg="#0b1118",
            bd=0,
            highlightthickness=0,
            yscrollcommand=update_scroll,
        )
        detail_canvas.pack(side="left", fill="both", expand=True)
        self.detail_cards = tk.Frame(detail_canvas, bg="#0b1118")
        cards_window = detail_canvas.create_window(
            (0, 0), window=self.detail_cards, anchor="nw"
        )
        self.detail_cards.bind(
            "<Configure>",
            lambda _event: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")),
        )
        detail_canvas.bind(
            "<Configure>",
            lambda event: detail_canvas.itemconfigure(cards_window, width=event.width),
        )
        self.detail_canvas = detail_canvas
        self.detail_text = self.detail_cards

        def scroll_wheel(event: Any) -> str:
            units = -1 if event.delta > 0 else 1
            detail_canvas.yview_scroll(units * 3, "units")
            return "break"

        def scroll_to(event: Any) -> str:
            height = max(1, scroll_track.winfo_height())
            detail_canvas.yview_moveto(min(1.0, max(0.0, event.y / height)))
            return "break"

        def start_scroll_drag(event: Any) -> str:
            top = float(scroll_state["top"] or 0.0)
            bottom = float(scroll_state["bottom"] or 0.0)
            if top <= event.y <= bottom:
                scroll_state["drag_offset"] = float(event.y) - top
                return "break"
            return scroll_to(event)

        def drag_scroll_thumb(event: Any) -> str:
            offset = scroll_state["drag_offset"]
            if offset is None:
                return "break"
            height = max(1, scroll_track.winfo_height())
            span = max(0.0, float(scroll_state["bottom"] or 0.0) - float(scroll_state["top"] or 0.0))
            maximum = max(0.0, (height - span) / height)
            fraction = min(maximum, max(0.0, (float(event.y) - offset) / height))
            detail_canvas.yview_moveto(fraction)
            return "break"

        def end_scroll_drag(_event: Any) -> str:
            scroll_state["drag_offset"] = None
            return "break"

        def scroll_key(event: Any) -> str | None:
            return "break" if scroll_panel_by_key(detail_canvas, event.keysym) else None

        panel.bind("<MouseWheel>", scroll_wheel)
        scroll_track.bind("<MouseWheel>", scroll_wheel)
        scroll_track.bind("<ButtonPress-1>", start_scroll_drag)
        scroll_track.bind("<B1-Motion>", drag_scroll_thumb)
        scroll_track.bind("<ButtonRelease-1>", end_scroll_drag)
        panel.bind("<Up>", scroll_key)
        panel.bind("<Down>", scroll_key)
        panel.bind("<Prior>", scroll_key)
        panel.bind("<Next>", scroll_key)
        panel.bind("<Home>", scroll_key)
        panel.bind("<End>", scroll_key)

        controls = tk.Frame(shell, bg="#0f1720", height=50)
        controls.pack(fill="x", side="bottom")
        controls.pack_propagate(False)
        self.detail_status = tk.Label(
            controls,
            text=texts["read_only_snapshot"],
            bg="#0f1720",
            fg="#839894",
            font=typography["caption"],
            anchor="w",
        )
        self.detail_status.pack(side="left", fill="x", expand=True, padx=14)
        refresh_slot = tk.Frame(
            controls,
            width=PANEL_BUTTON_MIN_SIZE["refresh"][0] + 24,
            height=PANEL_BUTTON_MIN_SIZE["refresh"][1] + 18,
            bg="#0f1720",
        )
        refresh_slot.pack(side="right")
        refresh_slot.pack_propagate(False)
        refresh_button = tk.Button(
            refresh_slot,
            text=texts["refresh"],
            command=self._manual_refresh,
            bg="#315f57",
            activebackground="#41776d",
            disabledforeground="#66716f",
            fg="#f1f7f5",
            activeforeground="#ffffff",
            font=typography["section"],
            relief="flat",
            bd=0,
            highlightbackground="#26343d",
            highlightcolor="#6fb3a6",
            highlightthickness=2,
            cursor="hand2",
            takefocus=True,
        )
        self.refresh_button = refresh_button
        refresh_button.pack(fill="both", expand=True, padx=12, pady=9)
        refresh_state = {"hover": False, "focus": False}

        def set_refresh_visual(*, hover: bool | None = None, focus: bool | None = None) -> None:
            if hover is not None:
                refresh_state["hover"] = hover
            if focus is not None:
                refresh_state["focus"] = focus
            if str(refresh_button.cget("state")) == "disabled":
                return
            active = refresh_state["hover"] or refresh_state["focus"]
            ring = "#8bd0c2" if refresh_state["focus"] else "#26343d"
            refresh_button.configure(
                bg="#41776d" if active else "#315f57",
                highlightbackground=ring,
                highlightcolor=ring,
            )

        refresh_button.bind("<Enter>", lambda _event: set_refresh_visual(hover=True))
        refresh_button.bind("<Leave>", lambda _event: set_refresh_visual(hover=False))
        refresh_button.bind("<FocusIn>", lambda _event: set_refresh_visual(focus=True))
        refresh_button.bind("<FocusOut>", lambda _event: set_refresh_visual(focus=False))
        self._render_detail_panel()
        self._update_refresh_button()
        try:
            panel.lift()
            refresh_button.focus_set()
        except Exception:
            pass

    def _close_details(self, _event: Any = None) -> str:
        panel = getattr(self, "detail_window", None)
        self.detail_window = None
        self.detail_text = None
        self.detail_cards = None
        self.detail_canvas = None
        self.refresh_button = None
        self.detail_status = None
        if panel is not None:
            try:
                panel.destroy()
            except Exception:
                pass
        return "break"

    def _render_detail_panel(self) -> None:
        cards_container = getattr(self, "detail_cards", None)
        if cards_container is None or not self._detail_is_open():
            return
        import tkinter as tk

        language = getattr(self, "language", "en")
        typography = panel_typography(language)
        texts = panel_ui_text(getattr(self, "language", "en"))
        model = detail_panel_model(
            getattr(self, "snapshot", None),
            language=language,
            local_timezone=getattr(self, "local_timezone", None),
        )
        error = getattr(self, "_last_refresh_error", None)
        try:
            for child in cards_container.winfo_children():
                child.destroy()

            if model["demo"]:
                tk.Label(
                    cards_container,
                    text=model["demo"],
                    bg="#2f2616",
                    fg="#f2c66d",
                    font=typography["section"],
                    anchor="center",
                    padx=9,
                    pady=3,
                ).pack(anchor="w", padx=1, pady=(0, 8))

            summary = model["summary"]
            summary_card = tk.Frame(
                cards_container,
                bg="#132129",
                highlightbackground="#34524f",
                highlightthickness=1,
                bd=0,
            )
            summary_card.pack(fill="x", padx=1, pady=(0, 8))
            remaining_box = tk.Frame(summary_card, bg="#132129")
            remaining_box.pack(side="left", padx=12, pady=10)
            tk.Label(
                remaining_box,
                text=summary["remaining"],
                bg="#132129",
                fg="#edf5f2",
                font=typography["key"],
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                remaining_box,
                text=texts["remaining"],
                bg="#132129",
                fg="#73aa9f",
                font=typography["section"],
                anchor="w",
            ).pack(anchor="w")
            summary_meta = tk.Frame(summary_card, bg="#132129")
            summary_meta.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=11)
            for label, value in (
                (texts["summary_scope"], summary["scope"]),
                (texts["reset"], summary["reset"]),
                (texts["plan"], summary["plan"]),
                (texts["source"], summary["source"]),
            ):
                tk.Label(
                    summary_meta,
                    text=f"{label}  {value}",
                    bg="#132129",
                    fg="#b8c6c3",
                    font=typography["body"],
                    anchor="w",
                    justify="left",
                    wraplength=210,
                ).pack(fill="x", pady=2)

            cards = list(model["cards"])
            if error:
                cards.append(
                    {"title": texts["refresh_section"], "body": texts["refresh_failed"]}
                )
            for card in cards:
                card_frame = tk.Frame(
                    cards_container,
                    bg="#101820",
                    highlightbackground="#2a3b45",
                    highlightthickness=1,
                    bd=0,
                )
                card_frame.pack(fill="x", padx=1, pady=(0, 8))
                tk.Label(
                    card_frame,
                    text=card["title"],
                    bg="#101820",
                    fg="#73aa9f",
                    font=typography["section"],
                    anchor="w",
                ).pack(fill="x", padx=11, pady=(9, 5))
                body_rows = tk.Frame(card_frame, bg="#101820")
                body_rows.pack(fill="x", padx=11, pady=(0, 10))
                for row, tone in panel_body_rows(card["body"], language=language):
                    tk.Label(
                        body_rows,
                        text=row,
                        bg="#101820",
                        fg="#d1a66b" if tone == "unavailable" else "#c7d1cf",
                        font=typography["body"],
                        anchor="w",
                        justify="left",
                        wraplength=326,
                    ).pack(fill="x")

            canvas = getattr(self, "detail_canvas", None)
            if canvas is not None:
                canvas.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            self._close_details()

    def _update_refresh_button(self) -> None:
        texts = panel_ui_text(getattr(self, "language", "en"))
        in_flight = bool(getattr(self, "_refresh_in_flight", False))
        button = getattr(self, "refresh_button", None)
        if button is not None:
            try:
                button.configure(
                    state="disabled" if in_flight else "normal",
                    text=texts["refresh"],
                    bg="#24332f" if in_flight else "#315f57",
                    cursor="arrow" if in_flight else "hand2",
                )
            except Exception:
                pass
        status = getattr(self, "detail_status", None)
        if status is not None:
            try:
                if in_flight:
                    text = texts["refreshing"]
                elif getattr(self, "_last_refresh_error", None):
                    text = texts["refresh_unavailable"]
                else:
                    text = texts["read_only_snapshot"]
                status.configure(text=text)
            except Exception:
                pass

    def _manual_refresh(self) -> None:
        self._start_snapshot_refresh()

    def _can_schedule(self) -> bool:
        if getattr(self, "_destroyed", False):
            return False
        exists = getattr(self.root, "winfo_exists", None)
        if exists is None:
            return True
        try:
            return bool(exists())
        except Exception:
            self._destroyed = True
            return False

    def _schedule_refresh(self, delay: int) -> None:
        if self._can_schedule():
            self._refresh_after = self.root.after(delay, self._refresh)

    def _schedule_animation(self) -> None:
        if self._can_schedule():
            delay = (
                REDUCED_MOTION_POLL_MS
                if getattr(self, "reduced_motion", False)
                else ANIMATION_MS
            )
            self._animation_after = self.root.after(delay, self._animate)

    def _on_destroy(self, event: Any) -> None:
        if getattr(event, "widget", self.root) is not self.root:
            return
        self._destroyed = True
        self._close_details()
        self._photo_image = None
        for attribute in ("_animation_after", "_refresh_after"):
            callback = getattr(self, attribute, None)
            if callback is not None:
                try:
                    self.root.after_cancel(callback)
                except Exception:
                    pass
            setattr(self, attribute, None)
        results = getattr(self, "_snapshot_results", None)
        if results is not None:
            while True:
                try:
                    results.get_nowait()
                except queue.Empty:
                    break

    def _apply_snapshot_result(self) -> bool:
        results = getattr(self, "_snapshot_results", None)
        if results is None or getattr(self, "_destroyed", False):
            return False
        latest: object = _NO_SNAPSHOT_RESULT
        while True:
            try:
                latest = results.get_nowait()
            except queue.Empty:
                break
        if latest is _NO_SNAPSHOT_RESULT:
            return False
        self._refresh_in_flight = False
        snapshot, error = latest
        self._last_refresh_error = error
        if isinstance(snapshot, Mapping):
            self.snapshot = snapshot
            self.remaining = select_remaining_percent(snapshot)
        self._render_detail_panel()
        self._update_refresh_button()
        return isinstance(snapshot, Mapping)

    def _collect_snapshot(self) -> None:
        try:
            raw_snapshot = self.source.snapshot()
            if not isinstance(raw_snapshot, Mapping):
                raise TypeError("Snapshot source did not return a mapping")
            result: tuple[Mapping[str, Any] | None, str | None] = (dict(raw_snapshot), None)
        except Exception:
            result = (None, "Refresh failed; showing the latest verified snapshot.")
        if not getattr(self, "_destroyed", False):
            results = getattr(self, "_snapshot_results", None)
            if results is not None:
                results.put(result)

    def _start_snapshot_refresh(self) -> bool:
        if not self._can_schedule() or getattr(self, "_refresh_in_flight", False):
            return False
        self._refresh_in_flight = True
        if not hasattr(self, "_snapshot_results"):
            self._snapshot_results = queue.SimpleQueue()
        threading.Thread(target=self._collect_snapshot, daemon=True).start()
        self._update_refresh_button()
        return True

    def _animate(self) -> None:
        self._animation_after = None
        if not self._can_schedule():
            return
        # Schedule from the beginning of the tick so render time does not lower 25 FPS.
        self._schedule_animation()
        snapshot_changed = self._apply_snapshot_result()
        if getattr(self, "reduced_motion", False):
            if snapshot_changed:
                self._draw(self.remaining)
            return
        self.liquid_phase, self.bubble_phase = next_animation_state(
            getattr(self, "liquid_phase", 0.0),
            getattr(self, "bubble_phase", 0.0),
            reduced_motion=getattr(self, "reduced_motion", False),
        )
        self._draw(self.remaining)

    def _refresh(self) -> None:
        self._refresh_after = None
        if not self._can_schedule():
            return
        self._start_snapshot_refresh()
        visible = clamp_position_to_areas(
            self._current_position(),
            WIDGET_SIZE,
            self._areas(),
        )
        if visible != self._current_position():
            self._set_position(visible)
            save_position(self.state_path, visible)
        self._schedule_refresh(self.refresh_ms)

    def _draw(self, remaining: float | None) -> None:
        from PIL import ImageTk

        frame = render_orb_frame(
            remaining,
            phase=getattr(self, "liquid_phase", 0.0),
            bubble_phase=getattr(self, "bubble_phase", 0.0),
            reduced_motion=getattr(self, "reduced_motion", False),
            pressed=getattr(self, "pressed", False),
            focused=getattr(self, "focus_visible", False),
            language=getattr(self, "language", "en"),
        )
        if os.name == "nt":
            frame = prepare_windows_display_frame(frame)
        self._photo_image = ImageTk.PhotoImage(frame)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo_image)


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


def acquire_windows_widget_mutex() -> int | None:
    """Return a held Windows mutex handle, or None when another instance exists."""

    try:
        kernel32 = ctypes.windll.kernel32
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        create_mutex.restype = ctypes.c_void_p
        handle = create_mutex(None, False, WIDGET_MUTEX_NAME)
        if not handle:
            return None
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except (AttributeError, OSError):
        return None


def release_windows_widget_mutex(handle: int) -> None:
    try:
        ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Open the independent draggable Quota Orb desktop widget."
    )
    parser.add_argument("--state-file", type=Path, default=default_state_path())
    parser.add_argument("--refresh-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    if not math.isfinite(args.refresh_seconds) or args.refresh_seconds <= 0:
        parser.error("--refresh-seconds must be finite and greater than zero")
    mutex_handle = acquire_windows_widget_mutex() if os.name == "nt" else None
    if os.name == "nt" and mutex_handle is None:
        return
    try:
        run_widget(state_path=args.state_file, refresh_seconds=args.refresh_seconds)
    finally:
        if mutex_handle is not None:
            release_windows_widget_mutex(mutex_handle)


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"


def _utc_now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _identity(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _percent(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    if not isfinite(result):
        return None
    return max(0.0, min(100.0, result))


def _unavailable_section(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": "unavailable",
        "unavailable_reason": reason,
    }


def unavailable_snapshot(
    *,
    platform: str,
    provider: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    subscription = _unavailable_section(reason)
    subscription.update({"plan": None, "windows": []})
    api_quota = _unavailable_section("No official API quota source is configured.")
    api_quota["limits"] = []
    local_usage = _unavailable_section("No local usage source is configured.")
    local_usage.update({"day": None, "totals": None, "by_provider": []})
    token_billing = _unavailable_section("No official token billing source is configured.")
    token_billing.update({"usage": None, "allowance": None, "cost": None})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(now).isoformat(),
        "platform": platform,
        "provider": provider,
        "profile": None,
        "account": None,
        "model": None,
        "subscription_quota": subscription,
        "api_quota": api_quota,
        "local_usage": local_usage,
        "token_billing": token_billing,
    }


def _normalize_windows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    windows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        remaining = _percent(raw.get("remaining_percent"))
        used = _percent(raw.get("used_percent"))
        if remaining is None and used is not None:
            remaining = 100.0 - used
        if used is None and remaining is not None:
            used = 100.0 - remaining
        windows.append(
            {
                "label": str(raw.get("label") or "Quota"),
                "used_percent": used,
                "remaining_percent": remaining,
                "reset_at": _identity(raw.get("reset_at")),
                "detail": raw.get("detail"),
            }
        )
    return windows


_API_LIMIT_FIELDS = ("label", "remaining", "limit", "used", "reset_at", "unit", "detail")
_USAGE_NUMBER_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
    "total_tokens",
    "api_calls",
    "sessions",
)


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return value
    return None


def _normalize_api_limits(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    limits: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        item = {
            key: _safe_scalar(raw[key])
            for key in _API_LIMIT_FIELDS
            if key in raw and _safe_scalar(raw[key]) is not None
        }
        if item:
            limits.append(item)
    return limits


def _normalize_usage_numbers(raw: Mapping[str, Any]) -> dict[str, int | float]:
    return {
        key: raw[key]
        for key in _USAGE_NUMBER_FIELDS
        if isinstance(raw.get(key), (int, float))
        and not isinstance(raw.get(key), bool)
        and isfinite(float(raw[key]))
    }


def _normalize_model_groups(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    groups: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = _normalize_usage_numbers(raw)
        model = _identity(raw.get("model"))
        if model is not None:
            item["model"] = model
        if item:
            groups.append(item)
    return groups


def _normalize_provider_groups(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    groups: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = _normalize_usage_numbers(raw)
        provider = _identity(raw.get("provider"))
        if provider is not None:
            item["provider"] = provider
        models = _normalize_model_groups(raw.get("models"))
        if models:
            item["models"] = models
        if item:
            groups.append(item)
    return groups


_TOKEN_ALLOWANCE_FIELDS = ("limit_tokens", "used_tokens", "remaining_tokens")
_TOKEN_COST_TEXT_FIELDS = (
    "basis",
    "model",
    "pricing_effective_at",
    "period_start",
    "period_end",
)


def _nonnegative_number(value: Any) -> int | float | None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(float(value))
        or value < 0
    ):
        return None
    return value


def _normalize_billing_usage(value: Any) -> dict[str, int | float] | None:
    if not isinstance(value, Mapping):
        return None
    result = {
        key: number
        for key in _USAGE_NUMBER_FIELDS
        if (number := _nonnegative_number(value.get(key))) is not None
    }
    return result or None


def _normalize_token_allowance(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {
        key: number
        for key in _TOKEN_ALLOWANCE_FIELDS
        if (number := _nonnegative_number(value.get(key))) is not None
    }
    remaining_percent = _percent(value.get("remaining_percent"))
    limit_tokens = result.get("limit_tokens")
    used_tokens = result.get("used_tokens")
    remaining_tokens = result.get("remaining_tokens")
    if remaining_percent is None and limit_tokens:
        if remaining_tokens is not None:
            remaining_percent = _percent((remaining_tokens / limit_tokens) * 100.0)
        elif used_tokens is not None:
            remaining_percent = _percent(
                (max(0.0, float(limit_tokens) - float(used_tokens)) / limit_tokens) * 100.0
            )
    if remaining_percent is not None:
        result["remaining_percent"] = remaining_percent
    reset_at = _identity(value.get("reset_at"))
    if reset_at is not None:
        result["reset_at"] = reset_at
    return result or None


def _normalize_token_cost(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    amount = _nonnegative_number(value.get("amount"))
    currency_value = _identity(value.get("currency"))
    currency = currency_value.upper() if currency_value else None
    classification = _identity(value.get("classification"))
    if amount is None or currency is None or classification not in {"actual", "estimated"}:
        return None
    result: dict[str, Any] = {
        "amount": amount,
        "currency": currency,
        "classification": classification,
    }
    for key in _TOKEN_COST_TEXT_FIELDS:
        text = _identity(value.get(key))
        if text is not None:
            result[key] = text
    return result


def normalize_snapshot(raw: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    platform = _identity(raw.get("platform")) or "unknown"
    provider = _identity(raw.get("provider")) or "unknown"
    result = unavailable_snapshot(
        platform=platform,
        provider=provider,
        reason="No official subscription quota source is configured.",
        now=now,
    )
    for key in ("profile", "account", "model"):
        result[key] = _identity(raw.get(key))

    subscription = raw.get("subscription_quota")
    if isinstance(subscription, Mapping):
        result["subscription_quota"] = {
            "available": subscription.get("available") is True,
            "source": _identity(subscription.get("source")) or "unavailable",
            "plan": _identity(subscription.get("plan")),
            "windows": _normalize_windows(subscription.get("windows")),
            "unavailable_reason": _identity(subscription.get("unavailable_reason")),
        }

    api_quota = raw.get("api_quota")
    if isinstance(api_quota, Mapping):
        result["api_quota"] = {
            "available": api_quota.get("available") is True,
            "source": _identity(api_quota.get("source")) or "unavailable",
            "limits": _normalize_api_limits(api_quota.get("limits")),
            "unavailable_reason": _identity(api_quota.get("unavailable_reason")),
        }

    local_usage = raw.get("local_usage")
    if isinstance(local_usage, Mapping):
        totals = local_usage.get("totals")
        groups = local_usage.get("by_provider")
        result["local_usage"] = {
            "available": local_usage.get("available") is True,
            "source": _identity(local_usage.get("source")) or "unavailable",
            "day": _identity(local_usage.get("day")),
            "totals": _normalize_usage_numbers(totals) if isinstance(totals, Mapping) else None,
            "by_provider": _normalize_provider_groups(groups),
            "unavailable_reason": _identity(local_usage.get("unavailable_reason")),
        }

    token_billing = raw.get("token_billing")
    if isinstance(token_billing, Mapping):
        result["token_billing"] = {
            "available": token_billing.get("available") is True,
            "source": _identity(token_billing.get("source")) or "unavailable",
            "usage": _normalize_billing_usage(token_billing.get("usage")),
            "allowance": _normalize_token_allowance(token_billing.get("allowance")),
            "cost": _normalize_token_cost(token_billing.get("cost")),
            "unavailable_reason": _identity(token_billing.get("unavailable_reason")),
        }

    return result

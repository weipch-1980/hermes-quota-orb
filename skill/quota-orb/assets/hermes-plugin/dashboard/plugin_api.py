from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Query


router = APIRouter()


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def aggregate_daily_usage(connection: Any, *, start_ts: float, end_ts: float) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT
            COALESCE(model, 'unknown') AS model,
            COALESCE(billing_provider, '') AS provider,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(api_call_count), 0) AS api_calls,
            COUNT(*) AS sessions
        FROM sessions
        WHERE started_at >= ? AND started_at < ?
        GROUP BY model, billing_provider
        """,
        (start_ts, end_ts),
    ).fetchall()

    by_model = []
    for row in rows:
        item = dict(row)
        item["total_tokens"] = int(item["input_tokens"] or 0) + int(item["output_tokens"] or 0)
        by_model.append(item)
    by_model.sort(key=lambda item: item["total_tokens"], reverse=True)

    totals = {
        "input_tokens": sum(int(item["input_tokens"] or 0) for item in by_model),
        "output_tokens": sum(int(item["output_tokens"] or 0) for item in by_model),
        "cache_read_tokens": sum(int(item["cache_read_tokens"] or 0) for item in by_model),
        "reasoning_tokens": sum(int(item["reasoning_tokens"] or 0) for item in by_model),
        "api_calls": sum(int(item["api_calls"] or 0) for item in by_model),
        "sessions": sum(int(item["sessions"] or 0) for item in by_model),
    }
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["provider"] = next((item["provider"] for item in by_model if item["provider"]), "")
    totals["by_model"] = by_model
    return totals


def build_snapshot(
    connection: Any,
    *,
    provider: str,
    now: datetime,
    quota_fetcher: Callable[[str], Any],
) -> dict[str, Any]:
    local_now = now.astimezone()
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    today = aggregate_daily_usage(
        connection,
        start_ts=start.timestamp(),
        end_ts=end.timestamp(),
    )
    try:
        account_snapshot = quota_fetcher(provider)
    except Exception:
        account_snapshot = None
    quota = serialize_account_snapshot(account_snapshot)
    if not quota.get("provider"):
        quota["provider"] = provider
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "day": start.date().isoformat(),
        "today": today,
        "quota": quota,
    }


def serialize_account_snapshot(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {
            "available": False,
            "provider": None,
            "source": None,
            "fetched_at": None,
            "title": "Account limits",
            "plan": None,
            "windows": [],
            "details": [],
            "unavailable_reason": "No provider quota data available.",
        }

    windows = []
    for window in getattr(snapshot, "windows", ()):
        used = getattr(window, "used_percent", None)
        used_value = float(used) if isinstance(used, (int, float)) else None
        windows.append(
            {
                "label": str(getattr(window, "label", "Quota")),
                "used_percent": used_value,
                "remaining_percent": max(0.0, min(100.0, 100.0 - used_value)) if used_value is not None else None,
                "reset_at": _iso(getattr(window, "reset_at", None)),
                "detail": getattr(window, "detail", None),
            }
        )

    return {
        "available": bool(getattr(snapshot, "available", False)),
        "provider": getattr(snapshot, "provider", None),
        "source": getattr(snapshot, "source", None),
        "fetched_at": _iso(getattr(snapshot, "fetched_at", None)),
        "title": getattr(snapshot, "title", "Account limits"),
        "plan": getattr(snapshot, "plan", None),
        "windows": windows,
        "details": list(getattr(snapshot, "details", ())),
        "unavailable_reason": getattr(snapshot, "unavailable_reason", None),
    }


def _latest_provider(connection: Any) -> str:
    row = connection.execute(
        """
        SELECT billing_provider
        FROM sessions
        WHERE billing_provider IS NOT NULL AND billing_provider != ''
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        value = row[0] if not hasattr(row, "keys") else row["billing_provider"]
        if value:
            return str(value)
    try:
        from hermes_cli.config import load_config

        config = load_config()
        model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
        return str(model_config.get("provider") or config.get("provider") or "").strip()
    except Exception:
        return ""


def _snapshot_now(provider: str | None = None) -> dict[str, Any]:
    from agent.account_usage import fetch_account_usage
    from hermes_state import SessionDB

    db = SessionDB(read_only=True)
    try:
        resolved_provider = str(provider or "").strip().lower() or _latest_provider(db._conn)
        return build_snapshot(
            db._conn,
            provider=resolved_provider,
            now=datetime.now(timezone.utc),
            quota_fetcher=fetch_account_usage,
        )
    finally:
        db.close()


@router.get("/snapshot")
async def snapshot(provider: str | None = Query(default=None, max_length=80)) -> dict[str, Any]:
    """Return local daily token totals plus provider-reported account quota."""
    return await asyncio.to_thread(_snapshot_now, provider)

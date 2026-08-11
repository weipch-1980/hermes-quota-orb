from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .core import normalize_snapshot, unavailable_snapshot


MAX_SNAPSHOT_BYTES = 1_048_576


class SnapshotSource(Protocol):
    def snapshot(self, provider: str | None = None) -> dict[str, Any]: ...


class UnavailableSource:
    def __init__(
        self,
        *,
        platform: str = "unknown",
        provider: str = "unknown",
        reason: str = "No read-only quota snapshot source is configured.",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.platform = platform
        self.provider = provider
        self.reason = reason
        self.now = now

    def snapshot(self, provider: str | None = None) -> dict[str, Any]:
        return unavailable_snapshot(
            platform=self.platform,
            provider=provider or self.provider,
            reason=self.reason,
            now=self.now() if self.now else None,
        )


class JsonSnapshotSource:
    def __init__(
        self,
        path: str | Path,
        *,
        platform: str = "unknown",
        provider: str = "unknown",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.platform = platform
        self.provider = provider
        self.now = now

    def _unavailable(self, provider: str | None, detail: str) -> dict[str, Any]:
        return unavailable_snapshot(
            platform=self.platform,
            provider=provider or self.provider,
            reason=f"Quota snapshot {detail}.",
            now=self.now() if self.now else None,
        )

    def snapshot(self, provider: str | None = None) -> dict[str, Any]:
        try:
            with self.path.open("rb") as stream:
                content = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(content) > MAX_SNAPSHOT_BYTES:
                return self._unavailable(provider, "exceeds the 1 MiB read limit")
            raw = json.loads(content.decode("utf-8"))
            if not isinstance(raw, Mapping):
                return self._unavailable(provider, "must contain a JSON object")
            return normalize_snapshot(raw, now=self.now() if self.now else None)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._unavailable(provider, "is missing, unreadable, or invalid")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_loopback_json(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    with opener.open(request, timeout=timeout) as response:
        return response.read(MAX_SNAPSHOT_BYTES + 1)


class HermesHttpSource:
    """Read the existing Hermes plugin snapshot from an explicit loopback URL."""

    SNAPSHOT_PATH = "/api/plugins/quota-orb/snapshot"

    def __init__(
        self,
        url: str,
        *,
        fetcher: Callable[[str, float], bytes] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Hermes snapshot URL has an invalid port.") from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != self.SNAPSHOT_PATH
            or parsed.query
            or parsed.fragment
            or port is None
        ):
            raise ValueError(
                "Hermes snapshot URL must be loopback HTTP with an explicit port and the exact snapshot path."
            )
        self.url = url
        self.fetcher = fetcher or _fetch_loopback_json
        self.now = now

    def _unavailable(self, provider: str | None, detail: str) -> dict[str, Any]:
        return unavailable_snapshot(
            platform="hermes",
            provider=provider or "unknown",
            reason=f"Hermes loopback snapshot {detail}.",
            now=self.now() if self.now else None,
        )

    def snapshot(self, provider: str | None = None) -> dict[str, Any]:
        try:
            content = self.fetcher(self.url, 2.0)
            if len(content) > MAX_SNAPSHOT_BYTES:
                return self._unavailable(provider, "exceeds the 1 MiB read limit")
            raw = json.loads(content.decode("utf-8"))
            if not isinstance(raw, Mapping):
                return self._unavailable(provider, "must contain a JSON object")
            result = translate_hermes_snapshot(raw, now=self.now() if self.now else None)
            if provider and result["provider"] == "unknown":
                result["provider"] = provider
            return result
        except (OSError, HTTPError, URLError, UnicodeError, json.JSONDecodeError):
            return self._unavailable(provider, "is unavailable or invalid")


def translate_hermes_snapshot(
    raw: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    quota = raw.get("quota") if isinstance(raw.get("quota"), Mapping) else {}
    today = raw.get("today") if isinstance(raw.get("today"), Mapping) else {}
    provider = quota.get("provider") if isinstance(quota.get("provider"), str) else "unknown"
    subscription_available = quota.get("available") is True
    canonical = {
        "platform": "hermes",
        "provider": provider,
        "subscription_quota": {
            "available": subscription_available,
            "source": quota.get("source") or "unavailable",
            "plan": quota.get("plan"),
            "windows": quota.get("windows") if subscription_available and isinstance(quota.get("windows"), list) else [],
            "unavailable_reason": quota.get("unavailable_reason"),
        },
        "api_quota": {
            "available": False,
            "source": "unavailable",
            "limits": [],
            "unavailable_reason": "Hermes account windows are reported separately from API rate limits.",
        },
        "local_usage": {
            "available": bool(today),
            "source": "hermes-state-db" if today else "unavailable",
            "day": raw.get("day"),
            "totals": dict(today) if today else None,
            "by_provider": today.get("by_provider", []) if today else [],
            "unavailable_reason": None if today else "No Hermes local daily usage is available.",
        },
    }
    return normalize_snapshot(canonical, now=now)


def source_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    now: Callable[[], datetime] | None = None,
) -> SnapshotSource:
    values = os.environ if environ is None else environ
    path = str(values.get("QUOTA_ORB_SNAPSHOT_FILE") or "").strip()
    hermes_url = str(values.get("QUOTA_ORB_HERMES_URL") or "").strip()
    platform = str(values.get("QUOTA_ORB_PLATFORM") or "unknown").strip() or "unknown"
    provider = str(values.get("QUOTA_ORB_PROVIDER") or "unknown").strip() or "unknown"
    if path:
        return JsonSnapshotSource(path, platform=platform, provider=provider, now=now)
    if hermes_url:
        try:
            return HermesHttpSource(hermes_url, now=now)
        except ValueError:
            return UnavailableSource(
                platform="hermes",
                provider=provider,
                reason="The configured Hermes snapshot URL is not a safe loopback endpoint.",
                now=now,
            )
    return UnavailableSource(platform=platform, provider=provider, now=now)

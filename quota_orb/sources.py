from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .core import normalize_snapshot, unavailable_snapshot


MAX_SNAPSHOT_BYTES = 1_048_576
MAX_APP_SERVER_LINES = 32
APP_SERVER_TIMEOUT_SECONDS = 2.0


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


def _utc_iso(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
        except (OverflowError, ValueError):
            return None
        if not isfinite(timestamp):
            return None
        if abs(timestamp) > 100_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if isfinite(result) else None


def _rate_limit_buckets(raw: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    buckets: list[tuple[str, Mapping[str, Any]]] = []
    by_limit_id = raw.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, Mapping):
        bucket = by_limit_id.get("codex")
        if isinstance(bucket, Mapping) and bucket.get("limitId", "codex") == "codex":
            buckets.append(("codex", bucket))
    rate_limits = raw.get("rateLimits")
    if isinstance(rate_limits, Mapping) and not buckets:
        buckets.append(
            ("default", rate_limits if "rateLimits" in rate_limits or "planType" in rate_limits else raw)
        )
    return buckets


def translate_codex_rate_limits(
    raw: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    plan: str | None = None
    for fallback_id, bucket in _rate_limit_buckets(raw):
        limit_id = bucket.get("limitId") if isinstance(bucket.get("limitId"), str) else fallback_id
        limit_name = bucket.get("limitName") if isinstance(bucket.get("limitName"), str) else limit_id
        plan_type = bucket.get("planType")
        if plan is None and isinstance(plan_type, str) and plan_type:
            plan = plan_type
        nested_limits = bucket.get("rateLimits")
        limits = nested_limits if isinstance(nested_limits, Mapping) else bucket
        for name in ("primary", "secondary"):
            window = limits.get(name)
            if not isinstance(window, Mapping):
                continue
            used = window.get("usedPercent")
            duration = window.get("windowDurationMins")
            reset_at = _utc_iso(window.get("resetsAt"))
            used_number = _finite_float(used)
            duration_number = _finite_float(duration)
            if (
                used_number is None
                or not 0 <= used_number <= 100
                or duration_number is None
                or duration_number <= 0
                or reset_at is None
            ):
                continue
            windows.append(
                {
                    "label": f"{limit_name} {name}",
                    "used_percent": used,
                    "remaining_percent": 100 - used,
                    "reset_at": reset_at,
                    "detail": {
                        "limitId": limit_id,
                        "limitName": limit_name,
                        "windowDurationMins": duration,
                    },
                }
            )
    available = bool(windows)
    canonical = unavailable_snapshot(
        platform="codex",
        provider="openai-codex",
        reason="Codex app-server rate limit snapshot is unavailable.",
        now=now,
    )
    canonical["subscription_quota"] = {
        "available": available,
        "source": "official-codex-app-server" if available else "unavailable",
        "plan": plan,
        "windows": windows,
        "unavailable_reason": None if available else "Codex app-server returned no valid quota windows.",
    }
    return normalize_snapshot(canonical, now=now)


def _read_line_with_timeout(stream: Any, size: int, timeout: float) -> bytes:
    result: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put(stream.readline(size))
        except BaseException as exc:  # pragma: no cover - platform stream implementations vary.
            result.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        value = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("Codex app-server response timed out.") from exc
    if isinstance(value, BaseException):
        raise value
    return value


class CodexAppServerSource:
    """Read subscription rate limits from an explicitly selected Codex app-server."""

    def __init__(
        self,
        executable: str | Path,
        *,
        popen: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.executable = str(executable)
        self.popen = popen or subprocess.Popen
        self.now = now

    def _unavailable(self) -> dict[str, Any]:
        return unavailable_snapshot(
            platform="codex",
            provider="openai-codex",
            reason="Codex app-server rate limit snapshot is unavailable.",
            now=self.now() if self.now else None,
        )

    @staticmethod
    def _write(process: Any, message: Mapping[str, Any]) -> None:
        if process.stdin is None:
            raise OSError("Codex app-server stdin is unavailable.")
        process.stdin.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
        process.stdin.flush()

    @staticmethod
    def _response(
        process: Any,
        expected_id: int,
        remaining_bytes: int,
        remaining_lines: int,
        deadline: float,
    ) -> tuple[Mapping[str, Any], int, int]:
        if process.stdout is None:
            raise OSError("Codex app-server stdout is unavailable.")
        for _ in range(remaining_lines):
            timeout = deadline - monotonic()
            if timeout <= 0:
                raise TimeoutError("Codex app-server response timed out.")
            line = _read_line_with_timeout(
                process.stdout, remaining_bytes + 1, timeout
            )
            if not line or len(line) > remaining_bytes:
                raise ValueError("Codex app-server response is invalid.")
            remaining_bytes -= len(line)
            remaining_lines -= 1
            message = json.loads(line.decode("utf-8"))
            if not isinstance(message, Mapping) or message.get("id") != expected_id:
                continue
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise ValueError("Codex app-server response is invalid.")
            return result, remaining_bytes, remaining_lines
        raise ValueError("Codex app-server response is invalid.")

    @staticmethod
    def _close(process: Any) -> None:
        try:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError, AttributeError):
            try:
                process.kill()
            except (OSError, subprocess.SubprocessError, AttributeError):
                pass

    def snapshot(self, provider: str | None = None) -> dict[str, Any]:
        process = None
        try:
            deadline = monotonic() + APP_SERVER_TIMEOUT_SECONDS
            process = self.popen(
                [self.executable, "app-server", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            self._write(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "quota-orb", "version": "0.5.0"},
                    },
                },
            )
            _, remaining_bytes, remaining_lines = self._response(
                process, 1, MAX_SNAPSHOT_BYTES, MAX_APP_SERVER_LINES, deadline
            )
            self._write(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
            self._write(
                process,
                {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}},
            )
            raw, _, _ = self._response(process, 2, remaining_bytes, remaining_lines, deadline)
            return translate_codex_rate_limits(raw, now=self.now() if self.now else None)
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            RecursionError,
            TimeoutError,
            subprocess.SubprocessError,
        ):
            return self._unavailable()
        finally:
            if process is not None:
                self._close(process)


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
    codex_executable = str(values.get("QUOTA_ORB_CODEX_EXE") or "").strip()
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
    if codex_executable:
        return CodexAppServerSource(codex_executable, now=now)
    return UnavailableSource(platform=platform, provider=provider, now=now)


def desktop_source_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    now: Callable[[], datetime] | None = None,
) -> SnapshotSource:
    """Select a desktop source, with one fixed-path Codex fallback and no PATH search."""

    values = os.environ if environ is None else environ
    explicit_keys = (
        "QUOTA_ORB_SNAPSHOT_FILE",
        "QUOTA_ORB_HERMES_URL",
        "QUOTA_ORB_CODEX_EXE",
    )
    if any(str(values.get(key) or "").strip() for key in explicit_keys):
        return source_from_environment(values, now=now)

    profile = str(values.get("USERPROFILE") or "").strip()
    if profile:
        candidate = Path(profile) / ".codex" / "plugins" / ".plugin-appserver" / "codex.exe"
        try:
            if candidate.is_file():
                return CodexAppServerSource(candidate, now=now)
        except OSError:
            pass
    return source_from_environment(values, now=now)

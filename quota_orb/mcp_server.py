from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .sources import SnapshotSource, source_from_environment


ORB_RESOURCE_URI = "ui://quota-orb/v1.html"
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def supported_sources() -> dict[str, Any]:
    unavailable = "unavailable_without_official_source"
    snapshot_only = "explicit_snapshot_bridge_only"
    text_ui = "structured_text_fallback_or_windows_desktop_widget"
    return {
        "schema_version": "1.0",
        "platforms": {
            "hermes": {
                "transport": "native_plugin_or_local_mcp",
                "subscription_quota": "official_provider_adapters_when_available",
                "api_quota": "separate",
                "local_usage": "hermes_state_db",
                "token_billing": snapshot_only,
                "ui": "native_desktop_orb",
            },
            "chatgpt": {
                "transport": "streamable_http_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": "mcp_apps_inline_orb",
            },
            "codex": {
                "transport": "user_agent_skill_and_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "claude": {
                "transport": "claude_remote_connector_or_code_user_local_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "gemini": {
                "transport": "gemini_spark_remote_or_antigravity_gemini_cli_user_local_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "cursor": {
                "transport": "user_agent_skill_and_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "copilot": {
                "transport": "copilot_cli_user_agent_skill_and_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "qwen-code": {
                "transport": "user_agent_skill_and_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "kimi-cli": {
                "transport": "user_agent_skill_and_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "openclaw": {
                "transport": "official_global_skill_cli_and_user_local_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": snapshot_only,
                "ui": text_ui,
            },
            "workbuddy-code": {
                "transport": "codebuddy_user_skill_and_user_local_stdio_mcp",
                "subscription_quota": unavailable,
                "api_quota": snapshot_only,
                "local_usage": snapshot_only,
                "token_billing": "official_statusline_cost_or_explicit_snapshot_bridge",
                "ui": text_ui,
            },
        },
        "china_model_families": {
            "kimi": {
                "integration": "kimi_cli_user_skill_and_mcp",
                "integration_kind": "native_cli_skill_and_mcp",
                "native_skill": True,
                "native_mcp": True,
                "compatible_host": None,
                "user_global_skill_path": "~/.kimi/skills",
                "windows_support": "documented_by_native_cli",
                "subscription_quota": unavailable,
            },
            "qwen": {
                "integration": "qwen_code_user_skill_and_mcp",
                "integration_kind": "native_cli_skill_and_mcp",
                "native_skill": True,
                "native_mcp": True,
                "compatible_host": None,
                "user_global_skill_path": "~/.qwen/skills",
                "windows_support": "documented_by_native_cli",
                "subscription_quota": unavailable,
            },
            "deepseek": {
                "integration": "official_codex_model_provider_path",
                "integration_kind": "provider_via_compatible_host",
                "native_skill": False,
                "native_mcp": False,
                "compatible_host": "codex",
                "user_global_skill_path": "not_applicable",
                "windows_support": "inherits_compatible_host",
                "subscription_quota": unavailable,
            },
            "glm": {
                "integration": "official_claude_code_model_provider_path",
                "integration_kind": "provider_via_compatible_host",
                "native_skill": False,
                "native_mcp": False,
                "compatible_host": "claude-code",
                "user_global_skill_path": "not_applicable",
                "windows_support": "unavailable_in_documented_setup",
                "subscription_quota": unavailable,
            },
            "minimax": {
                "integration": "documented_skills_surface_without_native_mcp_claim",
                "integration_kind": "native_skill_surface_only",
                "native_skill": True,
                "native_mcp": False,
                "compatible_host": None,
                "user_global_skill_path": "not_published",
                "windows_support": "not_published",
                "subscription_quota": unavailable,
            },
        },
        "safety": {
            "credentials": "never_returned",
            "web_scraping": False,
            "unknown_is_zero": False,
            "read_only": True,
        },
    }


def create_server(
    source: SnapshotSource | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> FastMCP:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError(
            "Quota Orb may bind only to a loopback host; use an authenticated HTTPS reverse proxy for remote access."
        )
    snapshot_source = source or source_from_environment()
    literal_host = f"[{host}]" if host == "::1" else host
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{literal_host}:*"],
        allowed_origins=[f"http://{literal_host}:*"],
    )
    server = FastMCP(
        "Quota Orb",
        instructions=(
            "Read-only quota, token-billing, and local-usage snapshots. Keep subscription quota, "
            "API quota, local token usage, and token billing separate. Never treat unavailable "
            "quota or cost as zero, and never describe an estimate as an actual charge."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )

    @server.tool(
        name="get_quota_snapshot",
        title="Get quota snapshot",
        description=(
            "Return the current provider-neutral quota snapshot. Read-only; unavailable official "
            "subscription data remains unavailable rather than being estimated."
        ),
        annotations=_READ_ONLY,
        meta={
            "ui": {"resourceUri": ORB_RESOURCE_URI},
            "openai/outputTemplate": ORB_RESOURCE_URI,
        },
        structured_output=True,
    )
    def get_quota_snapshot(provider: str | None = None) -> dict[str, Any]:
        return snapshot_source.snapshot(provider)

    @server.tool(
        name="get_daily_usage",
        title="Get local daily usage",
        description="Return only the local daily token-usage partition from the current read-only snapshot.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def get_daily_usage(provider: str | None = None) -> dict[str, Any]:
        snapshot = snapshot_source.snapshot(provider)
        return {
            "schema_version": snapshot["schema_version"],
            "generated_at": snapshot["generated_at"],
            "platform": snapshot["platform"],
            "provider": snapshot["provider"],
            "local_usage": snapshot["local_usage"],
        }

    @server.tool(
        name="get_supported_sources",
        title="Get supported quota sources",
        description="Describe which quota and local-usage sources each platform can truthfully expose.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def get_supported_sources() -> dict[str, Any]:
        return supported_sources()

    @server.resource(
        ORB_RESOURCE_URI,
        name="quota-orb",
        title="Quota Orb",
        description="Portable read-only emerald quota visualization.",
        mime_type="text/html;profile=mcp-app",
        meta={"ui": {"prefersBorder": False}},
    )
    def quota_orb_resource() -> str:
        return (Path(__file__).parent / "assets" / "quota_orb_app.html").read_text(encoding="utf-8")

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the read-only Quota Orb MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    create_server(host=args.host, port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()

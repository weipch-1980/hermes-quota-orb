from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


ROOT = Path(__file__).parents[1]


class McpStdioEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_process_initializes_lists_calls_and_reads_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot_path = Path(temp) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "platform": "claude",
                        "provider": "Anthropic API",
                        "subscription_quota": {
                            "available": True,
                            "source": "e2e-fixture",
                            "windows": [
                                {"label": "Session", "remaining_percent": 0, "reset_at": None}
                            ],
                        },
                        "local_usage": {
                            "available": True,
                            "source": "e2e-log",
                            "day": "2026-08-11",
                            "totals": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                        },
                    }
                ),
                encoding="utf-8",
            )
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "quota_orb.mcp_server", "--transport", "stdio"],
                cwd=str(ROOT),
                env={**os.environ, "QUOTA_ORB_SNAPSHOT_FILE": str(snapshot_path)},
            )
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "Quota Orb")

                    tools = await session.list_tools()
                    self.assertEqual(
                        {tool.name for tool in tools.tools},
                        {"get_quota_snapshot", "get_daily_usage", "get_supported_sources"},
                    )
                    result = await session.call_tool("get_quota_snapshot", {})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent["provider"], "Anthropic API")
                    self.assertEqual(
                        result.structuredContent["subscription_quota"]["windows"][0]["remaining_percent"],
                        0.0,
                    )

                    resources = await session.list_resources()
                    resource = next(item for item in resources.resources if str(item.uri) == "ui://quota-orb/v1.html")
                    self.assertEqual(resource.mimeType, "text/html;profile=mcp-app")
                    rendered = await session.read_resource(resource.uri)
                    self.assertIn("ui/notifications/tool-result", rendered.contents[0].text)

    async def test_real_streamable_http_process_initializes_and_calls_tool(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        env = dict(os.environ)
        env.pop("QUOTA_ORB_SNAPSHOT_FILE", None)
        env.pop("QUOTA_ORB_HERMES_URL", None)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "quota_orb.mcp_server",
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                if process.poll() is not None:
                    self.fail(f"HTTP MCP server exited early with code {process.returncode}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                self.fail("HTTP MCP server did not become ready")

            hostile_request = Request(
                f"http://127.0.0.1:{port}/mcp",
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://attacker.example",
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as rejected:
                urlopen(hostile_request, timeout=2)
            self.assertEqual(rejected.exception.code, 403)

            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
                reader,
                writer,
                _,
            ):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool("get_supported_sources", {})
                    self.assertFalse(result.isError)
                    self.assertTrue(result.structuredContent["safety"]["read_only"])
                    self.assertEqual(
                        set(result.structuredContent["platforms"]),
                        {
                            "hermes",
                            "chatgpt",
                            "codex",
                            "claude",
                            "gemini",
                            "cursor",
                            "copilot",
                            "qwen-code",
                            "kimi-cli",
                            "openclaw",
                            "workbuddy-code",
                        },
                    )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

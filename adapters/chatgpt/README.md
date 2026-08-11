# ChatGPT adapter

Quota Orb exposes a portable MCP Apps resource with MIME type `text/html;profile=mcp-app`. The `get_quota_snapshot` tool links to that resource through `_meta.ui.resourceUri`, while all tools remain useful without UI.

For local protocol testing, install the project and start the Streamable HTTP transport:

```text
python -m quota_orb.mcp_server --transport streamable-http --host 127.0.0.1 --port 8787
```

The local endpoint is `http://127.0.0.1:8787/mcp`. The bundled server deliberately rejects non-loopback binds because it has no production authentication layer. A real ChatGPT developer-mode connection requires a stable, reachable **HTTPS** URL ending in `/mcp`, supplied by a separately reviewed OAuth-capable reverse proxy or hosting layer. This repository is **not deployed** and contains no production OAuth, hosting, domain, or user-account configuration.

Set `QUOTA_ORB_SNAPSHOT_FILE` only to an explicit read-only canonical snapshot file. Without an official source, personal ChatGPT subscription quota remains **Unavailable**; API quota and local usage remain separate.

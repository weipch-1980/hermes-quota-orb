# OpenAI Codex adapter

Quota Orb installs into Codex itself at user scope; it does not install another client.

## User-global Skill

```powershell
python scripts/install_agent_skill.py --target codex
python scripts/install_agent_skill.py --target codex --apply
```

The destination is `~/.agents/skills/quota-orb/SKILL.md`, available to Codex across projects.

## User-global MCP

Install the Python package, then register the local read-only stdio server with Codex:

```powershell
python -m pip install .
codex mcp add quota-orb --env QUOTA_ORB_PLATFORM=codex --env QUOTA_ORB_PROVIDER=openai-codex --env QUOTA_ORB_CODEX_EXE=C:\Users\admin\.codex\plugins\.plugin-appserver\codex.exe -- python -m quota_orb.mcp_server --transport stdio --autostart-widget
```

Codex owns both registrations. No other AI client is required. `--autostart-widget` is an explicit Windows opt-in: each MCP startup tries to launch the independent orb, while its local named mutex keeps a single visible instance. `QUOTA_ORB_CODEX_EXE` selects the local Codex executable explicitly; the Windows widget may otherwise discover only the fixed user app-server path. Quota Orb starts the experimental `codex app-server --stdio` protocol and calls only the read-only `account/rateLimits/read` method. It exposes no independent REST API, sends no credentials, reads no credential files, and preserves the app-server's quota-window labels verbatim. Personal ChatGPT/Codex subscription allowance remains `Unavailable` when that official source is absent, invalid, or unsupported.

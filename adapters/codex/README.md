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
codex mcp add quota-orb --env QUOTA_ORB_SNAPSHOT_FILE=<absolute-path-to-snapshot.json> -- python -m quota_orb.mcp_server --transport stdio
```

Codex owns both registrations. No other AI client is required. The snapshot path is explicit and should contain no authentication material. Personal ChatGPT/Codex subscription allowance remains Unavailable unless an official source supplies it.

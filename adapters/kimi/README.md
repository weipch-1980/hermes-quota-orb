# Kimi Code CLI adapter

Kimi is one of the Chinese frontier model families selected in the August 2026 compatibility set. Quota Orb installs into Kimi CLI's own user scope.

## User-global Skill

```powershell
python scripts/install_agent_skill.py --target kimi-cli
python scripts/install_agent_skill.py --target kimi-cli --apply
```

The destination is `~/.kimi/skills/quota-orb/SKILL.md`.

## User-global MCP

After `python -m pip install .`, add the stdio server with Kimi's MCP command or merge `mcp.json.example` into `~/.kimi/mcp.json`:

```powershell
kimi mcp add --transport stdio quota-orb -- python -m quota_orb.mcp_server --transport stdio
```

If an explicit snapshot file is needed, use the example configuration so the environment value remains local. Kimi subscription allowance is Unavailable unless an official authorized source supplies it.

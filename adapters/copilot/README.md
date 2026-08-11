# GitHub Copilot CLI adapter

Quota Orb installs into GitHub Copilot CLI's personal user Skill scope; it does not install another client.

## User-global Skill

```powershell
python scripts/install_agent_skill.py --target copilot
python scripts/install_agent_skill.py --target copilot --apply
```

The destination is `~/.copilot/skills/quota-orb/SKILL.md` and is available across Copilot CLI sessions. Other Copilot surfaces must be checked against their own official customization rules.

## User-global MCP

After `python -m pip install .`, use Copilot CLI's user configuration command or merge `mcp.json.example` into the supported Copilot MCP configuration. The server command is local stdio and exposes only three read-only tools.

GitHub Copilot plan allowance has no general official remaining-percent bridge in this project; it is reported as Unavailable unless an official source supplies it.

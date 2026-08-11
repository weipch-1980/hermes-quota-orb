# Google Gemini and Antigravity adapters

Google exposes distinct client surfaces; user-global paths must remain distinct.

## Antigravity CLI user scope

```powershell
python scripts/install_agent_skill.py --target antigravity
python scripts/install_agent_skill.py --target antigravity --apply
```

Destination: `~/.gemini/config/skills/quota-orb/SKILL.md`. Merge `antigravity-mcp.json.example` into Antigravity's user MCP configuration.

## Gemini CLI user scope

```powershell
python scripts/install_agent_skill.py --target gemini-cli
python scripts/install_agent_skill.py --target gemini-cli --apply
```

Destination: `~/.gemini/skills/quota-orb/SKILL.md`. Merge `settings.json.example` into `~/.gemini/settings.json`; only the three read-only tools are included and `trust` stays false.

## Gemini Spark Connected Apps

Gemini Spark can connect a custom app to a remote MCP server. A real Connected App requires stable reachable **HTTPS**, authentication, account eligibility, and any required review. This repository is **not deployed**.

Gemini API quota, consumer subscription allowance, and local Token totals remain separate; unsupported subscription allowance is Unavailable.

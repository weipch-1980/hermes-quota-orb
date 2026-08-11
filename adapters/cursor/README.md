# Cursor adapter

Quota Orb installs as a Cursor user Skill and local MCP server; it does not install another client.

## User-global Skill

```powershell
python scripts/install_agent_skill.py --target cursor
python scripts/install_agent_skill.py --target cursor --apply
```

The destination is `~/.cursor/skills/quota-orb/SKILL.md`.

## User-global MCP

Install the Python package, then merge `mcp.json.example` into Cursor's global `~/.cursor/mcp.json`. The example starts only the local read-only stdio server and contains no credentials.

Cursor model selection does not change quota semantics. OpenAI, Anthropic, Google, Chinese-provider API quota, provider subscriptions, and local Token usage remain separate data classes. Unsupported personal subscription allowance is Unavailable.

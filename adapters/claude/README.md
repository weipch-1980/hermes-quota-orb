# Claude and Claude Code adapters

## Claude.ai, Claude Desktop, Cowork, and mobile

Claude supports a remote MCP **Custom Connector** across its main products. A real connector requires a stable reachable **HTTPS** endpoint and reviewed authentication. This repository is **not deployed** and does not claim OAuth, organization approval, privacy policy, or connector review is configured.

## Claude Code user-global install

```powershell
python scripts/install_agent_skill.py --target claude
python scripts/install_agent_skill.py --target claude --apply
python -m pip install .
claude mcp add --scope user --transport stdio quota-orb -- python -m quota_orb.mcp_server --transport stdio
```

The Skill destination is `~/.claude/skills/quota-orb/SKILL.md`; the MCP server is stored in Claude Code's user scope. Both belong to Claude Code, not another AI client. Use `mcp.json.example` when an explicit snapshot environment value is needed.

A safe loopback source may optionally reference the exact local snapshot endpoint. Claude subscription allowance remains Unavailable unless an official source supplies it.

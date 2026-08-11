# WorkBuddy / CodeBuddy Code adapter

Quota Orb supports Tencent WorkBuddy's CodeBuddy Code CLI Skill and MCP contracts. It never installs into Hermes and does not modify the WorkBuddy desktop client's configuration automatically.

## User-level global Skill

Install the portable Skill for the current user at:

```text
~/.codebuddy/skills/quota-orb/SKILL.md
```

From the Universal package root, the Quota Orb installer can place only this Skill into a temporary or selected HOME:

```bash
python scripts/install_agent_skill.py --target workbuddy-code
python scripts/install_agent_skill.py --target workbuddy-code --apply
```

The first command is preview-only. The second is the explicit write action.

## User-level MCP

WorkBuddy's official CodeBuddy documentation recommends the user-scope file:

```text
~/.codebuddy/.mcp.json
```

The equivalent official CLI form is:

```bash
codebuddy mcp add --scope user quota-orb -- python -m quota_orb.mcp_server --transport stdio
```

`mcp.json.example` contains the same read-only stdio server without credentials.

Official references:

- Skills example: https://www.workbuddy.ai/docs/cli/best-practices#create-skills
- MCP user scope: https://www.workbuddy.ai/docs/cli/mcp
- Status line cost field: https://www.workbuddy.ai/docs/cli/statusline

## Token billing

The official status-line payload documents `cost.total_cost_usd`. When that exact provider-reported value is bridged into `token_billing.cost`, Quota Orb labels it as **actual** provider-reported cost. A cost calculated from a dated official model price table must instead be labeled **estimated**. Local Token totals are never presented as an invoice.

If WorkBuddy/CodeBuddy exposes Token usage but not an allowance, budget, or cost for the selected account, Quota Orb shows the known usage and reports the missing remaining percentage or billing amount as `Unavailable`.

## Data boundary

Skill/MCP availability does not prove that personal subscription quota is exposed. No webpage scraping, browser storage, cookie, API key, or private endpoint is used.

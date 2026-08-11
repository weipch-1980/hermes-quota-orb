# OpenClaw adapter

Quota Orb supports OpenClaw through its official global Skill installer and local MCP registration surface. This adapter never installs into Hermes and does not guess a private OpenClaw filesystem path.

## User-level global Skill

From the extracted Universal package root, let the **official CLI** choose OpenClaw's shared managed skills directory:

```bash
openclaw skills install ./skills/quota-orb --as quota-orb --global
openclaw skills verify quota-orb --global
```

The official contract says `--global` targets the **shared managed skills directory** for all local agents. Because OpenClaw owns that location and may evolve it, Quota Orb intentionally does not hard-code a private Skill destination.

Official references:

- Skills: https://docs.openclaw.ai/tools/skills
- CLI: https://docs.openclaw.ai/cli/skills
- MCP: https://docs.openclaw.ai/cli

## MCP

Register the read-only stdio server using the current OpenClaw MCP command documented by the installed CLI. Use this server command and arguments:

```text
python -m quota_orb.mcp_server --transport stdio
```

Set `QUOTA_ORB_SNAPSHOT_FILE` only to a user-selected absolute JSON snapshot path. Do not place API keys, access tokens, browser data, or credentials in the snapshot.

## Data boundary

OpenClaw Skill/MCP support does not imply access to an OpenClaw or upstream model subscription balance. Subscription quota, API quota, local usage, and Token billing remain separate. Without an official authorized source, each unavailable value is reported as `Unavailable` rather than zero.

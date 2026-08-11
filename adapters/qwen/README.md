# Qwen Code adapter

Qwen is one of the Chinese frontier model families selected in the August 2026 compatibility set. Quota Orb installs into Qwen Code's own user scope.

## User-global Skill

```powershell
python scripts/install_agent_skill.py --target qwen-code
python scripts/install_agent_skill.py --target qwen-code --apply
```

The destination is `~/.qwen/skills/quota-orb/SKILL.md`.

## User-global MCP

After `python -m pip install .`, merge `settings.json.example` into `~/.qwen/settings.json`. It starts the same local read-only stdio MCP server, allowlists the three Quota Orb tools, and sets `trust` to false.

Qwen model API limits, Alibaba Cloud Coding Plan, consumer-chat allowance, and local usage are separate. Without an official authorized quota source, personal subscription allowance is Unavailable.

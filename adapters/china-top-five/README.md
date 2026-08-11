# China frontier model compatibility set — August 2026

This set was checked in **2026-08** using the Artificial Analysis Intelligence Index/leaderboard as the independent capability reference, then constrained by each vendor's official Agent, Skill, MCP, or supported coding-host documentation. Rankings change; this is a dated compatibility set, not a permanent performance claim.

Reference: <https://artificialanalysis.ai/leaderboards/models>

| Model family | Vendor | Quota Orb integration | Truthful quota boundary |
|---|---|---|---|
| Kimi | Moonshot AI | Kimi Code CLI user Skill + local stdio MCP | Personal subscription quota is Unavailable without an official authorized source |
| Qwen | Alibaba | Qwen Code user Skill + local stdio MCP | API quota, Coding Plan, and consumer allowance stay separate |
| DeepSeek | DeepSeek | Officially supported model provider in Codex; Quota Orb remains installed in Codex | No claim that the DeepSeek web client installs this Skill |
| GLM | Z.ai / Zhipu | Official GLM Coding Plan integration through Claude Code; Quota Orb remains installed in Claude Code; the documented vendor setup is unavailable on Windows | No credential collection; unsupported allowance is Unavailable |
| MiniMax | MiniMax | MiniMax Code documents a native Skills surface; no native MCP support or stable user-global Skill path is claimed | MiniMax plan and credit data are not inferred from API or local usage |

## Official integration evidence

- Qwen Code Skills and MCP: <https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/> and <https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/>
- Kimi CLI Skills and MCP: <https://moonshotai.github.io/kimi-cli/en/customization/skills.html> and <https://moonshotai.github.io/kimi-cli/en/customization/mcp.html>
- DeepSeek Codex integration: <https://api-docs.deepseek.com/quick_start/agent_integrations/codex/>
- GLM Claude Code integration: <https://docs.bigmodel.cn/cn/guide/develop/claude>
- MiniMax Code Skills surface: <https://agent.minimax.io/docs/code/welcome>

Calling a model API is not the same as installing into that vendor's official chat client. Quota Orb never requests provider credentials. Users may inject an explicit normalized snapshot; unsupported personal subscription data remains **Unavailable**.

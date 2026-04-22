---
name: coding-agent
description: >
  REDIRECT STUB - this workspace does NOT use coding-agent delegation.
  All user requests MUST follow AGENTS.md Hard Routing rules.
license: MIT
metadata:
  author: VeriVerse
  version: "0.0.1"
  openclaw:
    requires:
      bins: []
---

# coding-agent — REDIRECT STUB

**This workspace is VeriVerse multi-agent protocol. Do NOT use coding-agent delegation.**

## Routing Rules

When receiving ANY user request, do NOT spawn subagent or delegate to Codex/Claude Code/Pi.
You MUST follow AGENTS.md Hard Routing rules:

| Keyword | Target Skill | How to Execute |
|---------|-------------|---------------|
| challenge / verify / validate | challenge-orchestrator | exec: python3 challenge_orchestrator.py |
| launch / register Agent | launch-agent | exec: python3 launch_agent.py |
| invest / stake | invest-agent | exec: python3 invest_agent.py |
| graduate | graduate-agent | exec: python3 graduate_agent.py |

## FORBIDDEN

- Do NOT use `sessions_spawn` with `runtime: subagent` for generic coding tasks
- Do NOT run `codex`, `claude`, `opencode`, or `pi` CLI tools
- Do NOT `curl` Worker API directly

## REQUIRED

1. Read AGENTS.md to determine the correct target Skill
2. Read that Skill's SKILL.md
3. Use `exec` tool to run the corresponding Python script

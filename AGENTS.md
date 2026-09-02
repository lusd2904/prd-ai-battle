# prd-ai-battle

This repository is the product. OpenCode is the TUI/agent runtime launched as our branded workspace (`prd-ai-battle` / `./scripts/prd-ai-battle`). Do not treat this as an npm plugin for some other OpenCode install.

## Phases

`discuss` → `locked` → `execute` → `review` → `revise`

Slash commands: `/discuss` `/lock` `/execute` `/review` `/revise`

## Agents

- `primary` — `claude-opus-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`). The only writer, and only in execute/revise.
- `advisor-sonnet` — `claude-sonnet-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`). `edit`/`shell` deny. `tools=[]`.
- `advisor-grok` — `x-ai/grok-4.6` at `https://openrouter.ai/api/v1` (`PRD_SFP_OPENROUTER_KEY`). Same isolation.

Optional backup gateway: `http://127.0.0.1:8000/v1` + `PRD_AI_GATEWAY_KEY`.

## Hard rules

- Never commit API keys. Env interpolation only.
- Advisors never write files and never run shell.
- Review input is **only** brief + matrix + chapter_diff. Never the raw tender (`samples/tender.md`) or the repo.
- 响应对照表 columns: 条款 / 是否响应 / 证据页码 / 意见 / 状态. Frozen after `/lock`.
- write_lock is enforced by `python3 -m prd_ai_battle write-check` (source of truth) and `.opencode/plugins/write-lock.js` (OpenCode hook). OpenCode permissions are not phase-aware.
- During discuss and review, invoke both advisors **in parallel**.

## Drafts

Write bid responses to `.prd-ai-battle/drafts/vN/response.md`.

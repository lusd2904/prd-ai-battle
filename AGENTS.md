# prd-ai-battle

This repository is the product. OpenCode is the TUI/agent runtime launched as our branded workspace (`prd-ai-battle` / `./scripts/prd-ai-battle`). Do not treat this as an npm plugin for some other OpenCode install.

## Phases

`discuss` → `locked` → `execute` → `review` → `revise`

Slash commands: `/discuss` `/lock` `/execute` `/review` `/revise`

## Config

Committed `config.example.yaml` / `opencode.json` are **seed only**. Live models, `base_url`, agent ids, and key env names come from gitignored `prd-ai-battle.yaml`. Key *names* are listed in committed `prd-ai-battle.env.example`; copy that to gitignored `prd-ai-battle.env` and fill values. Launch loads the env file into the process environment.

`write_lock` binds the **current yaml `primary.id`**, not `claude-opus-5` and not a hardcoded agent name.

Seed snapshot (changeable):

- `primary` — `claude-opus-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`)
- `advisor-sonnet` — `claude-sonnet-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`)
- `advisor-grok` — `x-ai/grok-4.6` at `https://openrouter.ai/api/v1` (`PRD_SFP_OPENROUTER_KEY`)
- optional `prd-gateway` backup — `grok-4.5` / `grok-composer-2.5-fast` at `http://127.0.0.1:8000/v1` (`PRD_AI_GATEWAY_KEY`). grok2api, **not Claude**. 429 quota = reachable, credits empty — keep optional.

## Hard rules

- Never commit API keys.
- Advisors never write files and never run shell.
- Review input is **only** brief + matrix + chapter_diff. Never the raw tender (`samples/tender.md`, a 招标 PDF) or the repo. Ingest parses PDFs locally (`prd-ai-battle ingest file.pdf`); advisors never receive the file.
- 响应对照表 columns: 条款 / 是否响应 / 证据页码 / 意见 / 状态. Frozen after `/lock`.
- write_lock is enforced by `python3 -m prd_ai_battle write-check` (source of truth) and `.opencode/plugins/write-lock.js`.
- During discuss and review, invoke every configured advisor **in parallel**. One advisor timeout or HTTP fail must not abort the others (`stream_parallel` isolates errors; OpenCode primary continues if a teammate fails).

## Drafts

Write bid responses to `.prd-ai-battle/drafts/vN/response.md`.

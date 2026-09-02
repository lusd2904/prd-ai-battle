---
name: prd-battle
description: Drive prd-ai-battle phases discuss → locked → execute → review → revise with write_lock and advisor isolation
license: MIT
compatibility: opencode
metadata:
  audience: operators
  workflow: bid-response
---

# prd-ai-battle

This repo **is** the product. OpenCode is the TUI/agent runtime launched as our branded workspace (`prd-ai-battle`). Do not install a separate npm plugin into upstream OpenCode.

## Team

| Agent | Model | Writes |
| --- | --- | --- |
| `primary` | `claude-opus-5` via xixiapi.io | Only in `execute` / `revise` |
| `advisor-sonnet` | `claude-sonnet-5` via xixiapi.io | Never (`tools=[]`, edit/shell deny) |
| `advisor-grok` | `x-ai/grok-4.6` via OpenRouter | Never (`tools=[]`, edit/shell deny) |

Keys: `PRD_SFP_XIXI_KEY`, `PRD_SFP_OPENROUTER_KEY` (names in `prd-ai-battle.env.example`; values never in git). Optional `prd-gateway` backup: `http://127.0.0.1:8000/v1` + `PRD_AI_GATEWAY_KEY` — grok2api (`grok-4.5` / `grok-composer-2.5-fast`), **not Claude**.

## Commands

- `/discuss` — ingest sample tender if needed, fan-out parallel discussion, no writes
- `/lock` — freeze 响应对照表 (条款 / 是否响应 / 证据页码 / 意见 / 状态)
- `/execute` — primary writes `.prd-ai-battle/drafts/v1/response.md`
- `/review` — advisors get **only** brief + matrix + chapter_diff
- `/revise` — primary writes the next version

## Enforcement

Python `prd-ai-battle write-check` is the source of truth. The in-repo overlay hook (`.opencode/plugins/write-lock.js`) intercepts write/edit/bash and denies unless write_lock allows it. This hook ships with the product; it is not an npm package users install into other OpenCode projects.

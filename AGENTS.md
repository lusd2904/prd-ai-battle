# prd-ai-battle

This repository is the product. The user-facing skin is the Chinese Textual **board** (`prd-ai-battle` / `prd-ai-battle tui` / `./scripts/prd-ai-battle`) with a left **项目** list (many mounted projects; 新建; click to switch). OpenCode is the execute/revise engine (`prd-ai-battle launch` / slash-command plugin), not a second window. Do not treat this as an npm plugin for some other OpenCode install.

## Phases

`discuss` → `locked` → `execute` → `review` → `revise`

Slash commands: `/discuss` `/lock` `/execute` `/review` `/revise`

## Config

Committed `config.example.yaml` / `opencode.json` are **seed only**. Live models, `base_url`, agent ids, and key env names come from gitignored `prd-ai-battle.yaml`. Key *names* are listed in committed `prd-ai-battle.env.example`; copy that to gitignored `prd-ai-battle.env` and fill values. Launch loads the env file into the process environment.

`write_lock` binds the **active project's yaml `primary.id`**, not `claude-opus-5` and not a hardcoded agent name. Each project has its own workspace, yaml, and gitignored env — keys and models must not leak across projects.

Seed snapshot (changeable):

- `primary` — `claude-opus-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`)
- `advisor-sonnet` — `claude-sonnet-5` at `https://xixiapi.io/v1` (`PRD_SFP_XIXI_KEY`)
- `advisor-glm` — `z-ai/glm-5.2:free` at `https://openrouter.ai/api/v1` (`PRD_SFP_OPENROUTER_KEY`). Verified OpenRouter `:free`. **Not** `x-ai/grok-4.6` (402 without credits).
- Advisor pool also accepts OpenCode Zen Free (`opencode` provider, `https://opencode.ai/zen/v1`): `mimo-v2.5-free`, `ling-3.0-flash-fin-free`, `nemotron-3.5-lightning-free`, `nemotron-3-ultra-free`, `big-pickle`. These are **not** OpenRouter slugs. Muse Spark 1.2 on OpenRouter is `meta/muse-spark-1.2` (paid).
- optional `prd-gateway` backup — `grok-4.5` / `grok-composer-2.5-fast` at `http://127.0.0.1:8000/v1` (`PRD_AI_GATEWAY_KEY`). grok2api, **not Claude**. 429 quota = reachable, credits empty — keep optional.
- optional Mac speakers (not the seed team; `config set` as primary or advisor): Codex CLI, Claude Code CLI, Antigravity (`agy` / `antigravity`, Gemini CLI fallback), Grok CLI / grok2api, optional `prd-xai`, OpenCode Zen Free. Each supports `transport: http` or `transport: cli`. write_lock still binds yaml `primary.id`.

## Hard rules

- Never commit API keys.
- Advisors never write files and never run shell.
- Review input is **only** brief + matrix + chapter_diff. Never the raw tender (`samples/tender.md`, a 招标 PDF) or the repo. Ingest parses PDFs locally (`prd-ai-battle ingest file.pdf`); advisors never receive the file.
- 响应对照表 columns: 条款 / 是否响应 / 证据页码 / 意见 / 状态. Frozen after `/lock`.
- write_lock is enforced by `python3 -m prd_ai_battle write-check` (source of truth) and `.opencode/plugins/write-lock.js`.
- During discuss, yaml `primary` + `advisors[]` (not hardcoded names) run a **group chat** on **one shared timeline**: round 0 is a parallel opening on the brief; later rounds give every speaker the FULL `timeline[]` plus brief so they can agree, disagree, or ask each other. Repeat until `/lock`. Advisors stay `tools=[]`. write_lock stays closed. User can interrupt (Esc / 停止); partial utterances stay. Do not spawn OpenCode teammate / sidecar panes. One advisor timeout, HTTP fail, **402**, or quota must **skip that speaker** (log the skip); remaining speakers continue (`stream_parallel` isolates errors).
- During review, every configured advisor runs **in parallel**. Input is **only** brief + matrix + chapter_diff. Findings fold into the same labeled timeline. A 402/quota/ping fail skips that advisor; others still review.

## Docker (local only)

`Dockerfile` / `docker-compose.yml` deliver the Chinese TUI on the Mac (`docker compose build && docker compose run --rm prd-ai-battle`). Default CMD is the board, not `discuss --offline`. Container speakers are HTTP (xixi / OpenRouter); Mac CLI binaries stay on the host. No cloud-host deploy. No secrets in git or the image. Do not bind `0.0.0.0` or port `8080`. Do not touch 金融台 containers.

The Mac **window** is `crates/prd-board-macos` (`cargo run` on a Mac): a PTY around `prd-ai-battle` (prefer `.venv`, else `docker compose run`). It must not write drafts; `write-check` stays in Python. Optional read-only 对照表: `prd-ai-battle web` at `http://127.0.0.1:1780` only.

## Drafts

Write bid responses to `.prd-ai-battle/drafts/vN/response.md`.

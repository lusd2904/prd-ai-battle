# prd-ai-battle

This repository **is the product**. The user-facing skin is the Chinese **Textual board**: one shared labeled timeline, yaml speaker colors, phase rail, and who holds `write_lock` always visible. [OpenCode](https://opencode.ai) stays the execute/revise engine (`prd-ai-battle launch` / slash-command plugin) — not a second window. We do not ship an npm plugin, and we do not grow OpenCode teammate panes.

Mac. Clone this repo, save local config, run `prd-ai-battle`. That opens the board. `write_lock` binds to **whatever primary id is in your last-saved yaml**.

```
discuss → locked → execute (primary writes v1)
       → review (brief + matrix + chapter_diff)
       → revise (primary writes v2)
```

## Seed vs local config (you can change everything)

`config.example.yaml` and committed `opencode.json` are **seed/defaults only** (a finance-platform snapshot: `claude-opus-5`, `claude-sonnet-5`, `x-ai/grok-4.6`, xixi / OpenRouter URLs). They are not locked into the runtime.

| File | Git | Role |
| --- | --- | --- |
| `config.example.yaml` | committed | Seed. First `init` / launch copies it. |
| `prd-ai-battle.yaml` | **gitignored** | Last-saved primary, advisors, `base_url`, `api_key_env`. Next launch reads this. |
| `prd-ai-battle.env.example` | committed | Key *names* only (empty values). Copy to `prd-ai-battle.env`. |
| `prd-ai-battle.env` | **gitignored** | Key *values* loaded into the process environment. Never yaml, never git. |
| `prd-ai-battle.opencode.json` | **gitignored** | Generated OpenCode overlay from the yaml so agents/*.md cannot freeze models. |

```bash
prd-ai-battle init                 # copy seed → gitignored prd-ai-battle.yaml
prd-ai-battle config show          # last saved; keys redacted
prd-ai-battle config set --primary-model my-opus --primary-base-url http://127.0.0.1:8000/v1
prd-ai-battle config set --primary-key-env MY_KEY --primary-key '…'
prd-ai-battle config set --advisor-id advisor-grok --model other-grok --base-url https://example.invalid/v1
prd-ai-battle config set --advisor-id advisor-grok --key-env MY_GROK_KEY --key '…'
prd-ai-battle doctor               # resolved URLs; keys are "set"/"missing"
prd-ai-battle ping                 # 8-token POST per provider; keys redacted
```

```bash
cp prd-ai-battle.env.example prd-ai-battle.env   # then fill values; do not commit
```

Edit `prd-ai-battle.yaml` directly if you prefer, then relaunch. Launch always:

1. Loads `prd-ai-battle.env` into the environment (does not override vars you already exported).
2. Reads `prd-ai-battle.yaml` (creates it from seed if missing).
3. Generates `prd-ai-battle.opencode.json` and points OpenCode at it.

`write_lock` allows writes only for the **current yaml `primary.id`**, not for the model name `claude-opus-5`, not for a leftover agent named `primary` if you renamed the lead, and not for a CLI binary name (`claude`, `codex`, …).

## Optional Mac speakers (HTTP and local CLI)

Seed team stays xixi Opus / Sonnet + OpenRouter Grok until you `config set` a speaker. Each optional speaker supports **both** transports:

| Transport | yaml | What runs |
| --- | --- | --- |
| `http` | `base_url` + `api_key_env` | OpenAI-compatible Chat Completions (timeouts, 429/5xx retry, redacted errors) |
| `cli` | `transport: cli` + `command:` | Mac-local binary on `PATH` |

| Speaker | `command` / binaries | HTTP key env (names only) | Notes |
| --- | --- | --- | --- |
| Codex | `codex` | `PRD_CODEX_KEY` or `OPENAI_API_KEY` | Or `opencode auth` / `codex login` (ChatGPT subscription) |
| Claude Code | `claude` | `PRD_CLAUDE_CODE_KEY` or `ANTHROPIC_API_KEY` | Local Claude CLI — **not** the seed xixi HTTP Claude path |
| Antigravity (反重力) | `agy`, then `antigravity` | `PRD_ANTIGRAVITY_KEY` | Gemini CLI `gemini` is the fallback if Antigravity is missing |
| Gemini CLI | `gemini` | `PRD_GEMINI_KEY` or `GEMINI_API_KEY` | Use when `agy` / `antigravity` are not installed |
| Grok local | `grok` | `PRD_AI_GATEWAY_KEY` (grok2api) or `PRD_XAI_KEY` | Local tool: grok2api at `:8000`. Optional official xAI HTTP is `prd-xai`, not OpenRouter |

Missing binary or empty optional env: `prd-ai-battle doctor` / `ping` report `missing` / `skipped_optional`. `init` does not crash. Do not install CLIs on cloud hosts.

```bash
# Point primary at Claude Code CLI (write_lock still follows yaml primary.id)
prd-ai-battle config set --primary-transport cli --primary-command claude --primary-model claude-opus-5

# Same speaker over HTTP (your OpenAI-compat root — not hardcoded)
prd-ai-battle config set --primary-transport http --primary-model claude-opus-5 \
  --primary-base-url https://xixiapi.io/v1 --primary-key-env PRD_SFP_XIXI_KEY

# Add Antigravity / Gemini / Codex / Grok as an advisor
prd-ai-battle config set --add-advisor --advisor-id advisor-agy --transport cli --command antigravity
prd-ai-battle config set --add-advisor --advisor-id advisor-codex --transport cli --command codex
prd-ai-battle config set --advisor-id advisor-grok --transport cli --command grok --model grok-4
```

## Seed team (until you change it)

| Role | Seed agent id | Seed model | Seed `base_url` | Seed key env | Writes |
| --- | --- | --- | --- | --- | --- |
| Lead | `primary` | `claude-opus-5` | `https://xixiapi.io/v1` | `PRD_SFP_XIXI_KEY` | Only in `execute` / `revise` |
| Advisor | `advisor-sonnet` | `claude-sonnet-5` | `https://xixiapi.io/v1` | `PRD_SFP_XIXI_KEY` | Never (`edit`/`shell` deny, `tools=[]`) |
| Advisor | `advisor-grok` | `x-ai/grok-4.6` | `https://openrouter.ai/api/v1` | `PRD_SFP_OPENROUTER_KEY` | Never |
| Backup (optional) | `prd-gateway` | `grok-4.5` (also `grok-composer-2.5-fast`) | `http://127.0.0.1:8000/v1` | `PRD_AI_GATEWAY_KEY` | Never — grok2api, **not Claude**. 429 = reachable, quota empty; keep optional. |

## Session contract

Persisted as `.prd-ai-battle/session.json` (see `schemas/session.schema.json`):

| Field | Meaning |
| --- | --- |
| `phase` | `discuss` \| `locked` \| `execute` \| `review` \| `revise` |
| `primary` | Primary agent id |
| `advisors[]` | Advisor agent ids |
| `brief` | Tender / requirement summary (not the raw file) |
| `matrix` | 响应对照表 |
| `artifact_version` | `v1` / `v2` / … |
| `write_lock` | Artifact writes only when `phase` is `execute` or `revise` **and** the actor equals the current config `primary.id` |

Matrix row columns: **条款** (`clause`) · **是否响应** (`responded`) · **证据页码** (`evidence_page`) · **意见** (`opinion`) · **状态** (`status`). Locked after discuss; cannot edit when locked.

Hard rules:

- Advisors always receive `tools: []` (no tool calls, no writes). OpenCode also sets `edit`/`shell` to deny.
- Review-phase model input is **only** `brief + matrix + chapter_diff`.
- OpenCode permissions are not phase-aware; `prd-ai-battle write-check` + `.opencode/plugins/write-lock.js` enforce write_lock.
- Deploy target is a local Mac + this repo. Do not add cloud-host / PaaS deploy docs or artifacts.

## Install (Mac)

```bash
brew install anomalyco/tap/opencode

git clone https://github.com/lusd2904/prd-ai-battle.git
cd prd-ai-battle

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

prd-ai-battle init
cp prd-ai-battle.env.example prd-ai-battle.env   # fill PRD_SFP_XIXI_KEY / PRD_SFP_OPENROUTER_KEY
prd-ai-battle config set --primary-key '…' --advisor-id advisor-grok --key '…'
# or: export the api_key_env names from the yaml (seed: PRD_SFP_XIXI_KEY / PRD_SFP_OPENROUTER_KEY)

prd-ai-battle ping                 # HTTP probe; backup 429 is not a hard fail
prd-ai-battle                      # 打开产品看板
prd-ai-battle --offline            # 看板离线（模拟模型，无网络）
# or: ./scripts/prd-ai-battle
prd-ai-battle launch               # OpenCode 执行/修订引擎（可选）
```

`prd-ai-battle` opens the board. Seed ids are `primary` + `advisor-sonnet` + `advisor-grok` until you change them. OpenCode is optional and used for `/execute` / `/revise` when you launch the engine.

Then (board keys or OpenCode slash commands):

| Command | What happens |
| --- | --- |
| `/discuss` | Ingest the sample 招标文件 if needed; yaml `primary` + `advisors[]` **group-chat** the **brief**: round 0 parallel opening, later rounds read the full timeline and respond; no writes |
| `/lock` | Freeze the 对照表 → `phase=locked` |
| `/execute` | `phase=execute` — only the **configured primary id** may write `.prd-ai-battle/drafts/v1/response.md` |
| `/review` | Advisors review **brief + matrix + chapter_diff** only |
| `/revise` | `phase=revise` — primary writes the next version |

Do not run this on a cloud VM.

```bash
prd-ai-battle init
prd-ai-battle doctor        # resolved URLs; keys redacted as "set"/"missing"
prd-ai-battle ping          # 8-token POST per provider; 429 on backup = quota empty
prd-ai-battle phase status
prd-ai-battle discuss --offline   # 交叉讨论，一条时间线，无网络
prd-ai-battle export --offline    # 导出标书正文 / 对照表 / 讨论记录
```

## Discuss is a group chat

`/discuss` and `prd-ai-battle discuss` do **not** open OpenCode Agent Teams / sidecar teammate panes. Python is the orchestrator:

1. Reads the **current yaml** `primary` + every `advisors[]` entry (add/remove models there; commands never hardcode seed ids).
2. **Round 0:** parallel opening on the brief (`tools=[]` for advisors). Speakers do not see each other yet.
3. **Later rounds:** every speaker is given the **FULL** current `timeline[]` (labeled `[agent-id · timestamp]`) plus the brief, then replies — agree, disagree, or ask each other.
4. Merges streamed replies into **one timeline** — `.prd-ai-battle/transcript.jsonl` and `session.json`.
5. Repeat until `/lock`. Esc or `停止` cancels an in-flight round; partial utterances stay; no files are written; `write_lock` stays closed.

```bash
prd-ai-battle discuss --offline --workspace .prd-ai-battle
prd-ai-battle discuss --offline --prompt "Lock 等保 and ★ storage first"
```

`--offline` is offline (mock models, no network). It is not a demo mode.

## Ingest a 招标 PDF (Mac)

Parse the tender **on your Mac**. The raw PDF is never sent to advisors. Pipeline:

`PDF → local text (pypdf) → brief (目录 / 评分点 / 废标项) → 对照表 seed`

```bash
cd prd-ai-battle
source .venv/bin/activate
pip install -e ".[dev]"          # pulls pypdf

# text-layer PDF exported from Word / 招标系统 (not a scanned image)
prd-ai-battle ingest ~/Downloads/招标文件.pdf --workspace .prd-ai-battle

# markdown still works
prd-ai-battle ingest samples/tender.md --workspace .prd-ai-battle

prd-ai-battle phase status --workspace .prd-ai-battle
prd-ai-battle                 # 打开看板 — 模型只看摘要
```

Notes:

- This reads the PDF text layer locally. Image-only scans are not OCR'd.
- Extracted text lands in `.prd-ai-battle/requirement.md`; the shared brief is `brief.md` / `brief.json`.
- Discuss still shares the brief, not the file. Review is still **brief + matrix + chapter_diff** only.
- `write_lock` is unchanged: advisors stay `tools=[]`; primary writes only in `execute` / `revise`.

## 看板与离线

产品界面就是看板（`prd-ai-battle` / `prd-ai-battle tui`）。`--offline` 只表示不用网络：

```bash
prd-ai-battle --offline
prd-ai-battle tui --offline
prd-ai-battle export --offline --workspace .prd-ai-battle
prd-ai-battle demo --workspace .prd-ai-battle   # 无界面跑通 discuss→revise
```

## Workspace layout

```
.prd-ai-battle/
  requirement.md
  brief.json
  brief.md
  matrix.json
  review-packet.md      # the only advisor input in review
  transcript.jsonl      # one shared chat (labeled speakers)
  session.json          # SessionState contract + timeline[]
  drafts/v1/response.md
  drafts/v2/response.md
```

## Library

Python is the contract engine and the board orchestrator:

```
src/prd_ai_battle/
  models.py        # Phase, SessionState, matrix columns, ReviewPacket
  state.py         # discuss → locked → execute → review → revise
  write_lock.py    # primary + execute|revise only
  bridge.py        # write-check used by the OpenCode overlay
  phase.py         # slash-command backend
  launch.py        # exec OpenCode as execute/revise engine
  export.py        # dated folder: 标书正文 / 对照表 / transcript / session
  ping.py          # 8-token provider probe (keys redacted)
  ingest.py        # brief extraction (markdown + local PDF)
  store.py         # transcript + session.json
  llm.py           # OpenAI-compatible SSE; advisors get tools: []
  session.py       # group-chat discuss + interrupt
  tui/app.py       # product board (one timeline)
  data/tender.md   # bundled sample
.opencode/
  opencode.json    # providers, agents, commands (app overlay)
  agents/          # primary + two advisors
  commands/        # /discuss /lock /execute /review /revise
  plugins/         # in-repo write_lock hook (not an npm package)
  skills/prd-battle/
opencode.json      # app entry (same product config)
schemas/
  config.schema.json
  session.schema.json
```

Tests:

```bash
pytest
```

`tests/test_write_lock.py` still proves advisors always get `tools: []` and cannot write; primary writes only in `execute`/`revise`.

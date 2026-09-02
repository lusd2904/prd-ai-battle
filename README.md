# prd-ai-battle

This repository **is the product**. [OpenCode](https://opencode.ai) (`sst/opencode`) is the TUI / coding-agent runtime. We do not ship a plugin you install into some other OpenCode project, and we do not grow a from-scratch Textual TUI as the main UX.

Mac only. Clone this repo, install OpenCode, save local config, run `prd-ai-battle`. That launches OpenCode **in this workspace** with write_lock bound to **whatever primary id is in your last-saved yaml**.

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

`write_lock` allows writes only for the **current yaml `primary.id`**, not for the model name `claude-opus-5` and not for a leftover agent named `primary` if you renamed the lead.

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
prd-ai-battle
# or: ./scripts/prd-ai-battle
```

`prd-ai-battle` reads your gitignored yaml, generates the OpenCode overlay, then execs `opencode`. Seed ids are `primary` + `advisor-sonnet` + `advisor-grok` until you change them.

Then:

| Command | What happens |
| --- | --- |
| `/discuss` | Ingest the sample 招标文件 if needed; yaml `primary` + `advisors[]` discuss the **brief** in **one shared chat** (labeled speakers); no writes |
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
prd-ai-battle discuss --offline   # one labeled timeline, no network
```

## Discuss is one shared chat

`/discuss` and `prd-ai-battle discuss` do **not** open OpenCode Agent Teams / sidecar teammate panes. A product-level orchestrator:

1. Reads the **current yaml** `primary` + every `advisors[]` entry (add/remove models there; commands never hardcode seed ids).
2. Fans the discuss prompt out **in parallel** (`tools=[]` for advisors).
3. Merges streamed replies into **one timeline** — `.prd-ai-battle/transcript.jsonl` and the `timeline` array on `session.json`.
4. Prints that stream as labeled bubbles: `[agent-id · HH:MM:SS]`.

It looks like several mouths in a single chat. Each speaker sees prior utterances on that shared timeline (follow-up `/discuss` or `prd-ai-battle discuss --prompt …` rounds include them). OpenCode remains the editor/runtime for `/execute` / `/revise`.

```bash
prd-ai-battle discuss --offline --workspace .prd-ai-battle
prd-ai-battle discuss --offline --prompt "Lock 等保 and ★ storage first"
```

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
prd-ai-battle                 # then /discuss — models see the brief only
```

Notes:

- This reads the PDF text layer locally. Image-only scans are not OCR'd.
- Extracted text lands in `.prd-ai-battle/requirement.md`; the shared brief is `brief.md` / `brief.json`.
- Discuss still shares the brief, not the file. Review is still **brief + matrix + chapter_diff** only.
- `write_lock` is unchanged: advisors stay `tools=[]`; primary writes only in `execute` / `revise`.

## Optional Textual demo

The old Python TUI is **not** the product shell. It remains as an offline demo:

```bash
prd-ai-battle --offline
# or: prd-ai-battle tui --offline
prd-ai-battle demo --workspace .prd-ai-battle
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

## Library (not the UX)

Python stays as the contract engine used by OpenCode commands and the overlay hook:

```
src/prd_ai_battle/
  models.py        # Phase, SessionState, matrix columns, ReviewPacket
  state.py         # discuss → locked → execute → review → revise
  write_lock.py    # primary + execute|revise only
  bridge.py        # write-check used by the OpenCode overlay
  phase.py         # slash-command backend
  launch.py        # exec OpenCode as this product
  ping.py          # 8-token provider probe (keys redacted)
  ingest.py        # brief extraction (markdown + local PDF)
  store.py         # transcript + session.json
  llm.py           # OpenAI-compatible SSE; advisors get tools: []
  session.py       # shared-timeline orchestrator (also used by --offline)
  tui/app.py       # optional Textual demo (one chat pane)
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

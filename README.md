# prd-ai-battle

This repository **is the product**. [OpenCode](https://opencode.ai) (`sst/opencode`) is the TUI / coding-agent runtime. We do not ship a plugin you install into some other OpenCode project, and we do not grow a from-scratch Textual TUI as the main UX.

Mac only. Clone this repo, install OpenCode, export keys, run `prd-ai-battle`. That launches OpenCode **in this workspace** with our agents, slash commands, and write_lock.

```
discuss → locked → execute (primary writes v1)
       → review (brief + matrix + chapter_diff)
       → revise (primary writes v2)
```

## Team (one lead + two advisors)

| Role | OpenCode agent | Model | Provider | Key env | Writes |
| --- | --- | --- | --- | --- | --- |
| Lead | `primary` | `claude-opus-5` | `https://xixiapi.io/v1` | `PRD_SFP_XIXI_KEY` | Only in `execute` / `revise` |
| Advisor | `advisor-sonnet` | `claude-sonnet-5` | `https://xixiapi.io/v1` | `PRD_SFP_XIXI_KEY` | Never (`edit`/`shell` deny, `tools=[]`) |
| Advisor | `advisor-grok` | `x-ai/grok-4.6` | `https://openrouter.ai/api/v1` | `PRD_SFP_OPENROUTER_KEY` | Never |

Optional backup (currently may 429 on credits): `http://127.0.0.1:8000/v1` + `PRD_AI_GATEWAY_KEY`.

**Never put API keys in git.** Example yaml/json interpolate env vars only.

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
| `write_lock` | Artifact writes only when `phase` is `execute` or `revise` **and** the actor is `primary` |

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

export PRD_SFP_XIXI_KEY=...
export PRD_SFP_OPENROUTER_KEY=...
# optional backup:
# export PRD_AI_GATEWAY_KEY=...
# export PRD_AI_GATEWAY_URL=http://127.0.0.1:8000/v1

prd-ai-battle
# or: ./scripts/prd-ai-battle
```

`prd-ai-battle` execs `opencode` in this repo (the product overlay). You should see `primary` plus `advisor-sonnet` and `advisor-grok`.

Then:

| Command | What happens |
| --- | --- |
| `/discuss` | Ingest the sample 招标文件 if needed; all three models discuss the **brief** in parallel; no writes |
| `/lock` | Freeze the 对照表 → `phase=locked` |
| `/execute` | `phase=execute` — only `primary` may write `.prd-ai-battle/drafts/v1/response.md` |
| `/review` | Advisors review **brief + matrix + chapter_diff** only |
| `/revise` | `phase=revise` — primary writes the next version |

Tab cycles primary agents. `@advisor-sonnet` / `@advisor-grok` invoke teammates. Do not run this on a cloud VM.

Copy the example Python config if you also want the library CLI:

```bash
prd-ai-battle init          # config.example.yaml → ./prd-ai-battle.yaml
prd-ai-battle doctor        # resolved URLs; keys redacted as "set"/"missing"
prd-ai-battle phase status
```

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
  transcript.jsonl
  session.json          # SessionState contract
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
  ingest.py        # brief extraction
  store.py         # transcript + session.json
  llm.py           # OpenAI-compatible SSE; advisors get tools: []
  session.py       # orchestration (also used by --offline)
  tui/app.py       # optional Textual demo
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

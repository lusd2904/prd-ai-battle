# prd-ai-battle

Local TUI (Python + [Textual](https://textual.textualize.io/)) for **multi-model collaborative drafting**. Runs on your **Mac** (or any local machine) against **this GitHub repo**. There is no cloud host and this project does not include deploy artifacts.

You paste a long requirement (招标文件 / PRD). Configured LLM advisors discuss it in **one shared chat**. You lock a **响应对照表**. Only then the designated **primary** may write artifacts — and only in `execute` / `revise`. Advisors review `brief + matrix + chapter_diff` only.

```
discuss → locked → execute (primary writes v1)
       → review (brief + matrix + chapter_diff)
       → revise (primary writes v2)
```

All session state lives in a workspace directory on disk (default `.prd-ai-battle/`).

## Session contract

These fields are required on `SessionState` (see `schemas/session.schema.json`):

| Field | Meaning |
| --- | --- |
| `phase` | `discuss` \| `locked` \| `execute` \| `review` \| `revise` |
| `primary` | Primary model id |
| `advisors[]` | Advisor model ids |
| `brief` | Tender / requirement summary (not the raw file) |
| `matrix` | 响应对照表 |
| `artifact_version` | `v1` / `v2` / … |
| `write_lock` | Artifact writes only when `phase` is `execute` or `revise` **and** the actor is `primary` |

Matrix row columns: **条款** (`clause`) · **是否响应** (`responded`) · **证据页码** (`evidence_page`) · **意见** (`opinion`) · **状态** (`status`).

Hard rules:

- Advisors always receive `tools: []` (no tool calls, no writes).
- Review-phase model input is **only** `brief + matrix + chapter_diff`.
- Deploy target is local Mac + this repo. Do not add cloud-host / PaaS deploy docs or artifacts.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# first run — mock models, no API keys
prd-ai-battle --offline
```

In the TUI:

| Key | Action |
| --- | --- |
| `L` | Load the bundled sample 招标文件 and extract a shared brief |
| `D` | Discuss — all models stream in parallel (`tools: []`, no writes) |
| Enter on a 对照表 row | Cycle 是否响应 (`no` → `partial` → `yes` → `deviation`) |
| `C` | Lock the 对照表 → `phase=locked` (writes still blocked) |
| `E` | `phase=execute` — primary writes `drafts/v1/response.md` |
| `R` | `phase=review` — advisors get brief + matrix + chapter_diff |
| `V` | `phase=revise` — primary writes `drafts/v2/response.md` |
| `/` | Focus the discuss prompt (Escape returns to the matrix) |
| `Q` | Quit |

The left pane has Requirement / Brief / 对照表 / **State** (live contract fields). A phase rail under the header tracks the five official phases.

Headless offline pipeline:

```bash
prd-ai-battle demo --workspace .prd-ai-battle
```

Tests:

```bash
pytest
```

## Live models (local multi-key gateway)

No vendor or tunnel hostname is hardcoded. `base_url` and `api_key` come from the config file and environment variables. The default is **your local multi-key gateway** on loopback:

```bash
prd-ai-battle init
export PRD_AI_GATEWAY_URL=http://127.0.0.1:4000/v1   # optional; this is already the default
export PRD_AI_GATEWAY_KEY=...                        # key your local gateway expects
prd-ai-battle --config prd-ai-battle.yaml
prd-ai-battle doctor --config prd-ai-battle.yaml     # prints resolved URLs; key redacted
```

```yaml
gateway:
  base_url: ${PRD_AI_GATEWAY_URL:-http://127.0.0.1:4000/v1}
  api_key: ${PRD_AI_GATEWAY_KEY:-}

primary:
  id: primary
  model: gpt-4o          # whatever id the gateway routes
```

Per-model `base_url` / `api_key` / `api_key_env` override the shared gateway. An optional external tunnel is configured the same way — only in **your** yaml or env, never in this repository.

Discussion opens **one SSE stream per model**. Advisor requests always send `"tools": []`.

Zero-config (`prd-ai-battle` with no file) boots **offline mocks**.

## Workspace layout

```
.prd-ai-battle/
  requirement.md
  brief.json
  brief.md
  matrix.json
  transcript.jsonl
  session.json          # SessionState contract
  drafts/v1/response.md
  drafts/v2/response.md
```

## CLI

```
prd-ai-battle                 # TUI (offline mocks if no config)
prd-ai-battle --offline       # force mocks
prd-ai-battle --requirement samples/tender.md
prd-ai-battle demo --workspace .prd-ai-battle
prd-ai-battle init            # copy example YAML to ./prd-ai-battle.yaml
prd-ai-battle doctor          # resolved gateway base_url (key redacted)
prd-ai-battle screenshot -o tui.svg
```

## Project map

```
src/prd_ai_battle/
  models.py        # Phase, SessionState, matrix columns, ReviewPacket
  state.py         # discuss → locked → execute → review → revise
  write_lock.py    # primary + execute|revise only
  ingest.py        # brief extraction
  store.py         # transcript + session.json
  llm.py           # OpenAI-compatible SSE; advisors get tools: []
  session.py       # orchestration
  tui/app.py       # Textual UI
  data/tender.md   # bundled sample
schemas/
  config.schema.json
  session.schema.json
```

This is a **usable local skeleton**. It does not yet do tool-calling loops, PDF ingest, or multi-file repo edits, and it is not packaged for any cloud host.

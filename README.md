# prd-ai-battle

Local-first TUI (Python + [Textual](https://textual.textualize.io/)) for **multi-model collaborative drafting**.

You paste a long requirement (招标文件 / PRD). Configured LLM advisors discuss it in **one shared chat**. You lock a **响应对照表** (compliance matrix). Only then the designated **primary** model may write artifacts. Advisors review against the brief + matrix + chapter diffs — never a repo dump — and the primary revises.

```
ingest → discuss (read-only) → confirm / lock 对照表 → primary writes v1
      → review (brief + matrix + diffs only) → primary writes v2
```

No web UI. Nothing is deployed. All state lives in a workspace directory on disk.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# always-works first run (mock models, no API keys)
prd-ai-battle --offline
```

In the TUI:

| Key | Action |
| --- | --- |
| `L` | Load the bundled sample 招标文件 and extract a shared brief |
| `D` | Discuss round — all models stream in parallel (no filesystem writes) |
| Enter on a 对照表 row | Cycle 是否响应 (`no` → `partial` → `yes` → `deviation`) |
| `C` | Lock the 对照表 → confirm phase; primary may now write |
| `E` | Primary execute — writes `drafts/v1/response.md` |
| `R` | Advisor review stub (brief + matrix + section diffs only) |
| `V` | Primary revise → `drafts/v2/response.md` |
| `Q` | Quit |

The bottom input line also starts a discuss round with an optional prompt.

Headless offline pipeline (same success path, no TUI):

```bash
prd-ai-battle demo --workspace .prd-ai-battle
```

Tests:

```bash
pytest
```

## Live models (OpenAI-compatible)

```bash
prd-ai-battle init
# edit prd-ai-battle.yaml, then:
export OPENAI_API_KEY=...
export DEEPSEEK_API_KEY=...   # if you configured that advisor
prd-ai-battle --config prd-ai-battle.yaml
```

Every model is a Chat Completions endpoint (`base_url` + `api_key` via env var + `model` id). One is `primary`; the rest are `advisors[]`. Discussion opens **one SSE stream per model** and labels each bubble with model id + timestamp.

## Config

See [`config.example.yaml`](config.example.yaml) and the JSON Schema at [`schemas/config.schema.json`](schemas/config.schema.json).

```yaml
workspace: .prd-ai-battle
offline: false

primary:
  id: primary
  base_url: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
  api_key_env: OPENAI_API_KEY
  model: gpt-4o
  temperature: 0.3

advisors:
  - id: advisor-a
    base_url: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
    api_key_env: OPENAI_API_KEY
    model: gpt-4o-mini
  - id: advisor-b
    base_url: ${DEEPSEEK_BASE_URL:-https://api.deepseek.com/v1}
    api_key_env: DEEPSEEK_API_KEY
    model: deepseek-chat
```

Zero-config (`prd-ai-battle` with no file) boots **offline mocks** so the skeleton is always runnable.

## Hard rules this scaffold enforces

1. **Discuss** — every model is read-only. Write tools are not advertised. The write-lock rejects any filesystem write.
2. **Confirm** — the user locks the 响应对照表 (`条款 → 是否响应 → 证据页码 → 意见`). Only after that lock may the primary write.
3. **Review** — advisors receive **only** the extracted brief, the locked matrix, and chapter/section diffs. Not the raw tender, not the workspace tree.
4. **Write-lock** — advisors never get write tools, even after lock. Path traversal out of `drafts/vN/` is rejected.

Long documents are **ingested** into a shared brief (目录 / 评分点 / 废标项 / ★ must-respond). That brief is what models see.

## Workspace layout

```
.prd-ai-battle/
  requirement.md
  brief.json
  brief.md
  matrix.json
  transcript.jsonl
  session.json
  drafts/v1/response.md
  drafts/v2/response.md
```

## TUI layout

- **Left** — Requirement / Brief / 对照表 tabs
- **Right** — labeled streaming bubbles (one per model, true parallel)
- **Status** — phase, lock, draft version, model ids

## CLI

```
prd-ai-battle                 # TUI (offline mocks if no config)
prd-ai-battle --offline       # force mocks
prd-ai-battle --requirement samples/tender.md
prd-ai-battle demo            # full offline pipeline → JSON summary
prd-ai-battle init            # copy example YAML to ./prd-ai-battle.yaml
prd-ai-battle screenshot -o tui.svg
```

## Project map

```
src/prd_ai_battle/
  config.py        # YAML + ${ENV:-default}
  models.py        # Brief, ComplianceMatrix, Phase, ReviewPacket
  state.py         # discuss → confirm → review
  write_lock.py    # primary-only ArtifactWriter
  ingest.py        # brief extraction
  store.py         # transcript + versions
  llm.py           # OpenAI-compatible SSE + MockChatClient
  session.py       # orchestration
  tui/app.py       # Textual UI
  data/tender.md   # bundled sample 招标文件
```

This is a **usable skeleton**: the state machine, write-lock, persistence, mock/live client, and TUI are real. It does not yet do tool-calling loops, PDF ingest, or multi-file repo edits.

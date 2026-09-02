# prd-board-macos

macOS window for **prd-ai-battle**. The window is a **PTY shell** around the product Textual TUI — not a second write stack.

On a Mac, from the repo root or this crate:

```bash
cd crates/prd-board-macos
cargo run
```

Optional flags:

```bash
cargo run -- --offline          # pass through to the TUI
cargo run -- --matrix           # open/print http://127.0.0.1:1780
cargo run -- --serve-matrix     # host `prd-ai-battle web` + open the URL
cargo run -- --docker           # force `docker compose run --rm prd-ai-battle`
```

## How it finds the TUI

1. `PRD_BOARD_BIN` if set
2. Host **`.venv/bin/prd-ai-battle`** (preferred)
3. `prd-ai-battle` on `PATH`
4. Documented fallback: `docker compose run --rm prd-ai-battle`

Linux container speakers stay HTTP. Mac CLI binaries (`codex` / `claude` / `agy` / `grok`) stay on the host.

## write_lock

This crate **does not write drafts**. Artifact writes stay in the Python process and must pass `prd-ai-battle write-check`. Advisors still get `tools: []`. After `/lock`, clause text is not editable from this app (no second 对照表 editor).

## Optional 对照表 view

`http://127.0.0.1:1780` only. Never `0.0.0.0`, never port `8080`. Do not collide with 金融台 (`12580`, `3000`, `8008`, `8000`).

```bash
prd-ai-battle web    # binds 127.0.0.1:1780
```

No cloud-host deploy. No secrets in this crate.

"""The Mac PTY crate is a shell, not a second write stack."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "crates" / "prd-board-macos"


def _crate_text() -> str:
    parts = [p.read_text(encoding="utf-8") for p in CRATE.rglob("*") if p.suffix in {".rs", ".md", ".toml"}]
    return "\n".join(parts)


def test_crate_exists_and_documents_mac_cargo_run():
    assert (CRATE / "Cargo.toml").is_file()
    assert (CRATE / "src" / "main.rs").is_file()
    readme = (CRATE / "README.md").read_text(encoding="utf-8")
    assert "cargo run" in readme
    assert "write-check" in readme
    assert "127.0.0.1:1780" in readme
    assert "0.0.0.0" in readme  # forbidden, documented
    assert "8080" in readme


def test_crate_never_writes_drafts_itself():
    text = _crate_text()
    assert "write-check" in text
    assert "app_may_write_draft" in text
    assert "fs::write" not in (CRATE / "src" / "pty_host.rs").read_text(encoding="utf-8")
    assert "drafts/v" not in (CRATE / "src" / "pty_host.rs").read_text(encoding="utf-8")
    main = (CRATE / "src" / "main.rs").read_text(encoding="utf-8")
    assert "write_all" not in main or "PTY" in main
    assert "docker compose run" in text or "compose run" in text


def test_crate_freezes_clause_edit_after_lock():
    policy = (CRATE / "src" / "policy.rs").read_text(encoding="utf-8")
    assert "clause_text_editable" in policy
    assert "locked" in policy
    assert "fn app_may_write_draft() -> bool" in policy


def test_crate_bind_is_loopback_1780_not_8080():
    text = _crate_text()
    assert "127.0.0.1" in text
    assert "1780" in text
    policy = (CRATE / "src" / "policy.rs").read_text(encoding="utf-8")
    assert 'MATRIX_PORT: u16 = 1780' in policy
    assert "0.0.0.0" in policy
    assert "8080" in policy


def test_no_secrets_in_crate():
    text = _crate_text()
    assert "sk-" not in text
    assert "PRD_SFP_XIXI_KEY=" not in text
    assert "Bearer " not in text

//! Product rules the Mac window must not loosen.
//!
//! The window is a PTY shell. It has no draft writer and no 对照表 editor.
//! After `/lock`, clause text is frozen — this crate must not offer an edit path.

/// Phases where the 对照表 is frozen (product: locked after `/lock`).
pub const LOCKED_OR_LATER: &[&str] = &["locked", "execute", "review", "revise"];

/// The Mac app never writes `.prd-ai-battle/drafts/` itself.
pub fn app_may_write_draft() -> bool {
    false
}

/// Advisors never write. The app is not an advisor and not the primary writer.
pub fn app_is_writer_actor() -> bool {
    false
}

/// Clause text (条款) may be edited only while still discussing and unlocked.
/// After lock the TUI already refuses row edits; this crate must not add another editor.
pub fn clause_text_editable(phase: &str, matrix_locked: bool) -> bool {
    if matrix_locked {
        return false;
    }
    phase == "discuss"
}

pub fn phase_is_locked_or_later(phase: &str) -> bool {
    LOCKED_OR_LATER.contains(&phase)
}

/// Bind for the optional read-only matrix view. Never 0.0.0.0, never 8080.
pub const MATRIX_HOST: &str = "127.0.0.1";
pub const MATRIX_PORT: u16 = 1780;

pub fn allowed_matrix_bind(host: &str, port: u16) -> bool {
    matches!(host, "127.0.0.1" | "localhost") && port == MATRIX_PORT
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn never_writes_drafts() {
        assert!(!app_may_write_draft());
        assert!(!app_is_writer_actor());
    }

    #[test]
    fn freeze_clause_after_lock() {
        assert!(clause_text_editable("discuss", false));
        assert!(!clause_text_editable("discuss", true));
        for phase in LOCKED_OR_LATER {
            assert!(!clause_text_editable(phase, true));
            assert!(!clause_text_editable(phase, false));
        }
    }

    #[test]
    fn matrix_view_is_localhost_1780_only() {
        assert!(allowed_matrix_bind("127.0.0.1", 1780));
        assert!(!allowed_matrix_bind("0.0.0.0", 1780));
        assert!(!allowed_matrix_bind("127.0.0.1", 8080));
        assert!(!allowed_matrix_bind("127.0.0.1", 8000));
        assert!(!allowed_matrix_bind("127.0.0.1", 3000));
        assert!(!allowed_matrix_bind("127.0.0.1", 12580));
        assert!(!allowed_matrix_bind("127.0.0.1", 8008));
    }
}

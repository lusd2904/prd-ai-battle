//! macOS board client: a PTY shell around `prd-ai-battle`.
//!
//! This crate does **not** write drafts, mutate 对照表 clause text after lock,
//! or re-implement write_lock. Artifact writes stay in the Python process and
//! must pass `prd-ai-battle write-check`.

pub mod matrix_link;
pub mod policy;
pub mod pty_host;
pub mod resolve;
pub mod write_gate;

pub use matrix_link::{MATRIX_URL, open_matrix_url};
pub use policy::{app_may_write_draft, clause_text_editable};
pub use resolve::{Launch, LaunchKind, find_repo_root, resolve_launch};
pub use write_gate::{WriteCheckRequest, write_check_argv};

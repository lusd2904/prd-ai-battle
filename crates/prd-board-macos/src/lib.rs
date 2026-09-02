//! macOS board client: a PTY shell around `prd-ai-battle`.
//!
//! This crate does **not** write drafts, mutate 对照表 clause text after lock,
//! or re-implement write_lock. Artifact writes stay in the Python process and
//! must pass `prd-ai-battle write-check`.

pub mod matrix_link;
pub mod picker;
pub mod policy;
pub mod pty_host;
pub mod resolve;
pub mod workspace;
pub mod write_gate;

pub use matrix_link::{open_matrix_url, MATRIX_URL};
pub use picker::pick_workspace_folder;
pub use policy::{app_may_write_draft, clause_text_editable};
pub use resolve::{find_repo_root, resolve_launch, Launch, LaunchKind};
pub use workspace::{
    bind_chosen_folder, bind_launch_workspace, default_picker_directory, resolve_workspace,
    with_workspace_arg, write_escapes_workspace, WorkspaceChoice, WorkspaceError,
};
pub use write_gate::{write_check_argv, WriteCheckRequest};

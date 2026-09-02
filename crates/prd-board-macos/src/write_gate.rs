//! All filesystem artifact writes go through the Python `write-check`.
//!
//! This crate never calls `fs::write` on drafts. If a future hook needs to
//! *ask* whether a write is allowed, it must spawn the product CLI.

use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WriteCheckRequest {
    pub actor: String,
    pub tool: String,
    pub path: String,
}

impl WriteCheckRequest {
    pub fn new(actor: impl Into<String>, tool: impl Into<String>, path: impl Into<String>) -> Self {
        Self {
            actor: actor.into(),
            tool: tool.into(),
            path: path.into(),
        }
    }
}

/// argv for `prd-ai-battle write-check`. The Mac app does not write the file.
pub fn write_check_argv(bin: &Path, req: &WriteCheckRequest) -> Vec<String> {
    write_check_argv_for(bin, req, None)
}

/// Same as [`write_check_argv`], scoped to the chosen workspace when known.
pub fn write_check_argv_for(
    bin: &Path,
    req: &WriteCheckRequest,
    workspace: Option<&Path>,
) -> Vec<String> {
    let mut argv = vec![
        bin.display().to_string(),
        "write-check".to_string(),
        "--actor".to_string(),
        req.actor.clone(),
        "--tool".to_string(),
        req.tool.clone(),
        "--path".to_string(),
        req.path.clone(),
    ];
    if let Some(ws) = workspace {
        argv.push("--workspace".to_string());
        argv.push(ws.display().to_string());
    }
    argv
}

/// Spawn the Python write-check. Never persists a draft from this process.
pub fn run_write_check(
    bin: &Path,
    req: &WriteCheckRequest,
) -> std::io::Result<std::process::Output> {
    let argv = write_check_argv(bin, req);
    let mut cmd = Command::new(&argv[0]);
    cmd.args(&argv[1..]);
    cmd.output()
}

/// Refuse any in-process draft path. Callers must use the Python child instead.
pub fn refuse_in_process_draft_write(path: &Path) -> Result<(), String> {
    let text = path.to_string_lossy();
    if text.contains("drafts") || path.file_name().and_then(|n| n.to_str()) == Some("response.md") {
        return Err(format!(
            "prd-board-macos must not write {text}; use `prd-ai-battle write-check` in the Python process"
        ));
    }
    Ok(())
}

/// Locate the product binary for write-check (same preference as the PTY host).
pub fn product_bin_for_check(resolved: Option<&PathBuf>) -> Option<PathBuf> {
    resolved.cloned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn write_check_uses_python_cli_not_direct_write() {
        let bin = Path::new("/repo/.venv/bin/prd-ai-battle");
        let req = WriteCheckRequest::new("primary", "write", "drafts/v1/response.md");
        let argv = write_check_argv(bin, &req);
        assert_eq!(argv[1], "write-check");
        assert!(argv.contains(&"--actor".to_string()));
        assert!(argv.contains(&"primary".to_string()));
        assert!(!argv
            .iter()
            .any(|a| a == "write-file" && argv[1] != "write-check"));
    }

    #[test]
    fn in_process_draft_write_is_refused() {
        let err = refuse_in_process_draft_write(Path::new(".prd-ai-battle/drafts/v1/response.md"))
            .unwrap_err();
        assert!(err.contains("write-check"));
        assert!(refuse_in_process_draft_write(Path::new("README.md")).is_ok());
    }

    #[test]
    fn advisor_write_check_still_goes_to_python() {
        let req = WriteCheckRequest::new("advisor-sonnet", "write", "drafts/v1/sneaky.md");
        let argv = write_check_argv(Path::new("prd-ai-battle"), &req);
        assert_eq!(argv[1], "write-check");
        assert!(argv.contains(&"advisor-sonnet".to_string()));
    }

    #[test]
    fn write_check_argv_includes_chosen_workspace() {
        let req = WriteCheckRequest::new("primary", "write", "drafts/v1/response.md");
        let ws = Path::new("/tmp/round-matrix");
        let argv = write_check_argv_for(Path::new("prd-ai-battle"), &req, Some(ws));
        assert!(argv
            .windows(2)
            .any(|w| w[0] == "--workspace" && w[1] == ws.display().to_string()));
        assert!(crate::workspace::write_escapes_workspace(
            "/tmp/other-project/drafts/v1/response.md",
            ws
        ));
    }
}

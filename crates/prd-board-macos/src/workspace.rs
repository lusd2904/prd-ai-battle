//! Resolve the project workspace the PTY TUI should open.
//!
//! The chosen folder **is** the project workspace. It is passed to
//! `prd-ai-battle --workspace` (existing CLI). This crate does not keep a
//! second catalog — last-used comes from the product `catalog.json`.

use std::fs;
use std::path::{Component, Path, PathBuf};

use crate::resolve::Launch;

/// Native picker title (NSOpenPanel / rfd on macOS).
pub const PICKER_TITLE: &str = "选择工作区";

/// Product sibling / nested session dir name (see `discover_named_workspaces`).
pub const ROUND_MATRIX: &str = "round-matrix";

const SESSION_FILE: &str = "session.json";
const NESTED_WS: &str = ".prd-ai-battle";
const BOARD_DIR: &str = ".prd-ai-battle-board";
const CATALOG_NAME: &str = "catalog.json";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceChoice {
    Selected(PathBuf),
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceError {
    Cancelled,
}

impl WorkspaceError {
    /// Cancelled picker is a clean exit (not a failure).
    pub fn exit_code(&self) -> i32 {
        match self {
            WorkspaceError::Cancelled => 0,
        }
    }
}

/// Mirror of Python `peek_workspace_dir`: session.json here or under `.prd-ai-battle`.
pub fn peek_workspace_dir(path: &Path) -> Option<PathBuf> {
    if path.join(SESSION_FILE).is_file() {
        return Some(path.to_path_buf());
    }
    let nested = path.join(NESTED_WS);
    if nested.join(SESSION_FILE).is_file() {
        return Some(nested);
    }
    None
}

/// Apply a picker result. Cancelled → clean error (exit 0). Selected → session dir.
pub fn resolve_workspace(choice: WorkspaceChoice) -> Result<PathBuf, WorkspaceError> {
    match choice {
        WorkspaceChoice::Cancelled => Err(WorkspaceError::Cancelled),
        WorkspaceChoice::Selected(path) => Ok(bind_chosen_folder(&path)),
    }
}

/// The chosen folder is the workspace. If it already holds a session (or a
/// nested `.prd-ai-battle` session), open that — do not invent a new layout.
pub fn bind_chosen_folder(path: &Path) -> PathBuf {
    peek_workspace_dir(path).unwrap_or_else(|| path.to_path_buf())
}

/// Directory the folder picker should open on.
///
/// Prefer an existing `round-matrix` session (sibling or `.prd-ai-battle/round-matrix`).
/// Else the last-used catalog workspace. Else the repo root.
pub fn default_picker_directory(repo: &Path) -> PathBuf {
    if let Some(found) = existing_round_matrix(repo) {
        return found;
    }
    if let Some(last) = last_used_workspace(repo) {
        if last.is_dir() {
            return last;
        }
    }
    repo.to_path_buf()
}

/// Named product workspace the picker should land on when it already exists.
pub fn existing_round_matrix(repo: &Path) -> Option<PathBuf> {
    [
        repo.join(ROUND_MATRIX),
        repo.join(NESTED_WS).join(ROUND_MATRIX),
    ]
    .into_iter()
    .find(|cand| cand.is_dir() && peek_workspace_dir(cand).is_some())
}

/// Last-used workspace from the product catalog (not a Rust prefs file).
pub fn last_used_workspace(repo: &Path) -> Option<PathBuf> {
    product_catalog_paths(repo)
        .into_iter()
        .find_map(|catalog| active_workspace_from_catalog(&catalog))
}

fn product_catalog_paths(repo: &Path) -> [PathBuf; 2] {
    [
        repo.join(NESTED_WS).join(BOARD_DIR).join(CATALOG_NAME),
        repo.join(BOARD_DIR).join(CATALOG_NAME),
    ]
}

fn active_workspace_from_catalog(path: &Path) -> Option<PathBuf> {
    let text = fs::read_to_string(path).ok()?;
    let active = json_string_field(&text, "active_id").unwrap_or_default();
    if !active.is_empty() {
        for chunk in text.split("\"id\"") {
            if json_quoted_after_colon(chunk).as_deref() == Some(active.as_str()) {
                if let Some(ws) = json_string_field(chunk, "workspace") {
                    if !ws.is_empty() {
                        return Some(PathBuf::from(ws));
                    }
                }
            }
        }
    }
    json_string_field(&text, "workspace")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
}

fn json_string_field(text: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\"");
    let idx = text.find(&needle)?;
    json_quoted_after_colon(&text[idx + needle.len()..])
}

fn json_quoted_after_colon(text: &str) -> Option<String> {
    let colon = text.find(':')?;
    let rest = text[colon + 1..].trim_start();
    let rest = rest.strip_prefix('"')?;
    let mut out = String::new();
    let mut chars = rest.chars();
    loop {
        match chars.next()? {
            '\\' => match chars.next()? {
                'n' => out.push('\n'),
                't' => out.push('\t'),
                'r' => out.push('\r'),
                'u' => {
                    let hex: String = chars.by_ref().take(4).collect();
                    if let Ok(code) = u32::from_str_radix(&hex, 16) {
                        if let Some(ch) = char::from_u32(code) {
                            out.push(ch);
                        }
                    }
                }
                other => out.push(other),
            },
            '"' => break,
            c => out.push(c),
        }
    }
    Some(out)
}

/// `--workspace PATH` already on the child argv (skip the picker).
pub fn workspace_from_args(args: &[String]) -> Option<PathBuf> {
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--workspace" {
            if let Some(value) = args.get(i + 1) {
                if !value.starts_with('-') {
                    return Some(PathBuf::from(value));
                }
            }
            return None;
        }
        if let Some(rest) = args[i].strip_prefix("--workspace=") {
            if !rest.is_empty() {
                return Some(PathBuf::from(rest));
            }
        }
        i += 1;
    }
    None
}

/// Ensure child argv contains `--workspace <path>` (no second store).
pub fn with_workspace_arg(args: &[String], workspace: &Path) -> Vec<String> {
    let value = workspace.display().to_string();
    let mut out = Vec::with_capacity(args.len() + 2);
    let mut i = 0;
    let mut replaced = false;
    while i < args.len() {
        if args[i] == "--workspace" {
            out.push("--workspace".into());
            if i + 1 < args.len() && !args[i + 1].starts_with('-') {
                out.push(value.clone());
                i += 2;
            } else {
                out.push(value.clone());
                i += 1;
            }
            replaced = true;
            continue;
        }
        if args[i].starts_with("--workspace=") {
            out.push(format!("--workspace={value}"));
            replaced = true;
            i += 1;
            continue;
        }
        out.push(args[i].clone());
        i += 1;
    }
    if !replaced {
        out.push("--workspace".into());
        out.push(value);
    }
    out
}

/// Bind `--workspace` onto an already-resolved launch (cwd stays the repo).
pub fn bind_launch_workspace(launch: &Launch, repo: &Path, workspace: &Path) -> Launch {
    let value = workspace_cli_value(
        repo,
        workspace,
        launch.kind == crate::resolve::LaunchKind::DockerCompose,
    );
    let args = with_workspace_arg(&launch.args, &value);
    Launch {
        kind: launch.kind,
        program: launch.program.clone(),
        args,
        cwd: launch.cwd.clone(),
    }
}

/// Host: absolute path. Docker: repo-relative so `/app` bind mounts see it.
pub fn workspace_cli_value(repo: &Path, workspace: &Path, docker: bool) -> PathBuf {
    if docker {
        if let Ok(rel) = workspace.strip_prefix(repo) {
            if rel.as_os_str().is_empty() {
                return PathBuf::from(".");
            }
            return rel.to_path_buf();
        }
    }
    if workspace.is_absolute() {
        workspace.to_path_buf()
    } else {
        repo.join(workspace)
    }
}

/// True when a write path resolves outside `workspace` (another project's drafts).
pub fn write_escapes_workspace(path: &str, workspace: &Path) -> bool {
    if path.trim().is_empty() {
        return false;
    }
    let raw = Path::new(path);
    let candidate = if raw.is_absolute() {
        raw.to_path_buf()
    } else {
        workspace.join(raw)
    };
    let resolved = normalize_path(&candidate);
    let ws = normalize_path(workspace);
    !resolved.starts_with(&ws)
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(p) => out.push(p.as_os_str()),
            Component::RootDir => out.push(component.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            Component::Normal(c) => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn tmp(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("prd-ws-{name}-{nanos}"));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn write_session(dir: &Path) {
        fs::create_dir_all(dir).unwrap();
        fs::write(dir.join(SESSION_FILE), "{\"phase\":\"locked\"}\n").unwrap();
    }

    #[test]
    fn cancelled_picker_exits_cleanly() {
        let err = resolve_workspace(WorkspaceChoice::Cancelled).unwrap_err();
        assert_eq!(err, WorkspaceError::Cancelled);
        assert_eq!(err.exit_code(), 0);
    }

    #[test]
    fn selected_path_is_used_as_workspace() {
        let root = tmp("selected");
        let chosen = root.join("round-matrix");
        write_session(&chosen.join(".prd-ai-battle"));
        let ws = resolve_workspace(WorkspaceChoice::Selected(chosen.clone())).unwrap();
        assert_eq!(ws, chosen.join(".prd-ai-battle"));
        let args = with_workspace_arg(&["--offline".into()], &ws);
        assert_eq!(args[0], "--offline");
        assert_eq!(args[1], "--workspace");
        assert_eq!(args[2], ws.display().to_string());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn empty_chosen_folder_is_the_workspace() {
        let root = tmp("empty");
        let chosen = root.join("bid-a");
        fs::create_dir_all(&chosen).unwrap();
        let ws = resolve_workspace(WorkspaceChoice::Selected(chosen.clone())).unwrap();
        assert_eq!(ws, chosen);
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn default_prefers_existing_round_matrix() {
        let repo = tmp("rm");
        write_session(&repo.join("round-matrix").join(".prd-ai-battle"));
        assert_eq!(default_picker_directory(&repo), repo.join("round-matrix"));
        let _ = fs::remove_dir_all(&repo);
    }

    #[test]
    fn default_nested_prd_round_matrix() {
        let repo = tmp("nested-rm");
        write_session(&repo.join(".prd-ai-battle").join("round-matrix"));
        assert_eq!(
            default_picker_directory(&repo),
            repo.join(".prd-ai-battle").join("round-matrix")
        );
        let _ = fs::remove_dir_all(&repo);
    }

    #[test]
    fn default_falls_back_to_last_used_catalog_then_repo() {
        let repo = tmp("last");
        assert_eq!(default_picker_directory(&repo), repo);
        let last = repo.join("prior-bid");
        fs::create_dir_all(&last).unwrap();
        let catalog_dir = repo.join(".prd-ai-battle").join(".prd-ai-battle-board");
        fs::create_dir_all(&catalog_dir).unwrap();
        fs::write(
            catalog_dir.join("catalog.json"),
            format!(
                "{{\n  \"active_id\": \"p2\",\n  \"projects\": [\n    {{\"id\": \"p1\", \"name\": \"旧\", \"root\": \"x\", \"workspace\": \"{}/old\"}},\n    {{\"id\": \"p2\", \"name\": \"prior-bid\", \"root\": \"{0}\", \"workspace\": \"{1}\"}}\n  ]\n}}\n",
                repo.display(),
                last.display()
            ),
        )
        .unwrap();
        assert_eq!(default_picker_directory(&repo), last);
        let _ = fs::remove_dir_all(&repo);
    }

    #[test]
    fn write_outside_workspace_is_escape() {
        let mine = PathBuf::from("/tmp/project-a");
        assert!(write_escapes_workspace(
            "/tmp/project-b/drafts/v1/response.md",
            &mine
        ));
        assert!(write_escapes_workspace(
            "../project-b/drafts/v1/response.md",
            &mine
        ));
        assert!(!write_escapes_workspace("drafts/v1/response.md", &mine));
        assert!(!write_escapes_workspace(
            "/tmp/project-a/drafts/v1/response.md",
            &mine
        ));
    }

    #[test]
    fn bind_launch_uses_workspace_flag() {
        let launch = Launch {
            kind: crate::resolve::LaunchKind::HostVenv,
            program: "/repo/.venv/bin/prd-ai-battle".into(),
            args: vec!["--offline".into()],
            cwd: PathBuf::from("/repo"),
        };
        let bound =
            bind_launch_workspace(&launch, Path::new("/repo"), Path::new("/repo/round-matrix"));
        assert!(bound.args.contains(&"--workspace".to_string()));
        assert!(bound.args.contains(&"/repo/round-matrix".to_string()));
        assert_eq!(bound.cwd, PathBuf::from("/repo"));
    }

    #[test]
    fn existing_workspace_arg_skips_rebuild() {
        let args = vec!["--offline".into(), "--workspace".into(), "/tmp/keep".into()];
        assert_eq!(
            workspace_from_args(&args).as_deref(),
            Some(Path::new("/tmp/keep"))
        );
        let next = with_workspace_arg(&args, Path::new("/tmp/other"));
        assert_eq!(next, vec!["--offline", "--workspace", "/tmp/other"]);
    }
}

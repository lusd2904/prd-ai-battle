//! Native macOS folder picker (NSOpenPanel via rfd). Linux tests inject a choice.

use std::path::Path;

use crate::workspace::WorkspaceChoice;
#[cfg(target_os = "macos")]
use crate::workspace::PICKER_TITLE;

/// Show a system "Choose folder" dialog. Cancel → `WorkspaceChoice::Cancelled`.
///
/// On macOS this is `NSOpenPanel` through `rfd`. Other OS builds keep the
/// helper testable without a GUI: they return the default directory.
pub fn pick_workspace_folder(default_dir: &Path) -> WorkspaceChoice {
    pick_workspace_folder_with(default_dir, native_pick)
}

/// Test seam: `picker` is the native dialog (or a stub).
pub fn pick_workspace_folder_with<F>(default_dir: &Path, picker: F) -> WorkspaceChoice
where
    F: FnOnce(&Path) -> Option<std::path::PathBuf>,
{
    match picker(default_dir) {
        Some(path) => WorkspaceChoice::Selected(path),
        None => WorkspaceChoice::Cancelled,
    }
}

#[cfg(target_os = "macos")]
fn native_pick(default_dir: &Path) -> Option<std::path::PathBuf> {
    rfd::FileDialog::new()
        .set_title(PICKER_TITLE)
        .set_directory(default_dir)
        .pick_folder()
}

#[cfg(not(target_os = "macos"))]
fn native_pick(default_dir: &Path) -> Option<std::path::PathBuf> {
    // No NSOpenPanel on Linux CI. `resolve_workspace()` is the test surface.
    Some(default_dir.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workspace::{resolve_workspace, WorkspaceError};
    use std::path::PathBuf;

    #[test]
    fn stub_cancel_is_cancelled_choice() {
        let choice = pick_workspace_folder_with(Path::new("/tmp"), |_| None);
        assert_eq!(choice, WorkspaceChoice::Cancelled);
        assert_eq!(
            resolve_workspace(choice).unwrap_err(),
            WorkspaceError::Cancelled
        );
    }

    #[test]
    fn stub_select_returns_path() {
        let choice =
            pick_workspace_folder_with(Path::new("/tmp"), |start| Some(start.join("round-matrix")));
        assert_eq!(
            choice,
            WorkspaceChoice::Selected(PathBuf::from("/tmp/round-matrix"))
        );
    }
}

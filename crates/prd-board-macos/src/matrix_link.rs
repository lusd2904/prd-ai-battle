//! Optional read-only 对照表 view. Host-only loopback — never 0.0.0.0 / 8080.

use anyhow::Result;

pub const MATRIX_URL: &str = "http://127.0.0.1:1780";

/// Print (and on macOS, `open`) the matrix URL. Does not start a cloud server.
pub fn open_matrix_url() -> Result<()> {
    eprintln!("对照表（只读） {MATRIX_URL}");
    #[cfg(target_os = "macos")]
    {
        let _ = std::process::Command::new("open").arg(MATRIX_URL).status();
    }
    Ok(())
}

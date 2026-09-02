//! PTY host: the window is a shell around the product Textual TUI.
//!
//! Bytes go PTY ↔ current tty. This module never writes workspace files.

use crate::resolve::Launch;
use anyhow::{Context, Result};
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, size};
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use std::io::{self, Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

fn winsize() -> PtySize {
    let (cols, rows) = size().unwrap_or((120, 40));
    PtySize {
        rows,
        cols,
        pixel_width: 0,
        pixel_height: 0,
    }
}

pub fn run_pty(launch: &Launch) -> Result<u32> {
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(winsize())
        .context("open PTY for prd-ai-battle")?;

    let mut cmd = CommandBuilder::new(&launch.program);
    for arg in &launch.args {
        cmd.arg(arg);
    }
    cmd.cwd(&launch.cwd);
    cmd.env("TERM", "xterm-256color");
    cmd.env("PRD_BOARD_PTY", "1");

    let mut child = pair
        .slave
        .spawn_command(cmd)
        .with_context(|| format!("spawn {}", launch.display()))?;
    drop(pair.slave);

    let mut reader = pair.master.try_clone_reader().context("clone PTY reader")?;
    let mut writer = pair.master.take_writer().context("PTY writer")?;
    let running = Arc::new(AtomicBool::new(true));

    enable_raw_mode().ok();
    let raw_guard = RawGuard;

    let flag = running.clone();
    let out_thread = thread::spawn(move || {
        let mut stdout = io::stdout();
        let mut buf = [0u8; 4096];
        while flag.load(Ordering::Relaxed) {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    if stdout.write_all(&buf[..n]).is_err() {
                        break;
                    }
                    let _ = stdout.flush();
                }
                Err(_) => break,
            }
        }
    });

    let flag_in = running.clone();
    let in_thread = thread::spawn(move || {
        let mut stdin = io::stdin();
        let mut buf = [0u8; 1024];
        while flag_in.load(Ordering::Relaxed) {
            match stdin.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    if writer.write_all(&buf[..n]).is_err() {
                        break;
                    }
                    let _ = writer.flush();
                }
                Err(_) => break,
            }
        }
    });

    #[cfg(unix)]
    {
        let master = pair.master;
        let _ = thread::spawn(move || {
            let mut signals = match signal_hook::iterator::Signals::new([signal_hook::consts::SIGWINCH])
            {
                Ok(s) => s,
                Err(_) => return,
            };
            for _ in signals.forever() {
                let _ = master.resize(winsize());
            }
        });
    }

    let status = child.wait().context("wait for prd-ai-battle")?;
    running.store(false, Ordering::Relaxed);
    drop(raw_guard);
    let _ = out_thread.join();
    let _ = in_thread.join();
    Ok(status.exit_code())
}

struct RawGuard;

impl Drop for RawGuard {
    fn drop(&mut self) {
        let _ = disable_raw_mode();
    }
}

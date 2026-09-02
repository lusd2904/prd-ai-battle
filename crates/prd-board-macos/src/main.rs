//! macOS client: a window that is a PTY shell around `prd-ai-battle`.
//!
//! On launch, a native folder picker chooses the project workspace **before**
//! the PTY TUI starts. Prefer the host `.venv` binary. Fall back to
//! `docker compose run --rm prd-ai-battle`. This process does not write drafts.
//! After lock, it has no 对照表 editor.

use anyhow::{Context, Result};
use prd_board_macos::matrix_link::{open_matrix_url, MATRIX_URL};
use prd_board_macos::picker::pick_workspace_folder;
use prd_board_macos::policy::app_may_write_draft;
use prd_board_macos::pty_host::run_pty;
use prd_board_macos::resolve::{find_repo_root, resolve_launch};
use prd_board_macos::workspace::{
    bind_chosen_folder, bind_launch_workspace, default_picker_directory, resolve_workspace,
    with_workspace_arg, workspace_from_args,
};
use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

fn usage() {
    eprintln!(
        "\
prd-board-macos — PTY window around the product Textual TUI

  cargo run -p prd-board-macos
  cargo run -- --offline
  cargo run -- --workspace PATH
  cargo run -- --matrix
  cargo run -- --docker

On launch (macOS): native 选择工作区 folder picker, then the existing TUI
against that folder. `--workspace` skips the picker.

Looks for .venv/bin/prd-ai-battle, then PATH, then:
  docker compose run --rm prd-ai-battle

Does not write drafts. write_lock stays in Python (`prd-ai-battle write-check`).
After /lock, clause text is not editable from this app (no second 对照表 stack).
Optional 对照表: {MATRIX_URL}  (127.0.0.1:1780 only)
"
    );
}

#[derive(Debug, Default)]
struct Opts {
    force_docker: bool,
    bin: Option<PathBuf>,
    open_matrix: bool,
    serve_matrix: bool,
    child_args: Vec<String>,
}

fn parse_args(argv: &[String]) -> Result<Opts> {
    let mut opts = Opts::default();
    let mut i = 0;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                usage();
                std::process::exit(0);
            }
            "--docker" => opts.force_docker = true,
            "--bin" => {
                i += 1;
                opts.bin = Some(PathBuf::from(argv.get(i).context("--bin needs a path")?));
            }
            "--matrix" | "--open-matrix" => opts.open_matrix = true,
            "--serve-matrix" => {
                opts.serve_matrix = true;
                opts.open_matrix = true;
            }
            "--" => {
                opts.child_args.extend(argv[i + 1..].iter().cloned());
                break;
            }
            other => opts.child_args.push(other.to_string()),
        }
        i += 1;
    }
    Ok(opts)
}

fn spawn_matrix_server(bin: &Path, cwd: &Path, workspace: &Path) -> Result<std::process::Child> {
    // Host Python only — Docker 127.0.0.1 inside a container is not the Mac loopback.
    let child = Command::new(bin)
        .args(["web", "--workspace", &workspace.display().to_string()])
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .with_context(|| format!("start {} web (127.0.0.1:1780)", bin.display()))?;
    Ok(child)
}

fn choose_workspace(repo: &Path, child_args: &[String]) -> PathBuf {
    if let Some(explicit) = workspace_from_args(child_args) {
        return bind_chosen_folder(&explicit);
    }
    let start = default_picker_directory(repo);
    match resolve_workspace(pick_workspace_folder(&start)) {
        Ok(path) => path,
        Err(err) => {
            eprintln!("已取消，未打开看板");
            std::process::exit(err.exit_code());
        }
    }
}

fn main() -> Result<()> {
    debug_assert!(!app_may_write_draft());

    let argv: Vec<String> = env::args().skip(1).collect();
    let opts = parse_args(&argv)?;
    let cwd = env::current_dir()?;
    let repo = find_repo_root(&cwd).unwrap_or(cwd);

    let workspace = choose_workspace(&repo, &opts.child_args);

    let child_args = with_workspace_arg(&opts.child_args, &workspace);
    let launch = resolve_launch(&repo, opts.force_docker, opts.bin.as_deref(), &child_args)?;
    let launch = bind_launch_workspace(&launch, &repo, &workspace);

    eprintln!("prd-board-macos: {}", launch.display());
    eprintln!("工作区: {}", workspace.display());
    eprintln!("drafts: Python write-check only (this window does not write).");
    eprintln!("对照表: {MATRIX_URL}");

    let mut web_child = None;
    if opts.serve_matrix {
        match launch.kind {
            prd_board_macos::LaunchKind::DockerCompose => {
                eprintln!(
                    "--serve-matrix needs the host .venv binary so the server can bind 127.0.0.1:1780"
                );
            }
            _ => {
                web_child = Some(spawn_matrix_server(
                    Path::new(&launch.program),
                    &launch.cwd,
                    &workspace,
                )?);
            }
        }
    }
    if opts.open_matrix {
        open_matrix_url()?;
    }

    #[cfg(target_os = "macos")]
    {
        use std::io::IsTerminal;

        if !std::io::stdin().is_terminal() {
            eprintln!("no TTY — opening Terminal.app for the PTY board");
            open_self_in_terminal(&repo, &child_args)?;
            if let Some(mut c) = web_child {
                let _ = c.kill();
            }
            return Ok(());
        }
    }

    let code = run_pty(&launch)?;
    if let Some(mut c) = web_child {
        let _ = c.kill();
    }
    if code != 0 {
        std::process::exit(code as i32);
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn sh_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

#[cfg(target_os = "macos")]
fn open_self_in_terminal(repo: &Path, extra_args: &[String]) -> Result<()> {
    let exe = env::current_exe().context("current exe")?;
    let mut command = format!(
        "cd {} && {}",
        sh_single_quote(&repo.display().to_string()),
        sh_single_quote(&exe.display().to_string())
    );
    for arg in extra_args {
        command.push(' ');
        command.push_str(&sh_single_quote(arg));
    }
    let script =
        format!("tell application \"Terminal\"\n  activate\n  do script \"{command}\"\nend tell");
    Command::new("osascript")
        .arg("-e")
        .arg(script)
        .status()
        .context("open Terminal.app")?;
    Ok(())
}

//! Find the product TUI: host `.venv` first, then PATH, then `docker compose run`.

use anyhow::{bail, Result};
use std::env;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaunchKind {
    HostVenv,
    HostPath,
    DockerCompose,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Launch {
    pub kind: LaunchKind,
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
}

impl Launch {
    pub fn display(&self) -> String {
        let rest = self.args.join(" ");
        if rest.is_empty() {
            format!("{} ({:?})", self.program, self.kind)
        } else {
            format!("{} {} ({:?})", self.program, rest, self.kind)
        }
    }
}

pub fn find_repo_root(start: &Path) -> Option<PathBuf> {
    let mut cur = start.to_path_buf();
    loop {
        let pyproject = cur.join("pyproject.toml");
        let pkg = cur.join("src").join("prd_ai_battle");
        if pyproject.is_file() && pkg.is_dir() {
            return Some(cur);
        }
        if !cur.pop() {
            return None;
        }
    }
}

fn venv_binary(repo: &Path) -> PathBuf {
    repo.join(".venv").join("bin").join("prd-ai-battle")
}

fn is_executable(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .map(|m| m.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        true
    }
}

fn which_prd() -> Option<PathBuf> {
    let path = env::var_os("PATH")?;
    for dir in env::split_paths(&path) {
        let cand = dir.join("prd-ai-battle");
        if is_executable(&cand) {
            return Some(cand);
        }
    }
    None
}

pub fn docker_compose_launch(repo: &Path, child_args: &[String]) -> Launch {
    let mut args = vec![
        "compose".to_string(),
        "run".to_string(),
        "--rm".to_string(),
        "prd-ai-battle".to_string(),
    ];
    args.extend(child_args.iter().cloned());
    Launch {
        kind: LaunchKind::DockerCompose,
        program: "docker".to_string(),
        args,
        cwd: repo.to_path_buf(),
    }
}

pub fn resolve_launch(
    repo: &Path,
    force_docker: bool,
    explicit_bin: Option<&Path>,
    child_args: &[String],
) -> Result<Launch> {
    if let Some(bin) = explicit_bin {
        if !bin.exists() {
            bail!("--bin not found: {}", bin.display());
        }
        return Ok(Launch {
            kind: LaunchKind::HostPath,
            program: bin.display().to_string(),
            args: child_args.to_vec(),
            cwd: repo.to_path_buf(),
        });
    }
    if let Ok(env_bin) = env::var("PRD_BOARD_BIN") {
        let p = PathBuf::from(env_bin);
        if is_executable(&p) {
            return Ok(Launch {
                kind: LaunchKind::HostPath,
                program: p.display().to_string(),
                args: child_args.to_vec(),
                cwd: repo.to_path_buf(),
            });
        }
    }
    if !force_docker {
        let venv = venv_binary(repo);
        if is_executable(&venv) {
            return Ok(Launch {
                kind: LaunchKind::HostVenv,
                program: venv.display().to_string(),
                args: child_args.to_vec(),
                cwd: repo.to_path_buf(),
            });
        }
        if let Some(on_path) = which_prd() {
            return Ok(Launch {
                kind: LaunchKind::HostPath,
                program: on_path.display().to_string(),
                args: child_args.to_vec(),
                cwd: repo.to_path_buf(),
            });
        }
    }
    let compose = repo.join("docker-compose.yml");
    if compose.is_file() {
        return Ok(docker_compose_launch(repo, child_args));
    }
    bail!(
        "no prd-ai-battle binary (looked at .venv/bin and PATH) and no docker-compose.yml in {}. \
         Install the Python package into .venv or build the Docker image.",
        repo.display()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;

    fn touch_exec(path: &Path) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, "#!/bin/sh\nexit 0\n").unwrap();
        let mut perm = fs::metadata(path).unwrap().permissions();
        perm.set_mode(0o755);
        fs::set_permissions(path, perm).unwrap();
    }

    #[test]
    fn prefers_venv_over_docker() {
        let root = std::env::temp_dir().join(format!("prd-board-resolve-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("src/prd_ai_battle")).unwrap();
        fs::write(root.join("pyproject.toml"), "[project]\nname='prd-ai-battle'\n").unwrap();
        fs::write(root.join("docker-compose.yml"), "services: {}\n").unwrap();
        let bin = root.join(".venv/bin/prd-ai-battle");
        touch_exec(&bin);
        let launch = resolve_launch(&root, false, None, &[]).unwrap();
        assert_eq!(launch.kind, LaunchKind::HostVenv);
        assert_eq!(launch.program, bin.display().to_string());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn docker_when_forced_or_no_venv() {
        let root = std::env::temp_dir().join(format!("prd-board-docker-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("src/prd_ai_battle")).unwrap();
        fs::write(root.join("pyproject.toml"), "[project]\nname='prd-ai-battle'\n").unwrap();
        fs::write(root.join("docker-compose.yml"), "services: {}\n").unwrap();
        let launch = resolve_launch(&root, true, None, &["--offline".into()]).unwrap();
        assert_eq!(launch.kind, LaunchKind::DockerCompose);
        assert_eq!(launch.program, "docker");
        assert!(launch.args.starts_with(&[
            "compose".into(),
            "run".into(),
            "--rm".into(),
            "prd-ai-battle".into()
        ]));
        assert_eq!(launch.args.last().unwrap(), "--offline");
        let _ = fs::remove_dir_all(&root);
    }
}

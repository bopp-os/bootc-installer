//! Sandbox plumbing: how this frontend reaches fisherman and the host.
//! Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges).
//!
//! Live media and offline image stores are fisherman's facts now (probe's
//! `live` and `offline`, probe.rs). This module used to find them itself:
//! `bootc status` plus /run/ostree-live and /proc/cmdline for live media,
//! and $TUNA_OFFLINE_STORES and /etc/tuna-installer/offline-stores for the
//! stores. Inside a Flatpak those paths are the runtime's, not the host's.
//! It also wrote the recipe to a 0600 temp file; fisherman now reads it on
//! stdin (`fisherman -`).

use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

pub fn in_flatpak() -> bool {
    Path::new("/.flatpak-info").exists()
}

/// Program + args that run fisherman with privileges. fisherman reads the
/// recipe from stdin (`-`, tuna-os/fisherman#276): the caller writes the
/// JSON to the wrapper's stdin and closes it, so no file holds the
/// passphrase.
///
/// Flatpak runtimes ship no pkexec; escalate host-side. The live ISO
/// symlinks the flatpak-bundled fisherman to /usr/local/bin and installs
/// the polkit policy for it (tunaOS customize-live.sh).
pub fn fisherman_command() -> Vec<String> {
    fisherman_command_for(in_flatpak())
}

/// `fisherman_command` for an explicit sandbox state.
///
/// Under Flatpak, pkexec runs inside a host-side bash rather than straight
/// from `flatpak-spawn --host pkexec ...`. fisherman runs as root, so this
/// process can never signal it; it cancels when its PARENT dies
/// (tuna-os/fisherman#267). Launched directly, that parent was the host's
/// flatpak-session-helper, which nothing here can kill. No redirection:
/// stdin, stdout and stderr all pass through flatpak-spawn.
pub fn fisherman_command_for(flatpak: bool) -> Vec<String> {
    if flatpak {
        vec![
            "flatpak-spawn".into(),
            "--host".into(),
            "bash".into(),
            "-c".into(),
            "pkexec /usr/local/bin/fisherman -; exit $?".into(),
        ]
    } else {
        vec!["sudo".into(), "/usr/local/bin/fisherman".into(), "-".into()]
    }
}

/// Wrap argv so it executes on the host when sandboxed.
pub fn host_command(argv: &[&str]) -> Vec<String> {
    let mut cmd: Vec<String> = Vec::new();
    if in_flatpak() {
        cmd.push("flatpak-spawn".into());
        cmd.push("--host".into());
    }
    cmd.extend(argv.iter().map(|s| s.to_string()));
    cmd
}

/// Best-effort persistence of the fisherman install log, 0600 (it can hold
/// the recovery key), so a failed install can be diagnosed after the wizard
/// closes. Never fails the install: logging the log is not worth failing
/// the install over.
pub fn persist_install_log(log: &str) {
    use std::io::Write;

    let home = std::env::var("HOME").unwrap_or_default();
    let base = std::env::var("XDG_STATE_HOME").unwrap_or_else(|_| format!("{home}/.local/state"));
    let dir = Path::new(&base).join("tuna-installer");
    if let Err(e) = std::fs::create_dir_all(&dir) {
        tracing::warn!("could not create {}: {e}", dir.display());
        return;
    }

    let path = dir.join("install.log");
    let write = || -> std::io::Result<()> {
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .mode(0o600)
            .open(&path)?;
        f.write_all(log.as_bytes())
    };
    if let Err(e) = write() {
        tracing::warn!("could not persist install log to {}: {e}", path.display());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_workdir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "tuna-installer-offline-{}-{}",
            std::process::id(),
            tag
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    // ── sandbox detection / command construction ──────────────────────────────

    #[test]
    fn not_in_flatpak_in_test_environment() {
        // CI and developer machines are not sandboxed; the Flatpak branch of
        // fisherman_command/host_command is exercised by the live-ISO smoke.
        assert!(!in_flatpak());
    }

    #[test]
    fn fisherman_command_escalates_via_sudo_outside_flatpak() {
        assert_eq!(
            fisherman_command(),
            vec!["sudo".to_string(), "/usr/local/bin/fisherman".to_string(), "-".to_string()]
        );
    }

    #[test]
    fn fisherman_command_runs_pkexec_inside_a_host_bash_in_flatpak() {
        // Not `flatpak-spawn --host pkexec`: fisherman's parent would be the
        // host's session helper, and it could never be cancelled.
        assert_eq!(
            fisherman_command_for(true),
            vec![
                "flatpak-spawn",
                "--host",
                "bash",
                "-c",
                "pkexec /usr/local/bin/fisherman -; exit $?",
            ]
        );
    }

    #[test]
    fn flatpak_wrapper_passes_stdin_output_and_status_through() {
        // The wrapper's bash for real (everything after `flatpak-spawn
        // --host`), pkexec stubbed on PATH: what is written to the wrapper's
        // stdin is what fisherman reads, and `-` is its only argument.
        use std::io::Write;
        let dir = temp_workdir("wrapper");
        let bin = dir.join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        let stub = bin.join("pkexec");
        let seen = dir.join("stdin");
        use std::os::unix::fs::PermissionsExt;
        std::fs::write(
            &stub,
            format!(
                "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > {}\necho to-stderr >&2\nexit 7\n",
                seen.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&stub, std::fs::Permissions::from_mode(0o755)).unwrap();
        let argv = fisherman_command_for(true);
        let path = format!("{}:{}", bin.display(), std::env::var("PATH").unwrap_or_default());
        let mut child = std::process::Command::new(&argv[2])
            .args(&argv[3..])
            .env("PATH", path)
            .current_dir(&dir)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(br#"{"encryption":{"type":"luks-passphrase","passphrase":"s3cret"}}"#)
            .unwrap();
        let out = child.wait_with_output().unwrap();
        assert_eq!(out.status.code(), Some(7));
        assert_eq!(String::from_utf8_lossy(&out.stdout), "/usr/local/bin/fisherman|-\n");
        assert_eq!(String::from_utf8_lossy(&out.stderr), "to-stderr\n");
        assert!(std::fs::read_to_string(&seen).unwrap().contains("s3cret"));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn host_command_passes_through_outside_flatpak() {
        assert_eq!(host_command(&["bootc", "status"]), vec!["bootc".to_string(), "status".to_string()]);
        assert_eq!(host_command(&[]), Vec::<String>::new());
    }
}

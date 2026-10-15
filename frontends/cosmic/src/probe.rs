//! Hardware facts from `fisherman probe --json` (shared/probe/README.md).
//!
//! fisherman decides which disks may be installed to, labels their sizes, and
//! answers TPM 2.0 and the RAM/CPU/UEFI requirements. This frontend used to
//! run `lsblk -J` itself, offered every `TYPE == disk` (zram and the live USB
//! included), showed lsblk's size strings, and probed the TPM itself. This
//! module only runs the command and keeps the answer; it filters and formats
//! nothing.

use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::model::DiskInfo;

/// The schema version this reader understands (fisherman/docs/PROBE.md).
pub const PROTOCOL_VERSION: i64 = 1;

/// Test and screenshot seam: a file holding probe output. When set, no
/// process runs. Every frontend honours the same variable.
pub const FAKE_ENV: &str = "BOOTC_INSTALLER_FAKE_PROBE";

/// lsblk and `bootc status`; a hung host helper must not hang the wizard.
const TIMEOUT: Duration = Duration::from_secs(30);

/// What the wizard needs from one probe run.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Facts {
    /// Eligible disks only, in fisherman's order.
    pub disks: Vec<DiskInfo>,
    pub tpm_usable: bool,
    /// fisherman's `system.unmet`: "ram", "cpu", "uefi".
    pub unmet: Vec<String>,
    /// `live.is_live`: the host booted from live media. Only then may the
    /// recipe leave `image` empty, which installs the running system.
    pub is_live: bool,
    /// `live.live_image` when live (the booted image), else "".
    pub live_image: String,
    /// `offline.images`: image refs in the host's offline stores. The stores
    /// are fisherman's: a recipe that leaves additionalImageStores out gets
    /// them.
    pub offline_images: Vec<String>,
}

/// Parses probe output.
pub fn parse(json: &str) -> Result<Facts, String> {
    let root: serde_json::Value = serde_json::from_str(json)
        .map_err(|e| format!("fisherman probe printed invalid JSON: {e}"))?;
    if !root.is_object() {
        return Err("fisherman probe did not print a JSON object".into());
    }
    let version = root.get("protocol_version").and_then(|v| v.as_i64());
    if version != Some(PROTOCOL_VERSION) {
        return Err(format!(
            "fisherman probe protocol_version {version:?} is not {PROTOCOL_VERSION}"
        ));
    }
    let str_field = |v: &serde_json::Value, k: &str| {
        v.get(k).and_then(|s| s.as_str()).unwrap_or("").to_string()
    };
    let disks = root
        .get("disks")
        .and_then(|d| d.as_array())
        .map(|a| a.as_slice())
        .unwrap_or(&[])
        .iter()
        // A missing flag or an unknown excluded_reason means "not eligible".
        .filter(|d| d.get("eligible").and_then(|e| e.as_bool()) == Some(true))
        .map(|d| {
            let path = str_field(d, "path");
            let model = str_field(d, "model");
            DiskInfo {
                title: if model.is_empty() { path.clone() } else { model.clone() },
                path,
                model,
                size_label: str_field(d, "size_label"),
                transport_label: str_field(d, "transport_label"),
                removable: d.get("removable").and_then(|r| r.as_bool()).unwrap_or(false),
            }
        })
        .collect();
    let tpm_usable = root
        .pointer("/tpm/usable")
        .and_then(|u| u.as_bool())
        .unwrap_or(false);
    let unmet = root
        .pointer("/system/unmet")
        .and_then(|u| u.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|s| s.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let is_live = root.pointer("/live/is_live").and_then(|v| v.as_bool()).unwrap_or(false);
    let live_image = if is_live {
        root.pointer("/live/live_image").and_then(|v| v.as_str()).unwrap_or("").to_string()
    } else {
        String::new()
    };
    let offline_images = root
        .pointer("/offline/images")
        .and_then(|u| u.as_array())
        .map(|a| a.iter().filter_map(|s| s.as_str().map(str::to_string)).collect())
        .unwrap_or_default();
    Ok(Facts {
        disks,
        tpm_usable,
        unmet,
        is_live,
        live_image,
        offline_images,
    })
}

/// The unprivileged command: the fisherman the install runs, on the host
/// (`flatpak-spawn --host` when sandboxed). Never pkexec or sudo.
pub fn command(flatpak: bool) -> Vec<String> {
    let mut argv = Vec::new();
    if flatpak {
        argv.extend(["flatpak-spawn".to_string(), "--host".to_string()]);
    }
    argv.extend(["/usr/local/bin/fisherman", "probe", "--json"].map(String::from));
    argv
}

/// Runs the probe, or reads `BOOTC_INSTALLER_FAKE_PROBE`. Blocking: call it
/// off the UI thread. There is no fallback scan; the error says why.
pub fn run() -> Result<Facts, String> {
    if let Ok(fake) = std::env::var(FAKE_ENV) {
        if !fake.is_empty() {
            let text = std::fs::read_to_string(&fake).map_err(|e| format!("{FAKE_ENV}={fake}: {e}"))?;
            return parse(&text);
        }
    }
    let argv = command(crate::offline::in_flatpak());
    let mut child = Command::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("cannot run {}: {e}", argv[0]))?;
    let mut stdout = child.stdout.take().expect("piped");
    let mut stderr = child.stderr.take().expect("piped");
    // Drain both pipes on threads so a chatty probe cannot block on a full
    // pipe while this waits for it to exit.
    let out = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = stdout.read_to_string(&mut s);
        s
    });
    let err = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = stderr.read_to_string(&mut s);
        s
    });
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if start.elapsed() < TIMEOUT => std::thread::sleep(Duration::from_millis(20)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("fisherman probe did not finish within {}s", TIMEOUT.as_secs()));
            }
            Err(e) => return Err(format!("fisherman probe: {e}")),
        }
    };
    let stdout = out.join().unwrap_or_default();
    let stderr = err.join().unwrap_or_default();
    if !status.success() {
        let first = stderr.trim().lines().next().unwrap_or("no message").to_string();
        let code = status.code().map_or("signal".to_string(), |c| c.to_string());
        return Err(format!("fisherman probe failed (exit {code}): {first}"));
    }
    parse(&stdout)
}

/// The welcome page's warning lines for fisherman's unmet requirements:
/// `requirements_title`, then one line per item. Empty when all are met.
pub fn requirements_lines(unmet: &[String]) -> Vec<String> {
    if unmet.is_empty() {
        return Vec::new();
    }
    let b = crate::branding::get();
    let mut lines = vec![b.text("requirements_title")];
    for item in unmet {
        let key = match item.as_str() {
            "ram" => "requirements_ram",
            "cpu" => "requirements_cpu",
            "uefi" => "requirements_uefi",
            _ => continue,
        };
        lines.push(b.text(key));
    }
    lines.retain(|l| !l.is_empty());
    lines
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixtures() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../shared/probe/fixtures")
    }

    /// The same fixtures and expected renderings every frontend is tested
    /// against (shared/probe/README.md).
    #[test]
    fn probe_fixtures_render_like_every_frontend() {
        let dir = fixtures();
        if !dir.is_dir() {
            eprintln!("shared/probe/fixtures is absent; this tree is checked out alone");
            return;
        }
        for name in ["laptop", "container", "vm"] {
            let input = std::fs::read_to_string(dir.join(format!("{name}.json"))).unwrap();
            let want: serde_json::Value = serde_json::from_str(
                &std::fs::read_to_string(dir.join(format!("{name}.expected.json"))).unwrap(),
            )
            .unwrap();
            let facts = parse(&input).unwrap();
            let got: Vec<serde_json::Value> = facts
                .disks
                .iter()
                .map(|d| {
                    serde_json::json!({
                        "path": d.path, "title": d.title, "model": d.model,
                        "size_label": d.size_label, "transport_label": d.transport_label,
                        "removable": d.removable,
                    })
                })
                .collect();
            assert_eq!(serde_json::Value::Array(got), want["disks"], "{name}: disks");
            assert_eq!(serde_json::json!(facts.tpm_usable), want["tpm_usable"], "{name}: tpm");
            assert_eq!(serde_json::json!(facts.unmet), want["unmet"], "{name}: unmet");
            assert_eq!(serde_json::json!(facts.live_image), want["live_image"], "{name}: live image");
            assert_eq!(
                serde_json::json!(facts.offline_images),
                want["offline_images"],
                "{name}: offline images"
            );
        }
    }

    #[test]
    fn requirements_lines_name_each_unmet_item() {
        let b = crate::branding::get();
        let unmet: Vec<String> = ["ram", "cpu", "uefi"].map(String::from).to_vec();
        assert_eq!(
            requirements_lines(&unmet),
            ["requirements_title", "requirements_ram", "requirements_cpu", "requirements_uefi"]
                .map(|k| b.text(k))
                .to_vec()
        );
        assert!(requirements_lines(&[]).is_empty());
    }

    #[test]
    fn parse_rejects_what_it_cannot_read() {
        for text in ["", "not json", "[]", r#"{"protocol_version": 2}"#] {
            assert!(parse(text).is_err(), "{text:?}");
        }
        // An unknown excluded_reason, or no eligible flag, is not offered.
        let facts = parse(
            r#"{"protocol_version":1,"disks":[
                {"path":"/dev/a","eligible":false,"excluded_reason":"new"},
                {"path":"/dev/b"},
                {"path":"/dev/c","eligible":true,"model":"","size_label":"1 TiB"}]}"#,
        )
        .unwrap();
        assert_eq!(facts.disks.len(), 1);
        assert_eq!(facts.disks[0].title, "/dev/c");
    }

    #[test]
    fn command_is_unprivileged_and_on_the_host() {
        assert_eq!(command(false), ["/usr/local/bin/fisherman", "probe", "--json"]);
        assert_eq!(
            command(true),
            ["flatpak-spawn", "--host", "/usr/local/bin/fisherman", "probe", "--json"]
        );
    }
}

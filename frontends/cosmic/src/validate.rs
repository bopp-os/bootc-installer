//! `fisherman validate --json --partial -` and the encryption choices
//! (shared/recipe/README.md).
//!
//! fisherman owns the hostname, filesystem and encryption rules
//! (fisherman/docs/VALIDATE.md). The options page sends its fields here as a
//! partial recipe on stdin, never on argv: the passphrase is one of them, and
//! argv is world-readable in /proc. A problem is shown through the copy key
//! `validate_<code>`. A check that cannot run shows nothing and blocks
//! nothing: the install runs the same rules before it touches a disk.

use std::io::{Read, Write};
use std::process::{Command, Stdio};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use serde::Deserialize;

/// The schema version this reader understands.
pub const PROTOCOL_VERSION: i64 = 1;

/// A problem's copy key is this prefix plus its code (shared/branding).
pub const COPY_PREFIX: &str = "validate_";

/// `--partial` reads nothing from the machine; this only bounds a hung
/// flatpak-spawn.
const TIMEOUT: Duration = Duration::from_secs(10);

/// One problem fisherman reports.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Problem {
    #[serde(default)]
    pub field: String,
    #[serde(default)]
    pub code: String,
    #[serde(default)]
    pub message: String,
}

impl Problem {
    /// The line the page shows: the copy for the code, or fisherman's
    /// English message for a code this build has no copy for.
    pub fn render(&self) -> String {
        let line = if self.code.is_empty() {
            String::new()
        } else {
            crate::branding::get().text(&format!("{COPY_PREFIX}{}", self.code))
        };
        if line.is_empty() {
            self.message.clone()
        } else {
            line
        }
    }
}

/// Parses `validate --json` output.
pub fn parse(json: &str) -> Result<Vec<Problem>, String> {
    #[derive(Deserialize)]
    struct Answer {
        protocol_version: Option<i64>,
        errors: Option<Vec<Problem>>,
    }
    let answer: Answer =
        serde_json::from_str(json).map_err(|e| format!("fisherman validate printed invalid JSON: {e}"))?;
    if answer.protocol_version != Some(PROTOCOL_VERSION) {
        return Err(format!(
            "fisherman validate protocol_version {:?} is not {PROTOCOL_VERSION}",
            answer.protocol_version
        ));
    }
    answer.errors.ok_or_else(|| "fisherman validate printed no errors list".to_string())
}

/// The unprivileged command: the fisherman the install runs, on the host
/// (`flatpak-spawn --host` when sandboxed). Never pkexec or sudo.
pub fn command(flatpak: bool) -> Vec<String> {
    let mut argv = Vec::new();
    if flatpak {
        argv.extend(["flatpak-spawn".to_string(), "--host".to_string()]);
    }
    argv.extend(["/usr/local/bin/fisherman", "validate", "--json", "--partial", "-"].map(String::from));
    argv
}

/// Asks fisherman about `partial`. Blocking: call it off the UI thread.
pub fn check(partial: &serde_json::Value) -> Result<Vec<Problem>, String> {
    check_with(&command(crate::offline::in_flatpak()), partial)
}

/// `check` with the command given (tests).
pub fn check_with(argv: &[String], partial: &serde_json::Value) -> Result<Vec<Problem>, String> {
    let mut child = Command::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("cannot run {}: {e}", argv[0]))?;
    {
        // Written and closed: fisherman reads to EOF.
        let mut stdin = child.stdin.take().expect("piped");
        let _ = stdin.write_all(partial.to_string().as_bytes());
    }
    let mut stdout = child.stdout.take().expect("piped");
    let out = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = stdout.read_to_string(&mut s);
        s
    });
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if start.elapsed() < TIMEOUT => std::thread::sleep(Duration::from_millis(10)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("fisherman validate did not finish within {}s", TIMEOUT.as_secs()));
            }
            Err(e) => return Err(format!("fisherman validate: {e}")),
        }
    };
    let text = out.join().unwrap_or_default();
    match status.code() {
        Some(0) | Some(1) => parse(&text),
        code => Err(format!("fisherman validate failed (exit {code:?})")),
    }
}

/// One encryption type, from fisherman's data/encryption-choices.json.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Choice {
    #[serde(rename = "type")]
    pub enc_type: String,
    pub needs_passphrase: bool,
    pub needs_tpm2: bool,
}

/// The encryption choices in display order: a byte-identical copy of
/// fisherman's data/encryption-choices.json, compiled in
/// (tests/unit/test_encryption_choices.py).
pub fn choices() -> &'static [Choice] {
    static CHOICES: OnceLock<Vec<Choice>> = OnceLock::new();
    CHOICES.get_or_init(|| {
        #[derive(Deserialize)]
        struct Doc {
            choices: Vec<Choice>,
        }
        let doc: Doc = serde_json::from_str(include_str!("encryption-choices.json"))
            .expect("encryption-choices.json is compiled in and tested");
        doc.choices
    })
}

fn choice(enc_type: &str) -> Option<&'static Choice> {
    let enc_type = if enc_type.is_empty() { "none" } else { enc_type };
    choices().iter().find(|c| c.enc_type == enc_type)
}

/// Whether `enc_type` takes a passphrase (needs_passphrase).
pub fn needs_passphrase(enc_type: &str) -> bool {
    choice(enc_type).is_some_and(|c| c.needs_passphrase)
}

/// Whether `enc_type` needs a usable TPM 2.0 (needs_tpm2).
pub fn needs_tpm2(enc_type: &str) -> bool {
    choice(enc_type).is_some_and(|c| c.needs_tpm2)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn goldens() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../fisherman/fisherman/cmd/fisherman/testdata/validate")
    }

    #[test]
    fn every_golden_answer_parses() {
        let dir = goldens();
        if !dir.is_dir() {
            eprintln!("fisherman submodule absent; skipping");
            return;
        }
        let hostname = parse(&std::fs::read_to_string(dir.join("partial-hostname.golden")).unwrap()).unwrap();
        assert_eq!(hostname[0].field, "hostname");
        assert_eq!(hostname[0].code, "hostname_label_hyphen");
        assert_eq!(
            hostname[0].render(),
            crate::branding::get().text("validate_hostname_label_hyphen")
        );
        let valid = parse(&std::fs::read_to_string(dir.join("partial-valid.golden")).unwrap()).unwrap();
        assert!(valid.is_empty());
    }

    #[test]
    fn an_unknown_code_shows_fishermans_message() {
        let p = Problem { field: "hostname".into(), code: "brand_new".into(), message: "say why".into() };
        assert_eq!(p.render(), "say why");
    }

    #[test]
    fn parse_rejects_what_it_cannot_read() {
        for text in ["", "not json", "[]", r#"{"protocol_version":2,"errors":[]}"#, r#"{"protocol_version":1}"#] {
            assert!(parse(text).is_err(), "{text:?}");
        }
    }

    #[test]
    fn command_is_unprivileged_partial_and_on_stdin() {
        assert_eq!(
            command(false),
            ["/usr/local/bin/fisherman", "validate", "--json", "--partial", "-"]
        );
        assert_eq!(command(true)[..2], ["flatpak-spawn", "--host"]);
    }

    #[test]
    fn the_partial_recipe_goes_on_stdin_not_argv() {
        let dir = std::env::temp_dir().join(format!("cosmic-validate-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let fake = dir.join("fisherman");
        let seen = dir.join("stdin");
        std::fs::write(
            &fake,
            format!(
                "#!/bin/sh\ncat > {}\necho \"$@\" > {}.args\n\
                 echo '{{\"protocol_version\":1,\"valid\":false,\"errors\":[{{\"field\":\"encryption.passphrase\",\"code\":\"encryption_passphrase_required\",\"message\":\"m\"}}]}}'\nexit 1\n",
                seen.display(),
                seen.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        let partial = serde_json::json!({"encryption": {"type": "luks-passphrase", "passphrase": "s3cret"}});
        let mut argv = vec![fake.display().to_string()];
        argv.extend(command(false)[1..].iter().cloned());
        let problems = check_with(&argv, &partial).unwrap();
        assert_eq!(problems[0].code, "encryption_passphrase_required");
        let got: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&seen).unwrap()).unwrap();
        assert_eq!(got, partial);
        let args = std::fs::read_to_string(dir.join("stdin.args")).unwrap();
        assert!(!args.contains("s3cret"), "the passphrase reached argv: {args}");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn a_check_that_cannot_run_is_an_error_not_a_verdict() {
        assert!(check_with(&["/nonexistent/fisherman".to_string()], &serde_json::json!({})).is_err());
    }

    #[test]
    fn choices_come_from_the_file() {
        let types: Vec<&str> = choices().iter().map(|c| c.enc_type.as_str()).collect();
        assert_eq!(types, ["none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"]);
        assert!(needs_passphrase("tpm2-luks-passphrase") && !needs_passphrase("tpm2-luks"));
        assert!(needs_tpm2("tpm2-luks") && !needs_tpm2("luks-passphrase") && !needs_tpm2(""));
    }
}

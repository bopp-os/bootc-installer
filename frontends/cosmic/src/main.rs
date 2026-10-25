//! TunaOS installer — a real COSMIC application.
//!
//! This was previously plain `iced` with `.theme(|_| Theme::Dark)` hardcoded.
//! That is why it never looked like a COSMIC app: `libcosmic` was not a
//! dependency at all, so none of the COSMIC design system was linked in. It
//! also did not compile — the source was written against the iced 0.13 API
//! while `Cargo.toml` asked for 0.14, and nothing in CI ever built it.
//!
//! It is now a `cosmic::Application`: COSMIC header bar, `cosmic-theme`
//! palette and spacing, and the cosmic widget set.

mod capture;
mod model;
mod readiness;
mod offline;
mod probe;
mod progress;
mod branding;
mod ui;
mod validate;

use cosmic::app::{Core, Settings, Task};
use cosmic::iced::{Length, Size};
use cosmic::prelude::*;
use cosmic::widget;
use cosmic::iced::futures::{SinkExt, Stream, StreamExt};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command as TokioCommand;

pub use model::{DiskInfo, Recipe, FILESYSTEMS};

pub const APP_ID: &str = "org.tunaos.InstallerCosmic";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let flags = Flags {
        capture: capture::Capture::from_env(),
    };
    if flags.capture.is_some() {
        // Before the first icon lookup, and before any other thread.
        capture::stage_repo_icons();
    }

    let mut settings = Settings::default()
        // COSMIC ships its own icon theme, but the installer also runs on live
        // media that may only have Adwaita. freedesktop-icons falls back
        // through the theme's inherit chain, so naming Adwaita here means the
        // icons resolve in both places instead of silently drawing nothing —
        // which is exactly what the first screenshot run caught.
        .default_icon_theme("Adwaita")
        .size(Size::new(1000.0, 700.0))
        .size_limits(
            cosmic::iced::Limits::NONE
                .min_width(600.0)
                .min_height(480.0),
        );

    // Deterministic captures: the system preference is whatever the CI runner
    // happens to have, which would make the screenshots flap between light and
    // dark. Pin the theme when capturing, follow the user otherwise.
    if flags.capture.is_some() {
        settings = settings.theme(cosmic::theme::Theme::dark());
    }

    cosmic::app::run::<TunaInstaller>(settings, flags)?;
    Ok(())
}

pub struct Flags {
    pub capture: Option<capture::Capture>,
}

// ---------------------------------------------------------------- pages ----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Welcome,
    DiskSelect,
    Options,
    Confirm,
    Installing,
    Done,
}

impl Page {
    /// Wizard order. Also the capture order, so a new page cannot be added
    /// without appearing in the walkthrough.
    pub const ORDER: [Page; 6] = [
        Page::Welcome,
        Page::DiskSelect,
        Page::Options,
        Page::Confirm,
        Page::Installing,
        Page::Done,
    ];

    pub const fn slug(self) -> &'static str {
        match self {
            Page::Welcome => "welcome",
            Page::DiskSelect => "disk",
            Page::Options => "options",
            Page::Confirm => "confirm",
            Page::Installing => "installing",
            Page::Done => "done",
        }
    }

    pub const fn title(self) -> &'static str {
        match self {
            Page::Welcome => "Welcome",
            Page::DiskSelect => "Select a disk",
            Page::Options => "Options",
            Page::Confirm => "Confirm",
            Page::Installing => "Installing",
            Page::Done => "Finished",
        }
    }

    fn index(self) -> usize {
        Page::ORDER.iter().position(|p| *p == self).unwrap_or(0)
    }
}

/// The encryption types offered right now, in display order: fisherman's
/// encryption-choices.json (`validate::choices`, a byte-identical copy
/// compiled in). A `needs_tpm2` type is dropped entirely rather than shown
/// disabled when fisherman says no TPM 2.0 is usable (tunaOS#734): a dropdown
/// entry that produces an unenrollable recipe is worse than one that isn't
/// offered. What each one is called is branding copy
/// (`encryption_<type>_label` / `_description`), read in `ui.rs`.
pub fn available_encryption_choices(has_tpm: bool) -> Vec<&'static str> {
    validate::choices()
        .iter()
        .filter(|c| has_tpm || !validate::needs_tpm2(&c.enc_type))
        .map(|c| c.enc_type.as_str())
        .collect()
}

/// The options page's fields as a partial recipe, for
/// `validate --json --partial -` on stdin (never argv: the passphrase is one
/// of them). The passphrase goes only with a needs_passphrase choice.
fn partial_recipe(r: &Recipe) -> serde_json::Value {
    let mut encryption = serde_json::json!({ "type": r.encryption.enc_type });
    if validate::needs_passphrase(&r.encryption.enc_type) {
        encryption["passphrase"] = serde_json::json!(r.encryption.passphrase);
    }
    serde_json::json!({
        "hostname": r.hostname,
        "filesystem": r.filesystem,
        "btrfsSubvolumes": r.btrfs_subvolumes,
        "encryption": encryption,
    })
}

// -------------------------------------------------------------- messages ----

#[derive(Debug, Clone)]
pub enum Message {
    NextPage,
    BackPage,
    SelectDisk(usize),
    /// `fisherman probe --json` answered (shared/probe/README.md).
    Probed(Result<probe::Facts, String>),
    /// `fisherman validate --json --partial` answered for check number `.0`
    /// (shared/recipe/README.md). An answer for an older check is dropped.
    Validated(u64, Result<Vec<validate::Problem>, String>),
    HostnameChanged(String),
    FilesystemChanged(usize),
    EncryptionChanged(usize),
    PassphraseChanged(String),
    /// The options page's "Confirm passphrase" field.
    PassphraseConfirmChanged(String),
    TogglePassphraseVisible,
    /// The done page's "I have saved my recovery key" box.
    RecoveryAckToggled(bool),
    /// Put the recovery key on the clipboard.
    CopyRecoveryKey,
    StartInstall,
    /// One line of fisherman's stdout, as it arrives.
    ///
    /// run_fisherman() used to be `.output()`: it waited for the process to
    /// exit and handed back everything at once, so the log appeared only when
    /// the install was already over and any progress bar fed from it would
    /// have jumped from nothing to done. Parsing alone would not have given
    /// this frontend a working bar; it needed the output to arrive while the
    /// install is running.
    InstallLine(String),
    InstallFinished(Result<i32, String>),
    Quit,
    /// The done page's Restart: `systemctl reboot` on the host.
    Reboot,
    /// The done page's store link.
    OpenUrl(String),
    /// Capture harness only — never reachable from the UI.
    Capture(capture::Message),
}

/// The options page's own rule: a needs_passphrase choice holds Continue
/// until the passphrase was typed the same twice. Other choices carry no
/// passphrase, so there is nothing to confirm.
fn passphrase_confirmed(enc_type: &str, passphrase: &str, confirm: &str) -> bool {
    !validate::needs_passphrase(enc_type) || passphrase == confirm
}

pub struct TunaInstaller {
    core: Core,
    page: Page,
    /// `Some` (the booted image, possibly "") when fisherman's probe says the
    /// host booted from live media (`live.is_live`); then the recipe leaves
    /// `image` empty and fisherman installs the running system.
    live_image: Option<String>,
    /// fisherman's problems with the options page's fields
    /// (`validate --json --partial`), and the number of the latest check.
    problems: Vec<validate::Problem>,
    validate_seq: u64,
    recipe: Recipe,
    disks: Vec<DiskInfo>,
    selected_disk: Option<usize>,
    install_log: String,
    /// The install's position, parsed from fisherman's protocol
    /// (shared/progress/README.md). Before this the install page showed an
    /// indeterminate bar for the whole install — docs/PARITY.md gap #2.
    progress: progress::Progress,
    install_ok: bool,
    installing: bool,
    passphrase_hidden: bool,
    /// The passphrase typed a second time. Never in the recipe and never
    /// sent to fisherman: matching it is this frontend's only rule
    /// (shared/recipe/README.md), as on KDE and Niri.
    passphrase_confirm: String,
    /// Ticked by the user on the done page once they have written the
    /// recovery key down. It gates Restart (#129).
    recovery_ack: bool,
    /// fisherman's `tpm.usable`. Gates the two `tpm2-*` encryption choices.
    has_tpm: bool,
    /// fisherman's `system.unmet`: the welcome page warns about each one.
    unmet: Vec<String>,
    /// Why there are no disks, when the probe failed. No fallback scan.
    disk_error: Option<String>,
    /// Whether a probe answer (or failure) has arrived yet.
    probed: bool,
    /// `Some` only in capture mode. Its presence is also the hard interlock
    /// that stops the capture harness ever running a real install.
    capture: Option<capture::Capture>,
}

impl TunaInstaller {
    pub fn page(&self) -> Page {
        self.page
    }

    /// True while a recovery key is on screen that the user has not yet
    /// acknowledged (#129). The done page holds Restart until this clears:
    /// leaving that page is what ends the chance to read the key.
    ///
    /// A failed install enrolled nothing, so there is no key to hold for.
    pub fn recovery_key_pending(&self) -> bool {
        progress::holds_restart(
            self.install_ok,
            &self.progress.recovery_key,
            self.recovery_ack,
        )
    }

    pub fn recipe(&self) -> &Recipe {
        &self.recipe
    }
    pub fn disks(&self) -> &[DiskInfo] {
        &self.disks
    }
    pub fn selected_disk(&self) -> Option<usize> {
        self.selected_disk
    }
    pub fn live_image(&self) -> Option<&str> {
        self.live_image.as_deref()
    }
    pub fn install_log(&self) -> &str {
        &self.install_log
    }

    pub fn progress(&self) -> &progress::Progress {
        &self.progress
    }
    pub fn install_ok(&self) -> bool {
        self.install_ok
    }
    pub fn installing(&self) -> bool {
        self.installing
    }
    pub fn passphrase_hidden(&self) -> bool {
        self.passphrase_hidden
    }
    pub fn passphrase_confirm(&self) -> &str {
        &self.passphrase_confirm
    }
    /// The confirmation matches, or the choice takes no passphrase.
    pub fn passphrases_match(&self) -> bool {
        passphrase_confirmed(
            &self.recipe.encryption.enc_type,
            &self.recipe.encryption.passphrase,
            &self.passphrase_confirm,
        )
    }
    pub fn capturing(&self) -> bool {
        self.capture.is_some()
    }
    pub fn has_tpm(&self) -> bool {
        self.has_tpm
    }
    pub fn unmet(&self) -> &[String] {
        &self.unmet
    }
    pub fn disk_error(&self) -> Option<&str> {
        self.disk_error.as_deref()
    }
    pub fn probed(&self) -> bool {
        self.probed
    }

    /// Takes in a probe answer: the disks, TPM, requirements and live media
    /// together.
    fn apply_probe(&mut self, result: Result<probe::Facts, String>) {
        self.probed = true;
        match result {
            Ok(facts) => {
                self.disk_error = None;
                self.has_tpm = facts.tpm_usable;
                self.unmet = facts.unmet;
                // Live media is fisherman's answer. This used to be a
                // `bootc status` of our own plus /run/ostree-live and
                // /proc/cmdline, read inside the Flatpak sandbox.
                if facts.is_live {
                    self.live_image = Some(facts.live_image);
                    self.recipe.image.clear();
                } else {
                    self.live_image = None;
                    if self.recipe.image.is_empty() {
                        self.recipe.image = branding::get().default_image.clone();
                    }
                }
                let keep = self
                    .selected_disk
                    .and_then(|i| self.disks.get(i))
                    .map(|d| d.path.clone());
                self.disks = facts.disks;
                self.selected_disk = keep
                    .and_then(|p| self.disks.iter().position(|d| d.path == p))
                    .or((!self.disks.is_empty()).then_some(0));
            }
            Err(err) => {
                self.disk_error = Some(err);
                self.disks.clear();
                self.selected_disk = None;
            }
        }
        self.recipe.disk = self
            .selected_disk
            .and_then(|i| self.disks.get(i))
            .map(|d| d.path.clone())
            .unwrap_or_default();
    }

    /// fisherman's problem with a field of the options page, if it reported
    /// one: "hostname", or a prefix such as "encryption".
    pub fn problem(&self, field: &str) -> Option<&validate::Problem> {
        self.problems
            .iter()
            .find(|p| p.field == field || p.field.starts_with(&format!("{field}.")))
    }

    /// Whether the Options page is allowed to advance: fisherman knows no
    /// problem with the hostname, the filesystem or the encryption choice
    /// (an empty passphrase is `encryption_passphrase_required`). The rules
    /// are fisherman's; a check that could not run blocks nothing, because
    /// the install runs the same rules before it touches a disk.
    pub fn encryption_ok(&self) -> bool {
        self.problems.is_empty()
    }

    /// Whether Continue is live on the Options page: fisherman's rules
    /// (`encryption_ok`) and the passphrase confirmation, the one rule of
    /// this frontend. A mismatch is caught here, while it can be fixed,
    /// not at the first boot.
    pub fn options_ok(&self) -> bool {
        self.encryption_ok() && self.passphrases_match()
    }

    /// Asks fisherman about the options page after a pause in the typing,
    /// off the UI thread. Never in capture mode: nothing shells out there.
    fn check_fields(&mut self) -> Task<Message> {
        if self.capturing() {
            return Task::none();
        }
        self.validate_seq += 1;
        let seq = self.validate_seq;
        let partial = partial_recipe(&self.recipe);
        Task::perform(
            async move {
                tokio::time::sleep(std::time::Duration::from_millis(300)).await;
                tokio::task::spawn_blocking(move || validate::check(&partial))
                    .await
                    .map_err(|e| format!("Task join error: {e}"))?
            },
            move |r| cosmic::action::app(Message::Validated(seq, r)),
        )
    }

    fn advance(&mut self) -> Option<Page> {
        let next = match self.page {
            Page::Welcome => Page::DiskSelect,
            Page::DiskSelect => Page::Options,
            Page::Options => Page::Confirm,
            Page::Confirm | Page::Installing | Page::Done => return None,
        };
        self.page = next;
        Some(next)
    }

    fn retreat(&mut self) {
        self.page = match self.page {
            Page::Confirm => Page::Options,
            Page::Options => Page::DiskSelect,
            Page::DiskSelect => Page::Welcome,
            other => other,
        };
    }
}

impl cosmic::Application for TunaInstaller {
    type Executor = cosmic::executor::Default;
    type Flags = Flags;
    type Message = Message;

    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, flags: Flags) -> (Self, Task<Message>) {
        let capturing = flags.capture.is_some();

        // Recipe::default() is neutral; the product identity comes from the
        // branding contract (shared/branding/README.md). The default image
        // is what a non-live install writes when nothing else chooses one;
        // the probe clears it on live media (apply_probe).
        let mut recipe = Recipe::default();
        {
            let b = branding::get();
            recipe.distro_id = b.id.clone();
            recipe.hostname = b.default_hostname.clone();
            recipe.image = b.default_image.clone();
        }
        // No additional_image_stores: left out, fisherman exposes the offline
        // stores it finds on the host (tuna-os/fisherman#276).

        let mut app = Self {
            core,
            page: Page::Welcome,
            live_image: None,
            problems: Vec::new(),
            validate_seq: 0,
            recipe,
            selected_disk: None,
            disks: Vec::new(),
            install_log: String::new(),
            progress: progress::Progress::new(branding::name()),
            install_ok: false,
            installing: false,
            passphrase_hidden: true,
            passphrase_confirm: String::new(),
            recovery_ack: false,
            // Until the probe answers: no TPM choices, no warning.
            has_tpm: false,
            unmet: Vec::new(),
            disk_error: None,
            probed: false,
            capture: flags.capture,
        };
        if capturing {
            // The shared laptop fixture, through the same reader. A capture
            // without it would photograph an error, so refuse.
            let facts = capture::fixture_probe();
            if let Err(e) = &facts {
                eprintln!("capture: probe fixture unreadable: {e}");
                std::process::exit(2);
            }
            app.apply_probe(facts);
        }

        // The product name from the branding contract (branding.json, then
        // os-release), never a literal — see `branding`.
        let window_title = format!("{} Installer", branding::name());
        let mut tasks = vec![app.set_window_title(window_title.clone())];
        if app.capture.is_some() {
            tasks.push(capture::begin());
        } else {
            tasks.push(Task::perform(Self::probe(), |r| {
                cosmic::action::app(Message::Probed(r))
            }));
            tasks.push(app.check_fields());
        }
        app.set_header_title(window_title);

        (app, Task::batch(tasks))
    }

    fn header_start(&self) -> Vec<Element<'_, Message>> {
        // The step indicator lives in the COSMIC header bar rather than being
        // drawn by hand in the page body, which is what makes this read as a
        // COSMIC app instead of a generic iced window.
        let spacing = cosmic::theme::active().cosmic().spacing;
        vec![widget::text::caption(format!(
            "Step {} of {} · {}",
            self.page.index() + 1,
            Page::ORDER.len(),
            self.page.title()
        ))
        .apply(widget::container)
        .padding([0, spacing.space_xs])
        .into()]
    }

    fn header_end(&self) -> Vec<Element<'_, Message>> {
        vec![widget::progress_bar::determinate_linear(
            (self.page.index() as f32 + 1.0) / Page::ORDER.len() as f32,
        )
        .width(Length::Fixed(120.0))
        .into()]
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::NextPage => {
                if let Some(Page::DiskSelect) = self.advance() {
                    if !self.capturing() {
                        // Again on entering the page, so a disk plugged in
                        // after start-up appears.
                        return Task::perform(Self::probe(), |r| {
                            cosmic::action::app(Message::Probed(r))
                        });
                    }
                }
                Task::none()
            }
            Message::BackPage => {
                self.retreat();
                Task::none()
            }
            Message::SelectDisk(idx) => {
                if let Some(disk) = self.disks.get(idx) {
                    self.selected_disk = Some(idx);
                    self.recipe.disk = disk.path.clone();
                }
                Task::none()
            }
            Message::Probed(result) => {
                self.apply_probe(result);
                Task::none()
            }
            Message::Validated(seq, result) => {
                if seq == self.validate_seq {
                    self.problems = result.unwrap_or_else(|e| {
                        tracing::warn!("fisherman validate could not run: {e}");
                        Vec::new()
                    });
                }
                Task::none()
            }
            Message::HostnameChanged(h) => {
                self.recipe.hostname = h;
                self.check_fields()
            }
            Message::FilesystemChanged(idx) => {
                if let Some(fs) = FILESYSTEMS.get(idx) {
                    self.recipe.filesystem = (*fs).to_string();
                    self.recipe.btrfs_subvolumes = *fs == "btrfs";
                }
                self.check_fields()
            }
            Message::EncryptionChanged(idx) => {
                // Recompute the same has_tpm-filtered list ui.rs built the
                // dropdown from, so `idx` (a position in THAT list) resolves
                // to the same choice the user actually saw and clicked.
                let choices = available_encryption_choices(self.has_tpm);
                if let Some(choice) = choices.get(idx) {
                    self.recipe.encryption.enc_type = choice.to_string();
                    // Only a needs_passphrase choice carries a passphrase;
                    // clear it for the others so a stale value from a
                    // previous choice can't linger into the recipe.
                    if !validate::needs_passphrase(choice) {
                        self.recipe.encryption.passphrase.clear();
                        self.passphrase_confirm.clear();
                    }
                }
                self.check_fields()
            }
            Message::PassphraseChanged(p) => {
                self.recipe.encryption.passphrase = p;
                self.check_fields()
            }
            Message::PassphraseConfirmChanged(p) => {
                // Not a field fisherman checks, so no validate round-trip.
                self.passphrase_confirm = p;
                Task::none()
            }
            Message::TogglePassphraseVisible => {
                self.passphrase_hidden = !self.passphrase_hidden;
                Task::none()
            }
            Message::RecoveryAckToggled(v) => {
                self.recovery_ack = v;
                Task::none()
            }
            Message::CopyRecoveryKey => {
                cosmic::iced::clipboard::write(self.progress.recovery_key.clone())
            }
            Message::StartInstall => {
                // SAFETY INTERLOCK. Driving the wizard to the progress page
                // must never partition the CI runner's disk. A sibling repo
                // (tuna-installer-xfce) called start_install() from the
                // page-enter hook, so a naive capture would have done exactly
                // that. Here the capture harness sets `page` directly and
                // never emits StartInstall — and if it ever did, this refuses.
                if self.capturing() {
                    tracing::error!("StartInstall ignored: capture mode");
                    return Task::none();
                }
                self.page = Page::Installing;
                self.installing = true;
                self.progress.reset();
                let recipe = self.recipe.clone();
                Task::stream(Self::stream_fisherman(recipe).map(cosmic::action::app))
            }
            Message::InstallLine(line) => {
                // Through the same parser the capture harness drives, so the
                // bar on the screenshot is the bar a real install shows.
                if let Some(shown) = self.progress.consume(&line) {
                    self.install_log.push_str(&shown);
                    self.install_log.push('\n');
                }
                Task::none()
            }
            Message::InstallFinished(result) => {
                self.page = Page::Done;
                self.installing = false;
                match result {
                    Ok(code) => {
                        self.install_ok = code == 0;
                        self.install_log
                            .push_str(&format!("\n=== fisherman exited with code {code} ===\n"));
                    }
                    Err(e) => {
                        self.install_ok = false;
                        self.install_log.push_str(&format!("\n=== Error: {e} ===\n"));
                    }
                }
                offline::persist_install_log(&self.install_log);
                Task::none()
            }
            Message::Quit => {
                std::process::exit(i32::from(!self.install_ok));
            }
            Message::OpenUrl(url) => {
                let argv = offline::host_command(&["xdg-open", &url]);
                if let Some((program, args)) = argv.split_first() {
                    let _ = std::process::Command::new(program).args(args).spawn();
                }
                Task::none()
            }
            Message::Reboot => {
                let argv = offline::host_command(&["systemctl", "reboot"]);
                if let Some((program, args)) = argv.split_first() {
                    let _ = std::process::Command::new(program).args(args).spawn();
                }
                Task::none()
            }
            Message::Capture(msg) => capture::update(self, msg),
        }
    }

    fn view(&self) -> Element<'_, Message> {
        // First frame = the strongest honest "the UI came up" signal libcosmic
        // offers. See readiness.rs: this frontend is the one that proved
        // `flatpak ps` insufficient, by running with no window ever appearing
        // while the smoke check stayed green. Cheap after the first call.
        readiness::stamp_first_frame(APP_ID, self.page.slug());
        ui::view(self)
    }
}

// -------------------------------------------------------- async helpers ----

impl TunaInstaller {
    /// `fisherman probe --json`, off the UI thread (shared/probe/README.md).
    async fn probe() -> Result<probe::Facts, String> {
        tokio::task::spawn_blocking(probe::run)
            .await
            .map_err(|e| format!("Task join error: {e}"))?
    }

    /// Runs fisherman and yields its output a line at a time, then the exit
    /// code.
    ///
    /// This was `.output()`, which waits for the process to exit and returns
    /// everything at once. That was already a problem for the log — the Done
    /// page tells the user "the install log above has the details" and the
    /// log only existed once there was nothing left to watch — and it makes a
    /// progress bar impossible on its own terms: every event would arrive
    /// after the install had finished. Parsing fisherman's protocol was
    /// necessary for a working bar here but not sufficient; the output has to
    /// arrive while the install is running.
    ///
    /// stdout carries the newline-delimited JSON protocol
    /// (shared/progress/README.md); stderr is plain text and is interleaved
    /// into the same stream line by line (see `merged_lines`), which the
    /// parser passes through untouched.
    fn stream_fisherman(recipe: Recipe) -> impl Stream<Item = Message> {
        cosmic::iced::stream::channel(64, async move |mut output| {
            let json = match serde_json::to_string_pretty(&recipe) {
                Ok(json) => json,
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            // flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -'
            // in Flatpak, sudo /usr/local/bin/fisherman - otherwise. The
            // recipe goes to the wrapper's stdin, never to a file: it may
            // hold a passphrase (tuna-os/fisherman#276).
            let cmd = offline::fisherman_command();
            let mut child = match spawn_wrapper(&cmd, json.into_bytes()).await {
                Ok(child) => child,
                Err(e) => {
                    let _ = output
                        .send(Message::InstallFinished(Err(format!(
                            "Failed to run fisherman: {e}"
                        ))))
                        .await;
                    return;
                }
            };

            // Both pipes at once. stdout used to be read to EOF before stderr
            // was touched, so a fisherman that filled the stderr pipe (64 KiB)
            // blocked on write while this waited for stdout to end: both
            // processes hung for good. stderr still matters — fisherman writes
            // its failure summary there.
            let mut lines = merged_lines(child.stdout.take(), child.stderr.take());
            while let Some(line) = lines.recv().await {
                if output.send(Message::InstallLine(line)).await.is_err() {
                    break;
                }
            }

            let code = match child.wait().await {
                Ok(status) => status.code().unwrap_or(-1),
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            if code != 0 {
                tracing::error!("fisherman exited with code {code}");
            }
            let _ = output.send(Message::InstallFinished(Ok(code))).await;
        })
    }
}

/// Start fisherman's wrapper with piped output, as the leader of its own
/// process group, and hand it `stdin_data` (the recipe) on stdin, closed
/// after: fisherman reads to EOF.
///
/// The wrapper is the only process of the install this user can signal;
/// fisherman runs as root and cancels when its parent dies
/// (tuna-os/fisherman#267). The shared contract is "kill your wrapper's
/// process group", which must never be the installer's own group. This
/// frontend has no cancel UI, so nothing signals it yet.
async fn spawn_wrapper(argv: &[String], stdin_data: Vec<u8>) -> std::io::Result<tokio::process::Child> {
    use tokio::io::AsyncWriteExt;
    let mut child = TokioCommand::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()?;
    if let Some(mut stdin) = child.stdin.take() {
        // A wrapper that is already gone says why through its exit code.
        let _ = stdin.write_all(&stdin_data).await;
        let _ = stdin.shutdown().await;
    }
    Ok(child)
}

/// Every line from a child's stdout and stderr, read concurrently.
///
/// Each pipe gets its own task, so neither can fill up while the other is
/// being waited on. Lines are interleaved in arrival order; a line is never
/// split across the two streams. The tasks keep draining after the receiver
/// is dropped, so an abandoned install page cannot leave the child blocked on
/// a full pipe.
fn merged_lines<O, E>(stdout: Option<O>, stderr: Option<E>) -> tokio::sync::mpsc::UnboundedReceiver<String>
where
    O: tokio::io::AsyncRead + Unpin + Send + 'static,
    E: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    if let Some(stdout) = stdout {
        let tx = tx.clone();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let _ = tx.send(line);
            }
        });
    }
    if let Some(stderr) = stderr {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let _ = tx.send(line);
            }
        });
    }
    rx
}

#[cfg(test)]
mod tests {
    #[test]
    fn override_makes_all_four_choices_available() {
        assert_eq!(super::available_encryption_choices(false).len(), 2);
        assert_eq!(super::available_encryption_choices(true).len(), 4);
    }

    use super::*;

    #[test]
    fn recipe_default_values_and_json_serialization() {
        let recipe = Recipe::default();
        assert_eq!(recipe.filesystem, "xfs");
        assert_eq!(recipe.encryption.enc_type, "none");
        // Neutral until the branding contract fills them in at init().
        assert_eq!(recipe.distro_id, "linux");
        assert_eq!(recipe.hostname, "linux");
        assert!(recipe.image.is_empty());
        assert!(!recipe.selinux_disabled);

        let json_str = serde_json::to_string(&recipe).unwrap();
        let json: serde_json::Value = serde_json::from_str(&json_str).unwrap();

        assert_eq!(json["filesystem"], "xfs");
        assert_eq!(json["encryption"]["type"], "none");
        assert_eq!(json["distroID"], "linux");
        assert_eq!(json["hostname"], "linux");
        assert_eq!(json["selinuxDisabled"], false);
        assert!(json.get("image").is_none());
        assert!(json.get("targetImgref").is_none());
        assert!(json.get("bootloader").is_none());
    }

    #[test]
    fn a_passphrase_choice_needs_the_passphrase_twice() {
        use super::passphrase_confirmed;
        for t in ["luks-passphrase", "tpm2-luks-passphrase"] {
            assert!(passphrase_confirmed(t, "s3cret", "s3cret"), "{t}");
            assert!(!passphrase_confirmed(t, "s3cret", "s3cre"), "{t}");
            assert!(!passphrase_confirmed(t, "s3cret", ""), "{t}");
        }
        // No passphrase to confirm: never held by the confirmation.
        for t in ["", "none", "tpm2-luks"] {
            assert!(passphrase_confirmed(t, "", "leftover"), "{t}");
        }
    }

    #[test]
    fn encryption_choices_filtering() {
        let without_tpm = available_encryption_choices(false);
        assert_eq!(without_tpm.len(), 2);
        assert!(without_tpm.iter().all(|c| !validate::needs_tpm2(c)));
        assert_eq!(without_tpm[0], "none");
        assert_eq!(without_tpm[1], "luks-passphrase");

        let with_tpm = available_encryption_choices(true);
        assert_eq!(with_tpm.len(), 4);
        assert_eq!(with_tpm[2], "tpm2-luks");
        assert_eq!(with_tpm[3], "tpm2-luks-passphrase");
    }

    /// End to end: the Install button's code path against the real backend.
    ///
    /// `run_fisherman` is what `Message::StartInstall` performs: it writes
    /// the 0600 recipe, runs `fisherman_command()` (sudo
    /// /usr/local/bin/fisherman outside Flatpak), collects the output and
    /// persists the log. In the end-to-end job shared/e2e/setup.sh has put
    /// the validating shim at that path, so this exercises the real
    /// fisherman's Validate() on the recipe this crate serialises. Ignored
    /// by default: it needs TUNA_E2E_DISK and the shim.
    ///
    ///     TUNA_E2E_DISK=/dev/loopN cargo test --release -- --ignored e2e
    /// The process group a pid belongs to: field 5 of /proc/<pid>/stat.
    fn pgrp_of(pid: &str) -> u32 {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
        // comm (field 2) may hold spaces; the rest follows its closing ')'.
        let rest = &stat[stat.rfind(')').unwrap() + 2..];
        rest.split_whitespace().nth(2).unwrap().parse().unwrap()
    }

    #[test]
    fn wrapper_leads_its_own_process_group() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut child = super::spawn_wrapper(&["sleep".to_string(), "30".to_string()], Vec::new())
                .await
                .expect("sleep");
            let pid = child.id().unwrap();
            assert_eq!(pgrp_of(&pid.to_string()), pid, "the wrapper is not a group leader");
            assert_ne!(pgrp_of(&pid.to_string()), pgrp_of("self"));
            // Signalling that group reaches the wrapper, not this process.
            let killed = std::process::Command::new("kill")
                .args(["-TERM", "--", &format!("-{pid}")])
                .status()
                .unwrap();
            assert!(killed.success());
            let status = child.wait().await.unwrap();
            use std::os::unix::process::ExitStatusExt;
            assert_eq!(status.signal(), Some(15));
        });
    }

    /// fisherman reads the recipe on stdin (`fisherman -`): what the wrapper
    /// gets on stdin is the recipe, and stdin is closed so fisherman's read
    /// to EOF ends.
    #[test]
    fn the_recipe_goes_to_the_wrappers_stdin() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut recipe = Recipe::default();
            recipe.encryption.enc_type = "luks-passphrase".into();
            recipe.encryption.passphrase = "s3cret".into();
            let json = serde_json::to_string(&recipe).unwrap();
            let child = super::spawn_wrapper(&["cat".to_string()], json.clone().into_bytes())
                .await
                .expect("cat");
            let out = child.wait_with_output().await.unwrap();
            assert!(out.status.success());
            assert_eq!(String::from_utf8_lossy(&out.stdout), json);
            assert_eq!(super::offline::fisherman_command().last().map(String::as_str), Some("-"));
        });
    }

    /// The options page asks fisherman, and only its answer blocks Continue.
    #[test]
    fn the_partial_recipe_and_its_problems() {
        let r = Recipe {
            hostname: "my_pc".into(),
            encryption: crate::model::Encryption {
                enc_type: "tpm2-luks".into(),
                passphrase: "stale".into(),
            },
            ..Recipe::default()
        };
        let problems = vec![validate::Problem {
            field: "encryption.passphrase".into(),
            code: "encryption_passphrase_required".into(),
            message: "m".into(),
        }];
        // Only the fields the page has; a passphrase only for a type that
        // takes one.
        let partial = super::partial_recipe(&r);
        assert_eq!(
            partial,
            serde_json::json!({
                "hostname": "my_pc", "filesystem": "xfs",
                "btrfsSubvolumes": false, "encryption": {"type": "tpm2-luks"},
            })
        );
        let mut with_passphrase = r.clone();
        with_passphrase.encryption.enc_type = "tpm2-luks-passphrase".into();
        assert_eq!(super::partial_recipe(&with_passphrase)["encryption"]["passphrase"], "stale");
        let enc_problem = problems.iter().find(|p| p.field.starts_with("encryption."));
        assert!(enc_problem.is_some());
        assert_eq!(
            enc_problem.unwrap().render(),
            branding::get().text("validate_encryption_passphrase_required")
        );
        assert_eq!(partial["encryption"].get("passphrase"), None);
    }

    /// A child that writes more than a pipe buffer to stderr before it
    /// writes anything to stdout. Reading stdout to EOF first deadlocked:
    /// the child blocked on the full stderr pipe and never closed stdout.
    #[test]
    fn merged_lines_drains_a_full_stderr_pipe_before_stdout() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut child = super::TokioCommand::new("sh")
                .arg("-c")
                // 256 KiB on one stderr line, then a stdout line.
                .arg("head -c 262144 /dev/zero | tr '\\0' x >&2; echo >&2; echo stdout-done")
                .stdout(super::Stdio::piped())
                .stderr(super::Stdio::piped())
                .spawn()
                .expect("sh");
            let mut rx = super::merged_lines(child.stdout.take(), child.stderr.take());
            let collect = async {
                let mut got = Vec::new();
                while let Some(line) = rx.recv().await {
                    got.push(line);
                }
                got
            };
            let got = tokio::time::timeout(std::time::Duration::from_secs(20), collect)
                .await
                .expect("deadlocked: stderr was not drained while stdout was read");
            let status = child.wait().await.unwrap();
            assert!(status.success());
            assert!(got.iter().any(|l| l == "stdout-done"), "stdout line missing");
            assert!(
                got.iter().any(|l| l.len() == 262144 && l.bytes().all(|b| b == b'x')),
                "the 256 KiB stderr line was not delivered whole"
            );
        });
    }

    #[test]
    #[ignore]
    fn e2e_install_path_reaches_fisherman() {
        let disk = std::env::var("TUNA_E2E_DISK").expect("TUNA_E2E_DISK (run shared/e2e/setup.sh)");
        let mut recipe = Recipe::default();
        recipe.disk = disk;
        recipe.filesystem = "xfs".into();
        recipe.image = "quay.io/centos-bootc/centos-bootc:c10s".into();
        recipe.hostname = "cosmic-e2e".into();

        // Drive the real stream and feed it through the real parser, which
        // is what the install page does. The old form called run_fisherman()
        // and matched a string in its returned log; that function no longer
        // exists, because collecting the output after the process exits is
        // precisely what stopped this frontend having a progress bar.
        let rt = tokio::runtime::Runtime::new().unwrap();
        let (code, log, fraction) = rt.block_on(async {
            use cosmic::iced::futures::StreamExt;
            let mut stream = Box::pin(TunaInstaller::stream_fisherman(recipe));
            let mut progress = super::progress::Progress::new("ExampleOS");
            let mut log = String::new();
            let mut code = None;
            while let Some(message) = stream.next().await {
                match message {
                    Message::InstallLine(line) => {
                        if let Some(shown) = progress.consume(&line) {
                            log.push_str(&shown);
                            log.push('\n');
                        }
                    }
                    Message::InstallFinished(result) => {
                        code = Some(result.expect("fisherman could not be launched"));
                    }
                    _ => {}
                }
            }
            (code.expect("the stream ended without a result"), log, progress.fraction)
        });
        println!("{log}");
        assert_eq!(code, 0, "fisherman exit code");
        // Where the bar ended up, which is the property that was broken and
        // the one no string match could see: a frontend that does not parse
        // fisherman's protocol still reaches the Done page and still reports
        // success, and only the bar shows the difference.
        assert_eq!(
            fraction, 1.0,
            "the progress bar ended at {fraction}, not 1.0 — the install page              is not parsing fisherman's progress protocol              (shared/progress/README.md)"
        );
        assert!(
            log.contains("Installation complete"),
            "the log carried no completion event"
        );
        assert!(
            std::path::Path::new("/tmp/tuna-e2e/recipe.json").exists(),
            "the shim recorded no recipe"
        );
    }

    #[test]
    fn recipe_roundtrip_and_field_serialization() {
        let mut recipe = Recipe::default();
        recipe.disk = "/dev/nvme0n1".into();
        recipe.filesystem = "btrfs".into();
        recipe.btrfs_subvolumes = true;
        recipe.target_imgref = "ghcr.io/tuna-os/albacore:stable".into();
        recipe.bootloader = "systemd".into();
        recipe.compose_fs_backend = true;
        recipe.flatpaks = vec!["org.mozilla.firefox".into()];
        recipe.additional_image_stores = vec!["/run/media/oci".into()];
        recipe.encryption.enc_type = "luks-passphrase".into();
        recipe.encryption.passphrase = "secret123".into();

        let json_str = serde_json::to_string(&recipe).unwrap();
        let restored: Recipe = serde_json::from_str(&json_str).unwrap();

        assert_eq!(restored.disk, recipe.disk);
        assert_eq!(restored.filesystem, recipe.filesystem);
        assert_eq!(restored.btrfs_subvolumes, recipe.btrfs_subvolumes);
        assert_eq!(restored.target_imgref, recipe.target_imgref);
        assert_eq!(restored.bootloader, recipe.bootloader);
        assert_eq!(restored.compose_fs_backend, recipe.compose_fs_backend);
        assert_eq!(restored.flatpaks, recipe.flatpaks);
        assert_eq!(restored.additional_image_stores, recipe.additional_image_stores);
        assert_eq!(restored.encryption.enc_type, recipe.encryption.enc_type);
        assert_eq!(restored.encryption.passphrase, recipe.encryption.passphrase);
        // The field whose absence broke this round trip. It was never
        // asserted, so the test failed on the unwrap rather than on a claim.
        assert_eq!(restored.image, recipe.image);
    }

    /// The live-ISO recipe is the one that omits `image` on the wire, so it
    /// is the shape that cannot be read back if the field loses `default`.
    #[test]
    fn live_iso_recipe_with_no_image_survives_the_round_trip() {
        let mut recipe = Recipe::default();
        recipe.disk = "/dev/sda".into();
        assert!(recipe.image.is_empty());

        let json_str = serde_json::to_string(&recipe).unwrap();
        assert!(
            !json_str.contains("\"image\""),
            "an empty image should not be serialized: {json_str}"
        );

        let restored: Recipe = serde_json::from_str(&json_str).unwrap();
        assert!(restored.image.is_empty());
        assert_eq!(restored.disk, recipe.disk);
    }

    /// A populated image must still make the trip, so `default` is not
    /// quietly swallowing a value that was present.
    #[test]
    fn a_populated_image_round_trips_unchanged() {
        let mut recipe = Recipe::default();
        recipe.image = "ghcr.io/tuna-os/albacore:latest".into();

        let json_str = serde_json::to_string(&recipe).unwrap();
        let restored: Recipe = serde_json::from_str(&json_str).unwrap();
        assert_eq!(restored.image, "ghcr.io/tuna-os/albacore:latest");
    }
}

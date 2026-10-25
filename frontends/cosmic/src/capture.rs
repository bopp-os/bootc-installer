//! Screenshot harness for `docs/screenshots` and the README walkthrough.
//!
//! Why this lives inside the binary rather than beside it: libcosmic is
//! iced-on-wgpu, so the only trustworthy source of "what the user sees" is the
//! frame wgpu actually presented. `iced::window::screenshot` reads that frame
//! back off the GPU. An external X11 grab would also work, but it can hand you
//! a valid PNG of a surface that never acquired a real adapter. Reading back
//! the presented frame cannot.
//!
//! Two properties matter and are enforced in `audit`:
//!
//!  * SAFETY. Driving the wizard to the install page must never start an
//!    install. In `tuna-installer-xfce` the page-enter hook called
//!    `start_install()`, so a naive capture would have partitioned the CI
//!    runner's disk. Here the harness assigns `page` directly and never emits
//!    `Message::StartInstall`, and `update()` refuses that message outright
//!    while `capture` is `Some`. Every hardware query is replaced by fixtures.
//!
//!  * HONESTY. A blank page is a perfectly good 65 KB PNG.
//!    `bootc-installer-asahi` shipped a completely empty settings screen behind
//!    a green tick because its check asserted only that the files existed and
//!    were non-empty. So we read the pixels back and assert properties that
//!    only hold when the UI really drew, with thresholds calibrated against
//!    measured output from real renders.

use cosmic::app::Task;
use cosmic::iced::window::Screenshot;
use std::collections::HashSet;
use std::path::PathBuf;

use crate::{Page, TunaInstaller};

/// Rows occupied by the COSMIC header bar, excluded from the pixel audit.
/// Comfortably taller than the bar itself — the point is to be certain no
/// chrome leaks into the measurement, not to measure the bar precisely.
const HEADER_SKIP_PX: u32 = 56;

/// Frames to let the compositor and wgpu settle before grabbing. Grabbing too
/// early is the dangerous failure: it yields a valid PNG of a half-drawn
/// window, which looks like a screenshot and is not one.
const SETTLE_MS: u64 = 700;

/// The machine the screenshots show: fisherman's probe answer for a laptop,
/// the fixture every frontend's capture reads (shared/probe/README.md), read
/// through the same parser a real probe goes through. Its TPM 2.0 is usable,
/// so the encryption page shows the TPM choices on a runner without one.
/// `BOOTC_INSTALLER_FAKE_PROBE` overrides the file.
pub const FIXTURE_PROBE: &str =
    concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/probe/fixtures/laptop.json");

/// The repository's own app icons (data/icons/hicolor/scalable/apps).
/// `shared/walkthrough/capture-branding.json` names its logo as a theme icon
/// from there; see [`stage_repo_icons`].
const REPO_ICON_DIR: &str =
    concat!(env!("CARGO_MANIFEST_DIR"), "/../../data/icons/hicolor/scalable/apps");

/// The smallest hicolor index that makes `scalable/apps` searchable.
const STAGED_INDEX_THEME: &str = "[Icon Theme]\nName=Hicolor\nDirectories=scalable/apps\n\n\
     [scalable/apps]\nSize=128\nMinSize=8\nMaxSize=512\nType=Scalable\nContext=Applications\n";

/// Make the capture branding's themed logo resolvable, before anything looks
/// up an icon (freedesktop-icons reads `XDG_DATA_DIRS` once).
///
/// A live image whose branding names a theme icon ships that icon in its
/// theme. The CI runner has only Adwaita, so the welcome and done pages drew
/// the fallback and the documentation never showed a logo. This stages the
/// repository's copies in a private hicolor directory and puts it first on
/// `XDG_DATA_DIRS` -- for this process only, capture mode only. The variant
/// capture (an os-release with no LOGO) still renders the fallback, so both
/// paths stay in the walkthrough artifacts.
pub fn stage_repo_icons() {
    let Ok(entries) = std::fs::read_dir(REPO_ICON_DIR) else {
        return;
    };
    let root = std::env::temp_dir().join(format!("tuna-capture-icons-{}", std::process::id()));
    let hicolor = root.join("icons").join("hicolor");
    let apps = hicolor.join("scalable").join("apps");
    if std::fs::create_dir_all(&apps).is_err()
        || std::fs::write(hicolor.join("index.theme"), STAGED_INDEX_THEME).is_err()
    {
        return;
    }
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().is_some_and(|e| e == "svg") {
            let _ = std::fs::copy(&path, apps.join(entry.file_name()));
        }
    }
    let rest = std::env::var("XDG_DATA_DIRS")
        .ok()
        .filter(|d| !d.is_empty())
        .unwrap_or_else(|| "/usr/local/share:/usr/share".to_string());
    std::env::set_var("XDG_DATA_DIRS", format!("{}:{rest}", root.display()));
}

pub fn fixture_probe() -> Result<crate::probe::Facts, String> {
    let path = std::env::var(crate::probe::FAKE_ENV)
        .ok()
        .filter(|p| !p.is_empty())
        .unwrap_or_else(|| FIXTURE_PROBE.to_string());
    let text = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
    crate::probe::parse(&text)
}

// fisherman's real transcript (shared/progress/dry-run-transcript.ndjson),
// cut part-way through the image pull so the bar sits mid-way rather than at
// either end: newline-delimited JSON, one event per line, which is the only
// thing fisherman writes.
//
// This was hand-written "[n/9] " lines naming a specific image ref.
// fisherman has never emitted that prefix, so the parser now passes those
// lines through to the log unparsed and the bar stays at zero — which is
// what this fixture would show if it were left alone. The product name was
// the second problem: a fixture is rendered into the docs, so it shipped one
// product's branding to everyone who rebrands this installer.
/// fisherman emits this once, after TPM enrolment, and for a tpm2-luks
/// install it is the only way back into the disk if the TPM state changes
/// (#129). No CI runner does a TPM install, so it is synthesised -- but fed
/// through the SAME parser a real install uses. Assigning the key to the
/// view directly would keep passing if the parse broke.
const FIXTURE_RECOVERY_EVENT: &str = concat!(
    r#"{"type":"recovery_key","key":"mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf","#,
    r#""timestamp":"2026-01-01T00:00:00Z","elapsed_ms":1000}"#,
);

const FIXTURE_LOG_RUNNING: &[&str] = &[
    r#"{"cumulative_pct": 0, "elapsed_ms": 0, "step": 1, "step_name": "Partitioning disk", "timestamp": "1970-01-01T00:00:00Z", "total_steps": 8, "type": "step", "weight_pct": 0}"#,
    r#"{"cumulative_pct": 0, "elapsed_ms": 400, "step": 2, "step_name": "Formatting EFI partition", "timestamp": "1970-01-01T00:00:00Z", "total_steps": 8, "type": "step", "weight_pct": 1}"#,
    r#"{"cumulative_pct": 1, "elapsed_ms": 800, "step": 3, "step_name": "Formatting root filesystem", "timestamp": "1970-01-01T00:00:00Z", "total_steps": 8, "type": "step", "weight_pct": 0}"#,
    r#"{"cumulative_pct": 1, "elapsed_ms": 1200, "step": 4, "step_name": "Mounting filesystem", "timestamp": "1970-01-01T00:00:00Z", "total_steps": 8, "type": "step", "weight_pct": 0}"#,
    r#"{"cumulative_pct": 1, "elapsed_ms": 1600, "step": 5, "step_name": "Installing OS", "timestamp": "1970-01-01T00:00:00Z", "total_steps": 8, "type": "step", "weight_pct": 87}"#,
    r#"{"elapsed_ms": 2000, "message": "Pulling image: layer 18/71", "timestamp": "1970-01-01T00:00:00Z", "type": "substep"}"#,
    r#"{"elapsed_ms": 2400, "message": "Pulling image: layer 47/71", "timestamp": "1970-01-01T00:00:00Z", "type": "substep"}"#,
];

/// What the capture types into the options page's two passphrase fields.
const CAPTURE_PASSPHRASE: &str = "correct horse battery staple";

/// What the capture types into the account page. No product in any of them.
const CAPTURE_USERNAME: &str = "alex";
const CAPTURE_FULLNAME: &str = "Alex Example";
const CAPTURE_PASSWORD: &str = "tr0ub4dor and 3";

pub struct Capture {
    pub dir: PathBuf,
    pub index: usize,
    pub findings: Vec<Finding>,
    /// (page slug, the page's text) in capture order; written to
    /// `texts.json` for `shared/walkthrough/report_from_pngs.py`.
    pub texts: Vec<(String, String)>,
}

impl Capture {
    /// `TUNA_CAPTURE_DIR` is the only way in. There is no UI affordance and no
    /// command-line flag that a user could trip over.
    pub fn from_env() -> Option<Self> {
        std::env::var_os("TUNA_CAPTURE_DIR").map(|dir| Self {
            dir: PathBuf::from(dir),
            index: 0,
            findings: Vec::new(),
            texts: Vec::new(),
        })
    }
}

#[derive(Debug, Clone)]
pub struct Finding {
    pub name: String,
    pub width: u32,
    pub height: u32,
    pub colours: usize,
    /// Share of sampled pixels that are the single most common colour.
    pub flattest: f64,
    /// Share of sampled pixels that differ noticeably from that colour — text,
    /// icons, borders, controls. "Ink".
    pub ink: f64,
}

#[derive(Debug, Clone)]
pub enum Message {
    /// Show page N, then wait for it to settle.
    Show(usize),
    /// Read the presented frame back.
    Shoot,
    /// The frame arrived.
    Shot(Screenshot),
}

pub fn begin() -> Task<crate::Message> {
    cosmic::task::message(cosmic::action::app(crate::Message::Capture(Message::Show(
        0,
    ))))
}

fn settle_then(msg: Message) -> Task<crate::Message> {
    cosmic::task::future(async move {
        tokio::time::sleep(std::time::Duration::from_millis(SETTLE_MS)).await;
        cosmic::action::app(crate::Message::Capture(msg))
    })
}

pub fn update(app: &mut TunaInstaller, message: Message) -> Task<crate::Message> {
    match message {
        Message::Show(index) => {
            // One frame past the page list: the done page as a TPM install
            // leaves it. It is the same page in another state, not a page of
            // its own, so it is not in Page::ORDER.
            let Some(page) = Page::ORDER.get(index).copied() else {
                if index == Page::ORDER.len() {
                    app.page = Page::Done;
                    app.installing = false;
                    app.install_ok = true;
                    app.recovery_ack = false;
                    app.progress.consume(FIXTURE_RECOVERY_EVENT);
                    if app.progress.recovery_key.is_empty() {
                        eprintln!("capture: the recovery_key event did not parse");
                        std::process::exit(2);
                    }
                    app.capture.as_mut().unwrap().index = index;
                    return settle_then(Message::Shoot);
                }
                return finish(app);
            };

            // Assign the page directly. Going through the ordinary navigation
            // messages would emit StartInstall on the way to Installing.
            app.page = page;
            app.capture.as_mut().unwrap().index = index;

            match page {
                Page::Installing => {
                    app.installing = true;
                    // Through the parser, the way a real install feeds it,
                    // so this screenshot exercises the live code path rather
                    // than a private one. Assigning install_log directly, as
                    // this used to, is how a progress screen can be
                    // photographed without running any of what it shows.
                    app.install_log.clear();
                    app.progress.reset();
                    for line in FIXTURE_LOG_RUNNING {
                        if let Some(shown) = app.progress.consume(line) {
                            app.install_log.push_str(&shown);
                            app.install_log.push('\n');
                        }
                    }
                }
                Page::Done => {
                    app.installing = false;
                    app.install_ok = true;
                }
                // A passphrase choice, typed twice, so the walkthrough shows
                // the fields a needs_passphrase type adds (the KDE capture
                // shows the same state). Masked on screen; the text report
                // carries the field labels, never the value.
                Page::Options => {
                    app.recipe.encryption.enc_type = "luks-passphrase".into();
                    app.recipe.encryption.passphrase = CAPTURE_PASSPHRASE.into();
                    app.passphrase_confirm = CAPTURE_PASSPHRASE.into();
                }
                // Filled in through the page's own messages, so the recipe's
                // user block is built the way typing builds it (sync_user).
                // update() returns no task for these in capture mode: no
                // validate round-trip shells out.
                Page::Account => {
                    for msg in [
                        crate::Message::UsernameChanged(CAPTURE_USERNAME.into()),
                        crate::Message::FullnameChanged(CAPTURE_FULLNAME.into()),
                        crate::Message::PasswordChanged(CAPTURE_PASSWORD.into()),
                        crate::Message::PasswordConfirmChanged(CAPTURE_PASSWORD.into()),
                    ] {
                        let _ = cosmic::Application::update(app, msg);
                    }
                }
                _ => {}
            }

            settle_then(Message::Shoot)
        }
        Message::Shoot => {
            let Some(id) = app.core.main_window_id() else {
                eprintln!("capture: no main window");
                std::process::exit(2);
            };
            cosmic::iced::window::screenshot(id)
                .map(|shot| cosmic::action::app(crate::Message::Capture(Message::Shot(shot))))
        }
        Message::Shot(shot) => {
            let capture = app.capture.as_mut().unwrap();
            let index = capture.index;
            let page = Page::ORDER.get(index).copied();
            let name = match page {
                Some(p) => p.slug().to_string(),
                None => "recovery".to_string(),
            };

            let path = capture
                .dir
                .join(format!("{:02}-{}.png", index + 1, name));
            if let Err(e) = write_png(&path, &shot) {
                eprintln!("capture: failed writing {}: {e}", path.display());
                std::process::exit(2);
            }
            capture.findings.push(audit(&shot, &name));

            // The install page is the one screen with a progress bar, and a
            // bar that lays out but paints nothing is invisible to the audit
            // above (see widest_accent_run). Fail the capture rather than
            // publish a documentation image of a bar that is not there.
            if page == Some(Page::Installing) {
                let run = widest_accent_run(&shot);
                eprintln!("  installing: widest accent run {:.1}% of width", run * 100.0);
                // The fixture stops part-way through the image pull, so the
                // bar is a little over half full across a nearly full-width
                // track. A third of the window is clear of that and nowhere
                // near what an unpainted bar (0%) gives.
                if run < 0.33 {
                    eprintln!(
                        "capture: the progress bar on the install page is {:.1}% of the \
                         window wide — it is laid out but not painted \
                         (shared/progress/README.md)",
                        run * 100.0
                    );
                    std::process::exit(2);
                }
            }
            // The strings this page renders, from the same constants the
            // view is built from (ui::page_text). iced has no widget-tree
            // introspection, so this is how the COSMIC row of the parity
            // matrix stops reading "not measured".
            let text = crate::ui::page_text(app).join(" ");

            // The recovery frame is the one screen where a correct-looking
            // render can still be wrong: the panel can draw with the key
            // missing, and Restart can be live before the key is
            // acknowledged. Neither shows up in a pixel histogram.
            if page.is_none() {
                let key = app.progress.recovery_key.clone();
                if !text.contains(&key) {
                    eprintln!(
                        "capture: the recovery key is not in the rendered text -- the panel did not draw (#129)"
                    );
                    std::process::exit(2);
                }
                if !app.recovery_key_pending() {
                    eprintln!(
                        "capture: Restart is live before the recovery key was acknowledged (#129)"
                    );
                    std::process::exit(2);
                }
            }

            // A needs_passphrase choice must bring both fields with it,
            // and a matching pair must leave Continue live. Neither is
            // visible to a pixel histogram.
            if page == Some(Page::Options) {
                for label in [crate::ui::copy::OPTIONS_PASSPHRASE, crate::ui::copy::OPTIONS_PASSPHRASE_CONFIRM] {
                    if !text.contains(label) {
                        eprintln!("capture: options page with a passphrase choice has no {label:?} field");
                        std::process::exit(2);
                    }
                }
                if text.contains(CAPTURE_PASSPHRASE) {
                    eprintln!("capture: the passphrase leaked into the page text");
                    std::process::exit(2);
                }
                if !app.options_ok() {
                    eprintln!("capture: Continue is held although both passphrases match");
                    std::process::exit(2);
                }
            }

            // The account page must show its fields, keep the password off
            // the page, leave Continue live once filled in, and have put a
            // user block with the wheel group into the recipe.
            if page == Some(Page::Account) {
                for label in [
                    crate::ui::copy::ACCOUNT_USERNAME,
                    crate::ui::copy::ACCOUNT_FULLNAME,
                    crate::ui::copy::ACCOUNT_PASSWORD,
                    crate::ui::copy::ACCOUNT_PASSWORD_CONFIRM,
                ] {
                    if !text.contains(label) {
                        eprintln!("capture: the account page has no {label:?} field");
                        std::process::exit(2);
                    }
                }
                if text.contains(CAPTURE_PASSWORD) {
                    eprintln!("capture: the password leaked into the page text");
                    std::process::exit(2);
                }
                if !app.account_ok() {
                    eprintln!("capture: Continue is held although the account is complete");
                    std::process::exit(2);
                }
                let user = app.recipe().user.clone().unwrap_or_default();
                if user.username != CAPTURE_USERNAME || user.groups != crate::model::USER_GROUPS {
                    eprintln!("capture: the recipe's user block is {user:?}");
                    std::process::exit(2);
                }
            }
            if page == Some(Page::Confirm) && !text.contains(CAPTURE_USERNAME) {
                eprintln!("capture: the confirm page does not show the username");
                std::process::exit(2);
            }

            let capture = app.capture.as_mut().unwrap();
            capture.texts.push((name, text));

            cosmic::task::message(cosmic::action::app(crate::Message::Capture(Message::Show(
                index + 1,
            ))))
        }
    }
}

fn write_png(path: &std::path::Path, shot: &Screenshot) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::File::create(path)?;
    let mut encoder = png::Encoder::new(
        std::io::BufWriter::new(file),
        shot.size.width,
        shot.size.height,
    );
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder
        .write_header()
        .map_err(|e| std::io::Error::other(e.to_string()))?;
    writer
        .write_image_data(&shot.rgba)
        .map_err(|e| std::io::Error::other(e.to_string()))?;
    Ok(())
}

/// Is the install page's progress bar actually PAINTED?
///
/// The audit above cannot answer this and was never meant to: it measures ink
/// over the content region, and the install page supplies plenty of that from
/// the log text alone. The sibling KDE frontend shipped a progress bar that
/// laid out at full width, reported itself visible and opaque, and painted not
/// one pixel — and passed every check in this repository, this audit's
/// equivalent among them, because a page with a populated log looks populated
/// whether or not the bar drew.
///
/// So this looks for the bar specifically. A determinate bar is the only
/// accent-coloured thing in the content region — the wizard's step indicator
/// is accent too but lives in the header, above HEADER_SKIP_PX — so the
/// longest horizontal run of accent pixels on any row IS the filled part of
/// the bar. An unpainted bar gives a longest run of zero.
///
/// Returns the run length in pixels, as a share of the window width.
fn widest_accent_run(shot: &Screenshot) -> f64 {
    let accent = cosmic::theme::active().cosmic().accent_color();
    let (ar, ag, ab) = (
        (accent.red * 255.0) as i32,
        (accent.green * 255.0) as i32,
        (accent.blue * 255.0) as i32,
    );
    let (w, h) = (shot.size.width, shot.size.height);
    let top = HEADER_SKIP_PX.min(h);
    let mut widest: u32 = 0;

    for y in top..h {
        let mut run: u32 = 0;
        for x in 0..w {
            let i = ((y as usize * w as usize) + x as usize) * 4;
            if i + 2 >= shot.rgba.len() {
                break;
            }
            // Chebyshev distance, matching the audit's own notion of "the
            // same colour" rather than inventing a second one.
            let d = (shot.rgba[i] as i32 - ar)
                .abs()
                .max((shot.rgba[i + 1] as i32 - ag).abs())
                .max((shot.rgba[i + 2] as i32 - ab).abs());
            if d <= 24 {
                run += 1;
                widest = widest.max(run);
            } else {
                run = 0;
            }
        }
    }
    f64::from(widest) / f64::from(w.max(1))
}

/// Measure what only holds when the UI really rendered.
fn audit(shot: &Screenshot, name: &str) -> Finding {
    let (w, h) = (shot.size.width, shot.size.height);
    let mut counts: std::collections::HashMap<(u8, u8, u8), u64> =
        std::collections::HashMap::new();
    let mut distinct: HashSet<(u8, u8, u8)> = HashSet::new();
    let mut samples: u64 = 0;

    // Skip the COSMIC header bar. It draws identically whether or not the page
    // below it rendered anything, so including it makes a blank page look
    // populated: measured, a totally empty content area still scored 1.57%
    // "ink" and 98.4% flat purely from chrome, which straddles the range real
    // pages occupy. Auditing only the content region separates the two
    // cleanly. Anything measured over the whole frame is not a usable signal.
    let top = HEADER_SKIP_PX.min(h);

    // Sample every 3rd pixel in each direction; enough resolution for the
    // statistics and ~9x cheaper than the full frame.
    for y in (top..h).step_by(3) {
        for x in (0..w).step_by(3) {
            let i = ((y as usize * w as usize) + x as usize) * 4;
            if i + 2 >= shot.rgba.len() {
                continue;
            }
            let px = (shot.rgba[i], shot.rgba[i + 1], shot.rgba[i + 2]);
            *counts.entry(px).or_insert(0) += 1;
            distinct.insert(px);
            samples += 1;
        }
    }

    let (bg, bg_count) = counts
        .iter()
        .max_by_key(|(_, c)| **c)
        .map(|(p, c)| (*p, *c))
        .unwrap_or(((0, 0, 0), 0));

    // "Ink" = pixels far enough from the dominant background to be something
    // the user can see. Chebyshev distance keeps it cheap and channel-aware.
    let mut ink: u64 = 0;
    for (px, count) in &counts {
        let d = (px.0 as i32 - bg.0 as i32)
            .abs()
            .max((px.1 as i32 - bg.1 as i32).abs())
            .max((px.2 as i32 - bg.2 as i32).abs());
        if d > 24 {
            ink += count;
        }
    }

    let samples = samples.max(1) as f64;
    Finding {
        name: name.to_string(),
        width: w,
        height: h,
        colours: distinct.len(),
        flattest: bg_count as f64 / samples,
        ink: ink as f64 / samples,
    }
}

// Thresholds calibrated against MEASURED output from real headless renders on
// this rig (Xvfb 1400x1000 + Mesa lavapipe, window 1000x700), auditing the
// content region only. Both ends were measured — the working end by capturing
// the real pages, the broken end by capturing the same six pages with `view()`
// forced to an empty container (`TUNA_BLANK_SELFTEST=1`, still wired up so the
// baseline can be re-derived rather than re-guessed):
//
//     page          colours   largest-flat     ink
//     welcome           180          97.3%    2.45%
//     disk              172          58.5%    1.15%
//     options           190          76.7%    2.32%
//     confirm           241          56.2%    2.92%
//     installing        215          54.6%    2.28%
//     done              223          98.2%    1.71%
//     ---- blank ----     8          99.4%    0.60%
//
// The gates below sit in the gap between those two worlds, placed nearer the
// broken end so that a genuinely sparse page (welcome and done are mostly
// empty space by design) does not fail. Every run re-prints the table, so if
// the UI drifts enough to move the numbers the log says so before the gate
// does.
//
// Two things this exercise actually taught, both of which would have been
// wrong if guessed:
//
//   * `largest-flat` is the WEAKEST signal here, not the strongest. Real pages
//     reach 98.2% and a blank one is 99.4% — barely a point apart, because a
//     sparse dark page genuinely is almost all one colour. It is kept only as
//     a backstop. Colour count is the sharp discriminator: 8 versus 172+.
//   * Measured over the WHOLE frame these numbers do not separate at all. The
//     COSMIC header bar draws either way, which alone scored a blank page
//     1.57% ink and 98.4% flat — inside the range real pages occupy. Hence
//     HEADER_SKIP_PX.
//
// The sibling repo's first attempt guessed 0.97 for largest-flat and then
// failed a page that had rendered perfectly. Guessing a threshold and reading
// the resulting failure as a defect is how you end up "fixing" working code.
const MIN_COLOURS: usize = 60;
const MAX_FLATTEST: f64 = 0.99;
const MIN_INK: f64 = 0.009;

fn finish(app: &mut TunaInstaller) -> Task<crate::Message> {
    let capture = app.capture.as_ref().unwrap();
    let mut failures: Vec<String> = Vec::new();

    println!(
        "\n  {:<12} {:>10}  {:>8}  {:>12}  {:>7}",
        "page", "size", "colours", "largest-flat", "ink"
    );
    for f in &capture.findings {
        println!(
            "  {:<12} {:>4}x{:<5} {:>8}  {:>11.1}%  {:>6.2}%",
            f.name,
            f.width,
            f.height,
            f.colours,
            f.flattest * 100.0,
            f.ink * 100.0
        );
        if f.colours < MIN_COLOURS {
            failures.push(format!(
                "{}: only {} distinct colours — did not render",
                f.name, f.colours
            ));
        }
        if f.flattest > MAX_FLATTEST {
            failures.push(format!(
                "{}: {:.1}% of the frame is one flat colour — blank page",
                f.name,
                f.flattest * 100.0
            ));
        }
        if f.ink < MIN_INK {
            failures.push(format!(
                "{}: {:.2}% ink — nothing legible was drawn",
                f.name,
                f.ink * 100.0
            ));
        }
    }

    // Page::ORDER plus the recovery frame, which is the done page in its
    // other state rather than a page of its own.
    let expected_frames = Page::ORDER.len() + 1;
    if capture.findings.len() != expected_frames {
        failures.push(format!(
            "captured {} of {} frames",
            capture.findings.len(),
            expected_frames
        ));
    }

    if !failures.is_empty() {
        eprintln!();
        for msg in &failures {
            eprintln!("FAIL: {msg}");
        }
        std::process::exit(1);
    }

    let texts_path = capture.dir.join("texts.json");
    let texts: serde_json::Map<String, serde_json::Value> = capture
        .texts
        .iter()
        .map(|(name, text)| (name.clone(), serde_json::Value::String(text.clone())))
        .collect();
    if let Err(e) = std::fs::write(
        &texts_path,
        serde_json::to_string_pretty(&serde_json::Value::Object(texts)).unwrap() + "\n",
    ) {
        eprintln!("capture: failed writing {}: {e}", texts_path.display());
        std::process::exit(2);
    }

    println!(
        "\n  wrote {} screens + texts.json to {}",
        capture.findings.len(),
        capture.dir.display()
    );
    std::process::exit(0);
}

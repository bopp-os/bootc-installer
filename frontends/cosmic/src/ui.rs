//! Views, built from the cosmic widget set and the cosmic-theme palette.
//!
//! Nothing here hardcodes a colour or a pixel gap: colours come from
//! `cosmic::theme::active().cosmic()` and spacing from its `spacing` scale, so
//! the installer follows the user's COSMIC theme like every other COSMIC app.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::widget;

use crate::{
    available_encryption_choices, branding, Message, Page, TunaInstaller, FILESYSTEMS,
};

/// Every user-facing string of the wizard, in one place.
///
/// The view functions below and [`page_text`] both read from here, so the
/// text the capture harness reports for a page is, by construction, the text
/// that page renders. `{product}` is substituted with [`branding::name`].
/// Lines a product may rebrand are branding copy keys (shared/branding),
/// read through [`t`] rather than constants here.
pub mod copy {
    pub const BACK: &str = "Back";
    pub const CONTINUE: &str = "Continue";

    pub const WELCOME_BODY: &str =
        "Welcome. This assistant will guide you through installing {product} onto this computer.";
    pub const WELCOME_CAPTION: &str = "You will choose a target disk and a few options, and create \
         your account. Nothing is written to any disk until you confirm on the last step.";

    pub const DISK_TITLE: &str = "Select a disk";
    pub const DISK_SUBTITLE: &str = "Everything on the disk you pick will be erased.";
    pub const DISK_SCANNING: &str = "Scanning for disks\u{2026}";
    pub const DISK_NONE: &str = "No disk of at least 50 GiB was found. Connect one to install to.";
    pub const DISK_PROBE_FAILED: &str = "Could not detect disks";

    pub const OPTIONS_TITLE: &str = "Options";
    pub const OPTIONS_SUBTITLE: &str =
        "Sensible defaults are already chosen. Change them only if you need to.";
    pub const OPTIONS_SYSTEM: &str = "System";
    pub const OPTIONS_HOSTNAME: &str = "Computer name";
    pub const OPTIONS_FILESYSTEM: &str = "Filesystem";
    pub const OPTIONS_ENCRYPTION: &str = "Encryption";
    pub const OPTIONS_DISK_ENCRYPTION: &str = "Disk encryption";
    pub const OPTIONS_PASSPHRASE: &str = "Passphrase";
    pub const OPTIONS_PASSPHRASE_HINT: &str = "Required to unlock at boot";
    pub const OPTIONS_PASSPHRASE_CONFIRM: &str = "Confirm passphrase";
    pub const OPTIONS_PASSPHRASE_CONFIRM_HINT: &str = "Type it again";
    pub const OPTIONS_PASSPHRASE_MISMATCH: &str = "Passphrases do not match.";

    // The account page. No heading here may hold a parity-report screen
    // keyword (shared/walkthrough/parity_report.py SCREENS), or the report
    // credits this page as another screen.
    pub const ACCOUNT_TITLE: &str = "Create your account";
    pub const ACCOUNT_SUBTITLE: &str =
        "You will sign in with this account. It can administer the computer.";
    pub const ACCOUNT_SECTION: &str = "Account";
    pub const ACCOUNT_USERNAME: &str = "Username";
    pub const ACCOUNT_USERNAME_HINT: &str = "Lowercase, for example alex";
    pub const ACCOUNT_FULLNAME: &str = "Full name";
    pub const ACCOUNT_FULLNAME_HINT: &str = "Optional";
    pub const ACCOUNT_PASSWORD: &str = "Password";
    pub const ACCOUNT_PASSWORD_HINT: &str = "Required";
    pub const ACCOUNT_PASSWORD_CONFIRM: &str = "Confirm password";
    pub const ACCOUNT_PASSWORD_CONFIRM_HINT: &str = "Type it again";
    pub const ACCOUNT_PASSWORD_MISMATCH: &str = "Passwords do not match.";

    pub const CONFIRM_SUBTITLE: &str = "The last screen before anything is written.";
    pub const CONFIRM_SUMMARY: &str = "Summary";
    pub const CONFIRM_TARGET_DISK: &str = "Target disk";
    pub const CONFIRM_IMAGE: &str = "Image";
    pub const CONFIRM_LIVE_SUFFIX: &str = " (this system \u{2014} no download)";
    pub const INSTALLING_SUBTITLE: &str = "fisherman is writing the image to disk.";

    pub const DONE_FAIL_DETAIL: &str = "The install log above has the details.";
    pub const DONE_CLOSE: &str = "Close";
}

use copy::*;

/// A branding copy line (shared/branding/copy-defaults.json keys) with
/// `{name}` filled in.
fn t_line(key: &str) -> String {
    branding::text(key)
}

/// The same with `{disk}` filled in.
fn t_disk(key: &str, disk: &str) -> String {
    branding::get().text_with(key, &[("disk", disk)])
}

/// What an encryption type is called: `suffix` is `"_label"` or
/// `"_description"` (shared/branding/README.md, "Encryption choices").
fn encryption_text(enc_type: &str, suffix: &str) -> String {
    let id = if enc_type.is_empty() {
        "none"
    } else {
        enc_type
    };
    t_line(&format!("encryption_{}{suffix}", id.replace('-', "_")))
}

fn with_product(s: &str) -> String {
    s.replace("{product}", branding::name())
}

/// The strings the current page shows, in reading order.
///
/// This is what the capture harness writes to `texts.json` so the shared
/// parity report can match the COSMIC screens against the contract keywords
/// the way the GTK and Qt harnesses do from their widget trees. iced has no
/// widget-tree introspection, so the honest substitute is to render the pages
/// and their text from the same constants.
pub fn page_text(app: &TunaInstaller) -> Vec<String> {
    let recipe = app.recipe();
    match app.page() {
        Page::Welcome => {
            let mut t = vec![t_line("welcome_title"), with_product(WELCOME_BODY)];
            let sub = t_line("welcome_subtitle");
            if !sub.is_empty() {
                t.push(sub);
            }
            t.push(WELCOME_CAPTION.to_string());
            t.extend(crate::probe::requirements_lines(app.unmet()));
            t.push(t_line("welcome_button"));
            t
        }
        Page::DiskSelect => {
            let mut t = vec![DISK_TITLE.to_string(), DISK_SUBTITLE.to_string()];
            if app.disks().is_empty() {
                t.extend(disk_empty_text(app));
            }
            for disk in app.disks() {
                t.push(disk.title.clone());
                t.push(disk_caption(disk));
            }
            t.push(BACK.to_string());
            if app.selected_disk().is_some() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Options => {
            let choices = available_encryption_choices(app.has_tpm());
            let current = choices.iter().find(|c| **c == recipe.encryption.enc_type);
            let mut t = vec![
                OPTIONS_TITLE.to_string(),
                OPTIONS_SUBTITLE.to_string(),
                OPTIONS_SYSTEM.to_string(),
                OPTIONS_HOSTNAME.to_string(),
                recipe.hostname.clone(),
            ];
            if let Some(p) = app.problem("hostname") {
                t.push(p.render());
            }
            t.extend([
                OPTIONS_FILESYSTEM.to_string(),
                recipe.filesystem.clone(),
                OPTIONS_ENCRYPTION.to_string(),
                OPTIONS_DISK_ENCRYPTION.to_string(),
            ]);
            if let Some(c) = current {
                t.push(encryption_text(c, "_label"));
                t.push(encryption_text(c, "_description"));
            }
            if crate::validate::needs_passphrase(&recipe.encryption.enc_type) {
                t.push(OPTIONS_PASSPHRASE.to_string());
                t.push(OPTIONS_PASSPHRASE_HINT.to_string());
                t.push(OPTIONS_PASSPHRASE_CONFIRM.to_string());
                t.push(OPTIONS_PASSPHRASE_CONFIRM_HINT.to_string());
                if confirm_mismatch(app) {
                    t.push(OPTIONS_PASSPHRASE_MISMATCH.to_string());
                }
            }
            for field in ["encryption", "filesystem", "btrfsSubvolumes"] {
                if let Some(p) = app.problem(field) {
                    t.push(p.render());
                }
            }
            t.push(BACK.to_string());
            if app.options_ok() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Account => {
            // The field labels and the username; never the password.
            let mut t = vec![
                ACCOUNT_TITLE.to_string(),
                ACCOUNT_SUBTITLE.to_string(),
                ACCOUNT_SECTION.to_string(),
                ACCOUNT_USERNAME.to_string(),
                app.username().to_string(),
            ];
            if let Some(p) = app.problem("user") {
                t.push(p.render());
            }
            t.push(ACCOUNT_FULLNAME.to_string());
            if !app.fullname().is_empty() {
                t.push(app.fullname().to_string());
            }
            t.extend([
                ACCOUNT_PASSWORD.to_string(),
                ACCOUNT_PASSWORD_HINT.to_string(),
                ACCOUNT_PASSWORD_CONFIRM.to_string(),
                ACCOUNT_PASSWORD_CONFIRM_HINT.to_string(),
            ]);
            if app.password_mismatch() {
                t.push(ACCOUNT_PASSWORD_MISMATCH.to_string());
            }
            t.push(BACK.to_string());
            if app.account_ok() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Confirm => vec![
            t_line("confirm_title"),
            confirm_subtitle(),
            t_disk("confirm_warning", &confirm_disk(app)),
            t_line("confirm_body"),
            CONFIRM_SUMMARY.to_string(),
            CONFIRM_TARGET_DISK.to_string(),
            confirm_disk(app),
            OPTIONS_FILESYSTEM.to_string(),
            recipe.filesystem.clone(),
            OPTIONS_ENCRYPTION.to_string(),
            encryption_text(&recipe.encryption.enc_type, "_label"),
            OPTIONS_HOSTNAME.to_string(),
            recipe.hostname.clone(),
            ACCOUNT_USERNAME.to_string(),
            app.username().to_string(),
            CONFIRM_IMAGE.to_string(),
            confirm_image(app),
            BACK.to_string(),
            t_line("confirm_button"),
        ],
        Page::Installing => vec![
            t_line("progress_title"),
            INSTALLING_SUBTITLE.to_string(),
            app.install_log().to_string(),
            t_line("progress_note"),
        ],
        Page::Done => {
            let (title, detail) = done_copy(app.install_ok());
            let mut t = vec![title, detail];
            if app.install_ok() {
                // The recovery panel, when there is a key (#129). The key
                // itself goes in too: the capture asserts on it, and a
                // panel drawn without it is the failure worth catching.
                if !app.progress.recovery_key.is_empty() {
                    t.push(t_line("recovery_key_title"));
                    t.push(t_line("recovery_key_body"));
                    t.push(app.progress.recovery_key.clone());
                    t.push(t_line("recovery_key_copy"));
                    t.push(t_line("recovery_key_ack"));
                }
                if !branding::get().store_url.is_empty() {
                    t.push(t_line("store_label"));
                }
                t.push(t_line("done_restart"));
            }
            t.push(DONE_CLOSE.to_string());
            t
        }
    }
}

/// Below the disk's title (its model, or its path): the path, fisherman's
/// size label and the bus (shared/probe/README.md).
fn disk_caption(disk: &crate::model::DiskInfo) -> String {
    let mut bits = vec![disk.path.as_str(), disk.size_label.as_str()];
    if !disk.transport_label.is_empty() {
        bits.push(&disk.transport_label);
    }
    bits.join(" \u{b7} ")
}

/// What the disk page says while it has no disk to offer: scanning, the
/// probe's failure, or that fisherman found nothing eligible.
fn disk_empty_text(app: &TunaInstaller) -> Vec<String> {
    match app.disk_error() {
        Some(err) => vec![DISK_PROBE_FAILED.to_string(), err.to_string()],
        None if app.probed() => vec![DISK_NONE.to_string()],
        None => vec![DISK_SCANNING.to_string()],
    }
}

fn confirm_disk(app: &TunaInstaller) -> String {
    app.selected_disk()
        .and_then(|i| app.disks().get(i))
        .map_or_else(|| "?".to_string(), |d| d.path.clone())
}

fn confirm_image(app: &TunaInstaller) -> String {
    match (app.live_image(), app.recipe().image.is_empty()) {
        // Live media (fisherman's probe): the running system is installed.
        (Some(""), true) => format!("this system{CONFIRM_LIVE_SUFFIX}"),
        (Some(live), true) => format!("{live}{CONFIRM_LIVE_SUFFIX}"),
        _ => app.recipe().image.clone(),
    }
}

fn done_copy(ok: bool) -> (String, String) {
    if ok {
        (t_line("done_title"), t_line("done_subtitle"))
    } else {
        (t_line("done_failed_title"), DONE_FAIL_DETAIL.to_string())
    }
}

/// The confirm subtitle: the product's own line (CONFIRM_SUBTITLE is the
/// neutral explanation, used when the branding sets none).
fn confirm_subtitle() -> String {
    let line = t_line("confirm_subtitle");
    if line.is_empty() {
        CONFIRM_SUBTITLE.to_string()
    } else {
        line
    }
}

pub fn view(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    // Deliberately renders nothing, so the capture harness's pixel gate can be
    // calibrated against a measured blank frame instead of a guessed one. This
    // is how the numbers in `capture.rs` were derived at the broken end, and
    // re-running it is how they should be re-derived if the UI changes:
    //
    //     TUNA_BLANK_SELFTEST=1 TUNA_CAPTURE_DIR=/tmp/blank just capture
    //
    // It must FAIL. If it ever passes, the gate has stopped detecting a page
    // that did not render, which is the entire point of the gate.
    if std::env::var_os("TUNA_BLANK_SELFTEST").is_some() {
        return widget::container(widget::space::horizontal())
            .width(Length::Fill)
            .height(Length::Fill)
            .into();
    }
    let content: Element<Message> = match app.page() {
        Page::Welcome => welcome(app),
        Page::DiskSelect => disk_select(app),
        Page::Options => options(app),
        Page::Account => account(app),
        Page::Confirm => confirm(app),
        Page::Installing => installing(app),
        Page::Done => done(app),
    };

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .padding(spacing.space_l)
        .into()
}

/// Back / spacer / forward, the shape every COSMIC wizard uses.
fn nav_row<'a>(
    back: Option<Message>,
    forward: Option<(String, Message, bool)>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let mut row = widget::row::with_capacity(3).spacing(spacing.space_s);

    if let Some(msg) = back {
        row = row.push(widget::button::standard(BACK).on_press(msg));
    }
    row = row.push(widget::space::horizontal());
    if let Some((label, msg, destructive)) = forward {
        let button = if destructive {
            widget::button::destructive(label)
        } else {
            widget::button::suggested(label)
        };
        row = row.push(button.on_press(msg));
    }
    row.align_y(Alignment::Center).into()
}

/// One branding artwork value (an absolute file or a theme icon name,
/// `branding::logo_source`), resolved to something that is really there.
/// Missing/unreadable files and theme names the icon theme lacks are `None`,
/// never a placeholder: the caller decides the fallback.
fn resolve_artwork(spec: &str) -> Option<widget::icon::Handle> {
    let path = match branding::logo_source(spec, crate::offline::in_flatpak()) {
        branding::LogoSource::File(path) => Some(std::path::PathBuf::from(path)),
        branding::LogoSource::Theme(name) => widget::icon::from_name(name)
            .size(128).fallback(None).path(),
        branding::LogoSource::None => None,
    }?;
    if !path.is_file() || std::fs::File::open(&path).is_err() {
        return None;
    }
    Some(widget::icon::from_path(path))
}

/// The product's artwork for a page: the branding resolver's
/// `assets.<asset_key>` first, then its `logo`. Resolved once per page, after
/// the application has selected its icon theme.
fn product_artwork(asset_key: &str) -> Option<widget::icon::Handle> {
    let b = branding::get();
    b.assets
        .get(asset_key)
        .and_then(|spec| resolve_artwork(spec))
        .or_else(|| resolve_artwork(&b.logo))
}

fn welcome_artwork() -> Option<&'static widget::icon::Handle> {
    static ART: std::sync::OnceLock<Option<widget::icon::Handle>> = std::sync::OnceLock::new();
    ART.get_or_init(|| product_artwork("welcome_image")).as_ref()
}

fn complete_artwork() -> Option<&'static widget::icon::Handle> {
    static ART: std::sync::OnceLock<Option<widget::icon::Handle>> = std::sync::OnceLock::new();
    ART.get_or_init(|| product_artwork("complete_image")).as_ref()
}

/// Product artwork at hero size, as COSMIC Initial Setup shows a logo.
fn artwork_icon(handle: &widget::icon::Handle) -> Element<'static, Message> {
    handle
        .clone()
        .icon()
        .size(96)
        .content_fit(cosmic::iced::ContentFit::Contain)
        .into()
}

/// The welcome page's artwork. With no product artwork, a themed symbolic
/// icon in an accent-tinted disc, the shape Niri and GNOME's status pages
/// use, so the page reads as deliberate rather than as a missing image. It
/// used to be `drive-harddisk-symbolic` bare at 64 px, which Adwaita draws as
/// a rounded square with a circle: in the walkthrough it looked like a camera
/// placeholder. `computer-symbolic` (this computer is what gets installed
/// to) is in Adwaita, which the application names as its icon theme.
fn welcome_logo() -> Element<'static, Message> {
    if let Some(handle) = welcome_artwork() {
        return artwork_icon(handle);
    }
    widget::container(widget::icon::from_name("computer-symbolic").size(48).icon())
        .width(Length::Fixed(96.0))
        .height(Length::Fixed(96.0))
        .align_x(Alignment::Center)
        .align_y(Alignment::Center)
        .class(cosmic::theme::Container::custom(|theme| {
            let cosmic = theme.cosmic();
            let accent = cosmic.accent_color();
            cosmic::iced::widget::container::Style {
                icon_color: Some(cosmic.accent_text_color().into()),
                text_color: Some(cosmic.accent_text_color().into()),
                background: Some(cosmic::iced::Background::Color(
                    cosmic::iced::Color::from_rgba(accent.red, accent.green, accent.blue, 0.18),
                )),
                border: cosmic::iced::Border {
                    radius: 48.0.into(),
                    ..Default::default()
                },
                ..Default::default()
            }
        }))
        .into()
}

/// The successful done page's artwork: product artwork, else the themed
/// check. The failed-install page never calls this.
fn done_logo(fallback: &'static str) -> Element<'static, Message> {
    match complete_artwork() {
        Some(handle) => artwork_icon(handle),
        None => widget::icon::from_name(fallback).size(64).icon().into(),
    }
}

fn welcome(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let hero = widget::column::with_children(vec![
        welcome_logo(),
        widget::text::title1(t_line("welcome_title")).into(),
        widget::text::body(with_product(WELCOME_BODY)).into(),
    ]);
    let subtitle = t_line("welcome_subtitle");
    let hero = if subtitle.is_empty() {
        hero
    } else {
        hero.push(widget::text::body(subtitle))
    };
    let mut hero = hero.push(widget::text::caption(WELCOME_CAPTION));
    // fisherman's minimum requirements (RAM, CPU cores, UEFI). A warning,
    // not a gate: shared/probe/README.md.
    let warning = crate::probe::requirements_lines(app.unmet());
    if !warning.is_empty() {
        hero = hero.push(
            widget::row::with_children(vec![
                widget::icon::from_name("dialog-warning-symbolic").size(16).icon().into(),
                widget::text::body(warning.join("\n")).into(),
            ])
            .spacing(spacing.space_xs)
            .align_y(Alignment::Center),
        );
    }
    let hero = hero
        .spacing(spacing.space_s)
        .align_x(Alignment::Center)
        .width(Length::Fill);

    let next = t_line("welcome_button");
    widget::column::with_children(vec![
        widget::space::vertical().into(),
        hero.into(),
        widget::space::vertical().into(),
        nav_row(None, Some((next, Message::NextPage, false))),
    ])
    .spacing(spacing.space_m)
    .height(Length::Fill)
    .into()
}

fn disk_select(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let body: Element<Message> = if app.disks().is_empty() {
        let mut col = widget::column::with_capacity(3).spacing(spacing.space_s);
        if !app.probed() {
            col = col.push(widget::progress_bar::indeterminate_linear().width(Length::Fill));
        }
        for line in disk_empty_text(app) {
            col = col.push(widget::text::body(line));
        }
        col.into()
    } else {
        let mut list = widget::list_column().style(cosmic::theme::Container::List);
        for (i, disk) in app.disks().iter().enumerate() {
            let _selected = app.selected_disk() == Some(i);

            let label = widget::column::with_children(vec![
                widget::text::body(disk.title.clone()).into(),
                widget::text::caption(disk_caption(disk)).into(),
            ])
            .spacing(spacing.space_xxxs)
            .width(Length::Fill);

            let row = widget::row::with_children(vec![
                label.into(),
                widget::radio(widget::text::body(""), i, app.selected_disk(), Message::SelectDisk)
                    .into(),
            ])
            .align_y(Alignment::Center)
            .spacing(spacing.space_s);

            list = list.add(
                widget::mouse_area(row)
                    .on_press(Message::SelectDisk(i)),
            );
        }
        widget::scrollable(list.into_element())
            .height(Length::Fill)
            .into()
    };

    page_frame(
        DISK_TITLE,
        DISK_SUBTITLE,
        body,
        nav_row(
            Some(Message::BackPage),
            app.selected_disk()
                .map(|_| (CONTINUE.to_string(), Message::NextPage, false)),
        ),
    )
}

/// The confirmation has text and differs from the passphrase.
fn confirm_mismatch(app: &TunaInstaller) -> bool {
    !app.passphrase_confirm().is_empty() && !app.passphrases_match()
}

fn options(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let fs_index = FILESYSTEMS.iter().position(|f| *f == recipe.filesystem);

    // tunaOS#734: this list is `has_tpm`-filtered, same set XFCE offers on
    // this hardware, and `idx` below is a position in it — NOT in the full
    // `ENCRYPTION_TYPES` list. `update()`'s `EncryptionChanged` handler
    // rebuilds the identical filtered list before indexing into it, so the
    // two stay in lockstep without passing the list through a message.
    let enc_choices = available_encryption_choices(app.has_tpm());
    let enc_index = enc_choices
        .iter()
        .position(|c| *c == recipe.encryption.enc_type);
    let enc_labels: Vec<String> = enc_choices
        .iter()
        .map(|c| encryption_text(c, "_label"))
        .collect();
    let enc_description = enc_index
        .and_then(|i| enc_choices.get(i))
        .map(|c| encryption_text(c, "_description"))
        .unwrap_or_default();
    // The choice's needs_passphrase (encryption-choices.json). Whether the
    // passphrase is acceptable is fisherman's answer (`encryption_ok()`).
    let needs_passphrase = crate::validate::needs_passphrase(&recipe.encryption.enc_type);

    // fisherman's hostname rule, in the copy's words, under the field.
    let mut hostname_item = widget::settings::item::builder(OPTIONS_HOSTNAME);
    if let Some(p) = app.problem("hostname") {
        hostname_item = hostname_item.description(p.render());
    }
    let system = widget::settings::section()
        .title(OPTIONS_SYSTEM)
        .add(
            hostname_item.control(
                widget::text_input(branding::get().default_hostname.as_str(), &recipe.hostname)
                    .on_input(Message::HostnameChanged)
                    .width(Length::Fixed(260.0)),
            ),
        )
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::dropdown(&FILESYSTEMS, fs_index, Message::FilesystemChanged),
        ));

    // fisherman's problem with the choice (an empty passphrase, LUKS on
    // ZFS) replaces the description while it stands.
    let enc_description = ["encryption", "filesystem", "btrfsSubvolumes"]
        .iter()
        .find_map(|f| app.problem(f))
        .map_or(enc_description, |p| p.render());
    let mut security = widget::settings::section().title(OPTIONS_ENCRYPTION).add(
        widget::settings::item::builder(OPTIONS_DISK_ENCRYPTION)
            .description(enc_description)
            // Handed over by value, not as `.as_slice()`: the returned
            // `Element` outlives this function, so a borrow of the local
            // `Vec` would not compile (E0515). `Vec<String>` converts into
            // an owned `Cow<[String]>`, which the dropdown keeps.
            .control(widget::dropdown(
                enc_labels,
                enc_index,
                Message::EncryptionChanged,
            )),
    );

    // Only build the passphrase controls once the chosen encryption actually
    // carries one. The KDE sibling crashed precisely at this kind of
    // conditional: its constructor called setChecked() before the passphrase
    // widgets existed, so the toggled handler ran against uninitialised
    // pointers. In Rust the equivalent mistake cannot compile, but the
    // conditional is still the honest UI — and "tpm2-luks" alone must NOT show
    // this field, since fisherman never reads a passphrase for it.
    //
    // Typed twice, as on KDE and Niri: a typo in a passphrase nobody sees
    // is a disk nobody can unlock. The mismatch line appears once the
    // confirmation has text, and Continue waits for a match.
    if needs_passphrase {
        security = security.add(widget::settings::item(
            OPTIONS_PASSPHRASE,
            widget::secure_input(
                OPTIONS_PASSPHRASE_HINT,
                &recipe.encryption.passphrase,
                Some(Message::TogglePassphraseVisible),
                app.passphrase_hidden(),
            )
            .on_input(Message::PassphraseChanged)
            .width(Length::Fixed(260.0)),
        ));
        let mut confirm_item = widget::settings::item::builder(OPTIONS_PASSPHRASE_CONFIRM);
        if confirm_mismatch(app) {
            confirm_item = confirm_item.description(OPTIONS_PASSPHRASE_MISMATCH);
        }
        security = security.add(
            confirm_item.control(
                widget::secure_input(
                    OPTIONS_PASSPHRASE_CONFIRM_HINT,
                    app.passphrase_confirm(),
                    Some(Message::TogglePassphraseVisible),
                    app.passphrase_hidden(),
                )
                .on_input(Message::PassphraseConfirmChanged)
                .width(Length::Fixed(260.0)),
            ),
        );
    }

    let body = widget::scrollable(
        widget::settings::view_column(vec![system.into(), security.into()])
            .spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        OPTIONS_TITLE,
        OPTIONS_SUBTITLE,
        body.into(),
        nav_row(
            Some(Message::BackPage),
            // Blocked while fisherman reports a problem with the page (an
            // empty passphrase, a bad hostname), so it can never reach
            // Confirm/Install and only then be rejected (tunaOS#734).
            app.options_ok()
                .then_some((CONTINUE.to_string(), Message::NextPage, false)),
        ),
    )
}

/// The account the installed system is created with: the recipe's `user`
/// block. Required, because this frontend has no image catalog to say the
/// image makes its own first user. Continue waits for a username and a
/// password typed the same twice, and for fisherman to accept the username
/// (`validate --json --partial`, shown through `validate_username_*`).
fn account(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let mut username_item = widget::settings::item::builder(ACCOUNT_USERNAME);
    if let Some(p) = app.problem("user") {
        username_item = username_item.description(p.render());
    }
    let mut confirm_item = widget::settings::item::builder(ACCOUNT_PASSWORD_CONFIRM);
    if app.password_mismatch() {
        confirm_item = confirm_item.description(ACCOUNT_PASSWORD_MISMATCH);
    }

    let section = widget::settings::section()
        .title(ACCOUNT_SECTION)
        .add(
            username_item.control(
                widget::text_input(ACCOUNT_USERNAME_HINT, app.username())
                    .on_input(Message::UsernameChanged)
                    .width(Length::Fixed(260.0)),
            ),
        )
        .add(widget::settings::item(
            ACCOUNT_FULLNAME,
            widget::text_input(ACCOUNT_FULLNAME_HINT, app.fullname())
                .on_input(Message::FullnameChanged)
                .width(Length::Fixed(260.0)),
        ))
        .add(widget::settings::item(
            ACCOUNT_PASSWORD,
            widget::secure_input(
                ACCOUNT_PASSWORD_HINT,
                app.password(),
                Some(Message::TogglePasswordVisible),
                app.password_hidden(),
            )
            .on_input(Message::PasswordChanged)
            .width(Length::Fixed(260.0)),
        ))
        .add(
            confirm_item.control(
                widget::secure_input(
                    ACCOUNT_PASSWORD_CONFIRM_HINT,
                    app.password_confirm(),
                    Some(Message::TogglePasswordVisible),
                    app.password_hidden(),
                )
                .on_input(Message::PasswordConfirmChanged)
                .width(Length::Fixed(260.0)),
            ),
        );

    let body = widget::scrollable(
        widget::settings::view_column(vec![section.into()]).spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        ACCOUNT_TITLE,
        ACCOUNT_SUBTITLE,
        body.into(),
        nav_row(
            Some(Message::BackPage),
            app.account_ok()
                .then_some((CONTINUE.to_string(), Message::NextPage, false)),
        ),
    )
}

fn confirm(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let disk = confirm_disk(app);
    let image = confirm_image(app);

    let summary = widget::settings::section()
        .title(CONFIRM_SUMMARY)
        .add(widget::settings::item(CONFIRM_TARGET_DISK, widget::text::body(disk)))
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::text::body(recipe.filesystem.clone()),
        ))
        .add(widget::settings::item(
            OPTIONS_ENCRYPTION,
            widget::text::body(encryption_text(&recipe.encryption.enc_type, "_label")),
        ))
        .add(widget::settings::item(
            OPTIONS_HOSTNAME,
            widget::text::body(recipe.hostname.clone()),
        ))
        .add(widget::settings::item(
            ACCOUNT_USERNAME,
            widget::text::body(app.username().to_string()),
        ))
        .add(widget::settings::item(CONFIRM_IMAGE, widget::text::body(image)));

    // Not `widget::warning::warning`: its filled amber background renders the
    // body text near-invisible on the dark COSMIC palette, which the first
    // screenshot run made obvious and no diff ever would have. A card with
    // warning-coloured text keeps the emphasis and stays legible in both
    // light and dark.
    let theme = cosmic::theme::active();
    let warning = widget::container(
        widget::row::with_children(vec![
            widget::icon::from_name("dialog-warning-symbolic")
                .size(16)
                .icon()
                .into(),
            widget::text::body(t_disk("confirm_warning", &confirm_disk(app)))
            .class(cosmic::theme::Text::Color(
                theme.cosmic().warning_text_color().into(),
            ))
            .into(),
        ])
        .spacing(spacing.space_xs)
        .align_y(Alignment::Center),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill);

    let mut parts = vec![warning.into(), summary.into()];
    let tagline = t_line("confirm_body");
    if !tagline.is_empty() {
        parts.push(widget::text::body(tagline).into());
    }
    let body = widget::scrollable(
        widget::column::with_children(parts).spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        t_line("confirm_title"),
        confirm_subtitle(),
        body.into(),
        nav_row(
            Some(Message::BackPage),
            Some((t_line("confirm_button"), Message::StartInstall, true)),
        ),
    )
}

fn installing(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let log = widget::container(
        widget::scrollable(
            widget::text::monotext(app.install_log())
                .size(12)
                .width(Length::Fill),
        )
        .height(Length::Fill),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill)
    .height(Length::Fill);

    // The install's real position, from fisherman's protocol
    // (shared/progress/README.md). This was indeterminate_linear() for the
    // whole install — docs/PARITY.md gap #2 — which told the user only that
    // something was happening, for the twenty minutes it takes.
    //
    // Indeterminate is kept for the window before the first event lands, so
    // the page never looks stalled while fisherman starts up; that is the one
    // moment when "something is happening" really is all that is known.
    let progress = app.progress();
    let bar: Element<'_, Message> = if progress.started() {
        widget::progress_bar::determinate_linear(progress.fraction)
            .width(Length::Fill)
            .into()
    } else {
        widget::progress_bar::indeterminate_linear()
            .width(Length::Fill)
            .into()
    };

    let mut children: Vec<Element<'_, Message>> = vec![bar];
    if progress.started() {
        // "Step 5 of 8 — Installing <product>…". The count comes from the
        // event, never a constant: fisherman computes total_steps from the
        // recipe.
        children.push(
            widget::text::caption(format!(
                "Step {} of {} — {}",
                progress.step,
                progress.total_steps,
                progress.step_label(branding::get())
            ))
            .into(),
        );
    }

    let body = widget::column::with_children({
        children.extend(vec![
        log.into(),
        widget::text::caption(t_line("progress_note"))
            .class(cosmic::theme::Text::Color(cosmic_theme.warning_text_color().into()))
            .into(),
        ]);
        children
    })
    .spacing(spacing.space_s)
    .height(Length::Fill);

    page_frame(
        t_line("progress_title"),
        INSTALLING_SUBTITLE,
        body.into(),
        widget::space::horizontal().into(),
    )
}

fn done(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let (title, detail) = done_copy(app.install_ok());
    let (icon, colour) = if app.install_ok() {
        ("emblem-ok-symbolic", cosmic_theme.success_text_color())
    } else {
        ("dialog-error-symbolic", cosmic_theme.destructive_text_color())
    };

    let mut hero = widget::column::with_children(vec![
        if app.install_ok() {
            done_logo(icon)
        } else {
            widget::icon::from_name(icon).size(64).icon().into()
        },
        widget::text::title2(title)
            .class(cosmic::theme::Text::Color(colour.into()))
            .into(),
        widget::text::body(detail).into(),
    ]);
    // store_label -> store_url on every frontend when the branding sets a
    // store (docs/PARITY.md).
    let store_url = branding::get().store_url.clone();
    if app.install_ok() && !store_url.is_empty() {
        hero = hero.push(
            widget::button::link(t_line("store_label")).on_press(Message::OpenUrl(store_url)),
        );
    }
    let hero = hero
        .spacing(spacing.space_s)
        .align_x(Alignment::Center)
        .width(Length::Fill);

    // The recovery key (#129). fisherman emits it once, after TPM enrolment,
    // and for a tpm2-luks install it is the only way back into the disk if
    // the TPM state changes. It used to go to the log pane and nowhere else:
    // the log scrolls, nothing pauses, and a user could reach this page and
    // restart having never seen it.
    //
    // A panel rather than a dialog, for the same reason XFCE uses one: a
    // dialog is dismissed and then the key is gone, while this stays on
    // screen for as long as it takes to write down.
    let key = app.progress.recovery_key.clone();
    let show_recovery = app.install_ok() && !key.is_empty();
    let recovery: Option<Element<'_, Message>> = show_recovery.then(|| {
        widget::column::with_children(vec![
            widget::text::title4(t_line("recovery_key_title")).into(),
            widget::text::body(t_line("recovery_key_body")).into(),
            widget::text::monotext(key.clone()).into(),
            widget::button::standard(t_line("recovery_key_copy"))
                .on_press(Message::CopyRecoveryKey)
                .into(),
            widget::checkbox(app.recovery_ack)
                .label(t_line("recovery_key_ack"))
                .on_toggle(Message::RecoveryAckToggled)
                .into(),
        ])
        .spacing(spacing.space_xs)
        .align_x(Alignment::Center)
        .width(Length::Fill)
        .into()
    });

    // Restart is the primary action after a successful install (the same
    // as the other frontends); Close stays available either way.
    //
    // While a recovery key is on screen it stays dead until the box is
    // ticked: leaving this page is what ends the chance to read the key. An
    // iced button with no on_press IS the disabled state.
    let restart_ready = !app.recovery_key_pending();
    let actions: Element<'_, Message> = if app.install_ok() {
        let mut restart = widget::button::suggested(t_line("done_restart"));
        if restart_ready {
            restart = restart.on_press(Message::Reboot);
        }
        widget::row::with_children(vec![
            widget::space::horizontal().into(),
            widget::button::standard(DONE_CLOSE)
                .on_press(Message::Quit)
                .into(),
            restart.into(),
        ])
        .spacing(spacing.space_s)
        .into()
    } else {
        nav_row(None, Some((DONE_CLOSE.to_string(), Message::Quit, false)))
    };

    let mut children: Vec<Element<'_, Message>> = vec![
        widget::space::vertical().into(),
        hero.into(),
    ];
    if let Some(panel) = recovery {
        children.push(panel);
    }
    children.push(widget::space::vertical().into());
    children.push(actions);

    widget::column::with_children(children)
        .spacing(spacing.space_m)
        .height(Length::Fill)
        .into()
}

/// Title, subtitle, scrolling body, navigation footer.
fn page_frame<'a>(
    title: impl Into<std::borrow::Cow<'a, str>> + 'a,
    subtitle: impl Into<std::borrow::Cow<'a, str>> + 'a,
    body: Element<'a, Message>,
    footer: Element<'a, Message>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    widget::column::with_children(vec![
        widget::text::title2(title).into(),
        widget::text::caption(subtitle).into(),
        widget::divider::horizontal::default().into(),
        body,
        widget::divider::horizontal::default().into(),
        footer,
    ])
    .spacing(spacing.space_s)
    .height(Length::Fill)
    .into()
}

#[cfg(test)]
mod tests {
    use super::encryption_text;

    #[test]
    fn every_encryption_type_has_a_label_and_a_description() {
        for id in crate::validate::choices().iter().map(|c| c.enc_type.as_str()) {
            assert!(!encryption_text(id, "_label").is_empty(), "{id}: no label");
            assert!(
                !encryption_text(id, "_description").is_empty(),
                "{id}: no description"
            );
        }
    }

    /// The parity report credits a page with a screen when its text holds
    /// one of that screen's keywords. The account page is none of them.
    #[test]
    fn the_account_page_matches_no_parity_screen_keyword() {
        use super::copy::*;
        let report = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../shared/walkthrough/parity_report.py"
        ))
        .expect("parity_report.py");
        let mut keywords = Vec::new();
        for list in report.split("\"keywords\": [").skip(1) {
            let list = &list[..list.find(']').expect("keyword list ends")];
            for (i, part) in list.split('"').enumerate() {
                if i % 2 == 1 {
                    keywords.push(part.replace("\\u2026", "\u{2026}").to_lowercase());
                }
            }
        }
        assert!(keywords.len() > 20, "keywords not found: {keywords:?}");
        let page = [
            ACCOUNT_TITLE, ACCOUNT_SUBTITLE, ACCOUNT_SECTION, ACCOUNT_USERNAME,
            ACCOUNT_USERNAME_HINT, ACCOUNT_FULLNAME, ACCOUNT_FULLNAME_HINT,
            ACCOUNT_PASSWORD, ACCOUNT_PASSWORD_HINT, ACCOUNT_PASSWORD_CONFIRM,
            ACCOUNT_PASSWORD_CONFIRM_HINT, ACCOUNT_PASSWORD_MISMATCH, BACK, CONTINUE,
        ]
        .join(" ")
        .to_lowercase();
        for k in &keywords {
            assert!(!page.contains(k.as_str()), "the account page says {k:?}");
        }
    }

    #[test]
    fn the_confirm_page_names_the_type_rather_than_its_id() {
        // The summary row used to print the raw recipe id.
        assert_eq!(encryption_text("luks-passphrase", "_label"), "Passphrase");
        assert_eq!(encryption_text("none", "_label"), "No encryption");
        // fisherman reads "" as none; so does the summary.
        assert_eq!(encryption_text("", "_label"), "No encryption");
    }
}

# Branding contract

Every frontend shows a product name, seeds a hostname, writes a `distroID`
into the fisherman recipe and links to a website. None of that may be
hardcoded to a product. Each frontend resolves it the same way, in this
order, per key:

1. **A branding file**, `branding.json`. The first readable one wins, no
   merging across files:
   - the path in `$BOOTC_INSTALLER_BRANDING` (tests and screenshot harnesses);
   - `/run/host/etc/bootc-installer/branding.json`
   - `/run/host/usr/share/bootc-installer/branding.json`
   - `/etc/bootc-installer/branding.json`
   - `/usr/share/bootc-installer/branding.json`

   Host paths come first because every frontend ships as a Flatpak, where
   `/etc` is the runtime's. A live-ISO builder that wants to name the
   product, pick the default image or point at its own docs drops one file
   under `/etc/bootc-installer/`.
2. **`os-release`**, for every key the file does not set: the first readable
   of `/run/host/etc/os-release`, `/run/host/usr/lib/os-release`,
   `/etc/os-release`, `/usr/lib/os-release`.
3. **Neutral defaults**, never a product name.

`$BOOTC_INSTALLER_PRODUCT_NAME`, when set and non-empty, overrides `name`
only. The screenshot workflows use it so the committed walkthrough does not
read "Install Ubuntu 24.04 LTS" from the runner's os-release.

## Keys

| Key | `branding.json` | `os-release` fallback | neutral default |
|---|---|---|---|
| `name` | `name` | `PRETTY_NAME`, else `NAME` | `Linux` |
| `id` | `id` | `ID` | `linux` |
| `vendor` | `vendor` | `VENDOR_NAME`, else `NAME` | `""` |
| `home_url` | `home_url` | `HOME_URL` | `""` |
| `docs_url` | `docs_url` | `DOCUMENTATION_URL` | `""` |
| `support_url` | `support_url` | `SUPPORT_URL` | `""` |
| `logo` | `logo` (icon name or path) | `LOGO` | `""` |
| `default_hostname` | `default_hostname` | `DEFAULT_HOSTNAME`, else `ID` | `linux` |
| `default_image` | `default_image` (OCI reference) | none | `""` |

Values are strings; an empty or missing value in the file falls through to
the next source. Unknown keys are ignored, so a file may carry
frontend-specific extras. `shared/branding/branding.schema.json` is the
schema.

What each frontend does with them:

- `name`: every title and sentence that names the product ("Install
  {name}", "{name} is installed", window title).
- `id`: the recipe's `distroID`.
- `default_hostname`: the hostname field's initial value (GNOME derives a
  hardware name and uses this only as the fallback stem).
- `default_image`: the image installed when the frontend offers no catalog
  choice and the system is not a live ISO (Niri, COSMIC). Empty means the
  frontend must have another source or refuse to install.
- `home_url`, `docs_url`, `support_url`, `vendor`: about dialogs and help
  rows; a row whose URL is empty is hidden.
- `logo`: welcome and done page artwork; a themed icon name or an absolute
  path.

### One file for every desktop

Ship the same `/etc/bootc-installer/branding.json` in every live image.
`fixtures/fork-branding.json` is a minimal name/logo/URL example exercised
by all four language resolvers. There is no desktop-specific logo key.
Omitted identity fields retain the existing os-release fallbacks; the
example does not rename the base OS ID or hostname, or select a new image.

The portable `logo` forms are an absolute file path or an icon-theme name.
Use an absolute SVG or PNG installed in the live image for consistent
artwork across desktops: theme names depend on the installed theme.
`/usr/` and `/etc/` file paths map under `/run/host` **only in Flatpak**.
Other absolute paths, including `/app/` and already mapped `/run/host/`
paths, are unchanged. Files are interpreted as paths, so spaces and `#`
are not URL delimiters. Remote URLs and relative paths are not loaded.
`fixtures/logo-paths.json` locks down these rules for each adapter.

The non-GNOME frontends render this logo on welcome and successful
completion; failed installs keep their existing error presentation.
Missing files or themed icons retain each frontend's neutral fallback
(XFCE's text-only layout). GNOME and XFCE additionally understand GTK
`resource:///` references, but these are application resources and are
not portable live-image paths. Other `assets` keys still have the coverage
shown in `docs/PARITY.md`; a shared configuration does not imply that every
frontend implements every optional artwork slot.

## Flavour text, assets and the store

Everything a product might want to say in its own voice is a `copy` key.
The neutral lines are in `copy-defaults.json`; a `branding.json` sets any
subset under `"copy"`, and a key it sets to `""` hides that line wherever a
frontend can hide it. `{name}` is the product name and `{disk}` the disk
about to be erased.

| Key | Where it shows |
|---|---|
| `welcome_title`, `welcome_subtitle` | welcome heading and line under it |
| `welcome_install`, `welcome_install_subtitle`, `welcome_button` | the install row (GNOME) or the forward button |
| `encryption_<type>_label`, `encryption_<type>_description` | each encryption choice, and the confirm page's encryption row (the label) |
| `confirm_title`, `confirm_subtitle`, `confirm_body`, `confirm_warning`, `confirm_button` | the last page before the disk is written |
| `progress_title`, `progress_note` | while fisherman runs |
| `step_<step_id>` | the label of the install step that is running |
| `recovery_key_title`, `recovery_key_body`, `recovery_key_copy`, `recovery_key_ack` | the recovery-key panel after a TPM enrolment |
| `done_title`, `done_subtitle`, `done_restart`, `done_failed_title` | the done page |
| `store_label` | the store link on the done page, shown only when `store_url` is set |

### Encryption choices

`<type>` is a recipe encryption type with `-` written as `_`, for example
`encryption_tpm2_luks_passphrase_label`. The types and their display order
are the `encryption.type` enum in `shared/recipe/fisherman-recipe.schema.json`:
`none`, `luks-passphrase`, `tpm2-luks`, `tpm2-luks-passphrase`. An empty
type means `none`.

The list of ids, with `needs_passphrase` and `needs_tpm2` for each, is
fisherman's `data/encryption-choices.json`, copied to
`shared/recipe/encryption-choices.json`. Its `copy_key` is the stem of these
keys. A frontend reads its copy of that file. It builds each key from the id
and gets the words from its resolver. The confirm page shows the label of
the chosen type, never the id. `tests/unit/test_encryption_choices.py`
holds each copy to fisherman's file, and fails if a frontend hardcodes the
words or decides by the type's name. Do not set a label to `""`: the choice
then has no name.

### Recipe problems

`fisherman validate --json` reports each problem with a stable `code`
(`fisherman/docs/VALIDATE.md`). The line a frontend shows is the copy key
`validate_<code>`, for example `validate_hostname_invalid_char`. There is
one key for each code fisherman has; `tests/unit/test_shared_validate.py`
fails if a code has no key, or a key names a code that fisherman does not
have. A frontend joins the prefix and the code, so it renders every key of
the family. For a code with no line, or an empty one, the frontend shows
fisherman's English `message`. `shared/recipe/README.md` says how a
frontend asks.

### Install steps

fisherman gives each step it starts a stable `step_id` on its progress
stream (`shared/progress/README.md`). The label of that step is the copy key
`step_<step_id>`, for example `step_install_os`. The ids are:

| `step_id` | fisherman step | Default label |
|---|---|---|
| `prepare_disk` | Preparing disk | Checking your drive… |
| `partition` | Partitioning disk | Setting up your drive… |
| `format_efi` | Formatting EFI partition | Preparing the boot system… |
| `luks` | Setting up disk encryption | Securing your drive… |
| `format_root` | Formatting root filesystem | Formatting your drive… |
| `mount` | Mounting filesystem | Almost ready… |
| `format_var` | Formatting data disk (/var) | Preparing data storage… |
| `install_os` | Installing OS | Installing {name}… |
| `tpm2_enroll` | Enrolling TPM2 auto-unlock | Setting up auto-unlock… |
| `flatpaks` | Copying system Flatpaks | Installing your apps… |
| `configure` | Configuring installed system | Configuring your system… |
| `finalize` | Finalizing installation | Finishing up… |

fisherman owns the list. It never renames or reuses an id; a new step gets
a new id. A frontend keeps no list: it builds the key from the id on the
event and gets the words from its resolver. When the event has no
`step_id`, or the copy has no line for it, the frontend shows fisherman's
`step_name`. Thus a new step shows its real name until it gets a key. Do not
set a step label to `""`: the frontend then shows the step name.
`tests/unit/test_shared_progress.py` compares these keys with the ids in
fisherman's `internal/progress/bar.go`.

`confirm_quotes` maps a language tag (`"pt_BR"`) to lines used as the
confirm subtitle in that language. `assets` holds absolute host paths
(`welcome_image`, `complete_image`, `store_qr`); an empty or missing asset
hides or skips the element. `store_url` has no os-release fallback.

The aim is that every key above is rendered by every frontend, so a
product branded once reads the same on GNOME, KDE, COSMIC, Niri and Xfce.
`docs/PARITY.md` is the matrix and it is not all yes yet: the keys a
frontend still hardcodes are listed as `KNOWN_GAPS` in
`tests/unit/test_copy_coverage.py`, which fails both on a gap that is not
listed and on a listed gap that has since been closed. Nothing one desktop
alone can show is in the contract.
What a single frontend renders on top goes under `extensions.<frontend>`
in the branding file, read only by that frontend: today `extensions.gnome`
carries the tour page text, the install video and the credits file. Each
language embeds a byte-identical copy of `copy-defaults.json` (checked by
the identity test), so no frontend needs a data file at runtime. Niri's QML
cannot read a file at all, so its fallback table is generated into
`frontends/niri/ui/installer.qml` by `generate-qml-defaults.py`; run it
after any edit here, alongside the other copies.

`examples/bluefin/` is a complete branding for Bluefin, lifted from what
the GNOME frontend used to hardcode; its README says how a live ISO ships
it.

## Pinning branding for screenshots

A capture resolves branding exactly as the installer does, so an unpinned
capture is branded by the machine that took it. `shared/walkthrough/capture-branding.json`
is the pin, and both GTK capture harnesses point `BOOTC_INSTALLER_BRANDING`
at it (with `setdefault`, so a workflow naming a real product's file wins).

Pin the **whole object**, not `BOOTC_INSTALLER_PRODUCT_NAME`. That variable
covers `name` and nothing else, which is how the committed
`docs/screenshots/01-welcome.png` came to show the Ubuntu logo above
"Welcome to TunaOS" — os-release's `LOGO=ubuntu-logo` was never overridden.
XFCE showed the same fault in text: its heading read "Welcome to Ubuntu
24.04.5 LTS" next to a body reading "installs TunaOS", because only the one
f-string that reads `core.PRODUCT_NAME` had been pinned and every copy key
still came from the host.

`tests/unit/test_shared_branding.py::CaptureBrandingPinTest` resolves the pin
against a deliberately foreign os-release and fails if any host value
survives. Niri needs no env pin — its capture stubs the whole branding object
in `tests/qml-stubs`, which is why its walkthrough was always right.

## Implementations

One per language, each reading the same fixtures under `fixtures/`:

| Frontend | Resolver | Test |
|---|---|---|
| GNOME | `bootc_installer/utils/branding.py` (byte-identical copy of `branding.py`) | `tests/unit/test_shared_branding.py` |
| XFCE | `frontends/xfce/tuna_installer_xfce/branding.py` (byte-identical copy) | `frontends/xfce/tests/test_branding.py` |
| Niri | `frontends/niri/installer/branding.go` | `frontends/niri/installer/branding_test.go` |
| KDE | `frontends/kde/src/branding.{h,cpp}` | `frontends/kde/tests/test_backend.cpp` |
| COSMIC | `frontends/cosmic/src/branding.rs` | its `#[cfg(test)]` module |

`fixtures/expected.json` lists the outcome for three cases: file plus
os-release, os-release only, nothing readable. A resolver that disagrees
with it is wrong, whichever language it is in.

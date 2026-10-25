# Frontend parity

The GNOME frontend is the reference: it is the one that shipped and has
end-to-end tests. This page records what each of the other four renders
of the same contract. Each gap then shows as a line here, not as a surprise on an
ISO. `docs/DESIGN-AUDIT.md` covers how each looks against its desktop;
this page covers what each does.

## Branding copy keys

Every key in `shared/branding/copy-defaults.json` is a line a product may
rebrand. A frontend "renders" a key when the line appears where the table
says. "Hidden" means the frontend shows nothing for an empty value. "No"
means the frontend shows its own hardcoded text, so a product cannot
rebrand that line.

`tests/unit/test_copy_coverage.py` enforces the "no" cells. It scans each
frontend for every key and compares what it finds against its own
`KNOWN_GAPS` table. An unlisted gap fails the test. So does a listed gap
that the frontend has since closed. Before that check, four cells here
claimed a render that nobody had wired up.

| Key | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| `welcome_title` | page header | heading | title1 | heading | page title |
| `welcome_subtitle` | header subtitle, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `welcome_install` | install row title | no (own body text) | no (no install row) | no (no install row) | live-system radio |
| `welcome_install_subtitle` | install row subtitle | no | no | no | live-system radio subtitle |
| `welcome_button` | no (row activates, own label) | Next button on welcome | forward button | button | Next button on welcome |
| `requirements_title` | gate window text (blocks) | welcome inline message | welcome warning row | welcome warning | welcome warning row |
| `requirements_ram` | RAM gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `requirements_cpu` | CPU gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `requirements_uefi` | UEFI gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `encryption_none_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_none_description` | no (an on/off switch, no row for this choice) | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_luks_passphrase_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_luks_passphrase_description` | subtitle of the encrypt switch | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_tpm2_luks_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_tpm2_luks_description` | no (the page cannot select this type) | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_tpm2_luks_passphrase_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_tpm2_luks_passphrase_description` | subtitle of the TPM switch | radio row description | dropdown description | list row subtitle | caption under the radio |
| `confirm_title` | page header | step heading | page title | heading | page title |
| `confirm_subtitle` | header subtitle | italic label, hidden | page subtitle | label, hidden | label, hidden |
| `confirm_body` | dim label, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `confirm_warning` | summary warning row (own group above the summary, `{disk}` filled) | inline message | warning card | warning line | warning row naming the selected disk |
| `confirm_button` | pill button | Next button | forward button | button | Next button |
| `confirm_quotes` | random line per language | no | no | no | no |
| `progress_title` | image-writing step label (centred title) | label | page title | heading | page title |
| `progress_note` | dim caption under the bar | label | warning caption | caption | dim label under the bar |
| `step_prepare_disk` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_partition` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_efi` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_luks` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_root` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_mount` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_var` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_install_os` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_tpm2_enroll` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_flatpaks` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_configure` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_finalize` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `recovery_key_title` | page heading | heading | heading | heading | heading |
| `recovery_key_body` | label | label | body | label | label |
| `recovery_key_copy` | copy button tooltip | copy button | copy button | copy button | copy button |
| `recovery_key_ack` | checkbox | checkbox | checkbox | checkbox | checkbox |
| `done_title` | page header | heading | title2 | heading | headline |
| `done_subtitle` | header subtitle (+ elapsed time) | label | body | label | label |
| `done_restart` | Reboot Now button | Restart button | suggested button | button | suggested button beside Close |
| `done_failed_title` | page header | heading | title2 | heading | headline |
| `validate_*` | error line under the hostname (disk and confirm pages) and the username | inline message on the encryption step (passphrase) and the confirm step (hostname) | hostname row description; encryption row description | line under the hostname (confirm) and under the passphrase | line under the hostname, the username and the encryption choice |
| `store_label` | done page link to `store_url` (+ QR from `assets.store_qr`, US locale) | done page link | done page link | done page link | done page link |
| `logo` | product icon (GNOME file adapter tracked separately) | theme/file on welcome and successful done, after the asset; else `system-software-install` / `checkmark` | theme/file on welcome and successful done, after the asset; else `computer-symbolic` in an accent disc / the check | theme/file on welcome and successful done | theme/file/resource on welcome and successful done |
| `assets.welcome_image`, `assets.complete_image` | tour pages | welcome / successful done artwork, before `logo` | welcome / successful done artwork, before `logo` | welcome logo disc (`logo`) | no |

The eight `encryption_*` keys name the four types of encryption in the
recipe. The order of the types is the `encryption.type` enum in
`shared/recipe/fisherman-recipe.schema.json`. All five frontends use the same
words on the encryption page and on the confirm page.
`tests/unit/test_encryption_choices.py` makes sure that each frontend offers
those types in that order.

The confirm pages used to disagree. KDE showed "None" and "Passphrase
(LUKS)". GNOME showed its own phrases. COSMIC, Niri and Xfce showed the
recipe id, for example `luks-passphrase`. GNOME has a switch and a TPM
switch, not a list. Thus it shows only the two descriptions that its
switches can select.

The twelve `step_*` keys label the install step that runs. fisherman puts a
stable `step_id` on each step event, and each frontend reads the key
`step_<step_id>`. An event without a `step_id`, or an id with no copy line,
shows fisherman's `step_name`.

Before this, Niri showed the raw step name.
GNOME, Xfce, KDE and COSMIC each had their own table of the same words, so a
product could not change them. Those tables stay only as the fallback for a
fisherman without `step_id`. All five also draw the bar from fisherman's
`overall_pct` (`shared/progress/README.md`). Thus the bar now moves during
the Flatpak copy, where the old calculation in each frontend stopped.
XFCE hides its step label when it repeats the page title, which is the case
for `step_install_os` with the default copy.

The `validate_*` keys word fisherman's problems. Each frontend sends its
fields to `fisherman validate --json --partial -` while the user types and
shows each problem through the key `validate_<code>`
(`shared/recipe/README.md`). The codes are fisherman's
(`fisherman/docs/VALIDATE.md`), so the table has one row for the family. A
code with no copy line shows fisherman's own message. Before this, only
XFCE checked the hostname, and a username such as `root` failed after the
OS was on disk.

Outside the contract, under `extensions.gnome`: the tour page text, the
install video and the credits file. They are the last GNOME-only features.
The plan is to port the tour artwork (welcome and complete images) to the
other four. Video and credits then leave the contract; nothing else gets
them.

All five render the identity keys (`name`, `id`, `default_hostname`,
`default_image`, URLs); see `shared/branding/README.md`.

## Features

| Feature | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| Image catalog choice | yes (fisherman `images.json`) | no (live or `default_image`) | no (live or `default_image`) | no (live or `default_image`) | yes |
| Live-ISO install without download (live media from `fisherman probe --json`) | yes | yes | yes | yes | yes |
| Offline image stores (found by fisherman on the host) | yes | yes | yes | yes | yes |
| Recipe on fisherman's stdin, no recipe file | yes | yes | yes | yes | yes |
| Fields checked by `fisherman validate --json --partial` | hostname, username | passphrase, hostname | hostname, passphrase | hostname, passphrase | hostname, username, passphrase |
| Disk choice with erase warning | yes | yes | yes | yes | yes |
| Disk list from `fisherman probe --json` (`shared/probe/`) | yes | yes | yes | yes | yes |
| Disk row: model (path when unknown), path, size label, bus | yes | yes | yes | yes | yes |
| Disk probe failure shown on the disk page | yes | yes | yes | yes | yes |
| RAM / CPU / UEFI check (fisherman's `system.unmet`) | blocks (gate window) | warns on welcome | warns on welcome | warns on welcome | warns on welcome |
| Filesystem choice | yes | no (xfs, shown on confirm) | yes | no (xfs) | yes (Advanced) |
| Encryption: none / passphrase | yes | yes | yes | yes | yes |
| Passphrase typed twice, Next held on a mismatch | yes | yes | yes | yes | yes |
| Encryption: TPM / TPM + passphrase | yes | yes | yes | yes | yes |
| Recovery key page after TPM enrolment | yes | yes | yes | yes | yes |
| Hostname | generated, editable on confirm | no (branding default, shown on confirm) | field | field on confirm | field |
| User account | yes (companion or wizard) | yes (account step) | yes (account page) | yes (account page) | yes |
| Phone companion (QR) | yes | no | no | no | no |
| Keyboard / language / timezone | yes | no | no | no | no |
| Progress bar from fisherman's protocol | yes | yes | yes | yes | yes |
| Restart from the done page | yes | yes | yes | yes | yes |
| Show log after failure | yes | log path | log in page | log in page | log tail |
| Step indicator for the six-step contract | page header | "Step N of 7 · name" + dots | "Step N of 7 · name" + bar | "Step N of 7 · name" + dots | page title |
| Screenshot walkthrough + parity report | yes | yes | yes | yes | yes |
| End-to-end gate (real install and boot) | yes | yes | yes | yes | yes |

## Closing the gaps, in order

1. ~~**Encryption set** (KDE, XFCE)~~ — **not a gap.** Both offer TPM and
   TPM + passphrase today. Each hides the two choices when fisherman's
   `tpm.usable` is false. No CI runner has a TPM. The capture thus showed
   only two of the choices, and this table copied it. The captures now read
   `shared/probe/fixtures/laptop.json`, which has a usable TPM, so they show
   all four.
2. ~~**Progress bar**~~ — **closed.** All five read
   `shared/progress/README.md` now. This entry said that fisherman emits
   `[n/9]`. It does not. Three frontends used that claim, so their bars
   stayed at zero. Their fixtures used the same shape, so the pictures
   showed a bar that moved. Drive the bar from `cumulative_pct`, not from
   `step / total_steps`: `total_steps` changes with the recipe, and one
   step takes 87% of the time.
3. ~~**Recovery key page**~~ — closed. fisherman prints the key after TPM
   enrolment. GNOME shows a page. The other four show a panel on the done
   screen. Each holds the restart button until the user acknowledges the
   key (#129).
4. ~~**User account** (KDE, COSMIC, Niri)~~ — **closed.** Each now has a
   required account step (username, optional full name, password typed
   twice) that writes the recipe's `user` block in `wheel`, as XFCE does.
   Their TunaOS images all set `needs_user_creation`, so an install used to
   end with nobody to sign in as. The extra step makes their indicators read
   "of 7"; the screen contract is unchanged, and the account pages match no
   contract keyword. `shared/e2e/check-recipe.py` (`USER_STEP`) fails the
   E2E for any of the three that hands fisherman no user.
5. **Store and tour assets**: only worth it where the desktop has a place
   for artwork. Every resolver already resolves the keys, so this is view
   work only. KDE and COSMIC now show `welcome_image` and
   `complete_image` as the welcome and done artwork, ahead of `logo`.
6. **Companion and locale steps**: GNOME-only by design for now. Windows
   data migration (slurp) is not an installer feature at all: it belongs to
   wootc, and no frontend here offers it. The
   contract keeps their copy keys out of `copy-defaults.json`, so nothing
   else pretends to have them.

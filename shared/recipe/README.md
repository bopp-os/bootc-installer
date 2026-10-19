# The recipe: schema, validation and encryption choices

Every frontend builds one JSON recipe and gives it to fisherman. fisherman
owns the rules for that recipe. This directory holds what a frontend needs
to write the recipe and to show fisherman's answer about it.

| File | What |
|---|---|
| `fisherman-recipe.schema.json` | The recipe schema. KDE keeps a byte-identical copy (`tests/unit/test_shared_recipe_schema.py`). |
| `encryption-choices.json` | fisherman's `data/encryption-choices.json`, byte for byte: the encryption types in display order, with `needs_passphrase`, `needs_tpm2` and the branding `copy_key`. |
| `fisherman_validate.py` | The Python reader for `fisherman validate --json` and the choices file. GNOME and XFCE carry byte-identical copies. |

## Give the recipe to fisherman on stdin

A frontend writes no recipe file. It runs fisherman with `-` and writes the
JSON to the wrapper's stdin, then closes stdin:

```sh
bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'
# in a Flatpak:
flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'
```

`pkexec`, `sudo` and `flatpak-spawn --host` pass stdin through. fisherman
reads to EOF, so the writer must close its end. The recipe can hold the LUKS
passphrase and the user password, so it must not go into a temporary file or
onto the command line.

The cancel contract does not change: start the wrapper in its own process
group and kill that group to cancel. fisherman then exits 130 (see the cancel section of
`fisherman/docs/JSON-PROGRESS-FORMAT.md`).

## Image stores and live media are fisherman's facts

- Leave `additionalImageStores` out. fisherman then exposes the offline
  stores it finds on the host, the same ones `fisherman probe --json` lists
  under `offline.stores`. Write the field only when the ISO's own recipe
  names stores. `[]` turns the discovery off.
- An empty `image` tells fisherman to install the image that the live
  media booted. fisherman rejects it (`image_required`) unless the host
  booted from live media. A frontend reads that from the probe: send an
  empty `image` only when `live.is_live` is true, and show
  `live.live_image` as the image.
- A tag such as "available offline" comes from the probe's
  `offline.images`.

A frontend that looked for these itself ran inside its Flatpak sandbox,
where the host's `/etc` and `/usr` are not visible, so it found nothing.
GNOME also treated every ostree host as live media.
`tests/unit/test_no_frontend_detection.py` fails if a frontend does that
again.

## Validate while the user types

`fisherman validate --json --partial -` checks only the fields that are
present. It reads nothing from the machine and needs no root. Send the page
as a partial recipe on stdin:

```console
$ echo '{"hostname":"-router"}' | fisherman validate --json --partial -
{"protocol_version":1,"valid":false,"errors":[{"field":"hostname","code":"hostname_label_hyphen","message":"…"}]}
```

Show each problem through the copy key `validate_<code>`
(`shared/branding/copy-defaults.json`). Show fisherman's `message` for a
code that has no copy line. If the check cannot run, show nothing and do not
block: the install runs the same rules before it touches a disk. Run the
check off the UI thread, after a short pause in the typing.

The schema, the codes and the rules are in `fisherman/docs/VALIDATE.md`.
The frontend still owns these rules, which are not fisherman's: the user
password is not empty, it matches its confirmation, and how strong it is.

| Frontend | Fields it validates | How |
|---|---|---|
| GNOME | hostname (disk page), username (user page) | `fisherman_validate.LiveCheck` |
| KDE | passphrase (encryption step), hostname (confirm step) | `InstallerController::runValidate`, a `QProcess` |
| COSMIC | hostname, passphrase | `validate::check`, on a blocking task |
| Niri | hostname, passphrase | the backend's `validate` command, from a QML `Process` |
| XFCE | hostname, username, passphrase | `fisherman_validate.LiveCheck` |

## Encryption choices

Offer the types in the order of `encryption-choices.json`. Offer a
`needs_tpm2` type only when the probe says `tpm.usable`. Show the
passphrase field only for a `needs_passphrase` type. The label is the copy
key `<copy_key>_label`, the description `<copy_key>_description`.

`tests/unit/test_encryption_choices.py` holds the shared copy to the
submodule's file, and each frontend's copy to the shared one.

### GNOME live-media storage adapter

When the image step is absent, the GNOME system recipe may specify canonical
`composeFsBackend` (boolean), `bootloader`, `filesystem`, `imageType`, and
`flatpakVarPath`. These describe the image being installed, independently of
branding. For each field the adapter prefers explicit image-step metadata,
then the top-level system recipe, then matching image-catalog metadata.
An explicit `false` backend flag is preserved. Catalog matching follows nested
inheritance and registry/tag shorthand; unrelated first rows never choose the
backend. Matching uses the selected reference before NVIDIA and local-source
overrides. Empty strings fall through; malformed types and unsupported
filesystem/bootloader names stop recipe generation before fisherman launches.

Root filesystem values are the existing fisherman schema values (`xfs`,
`ext4`, `btrfs`, `zfs`); an image requirement overrides the disk picker and clears
stale btrfs subvolume selection when necessary. Manual mounts are retained.
The adapter does not infer a filesystem from the backend or relax fisherman
validation: for example, composefs plus XFS remains invalid. Sealed images may
use ext4 with either bootc storage backend, as specified by the image producer.
`local_imgref` changes the install source only (including an `oci:/...` source);
`targetImgref` continues to identify the selected update-tracking image.

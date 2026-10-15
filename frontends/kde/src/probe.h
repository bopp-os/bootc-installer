#pragma once

// Hardware facts from `fisherman probe --json` (shared/probe/README.md).
//
// fisherman decides which disks may be installed to, labels their sizes, and
// answers TPM 2.0 and the RAM/CPU/UEFI requirements. This frontend used to
// parse `lsblk -J` itself, offered every TYPE == disk (zram and the live USB
// included), showed lsblk's own size strings, and probed the TPM itself. This
// reader only runs the command and keeps the answer; it filters and formats
// nothing.

#include <QByteArray>
#include <QList>
#include <QString>
#include <QStringList>

namespace probe {

// The schema version this reader understands (fisherman/docs/PROBE.md).
inline constexpr int PROTOCOL_VERSION = 1;

// Test and screenshot seam: a file holding probe output. When set, no
// process runs. Every frontend honours the same variable.
inline constexpr const char *FAKE_ENV = "BOOTC_INSTALLER_FAKE_PROBE";

// One eligible disk, as every frontend renders it.
struct Disk {
    QString path;           // "/dev/nvme0n1"
    QString title;          // model, or path when the model is unknown
    QString model;
    QString sizeLabel;      // fisherman's size_label, verbatim ("953.9 GiB")
    QString transportLabel; // "NVMe", "SATA", "USB", ... or ""
    bool removable = false;
};

struct Result {
    bool ok = false;
    QString error;          // why the probe failed; empty when ok
    QList<Disk> disks;      // eligible only, in fisherman's order
    bool tpmUsable = false;
    QStringList unmet;      // "ram", "cpu", "uefi"
    // live.is_live: the host booted from live media. Only then may the
    // recipe leave `image` empty, which installs the running system.
    bool isLive = false;
    QString liveImage;      // live.live_image when live, else ""
    // offline.images: refs in the host's offline stores. The stores are
    // fisherman's: a recipe without additionalImageStores gets them.
    QStringList offlineImages;
};

// Parses probe output. A failure is a Result with ok == false and an error.
Result parse(const QByteArray &json);

// The unprivileged command: the fisherman the install runs, on the host
// (flatpak-spawn --host when sandboxed). Never pkexec or sudo.
QStringList command(bool flatpak);

// Runs the probe (or reads BOOTC_INSTALLER_FAKE_PROBE). There is no
// fallback scan: on failure, `error` says why and `disks` is empty.
Result run();

}

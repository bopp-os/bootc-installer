#pragma once

// Product branding: a branding.json first, os-release second, neutral last.
//
// The contract, the key table and the fixtures are in shared/branding/ at the
// monorepo root; every frontend resolves the same way and this is the C++
// copy, tested against the shared fixtures by tests/test_backend.cpp.
// Nothing in this file names a product.

#include <QHash>
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include <QVariantMap>

namespace branding {

struct Branding {
    QString name;
    QString id;
    QString vendor;
    QString homeUrl;
    QString docsUrl;
    QString supportUrl;
    QString logo;
    QString defaultHostname;
    QString defaultImage;
    QString storeUrl;
    // Every user-facing line a product may rebrand (copy-defaults.json, with
    // the branding file's `copy` merged over it); {name}/{disk} placeholders.
    QHash<QString, QString> copy;
    QHash<QString, QString> assets;
    QHash<QString, QStringList> confirmQuotes;

    // A copy line with {name} (and the given placeholders) filled in.
    QString text(const QString &key, const QHash<QString, QString> &values = {}) const;
    // The copy map as QML sees it (InstallerController.copy).
    QVariantMap copyAsVariantMap() const;
};

// Portable logo contract: a theme icon or an absolute local path. Keep the
// unescaped path separate from the QML URL so '#' and '%' remain filename
// characters, rather than URL fragments or escapes.
struct Logo {
    enum class Kind { None, Theme, File };
    Kind kind = Kind::None;
    QString value;

    QString source() const;
};

// Map host /usr/ and /etc/ paths only inside a Flatpak. No filesystem or
// icon-theme lookup here; Kirigami handles unavailable artwork via fallback.
Logo resolveLogo(const QString &spec, bool inFlatpak);

// copy-defaults.json (frontends/kde/copy-defaults.json, a byte-identical copy
// of shared/branding/copy-defaults.json) minus its "_comment".
QHash<QString, QString> copyDefaults();

// The branding for this machine: $BOOTC_INSTALLER_BRANDING or the standard
// branding.json paths (host first, this ships as a Flatpak), then os-release,
// then a neutral "Linux". $BOOTC_INSTALLER_PRODUCT_NAME overrides `name` only
// (screenshot harness).
Branding resolve();

// The same, with explicit search lists; what resolve() calls.
Branding resolveFrom(const QStringList &brandingPaths, const QStringList &osReleasePaths,
                     const QString &nameOverride);

// The pure merge rule from shared/branding/README.md, exposed for tests.
Branding fromSources(const QJsonObject &file, const QString &osReleaseText,
                     const QString &nameOverride = QString());

// KEY=value pairs from os-release text, quotes and backslash escapes removed.
QHash<QString, QString> parseOsRelease(const QString &text);

} // namespace branding

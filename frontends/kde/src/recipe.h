#ifndef RECIPE_H
#define RECIPE_H

#include <QJsonObject>
#include <QString>
#include <QStringList>

struct Recipe {
    QString disk;
    QString filesystem = "xfs";
    bool btrfsSubvolumes = false;
    struct {
        // One of encryptionTypes().
        QString type = "none";
        QString passphrase;
    } encryption;
    QString image; // may stay empty in live-ISO mode (bootc installs the running container)
    QString targetImgref;
    QString bootloader;        // "", "grub2", "systemd"
    bool composeFsBackend = false;
    QStringList flatpaks;
    // Offline OCI stores. Left empty (so absent), fisherman exposes the
    // stores it finds on the host; the wizard never fills it.
    QStringList additionalImageStores;
    QString distroID;            // filled from the branding contract by the controller
    // true makes bootc boot the installed system with selinux=0. Keep SELinux on.
    bool selinuxDisabled = false;
    QString hostname;            // likewise: branding default_hostname
    // fisherman's probe says the host booted from live media: an empty image
    // installs the running system, and is left out of the JSON.
    bool liveMode = false;

    QJsonObject toJson() const;
    static Recipe fromJson(const QJsonObject &obj);
    bool isValid() const;
    QString validationError() const;

    // The encryption types fisherman accepts, in the order the encryption
    // step offers them: the compiled-in copy of fisherman's
    // encryption-choices.json (tests/unit/test_encryption_choices.py).
    static const QStringList &encryptionTypes();
    // That file's needs_passphrase and needs_tpm2 for a type ("" is none).
    static bool needsPassphrase(const QString &type);
    static bool needsTpm2(const QString &type);
};

#endif // RECIPE_H

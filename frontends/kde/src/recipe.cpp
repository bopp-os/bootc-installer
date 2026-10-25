#include "recipe.h"
#include "encryption_choices.h"
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>

QJsonObject Recipe::toJson() const
{
    QJsonObject obj;
    obj["disk"] = disk;
    obj["filesystem"] = filesystem;
    obj["btrfsSubvolumes"] = btrfsSubvolumes;
    QJsonObject enc;
    enc["type"] = encryption.type;
    if (!encryption.passphrase.isEmpty())
        enc["passphrase"] = encryption.passphrase;
    obj["encryption"] = enc;
    if (!liveMode || !image.isEmpty())
        obj["image"] = image;
    if (!targetImgref.isEmpty())
        obj["targetImgref"] = targetImgref;
    if (!bootloader.isEmpty())
        obj["bootloader"] = bootloader;
    if (composeFsBackend)
        obj["composeFsBackend"] = true;
    if (!flatpaks.isEmpty())
        obj["flatpaks"] = QJsonArray::fromStringList(flatpaks);
    if (!additionalImageStores.isEmpty())
        obj["additionalImageStores"] = QJsonArray::fromStringList(additionalImageStores);
    obj["distroID"] = distroID;
    obj["selinuxDisabled"] = selinuxDisabled;
    obj["hostname"] = hostname;
    if (!user.username.isEmpty()) {
        obj["user"] = QJsonObject{
            {QStringLiteral("username"), user.username},
            {QStringLiteral("fullname"), user.fullname},
            {QStringLiteral("password"), user.password},
            {QStringLiteral("groups"), QJsonArray::fromStringList(user.groups)},
        };
    }
    return obj;
}

Recipe Recipe::fromJson(const QJsonObject &obj)
{
    Recipe r;
    r.disk = obj["disk"].toString();
    r.filesystem = obj["filesystem"].toString("xfs");
    r.btrfsSubvolumes = obj["btrfsSubvolumes"].toBool(false);
    auto enc = obj["encryption"].toObject();
    r.encryption.type = enc["type"].toString("none");
    r.encryption.passphrase = enc["passphrase"].toString();
    r.image = obj["image"].toString();
    r.targetImgref = obj["targetImgref"].toString();
    r.bootloader = obj["bootloader"].toString();
    r.composeFsBackend = obj["composeFsBackend"].toBool(false);
    for (const auto &val : obj["flatpaks"].toArray()) {
        r.flatpaks.append(val.toString());
    }
    for (const auto &val : obj["additionalImageStores"].toArray()) {
        r.additionalImageStores.append(val.toString());
    }
    r.distroID = obj["distroID"].toString();
    r.selinuxDisabled = obj["selinuxDisabled"].toBool(false);
    r.hostname = obj["hostname"].toString();
    const QJsonObject user = obj["user"].toObject();
    r.user.username = user["username"].toString();
    r.user.fullname = user["fullname"].toString();
    r.user.password = user["password"].toString();
    if (user.contains(QStringLiteral("groups"))) {
        r.user.groups.clear();
        for (const auto &val : user["groups"].toArray())
            r.user.groups.append(val.toString());
    }
    return r;
}

bool Recipe::isValid() const
{
    return validationError().isEmpty();
}

namespace {
struct Choices {
    QStringList types;
    QHash<QString, QJsonObject> byType;
};

const Choices &choices()
{
    static const Choices c = [] {
        Choices out;
        const QJsonArray list = QJsonDocument::fromJson(QByteArray(kEncryptionChoicesJson))
                                    .object()
                                    .value(QLatin1String("choices"))
                                    .toArray();
        for (const QJsonValue &v : list) {
            const QJsonObject o = v.toObject();
            const QString type = o.value(QLatin1String("type")).toString();
            out.types << type;
            out.byType.insert(type, o);
        }
        return out;
    }();
    return c;
}

bool flag(const QString &type, const char *name)
{
    const QString key = type.isEmpty() ? QStringLiteral("none") : type;
    return choices().byType.value(key).value(QLatin1String(name)).toBool();
}
}

const QStringList &Recipe::encryptionTypes()
{
    return choices().types;
}

bool Recipe::needsPassphrase(const QString &type)
{
    return flag(type, "needs_passphrase");
}

bool Recipe::needsTpm2(const QString &type)
{
    return flag(type, "needs_tpm2");
}

QString Recipe::validationError() const
{
    // The one thing the wizard checks itself: a disk was chosen. The image,
    // hostname and encryption rules are fisherman's (`validate --json`); the
    // install runs them before it touches a disk.
    if (disk.isEmpty())
        return QStringLiteral("No disk selected");
    return {};
}

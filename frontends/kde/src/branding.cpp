#include "branding.h"
#include "branding_defaults.h"

#include <QByteArray>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QUrl>

namespace branding {

namespace {

const char *kEnvFile = "BOOTC_INSTALLER_BRANDING";
const char *kEnvName = "BOOTC_INSTALLER_PRODUCT_NAME";
const char *kNeutralName = "Linux";
const char *kNeutralId = "linux";

const QStringList &brandingPaths()
{
    static const QStringList paths = {
        QStringLiteral("/run/host/etc/bootc-installer/branding.json"),
        QStringLiteral("/run/host/usr/share/bootc-installer/branding.json"),
        QStringLiteral("/etc/bootc-installer/branding.json"),
        QStringLiteral("/usr/share/bootc-installer/branding.json"),
    };
    return paths;
}

const QStringList &osReleasePaths()
{
    static const QStringList paths = {
        QStringLiteral("/run/host/etc/os-release"),
        QStringLiteral("/run/host/usr/lib/os-release"),
        QStringLiteral("/etc/os-release"),
        QStringLiteral("/usr/lib/os-release"),
    };
    return paths;
}

// The subset of shell quoting os-release allows: double quotes with backslash
// escapes, single quotes, or a bare word that ends at the first whitespace.
QString unquoteShell(const QString &value)
{
    if (value.isEmpty())
        return QString();
    const QChar first = value.at(0);
    if (first == QLatin1Char('"')) {
        QString out;
        bool escaped = false;
        for (int i = 1; i < value.size(); ++i) {
            const QChar c = value.at(i);
            if (escaped) {
                out.append(c);
                escaped = false;
            } else if (c == QLatin1Char('\\')) {
                escaped = true;
            } else if (c == QLatin1Char('"')) {
                break;
            } else {
                out.append(c);
            }
        }
        return out.trimmed();
    }
    if (first == QLatin1Char('\'')) {
        const QString rest = value.mid(1);
        const int end = rest.indexOf(QLatin1Char('\''));
        return (end >= 0 ? rest.left(end) : rest).trimmed();
    }
    const int ws = value.indexOf(QRegularExpression(QStringLiteral("\\s")));
    return ws >= 0 ? value.left(ws) : value;
}

QString pick(const QJsonObject &file, const QHash<QString, QString> &osr, const QString &key,
             const QStringList &osKeys, const QString &def)
{
    const QString fromFile = file.value(key).toString().trimmed();
    if (!fromFile.isEmpty())
        return fromFile;
    for (const QString &k : osKeys) {
        const QString v = osr.value(k).trimmed();
        if (!v.isEmpty())
            return v;
    }
    return def;
}

const QStringList &assetKeys()
{
    static const QStringList keys = {
        // Common to every frontend; desktop-specific keys live under extensions.<frontend>.
        QStringLiteral("welcome_image"), QStringLiteral("complete_image"), QStringLiteral("store_qr"),
    };
    return keys;
}

} // namespace

Logo resolveLogo(const QString &spec, bool inFlatpak)
{
    const QString value = spec.trimmed();
    if (value.isEmpty())
        return {};
    if (!value.startsWith(QLatin1Char('/'))) {
        // Kirigami also understands remote URLs. The portable branding
        // contract does not; invalid names must not cause network requests.
        if (value.contains(QLatin1Char('/')) || value.contains(QLatin1Char(':')))
            return {};
        return {Logo::Kind::Theme, value};
    }
    const bool hostPath = value.startsWith(QStringLiteral("/usr/"))
        || value.startsWith(QStringLiteral("/etc/"));
    return {Logo::Kind::File,
            inFlatpak && hostPath ? QStringLiteral("/run/host") + value : value};
}

QString Logo::source() const
{
    return kind == Kind::File ? QUrl::fromLocalFile(value).toString(QUrl::FullyEncoded) : value;
}

QHash<QString, QString> copyDefaults()
{
    QHash<QString, QString> out;
    const QJsonObject obj = QJsonDocument::fromJson(QByteArray(kCopyDefaultsJson)).object();
    for (auto it = obj.begin(); it != obj.end(); ++it) {
        if (it.key().startsWith(QLatin1Char('_')) || !it.value().isString())
            continue;
        out.insert(it.key(), it.value().toString());
    }
    return out;
}

QString Branding::text(const QString &key, const QHash<QString, QString> &values) const
{
    QString line = copy.value(key);
    line.replace(QStringLiteral("{name}"), name);
    for (auto it = values.begin(); it != values.end(); ++it)
        line.replace(QLatin1Char('{') + it.key() + QLatin1Char('}'), it.value());
    return line;
}

QVariantMap Branding::copyAsVariantMap() const
{
    QVariantMap out;
    for (auto it = copy.begin(); it != copy.end(); ++it)
        out.insert(it.key(), text(it.key()));
    return out;
}

QHash<QString, QString> parseOsRelease(const QString &text)
{
    QHash<QString, QString> out;
    const QStringList lines = text.split(QLatin1Char('\n'));
    for (const QString &raw : lines) {
        const QString line = raw.trimmed();
        if (line.isEmpty() || line.startsWith(QLatin1Char('#')))
            continue;
        const int eq = line.indexOf(QLatin1Char('='));
        if (eq < 0)
            continue;
        const QString key = line.left(eq).trimmed();
        if (key.isEmpty())
            continue;
        out.insert(key, unquoteShell(line.mid(eq + 1).trimmed()));
    }
    return out;
}

Branding fromSources(const QJsonObject &file, const QString &osReleaseText, const QString &nameOverride)
{
    const QHash<QString, QString> osr = parseOsRelease(osReleaseText);
    Branding b;
    b.name = pick(file, osr, QStringLiteral("name"),
                  {QStringLiteral("PRETTY_NAME"), QStringLiteral("NAME")}, QLatin1String(kNeutralName));
    b.id = pick(file, osr, QStringLiteral("id"), {QStringLiteral("ID")}, QLatin1String(kNeutralId));
    b.vendor = pick(file, osr, QStringLiteral("vendor"),
                    {QStringLiteral("VENDOR_NAME"), QStringLiteral("NAME")}, QString());
    b.homeUrl = pick(file, osr, QStringLiteral("home_url"), {QStringLiteral("HOME_URL")}, QString());
    b.docsUrl = pick(file, osr, QStringLiteral("docs_url"), {QStringLiteral("DOCUMENTATION_URL")}, QString());
    b.supportUrl = pick(file, osr, QStringLiteral("support_url"), {QStringLiteral("SUPPORT_URL")}, QString());
    b.logo = pick(file, osr, QStringLiteral("logo"), {QStringLiteral("LOGO")}, QString());
    b.defaultHostname = pick(file, osr, QStringLiteral("default_hostname"),
                             {QStringLiteral("DEFAULT_HOSTNAME"), QStringLiteral("ID")}, QLatin1String(kNeutralId));
    b.defaultImage = pick(file, osr, QStringLiteral("default_image"), {}, QString());
    b.storeUrl = pick(file, osr, QStringLiteral("store_url"), {}, QString());
    const QString overrideName = nameOverride.trimmed();
    if (!overrideName.isEmpty())
        b.name = overrideName;

    // Flavour: a present string key overrides, even when empty (that is how a
    // product hides a line); anything else keeps the neutral default.
    b.copy = copyDefaults();
    const QJsonObject fileCopy = file.value(QStringLiteral("copy")).toObject();
    for (auto it = fileCopy.begin(); it != fileCopy.end(); ++it) {
        if (it.value().isString() && b.copy.contains(it.key()))
            b.copy.insert(it.key(), it.value().toString().trimmed());
    }
    for (const QString &k : assetKeys())
        b.assets.insert(k, QString());
    const QJsonObject fileAssets = file.value(QStringLiteral("assets")).toObject();
    for (auto it = fileAssets.begin(); it != fileAssets.end(); ++it) {
        if (it.value().isString())
            b.assets.insert(it.key(), it.value().toString().trimmed());
    }
    const QJsonObject fileQuotes = file.value(QStringLiteral("confirm_quotes")).toObject();
    for (auto it = fileQuotes.begin(); it != fileQuotes.end(); ++it) {
        QStringList lines;
        for (const QJsonValue &v : it.value().toArray()) {
            const QString line = v.toString().trimmed();
            if (!line.isEmpty())
                lines.append(line);
        }
        if (!lines.isEmpty())
            b.confirmQuotes.insert(it.key(), lines);
    }
    return b;
}

Branding resolveFrom(const QStringList &brandingPathList, const QStringList &osReleasePathList,
                     const QString &nameOverride)
{
    QJsonObject file;
    for (const QString &path : brandingPathList) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        const QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
        if (!doc.isObject())
            continue;
        file = doc.object();
        break;
    }
    QString osRelease;
    for (const QString &path : osReleasePathList) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        const QString text = QString::fromUtf8(f.readAll());
        if (text.trimmed().isEmpty())
            continue;
        osRelease = text;
        break;
    }
    return fromSources(file, osRelease, nameOverride);
}

Branding resolve()
{
    QStringList paths = brandingPaths();
    const QString explicitPath = QString::fromUtf8(qgetenv(kEnvFile)).trimmed();
    if (!explicitPath.isEmpty())
        paths = {explicitPath};
    return resolveFrom(paths, osReleasePaths(), QString::fromUtf8(qgetenv(kEnvName)));
}

} // namespace branding

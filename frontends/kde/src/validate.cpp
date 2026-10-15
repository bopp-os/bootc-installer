#include "validate.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace validate {

Result parse(const QByteArray &json)
{
    Result r;
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        r.error = QStringLiteral("fisherman validate printed no JSON object");
        return r;
    }
    const QJsonObject root = doc.object();
    if (root.value(QLatin1String("protocol_version")).toInt(-1) != PROTOCOL_VERSION) {
        r.error = QStringLiteral("fisherman validate protocol_version is not %1").arg(PROTOCOL_VERSION);
        return r;
    }
    const QJsonValue errors = root.value(QLatin1String("errors"));
    if (!errors.isArray()) {
        r.error = QStringLiteral("fisherman validate printed no errors list");
        return r;
    }
    r.ok = true;
    for (const QJsonValue &v : errors.toArray()) {
        const QJsonObject o = v.toObject();
        r.problems.append({o.value(QLatin1String("field")).toString(),
                           o.value(QLatin1String("code")).toString(),
                           o.value(QLatin1String("message")).toString()});
    }
    return r;
}

QStringList command(bool flatpak)
{
    QStringList argv{QStringLiteral("/usr/local/bin/fisherman"), QStringLiteral("validate"),
                     QStringLiteral("--json"), QStringLiteral("--partial"), QStringLiteral("-")};
    if (flatpak)
        return QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")} + argv;
    return argv;
}

QString copyKey(const Problem &problem)
{
    return QLatin1String(COPY_PREFIX) + problem.code;
}

}

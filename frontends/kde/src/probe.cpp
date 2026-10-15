#include "probe.h"

#include "log.h"
#include "offline.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#if QT_CONFIG(process)
#include <QProcess>
#endif

namespace probe {

namespace {

Result failure(const QString &why)
{
    Result r;
    r.error = why;
    qCWarning(logInstaller) << "fisherman probe:" << why;
    return r;
}

}

Result parse(const QByteArray &json)
{
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError)
        return failure(QStringLiteral("fisherman probe printed invalid JSON: %1").arg(err.errorString()));
    if (!doc.isObject())
        return failure(QStringLiteral("fisherman probe did not print a JSON object"));
    const QJsonObject root = doc.object();
    const int version = root.value(QLatin1String("protocol_version")).toInt(-1);
    if (version != PROTOCOL_VERSION)
        return failure(QStringLiteral("fisherman probe protocol_version %1 is not %2")
                           .arg(version).arg(PROTOCOL_VERSION));

    Result r;
    r.ok = true;
    const QJsonArray disks = root.value(QLatin1String("disks")).toArray();
    for (const QJsonValue &value : disks) {
        const QJsonObject d = value.toObject();
        // Only fisherman's eligible disks; a missing flag or an unknown
        // excluded_reason means "not eligible".
        if (d.value(QLatin1String("eligible")) != QJsonValue(true))
            continue;
        Disk disk;
        disk.path = d.value(QLatin1String("path")).toString();
        disk.model = d.value(QLatin1String("model")).toString();
        disk.title = disk.model.isEmpty() ? disk.path : disk.model;
        disk.sizeLabel = d.value(QLatin1String("size_label")).toString();
        disk.transportLabel = d.value(QLatin1String("transport_label")).toString();
        disk.removable = d.value(QLatin1String("removable")).toBool();
        r.disks.append(disk);
    }
    r.tpmUsable = root.value(QLatin1String("tpm")).toObject().value(QLatin1String("usable")).toBool();
    const QJsonArray unmet = root.value(QLatin1String("system")).toObject().value(QLatin1String("unmet")).toArray();
    for (const QJsonValue &item : unmet)
        r.unmet.append(item.toString());
    const QJsonObject live = root.value(QLatin1String("live")).toObject();
    r.isLive = live.value(QLatin1String("is_live")).toBool();
    if (r.isLive)
        r.liveImage = live.value(QLatin1String("live_image")).toString();
    const QJsonArray images = root.value(QLatin1String("offline")).toObject().value(QLatin1String("images")).toArray();
    for (const QJsonValue &item : images)
        r.offlineImages.append(item.toString());
    return r;
}

QStringList command(bool flatpak)
{
    QStringList argv{QStringLiteral("/usr/local/bin/fisherman"), QStringLiteral("probe"),
                     QStringLiteral("--json")};
    if (flatpak)
        return QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")} + argv;
    return argv;
}

Result run()
{
    const QString fake = qEnvironmentVariable(FAKE_ENV);
    if (!fake.isEmpty()) {
        QFile f(fake);
        if (!f.open(QIODevice::ReadOnly))
            return failure(QStringLiteral("%1=%2: %3").arg(QLatin1String(FAKE_ENV), fake, f.errorString()));
        return parse(f.readAll());
    }
#if QT_CONFIG(process)
    const QStringList argv = command(offline::inFlatpak());
    QProcess p;
    p.start(argv.first(), argv.mid(1));
    if (!p.waitForStarted(5000))
        return failure(QStringLiteral("cannot run %1: %2").arg(argv.first(), p.errorString()));
    // lsblk and `bootc status`; a hung host helper must not hang the wizard.
    if (!p.waitForFinished(30000)) {
        p.kill();
        p.waitForFinished(1000);
        return failure(QStringLiteral("fisherman probe did not finish within 30 s"));
    }
    if (p.exitStatus() != QProcess::NormalExit || p.exitCode() != 0) {
        const QString stderrText = QString::fromUtf8(p.readAllStandardError()).trimmed();
        const QString first = stderrText.section(QLatin1Char('\n'), 0, 0);
        return failure(QStringLiteral("fisherman probe failed (exit %1): %2")
                           .arg(p.exitCode())
                           .arg(first.isEmpty() ? QStringLiteral("no message") : first));
    }
    return parse(p.readAllStandardOutput());
#else
    // Qt for WebAssembly: no process to run. The browser harness sets the
    // variable above, so reaching here means it was left out.
    return failure(QStringLiteral("no %1 and this build cannot run fisherman").arg(QLatin1String(FAKE_ENV)));
#endif
}

}

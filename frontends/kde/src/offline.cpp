#include "offline.h"

#include <QFile>
#if QT_CONFIG(process)
#include <QProcess>
#endif
#ifdef Q_OS_UNIX
#include <unistd.h>
#endif

namespace offline {

bool inFlatpak()
{
    return QFile::exists(QStringLiteral("/.flatpak-info"));
}

QStringList fishermanCommand()
{
    return fishermanCommand(inFlatpak());
}

QStringList fishermanCommand(bool flatpak)
{
    // Flatpak runtimes ship no pkexec; escalate host-side. The live ISO
    // symlinks the flatpak-bundled fisherman to /usr/local/bin and installs
    // the polkit policy for it (tunaOS customize-live.sh).
    //
    // pkexec runs inside a host-side bash, not straight from flatpak-spawn.
    // fisherman runs as root, so nothing here can signal it; it cancels when
    // its PARENT dies (tuna-os/fisherman#267). Run as `flatpak-spawn --host
    // pkexec ...`, that parent was the host's flatpak-session-helper, which
    // this frontend cannot kill. `-`: fisherman reads the recipe from stdin
    // (tuna-os/fisherman#276), so no file holds the passphrase. No
    // redirection: stdin, stdout and stderr all pass through flatpak-spawn.
    if (flatpak)
        return {QStringLiteral("flatpak-spawn"), QStringLiteral("--host"),
                QStringLiteral("bash"), QStringLiteral("-c"),
                QStringLiteral("pkexec /usr/local/bin/fisherman -; exit $?")};
    return {QStringLiteral("sudo"), QStringLiteral("/usr/local/bin/fisherman"),
            QStringLiteral("-")};
}

#if QT_CONFIG(process)
void startInOwnProcessGroup(QProcess &process)
{
#ifdef Q_OS_UNIX
    // The wrapper is the only process of the install this user can signal.
    // The shared contract is "kill your wrapper's process group", which
    // must never be the installer's own group.
    process.setChildProcessModifier([] { ::setpgid(0, 0); });
#else
    Q_UNUSED(process);
#endif
}
#endif

QStringList hostCommand(const QStringList &argv)
{
    if (!inFlatpak())
        return argv;
    QStringList wrapped{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")};
    wrapped += argv;
    return wrapped;
}

} // namespace offline

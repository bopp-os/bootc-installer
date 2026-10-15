#ifndef OFFLINE_H
#define OFFLINE_H

// Sandbox plumbing: how the wizard reaches fisherman and the host.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges).
//
// Live media and offline image stores are fisherman's facts now (probe's
// `live` and `offline`, probe.h). This file used to find them itself:
// `bootc status` plus /run/ostree-live and /proc/cmdline for live media, and
// $TUNA_OFFLINE_STORES and /etc/tuna-installer/offline-stores for the
// stores. Inside a Flatpak those paths are the runtime's, not the host's.

#include <QString>
#include <QStringList>
#include <QtCore/qtcore-config.h>

class QProcess;

namespace offline {

// True when running inside a Flatpak sandbox.
bool inFlatpak();

// Command (program + args) that runs fisherman with privileges, reading the
// recipe from stdin (`fisherman -`): the caller writes the JSON to the
// process's stdin and closes it. Inside Flatpak:
// flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'
// Outside: sudo /usr/local/bin/fisherman -.
QStringList fishermanCommand();
// The same, for an explicit sandbox state (tests).
QStringList fishermanCommand(bool flatpak);

#if QT_CONFIG(process)
// Makes `process` start as the leader of its own process group, so the
// fisherman wrapper can be signalled as a group without touching ours.
void startInOwnProcessGroup(QProcess &process);
#endif

// Wrap argv so it executes on the host when sandboxed (flatpak-spawn --host).
QStringList hostCommand(const QStringList &argv);

} // namespace offline

#endif // OFFLINE_H

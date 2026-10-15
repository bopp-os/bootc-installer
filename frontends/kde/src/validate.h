#pragma once

// `fisherman validate --json --partial -` (shared/recipe/README.md).
//
// fisherman owns the hostname, filesystem and encryption rules
// (fisherman/docs/VALIDATE.md). The wizard sends a step's fields as a
// partial recipe on stdin, never argv (the passphrase is one of them), and
// shows each problem through the copy key `validate_<code>`. A check that
// cannot run shows nothing and blocks nothing: the install runs the same
// rules before it touches a disk.

#include <QByteArray>
#include <QList>
#include <QString>
#include <QStringList>

namespace validate {

inline constexpr int PROTOCOL_VERSION = 1;
// A problem's copy key is this prefix plus its code.
inline constexpr const char *COPY_PREFIX = "validate_";

struct Problem {
    QString field;   // "hostname", "encryption.passphrase", ...
    QString code;    // stable; the copy key is COPY_PREFIX + code
    QString message; // fisherman's English, for a code with no copy
};

struct Result {
    bool ok = false;        // fisherman answered
    QString error;          // why not, when !ok
    QList<Problem> problems;
};

// Parses `validate --json` output.
Result parse(const QByteArray &json);

// The unprivileged command: the fisherman the install runs, on the host
// (flatpak-spawn --host when sandboxed). Never pkexec or sudo.
QStringList command(bool flatpak);

// The copy key for a problem.
QString copyKey(const Problem &problem);

}

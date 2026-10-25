// End to end: InstallerController drives the real backend launch path.
//
// This is the code the Install button runs, minus the button: the
// controller writes the 0600 recipe into its private directory, launches
// `sudo /usr/local/bin/fisherman <recipe>` (the same fishermanCommand() the
// shipped binary uses outside Flatpak), streams its stdout/stderr into the
// log, persists the log file and emits installCompleted(exitCode) when the
// process exits. shared/e2e/setup.sh has put the validating shim at that
// path, so what runs is the real fisherman's Validate() on the recipe this
// controller produced.
//
// Built with -DBUILD_E2E=ON as tuna-installer-e2e. Exit 0 only when the
// controller reports success and its log carried fisherman's completion event.

#include "installercontroller.h"

#include <QCoreApplication>
#include <QEventLoop>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <QTimer>

#include <functional>

int main(int argc, char *argv[])
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);

    const QByteArray disk = qgetenv("TUNA_E2E_DISK");
    if (disk.isEmpty()) {
        out << "FAIL: TUNA_E2E_DISK is not set (run shared/e2e/setup.sh)\n";
        return 2;
    }

    InstallerController controller;
    // What a user picks on the disk and options steps. The image is the
    // ostree + grub2 canary the VM job installs; no composefs on xfs.
    controller.setDisk(QString::fromUtf8(disk));
    controller.setFilesystem(QStringLiteral("xfs"));
    controller.setImage(QStringLiteral("quay.io/centos-bootc/centos-bootc:c10s"));
    controller.setEncryptionType(QStringLiteral("none"));
    controller.setHostname(QStringLiteral("kde-e2e"));

    // The account step. First a name fisherman refuses, through the same
    // `validate --json --partial -` the step runs while the user types (the
    // shim hands it to the real fisherman): the step must show the problem
    // and hold Next on it. Then the account the user actually creates.
    const auto waitFor = [](const std::function<bool()> &done, int ms) {
        QEventLoop wait;
        QTimer poll;
        QObject::connect(&poll, &QTimer::timeout, &wait, [&] {
            if (done())
                wait.quit();
        });
        QTimer::singleShot(ms, &wait, &QEventLoop::quit);
        poll.start(50);
        wait.exec();
        return done();
    };
    controller.setUsername(QStringLiteral("root"));
    if (!waitFor([&] { return !controller.usernameProblem().isEmpty(); }, 15000)) {
        out << "FAIL: fisherman reported no problem with the username \"root\" — the "
               "account step's validate --json --partial call is not reaching it\n";
        return 1;
    }
    out << "e2e: username \"root\" refused: " << controller.usernameProblem() << "\n";
    const QString username = QStringLiteral("kdeuser");
    controller.setUsername(username);
    controller.setFullname(QStringLiteral("KDE E2E"));
    controller.setUserPassword(QStringLiteral("kde-e2e-password"));
    if (!waitFor([&] { return controller.usernameProblem().isEmpty(); }, 15000)) {
        out << "FAIL: fisherman still reports a problem with the username \"" << username
            << "\": " << controller.usernameProblem() << "\n";
        return 1;
    }

    int exitCode = -1;
    QEventLoop loop;
    QObject::connect(&controller, &InstallerController::installCompleted, &loop,
                     [&](int code) { exitCode = code; loop.quit(); });
    QTimer::singleShot(120000, &loop, [&] {
        out << "FAIL: no installCompleted after 120s\n";
        loop.quit();
    });

    out << "e2e: pressing Install\n";
    controller.startInstall();
    loop.exec();

    out << "e2e: log path " << controller.logPath() << "\n";
    out << controller.log() << "\n";
    if (exitCode != 0) {
        out << "FAIL: fisherman exit code " << exitCode << "\n";
        return 1;
    }
    if (!controller.succeeded()) {
        out << "FAIL: controller does not report success\n";
        return 1;
    }
    // Where the progress bar ended up. This checked the log text for
    // fisherman's raw `"type":"complete"` event, which worked only while the
    // controller stored the protocol verbatim; it now renders events for the
    // log pane and keeps the raw lines in the log FILE, so that string is no
    // longer in log().
    //
    // Asserting the bar instead is the stronger check anyway, and matches
    // what the XFCE and Niri drivers do: a controller that does not parse
    // fisherman's protocol still reaches installCompleted(0) and still
    // reports success, and only the bar shows the difference.
    if (controller.installFraction() != 1.0) {
        out << "FAIL: the progress bar ended at " << controller.installFraction()
            << ", not 1.0 — the controller is not parsing fisherman's progress "
               "protocol (shared/progress/README.md)\n";
        return 1;
    }
    if (!controller.log().contains(QLatin1String("Installation complete"))) {
        out << "FAIL: the log carried no completion event\n";
        return 1;
    }
    // The recipe fisherman was handed on stdin, as the shim kept it: it
    // must create the account (shared/e2e/check-recipe.py then runs the
    // real fisherman's full validate and the schema over the same file).
    QFile kept(QStringLiteral("/tmp/tuna-e2e/recipe.json"));
    if (!kept.open(QIODevice::ReadOnly)) {
        out << "FAIL: the shim kept no recipe at /tmp/tuna-e2e/recipe.json\n";
        return 1;
    }
    const QJsonObject user = QJsonDocument::fromJson(kept.readAll()).object()
                                 .value(QStringLiteral("user")).toObject();
    if (user.value(QStringLiteral("username")).toString() != username
        || user.value(QStringLiteral("password")).toString().isEmpty()
        || user.value(QStringLiteral("groups")).toArray() != QJsonArray{QStringLiteral("wheel")}) {
        out << "FAIL: the recipe's user block is not the account the step created: "
            << QJsonDocument(QJsonObject{{QStringLiteral("username"), user.value(QStringLiteral("username"))},
                                         {QStringLiteral("groups"), user.value(QStringLiteral("groups"))}})
                   .toJson(QJsonDocument::Compact)
            << "\n";
        return 1;
    }
    out << "OK: KDE controller reached installCompleted(0) through sudo /usr/local/bin/fisherman\n";
    return 0;
}

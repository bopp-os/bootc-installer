#pragma once

// The wizard's state and the fisherman backend, exposed to QML.
//
// The wizard's recipe, the privileged fisherman QProcess (the recipe goes to
// its stdin, `fisherman -`), and fisherman's answers: `probe --json` for the
// hardware and live media, `validate --json --partial` for the fields.

#include <QFile>
#include <QObject>
#if QT_CONFIG(process)
#include <QProcess>
#else
// Qt for WebAssembly builds without QProcess. The browser harness never
// starts an install, so the pointer only has to exist; it stays null.
class QProcess;
#endif
#include <QString>
#include <QTimer>
#include <qqmlintegration.h>

#include "branding.h"

#include <QVariantMap>
#include "recipe.h"
#include "validate.h"

class InstallerController : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON

    Q_PROPERTY(QString disk READ disk WRITE setDisk NOTIFY recipeChanged)
    Q_PROPERTY(QString filesystem READ filesystem WRITE setFilesystem NOTIFY recipeChanged)
    Q_PROPERTY(bool btrfsSubvolumes READ btrfsSubvolumes WRITE setBtrfsSubvolumes NOTIFY recipeChanged)
    Q_PROPERTY(QString encryptionType READ encryptionType WRITE setEncryptionType NOTIFY recipeChanged)
    Q_PROPERTY(QString passphrase READ passphrase WRITE setPassphrase NOTIFY recipeChanged)
    Q_PROPERTY(QString hostname READ hostname WRITE setHostname NOTIFY recipeChanged)
    Q_PROPERTY(QString image READ image WRITE setImage NOTIFY recipeChanged)

    // fisherman's tpm.usable from `fisherman probe --json`
    // (shared/probe/README.md). TPM options are hidden, not disabled, when
    // false: offering them on a machine without one only fails later, at
    // install time. False when the probe failed.
    Q_PROPERTY(bool hasTpm READ hasTpm CONSTANT)
    // fisherman's system.unmet ("ram", "cpu", "uefi"), and the welcome
    // step's warning built from the requirements_* copy keys; empty when
    // every requirement is met or the probe failed. A warning, not a gate.
    Q_PROPERTY(QStringList unmetRequirements READ unmetRequirements CONSTANT)
    Q_PROPERTY(QString requirementsWarning READ requirementsWarning CONSTANT)
    // Every encryption type, in display order (Recipe::encryptionTypes()).
    // The encryption step repeats over it and hides the tpm2- ones without
    // a TPM; what each is called comes from encryptionLabel/Description.
    Q_PROPERTY(QStringList encryptionTypes READ encryptionTypes CONSTANT)

    // fisherman's probe: the host booted from live media (live.is_live), and
    // the booted image. On live media the recipe leaves `image` empty and
    // fisherman installs the running system.
    Q_PROPERTY(bool isLive READ isLive CONSTANT)
    Q_PROPERTY(QString liveImage READ liveImage CONSTANT)

    // fisherman's problems with the fields (`validate --json --partial`), in
    // the words of the copy key validate_<code>; empty when there is none or
    // the check could not run. The encryption step shows the passphrase
    // problem and holds Next on it; the confirm step shows the hostname's.
    Q_PROPERTY(QString hostnameProblem READ hostnameProblem NOTIFY problemsChanged)
    Q_PROPERTY(QString encryptionProblem READ encryptionProblem NOTIFY problemsChanged)

    // The product name, resolved ONCE at startup from the branding contract
    // (src/branding.h: branding.json, then os-release, then neutral). Every
    // user-visible string reads this; nothing names a product. CONSTANT: the
    // files cannot change under a running installer.
    Q_PROPERTY(QString productName READ productName CONSTANT)
    // Theme icon name or safely encoded local URL, using the host path only
    // when sandboxed. Welcome and successful completion share this source.
    Q_PROPERTY(QString logoSource READ logoSource CONSTANT)
    // The branding contract's optional artwork (`assets.welcome_image`,
    // `assets.complete_image`), resolved with the same rules as the logo.
    // Empty when unset; the welcome and done steps then fall back to
    // logoSource and finally to a themed icon.
    Q_PROPERTY(QString welcomeImageSource READ welcomeImageSource CONSTANT)
    Q_PROPERTY(QString completeImageSource READ completeImageSource CONSTANT)
    // Flavour text from the branding contract (shared/branding copy keys),
    // {name} already filled in; {disk} through text(). CONSTANT like the name.
    Q_PROPERTY(QVariantMap copy READ copy CONSTANT)
    Q_PROPERTY(QString storeUrl READ storeUrl CONSTANT)

    Q_PROPERTY(QString log READ log NOTIFY logChanged)

    // Where the same log is being written on disk, empty when the file could
    // not be opened. The done step shows it: the in-window log dies with the
    // window, and a failed install is exactly when someone needs to reboot,
    // ask for help, or attach the output to a bug report.
    Q_PROPERTY(QString logPath READ logPath NOTIFY logPathChanged)

    // Install progress, from fisherman's newline-delimited JSON protocol
    // (shared/progress/README.md). KDE had no progress bar at all: the
    // step showed a BusyIndicator and a log pane for the whole install,
    // which docs/PARITY.md listed as gap #2.
    //
    // installFraction, not step/totalSteps: fisherman computes total_steps
    // from the recipe, and the weights are wildly unequal — "Installing OS"
    // alone is 87% of a cold install while five other steps are 0% — so a
    // bar advanced one-nth per step sits near empty for the whole visible
    // install and then jumps.
    Q_PROPERTY(int installStep READ installStep NOTIFY progressChanged)
    Q_PROPERTY(int installTotalSteps READ installTotalSteps NOTIFY progressChanged)
    Q_PROPERTY(qreal installFraction READ installFraction NOTIFY progressChanged)
    Q_PROPERTY(QString installStepName READ installStepName NOTIFY progressChanged)

    Q_PROPERTY(bool installing READ installing NOTIFY installingChanged)
    Q_PROPERTY(bool installFinished READ installFinishedFlag NOTIFY installCompleted)
    Q_PROPERTY(int exitCode READ exitCode NOTIFY installCompleted)
    Q_PROPERTY(bool succeeded READ succeeded NOTIFY installCompleted)

    // The key fisherman emits once, after TPM enrolment (#129). The
    // "recovery_key" branch in consumeProgress() used to format a log line
    // and keep nothing, so after the install there was nothing left to show.
    Q_PROPERTY(QString recoveryKey READ recoveryKey NOTIFY recoveryChanged)
    Q_PROPERTY(bool recoveryAck READ recoveryAck WRITE setRecoveryAck NOTIFY recoveryChanged)
    // Restart is held while an unacknowledged key is on screen: leaving the
    // done page is what ends the chance to read it.
    Q_PROPERTY(bool recoveryKeyPending READ recoveryKeyPending NOTIFY recoveryChanged)

public:
    explicit InstallerController(QObject *parent = nullptr);

    QString disk() const { return m_recipe.disk; }
    void setDisk(const QString &v);
    QString filesystem() const { return m_recipe.filesystem; }
    void setFilesystem(const QString &v);
    bool btrfsSubvolumes() const { return m_recipe.btrfsSubvolumes; }
    void setBtrfsSubvolumes(bool v);
    QString encryptionType() const { return m_recipe.encryption.type; }
    void setEncryptionType(const QString &v);
    QString passphrase() const { return m_recipe.encryption.passphrase; }
    void setPassphrase(const QString &v);
    QString hostname() const { return m_recipe.hostname; }
    void setHostname(const QString &v);
    QString image() const { return m_recipe.image; }
    void setImage(const QString &v);

    bool hasTpm() const { return m_hasTpm; }
    QStringList unmetRequirements() const { return m_unmet; }
    QString requirementsWarning() const;
    QStringList encryptionTypes() const { return Recipe::encryptionTypes(); }
    Q_INVOKABLE bool needsPassphrase(const QString &type) const { return Recipe::needsPassphrase(type); }
    Q_INVOKABLE bool needsTpm2(const QString &type) const { return Recipe::needsTpm2(type); }
    bool isLive() const { return m_recipe.liveMode; }
    QString liveImage() const { return m_liveImage; }
    QString hostnameProblem() const { return problemText(QStringLiteral("hostname")); }
    QString encryptionProblem() const { return problemText(QStringLiteral("encryption")); }
    // The fields as a partial recipe for `validate --json --partial -`.
    QByteArray partialRecipe() const;
    // Takes in fisherman's answer (validate --json stdout). Public for tests.
    void applyValidateAnswer(const QByteArray &stdoutData);
    QString productName() const { return m_productName; }
    QString logoSource() const { return m_logoSource; }
    QString welcomeImageSource() const { return m_welcomeImageSource; }
    QString completeImageSource() const { return m_completeImageSource; }
    QVariantMap copy() const { return m_branding.copyAsVariantMap(); }
    QString storeUrl() const { return m_branding.storeUrl; }
    // A copy line with {name} and {disk} filled in.
    Q_INVOKABLE QString text(const QString &key, const QString &disk = QString()) const
    {
        return m_branding.text(key, {{QStringLiteral("disk"), disk.isEmpty() ? QStringLiteral("the selected disk") : disk}});
    }
    // The done page's Restart: systemctl reboot on the host.
    Q_INVOKABLE void reboot();
    QString log() const { return m_log; }
    QString logPath() const { return m_logPath; }
    int installStep() const { return m_step; }
    int installTotalSteps() const { return m_totalSteps; }
    qreal installFraction() const { return m_fraction; }
    QString installStepName() const { return m_stepName; }
    bool installing() const { return m_process != nullptr; }
    bool installFinishedFlag() const { return m_finished; }
    int exitCode() const { return m_exitCode; }
    bool succeeded() const { return m_finished && m_exitCode == 0; }
    QString recoveryKey() const { return m_recoveryKey; }
    bool recoveryAck() const { return m_recoveryAck; }
    void setRecoveryAck(bool v);
    // A failed install enrolled nothing, and a non-TPM install was never
    // given a key, so neither is held: a user must not be asked to tick a
    // box about a key they do not have.
    bool recoveryKeyPending() const
    {
        return succeeded() && !m_recoveryKey.isEmpty() && !m_recoveryAck;
    }

    // What an encryption type is called: the branding copy keys
    // encryption_<type>_label and _description (shared/branding/README.md).
    // The encryption and confirm steps both read these, so they cannot
    // drift apart.
    Q_INVOKABLE QString encryptionLabel(const QString &type) const;
    Q_INVOKABLE QString encryptionDescription(const QString &type) const;

    // Writes the recipe and launches fisherman. The ONLY thing that starts an
    // install — nothing on step activation does. Kept that way on purpose: the
    // screenshot harness walks every step, and must never install anything.
    Q_INVOKABLE void startInstall();

    // Screenshot/demo hook: fills the log and result so the progress and done
    // steps can be photographed. Runs no process and touches no disk.
    Q_INVOKABLE void loadDemoState(const QString &log, int exitCode);

    // fisherman's output, one read at a time. The live QProcess path calls
    // these from readyReadStandardOutput/-Error and finished(); they are
    // public so the tests can interleave the two streams the way a pipe does.
    // Only stdout lines are parsed as progress events.
    void consumeStdout(const QByteArray &data);
    void consumeStderr(const QByteArray &data);
    // Emits whatever partial line is left in either stream.
    void flushStreams();

Q_SIGNALS:
    void recipeChanged();
    void logChanged();
    void logPathChanged();
    void installingChanged();
    void progressChanged();
    void recoveryChanged();
    void problemsChanged();
    void installCompleted(int exitCode);

private:
    void openLogFile();
    void closeLogFile();
    void appendLine(const QString &line, bool parse = true);
    // Parses one fisherman event and updates the progress properties.
    // Returns the text to show in the log pane: the event rendered for a
    // person, or the line unchanged when it is not an event.
    QString consumeProgress(const QString &line);
    // The label for a step: copy key step_<stepId>, else the step name.
    QString stepLabel(const QString &stepId, const QString &stepName) const;
    void resetProgress();
    void drainBuffer(QByteArray &buffer, const QString &prefix, bool parse);
    void fail(const QString &message);
    // A problem's line: the copy for its code, or fisherman's message.
    QString problemText(const QString &fieldPrefix) const;
    // Asks fisherman about the fields after a pause in the changes.
    void checkFields();
    void runValidate();

    Recipe m_recipe;
    QString m_liveImage;
    QList<validate::Problem> m_problems;
    QTimer m_validateTimer;
    QProcess *m_validateProcess = nullptr;
    bool m_validateAgain = false;
    QString m_log;
    QFile *m_logFile = nullptr;
    QString m_logPath;
    // One partial line per stream; see consumeStdout().
    QByteArray m_stdoutBuffer;
    QByteArray m_stderrBuffer;
    QProcess *m_process = nullptr;
    bool m_finished = false;
    int m_step = 0;
    int m_totalSteps = 0;
    qreal m_fraction = 0.0;
    QString m_stepName;
    QString m_recoveryKey;
    bool m_recoveryAck = false;
    // Carried across lines so a substep can interpolate inside its step.
    int m_cumulativePct = 0;
    int m_weightPct = 0;
    // How far through the current step the bar is (0-1); never decreases
    // inside a step. m_postPullBase is m_stepFrac when the first post-pull
    // phase message arrived, or negative before that.
    double m_stepFrac = 0.0;
    double m_postPullBase = -1.0;
    bool m_hasTpm = false;
    QStringList m_unmet;
    QString m_productName;
    QString m_logoSource;
    QString m_welcomeImageSource;
    QString m_completeImageSource;
    branding::Branding m_branding;
    int m_exitCode = 0;
};

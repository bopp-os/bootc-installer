#include "installercontroller.h"
#include "probe.h"
#include "log.h"
#include "offline.h"
#include "branding.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QStandardPaths>

InstallerController::InstallerController(QObject *parent)
    : QObject(parent)
{
    // TPM 2.0 and the minimum requirements are fisherman's answers
    // (`fisherman probe --json`, shared/probe/README.md), read once. The
    // disk step runs the probe again when it opens, for hotplugged disks.
    // A capture points BOOTC_INSTALLER_FAKE_PROBE at a fixture with a
    // usable TPM, so the TPM choices show on a runner without one.
    const probe::Result facts = probe::run();
    m_hasTpm = facts.tpmUsable;
    m_unmet = facts.unmet;
    // Live media is fisherman's answer (probe's `live`). This used to be a
    // `bootc status` of our own plus /run/ostree-live and /proc/cmdline,
    // read inside the Flatpak sandbox.
    m_recipe.liveMode = facts.isLive;
    m_liveImage = facts.liveImage;
    // Product identity per shared/branding/README.md: branding.json, then
    // os-release, then neutral. Nothing in this frontend names a product.
    m_branding = branding::resolve();
    m_productName = m_branding.name;
    m_logoSource = branding::resolveLogo(m_branding.logo, offline::inFlatpak()).source();
    m_welcomeImageSource = branding::resolveLogo(
        m_branding.assets.value(QStringLiteral("welcome_image")), offline::inFlatpak()).source();
    m_completeImageSource = branding::resolveLogo(
        m_branding.assets.value(QStringLiteral("complete_image")), offline::inFlatpak()).source();
    m_recipe.distroID = m_branding.id;
    m_recipe.hostname = m_branding.defaultHostname;

    // One check at a time, after a pause in the changes.
    m_validateTimer.setSingleShot(true);
    m_validateTimer.setInterval(300);
    connect(&m_validateTimer, &QTimer::timeout, this, &InstallerController::runValidate);
    checkFields();
}

QByteArray InstallerController::partialRecipe() const
{
    QJsonObject enc{{QStringLiteral("type"), m_recipe.encryption.type}};
    if (Recipe::needsPassphrase(m_recipe.encryption.type))
        enc[QStringLiteral("passphrase")] = m_recipe.encryption.passphrase;
    const QJsonObject partial{
        {QStringLiteral("hostname"), m_recipe.hostname},
        {QStringLiteral("filesystem"), m_recipe.filesystem},
        {QStringLiteral("btrfsSubvolumes"), m_recipe.btrfsSubvolumes},
        {QStringLiteral("encryption"), enc},
    };
    return QJsonDocument(partial).toJson(QJsonDocument::Compact);
}

void InstallerController::checkFields()
{
    m_validateTimer.start();
}

void InstallerController::runValidate()
{
#if QT_CONFIG(process)
    if (m_validateProcess) {
        m_validateAgain = true;
        return;
    }
    QStringList argv = validate::command(offline::inFlatpak());
    m_validateProcess = new QProcess(this);
    m_validateProcess->setProgram(argv.takeFirst());
    m_validateProcess->setArguments(argv);
    connect(m_validateProcess, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
        // 0 valid, 1 invalid; anything else means no answer.
        if (status == QProcess::NormalExit && (code == 0 || code == 1))
            applyValidateAnswer(m_validateProcess->readAllStandardOutput());
        else
            qCWarning(logInstaller) << "fisherman validate could not run, exit" << code;
        m_validateProcess->deleteLater();
        m_validateProcess = nullptr;
        if (m_validateAgain) {
            m_validateAgain = false;
            checkFields();
        }
    });
    connect(m_validateProcess, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error != QProcess::FailedToStart)
            return;
        qCWarning(logInstaller) << "fisherman validate could not start:" << m_validateProcess->errorString();
        m_validateProcess->deleteLater();
        m_validateProcess = nullptr;
    });
    m_validateProcess->start();
    // The partial recipe on stdin, never argv: the passphrase is in it.
    m_validateProcess->write(partialRecipe());
    m_validateProcess->closeWriteChannel();
#endif
}

void InstallerController::applyValidateAnswer(const QByteArray &stdoutData)
{
    const validate::Result answer = validate::parse(stdoutData);
    if (!answer.ok)
        qCWarning(logInstaller) << "fisherman validate:" << answer.error;
    m_problems = answer.ok ? answer.problems : QList<validate::Problem>{};
    Q_EMIT problemsChanged();
}

QString InstallerController::problemText(const QString &fieldPrefix) const
{
    for (const validate::Problem &p : m_problems) {
        if (p.field != fieldPrefix && !p.field.startsWith(fieldPrefix + QLatin1Char('.')))
            continue;
        const QString line = p.code.isEmpty() ? QString() : text(validate::copyKey(p));
        return line.isEmpty() ? p.message : line;
    }
    return {};
}

QString InstallerController::requirementsWarning() const
{
    if (m_unmet.isEmpty())
        return {};
    // One copy key per fisherman `unmet` id; an id this build does not know
    // gets the title alone.
    static const QHash<QString, QString> keys{
        {QStringLiteral("ram"), QStringLiteral("requirements_ram")},
        {QStringLiteral("cpu"), QStringLiteral("requirements_cpu")},
        {QStringLiteral("uefi"), QStringLiteral("requirements_uefi")},
    };
    QStringList lines{text(QStringLiteral("requirements_title"))};
    for (const QString &item : m_unmet) {
        if (keys.contains(item))
            lines << text(keys.value(item));
    }
    lines.removeAll(QString());
    return lines.join(QLatin1Char('\n'));
}

void InstallerController::setDisk(const QString &v)
{
    if (m_recipe.disk == v)
        return;
    m_recipe.disk = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setFilesystem(const QString &v)
{
    if (m_recipe.filesystem == v)
        return;
    m_recipe.filesystem = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setBtrfsSubvolumes(bool v)
{
    if (m_recipe.btrfsSubvolumes == v)
        return;
    m_recipe.btrfsSubvolumes = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setEncryptionType(const QString &v)
{
    if (m_recipe.encryption.type == v)
        return;
    m_recipe.encryption.type = v;
    // A type that takes no passphrase (needs_passphrase in
    // encryption-choices.json) must not keep one lying around in the recipe.
    if (!Recipe::needsPassphrase(v))
        m_recipe.encryption.passphrase.clear();
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setPassphrase(const QString &v)
{
    if (m_recipe.encryption.passphrase == v)
        return;
    m_recipe.encryption.passphrase = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setHostname(const QString &v)
{
    if (m_recipe.hostname == v)
        return;
    m_recipe.hostname = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setImage(const QString &v)
{
    if (m_recipe.image == v)
        return;
    m_recipe.image = v;
    Q_EMIT recipeChanged();
}

// The copy key for an encryption type; fisherman reads "" as "none".
static QString encryptionKey(const QString &type, const char *suffix)
{
    const QString id = type.isEmpty() ? QStringLiteral("none") : type;
    return QStringLiteral("encryption_") + QString(id).replace(QLatin1Char('-'), QLatin1Char('_'))
        + QLatin1String(suffix);
}

QString InstallerController::encryptionLabel(const QString &type) const
{
    return text(encryptionKey(type, "_label"));
}

QString InstallerController::encryptionDescription(const QString &type) const
{
    return text(encryptionKey(type, "_description"));
}

// The install log existed only in m_log, i.e. only in the TextArea on the
// progress page. Everything fisherman said about a failure was gone the moment
// the window closed — and after a failed install the next step is usually to
// close it and reboot. Mirror it to a file as it arrives, so it outlives both
// the window and the session that produced it.
void InstallerController::openLogFile()
{
    // A retry must not keep advertising the previous run's file.
    closeLogFile();
    if (!m_logPath.isEmpty()) {
        m_logPath.clear();
        Q_EMIT logPathChanged();
    }

    const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (dir.isEmpty() || !QDir().mkpath(dir)) {
        qCWarning(logInstaller) << "no writable location for the install log:" << dir;
        return;
    }

    const QString path =
        QDir(dir).filePath(QStringLiteral("install-%1.log")
                               .arg(QDateTime::currentDateTimeUtc()
                                        .toString(QStringLiteral("yyyyMMdd-hhmmss"))));

    auto *file = new QFile(path, this);
    if (!file->open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) {
        qCWarning(logInstaller) << "cannot open the install log" << path << ":"
                                << file->errorString();
        delete file;
        return;
    }
    // fisherman's output is not expected to contain the passphrase, but this
    // file records a privileged install verbatim: keep it owner-only rather
    // than trusting the umask.
    file->setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);

    m_logFile = file;
    m_logPath = path;
    qCInfo(logInstaller) << "writing the install log to" << path;
    Q_EMIT logPathChanged();
}

void InstallerController::closeLogFile()
{
    if (!m_logFile)
        return;
    m_logFile->close();
    m_logFile->deleteLater();
    m_logFile = nullptr;
}

// Friendly labels for fisherman's step names, matching the other frontends
// (shared/progress/progress_parser.py). An unknown step falls back to its raw
// name, so a new step in fisherman degrades to showing what it really is
// rather than showing nothing.
// The step-name table: the fallback label for a step event without a
// step_id, from a fisherman older than tuna-os/fisherman#270. A step_id is
// labelled by the copy key step_<id> instead (stepLabel below); these labels
// match those keys' defaults.
static QString friendlyStep(const QString &name, const QString &product)
{
    static const QHash<QString, QString> labels = {
        {QStringLiteral("Preparing disk"), QStringLiteral("Checking your drive…")},
        {QStringLiteral("Partitioning disk"), QStringLiteral("Setting up your drive…")},
        {QStringLiteral("Formatting EFI partition"), QStringLiteral("Preparing the boot system…")},
        {QStringLiteral("Setting up disk encryption"), QStringLiteral("Securing your drive…")},
        {QStringLiteral("Formatting root filesystem"), QStringLiteral("Formatting your drive…")},
        {QStringLiteral("Mounting filesystem"), QStringLiteral("Almost ready…")},
        {QStringLiteral("Formatting data disk (/var)"), QStringLiteral("Preparing data storage…")},
        // The one label that names the product. It must say what THIS build
        // installs; nothing here may name a distro (CLAUDE.md).
        {QStringLiteral("Installing OS"), QStringLiteral("Installing %1…")},
        {QStringLiteral("Enrolling TPM2 auto-unlock"), QStringLiteral("Setting up auto-unlock…")},
        {QStringLiteral("Copying system Flatpaks"), QStringLiteral("Installing your apps…")},
        {QStringLiteral("Configuring installed system"), QStringLiteral("Configuring your system…")},
        {QStringLiteral("Finalizing installation"), QStringLiteral("Finishing up…")},
    };
    const QString label = labels.value(name, name);
    return label.contains(QLatin1String("%1")) ? label.arg(product) : label;
}

void InstallerController::setRecoveryAck(bool v)
{
    if (m_recoveryAck == v)
        return;
    m_recoveryAck = v;
    Q_EMIT recoveryChanged();
}

void InstallerController::resetProgress()
{
    m_step = 0;
    m_totalSteps = 0;
    m_fraction = 0.0;
    m_stepName.clear();
    m_recoveryKey.clear();
    m_recoveryAck = false;
    Q_EMIT recoveryChanged();
    m_cumulativePct = 0;
    m_weightPct = 0;
    m_stepFrac = 0.0;
    m_postPullBase = -1.0;
    Q_EMIT progressChanged();
}

// Share of a step's weight the layer pull covers; the rest is for the
// export, deploy and bootloader phases after it, which have no counter.
static constexpr double kPullShare = 0.6;

// Bar positions for the silent phases after the pull, as a share of what is
// left of the step, matched as message prefixes. Without these an offline
// install sat at 1% through ten minutes of export and deploy (#115). Same
// table and semantics as shared/progress/progress_parser.py; the numbers are
// pinned by shared/progress/fraction-cases.json.
static double phaseMilestone(const QString &message)
{
    static const struct {
        const char *prefix;
        double share;
    } milestones[] = {
        {"Exporting image to OCI layout", 0.05},
        {"OCI export complete", 0.30},
        {"Using ", 0.32},
        {"Initializing ostree layout", 0.35},
        {"Writing ", 0.35},
        {"Deploying image", 0.35},
        {"OS deployed, installing bootloader", 0.90},
        {"Detected bootloader", 0.92},
        {"Installing bootloader", 0.92},
        {"Configuring EFI boot entry", 0.95},
        {"Configuring GRUB", 0.95},
        {"Configuring SELinux", 0.95},
        {"Generating initramfs", 0.95},
        {"bootc installation complete", 1.0},
    };
    for (const auto &m : milestones) {
        if (message.startsWith(QLatin1String(m.prefix)))
            return m.share;
    }
    return -1.0;
}

// The label for a step: the branding copy line step_<step_id>
// (shared/branding/README.md, "Install steps"), so a product can rebrand it.
// An event without a step_id, or an id the copy has no line for, falls back
// to the step-name table and then to fisherman's raw step_name.
QString InstallerController::stepLabel(const QString &stepId, const QString &stepName) const
{
    if (!stepId.isEmpty()) {
        const QString label = text(QStringLiteral("step_") + stepId);
        if (!label.isEmpty())
            return label;
    }
    return friendlyStep(stepName, m_productName);
}

// fisherman's own bar (overall_pct, 0-100) on step, substep and complete
// events since tuna-os/fisherman#270. It is authoritative: when the event
// carries it, it replaces whatever the derivation in consumeProgress()
// computed. Clamped to 0-1 and never below the bar before this event.
// Returns false for an event without it (an older fisherman).
static bool applyOverallPct(const QJsonObject &event, qreal before, qreal &fraction)
{
    const QJsonValue v = event.value(QStringLiteral("overall_pct"));
    if (!v.isDouble())
        return false;
    fraction = qMax(before, qBound(0.0, v.toDouble() / 100.0, 1.0));
    return true;
}

QString InstallerController::consumeProgress(const QString &line)
{
    const QString trimmed = line.trimmed();
    if (!trimmed.startsWith(QLatin1Char('{')))
        return line;
    QJsonParseError err{};
    const QJsonDocument doc = QJsonDocument::fromJson(trimmed.toUtf8(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject())
        return line;

    const QJsonObject event = doc.object();
    const QString type = event.value(QStringLiteral("type")).toString();
    const qreal before = m_fraction;

    if (type == QLatin1String("step")) {
        const int step = event.value(QStringLiteral("step")).toInt();
        const QString name = event.value(QStringLiteral("step_name")).toString();
        // A repeated or earlier step is ignored, as in the canonical parser:
        // it must not reset the bar.
        if (m_step > 0 && step <= m_step) {
            return QStringLiteral("[%1/%2] %3")
                .arg(step)
                .arg(event.value(QStringLiteral("total_steps")).toInt())
                .arg(name);
        }
        m_step = step;
        m_totalSteps = event.value(QStringLiteral("total_steps")).toInt();
        m_stepFrac = 0.0;
        m_postPullBase = -1.0;
        m_cumulativePct = event.value(QStringLiteral("cumulative_pct")).toInt();
        m_weightPct = event.value(QStringLiteral("weight_pct")).toInt();
        // The derivation, the fallback when the event has no overall_pct.
        m_fraction = m_cumulativePct / 100.0;
        applyOverallPct(event, before, m_fraction);
        m_stepName = stepLabel(event.value(QStringLiteral("step_id")).toString(), name);
        Q_EMIT progressChanged();
        return QStringLiteral("[%1/%2] %3").arg(m_step).arg(m_totalSteps).arg(name);
    }
    if (type == QLatin1String("substep") || type == QLatin1String("info")) {
        const QString message = event.value(QStringLiteral("message")).toString();
        if (type == QLatin1String("substep") && m_weightPct > 0) {
            // The layer pull covers the first kPullShare of the step; the
            // named phases after it cover the rest.
            static const QRegularExpression layers(
                QStringLiteral("^Pulling image: layer (\\d+)/(\\d+)"));
            double stepFrac = -1.0;
            const QRegularExpressionMatch m = layers.match(message);
            if (m.hasMatch()) {
                const double done = m.captured(1).toDouble();
                const double total = m.captured(2).toDouble();
                if (total > 0)
                    stepFrac = qMin(done / total, 1.0) * kPullShare;
            } else {
                const double share = phaseMilestone(message);
                if (share >= 0) {
                    if (m_postPullBase < 0)
                        m_postPullBase = m_stepFrac;
                    stepFrac = m_postPullBase + share * (1.0 - m_postPullBase);
                }
            }
            if (stepFrac >= 0) {
                // Never move backwards: a retried pull restarts its count.
                m_stepFrac = qMax(m_stepFrac, stepFrac);
                m_fraction = qMin((m_cumulativePct + m_stepFrac * m_weightPct) / 100.0, 1.0);
            }
        }
        if (type == QLatin1String("substep"))
            applyOverallPct(event, before, m_fraction);
        if (m_fraction != before)
            Q_EMIT progressChanged();
        return message.isEmpty() ? QString() : QStringLiteral("  ") + message;
    }
    if (type == QLatin1String("complete")) {
        // cumulative_pct only ever reaches 99; `complete` fills the bar.
        m_fraction = 1.0;
        Q_EMIT progressChanged();
        const QString message = event.value(QStringLiteral("message")).toString();
        return message.isEmpty() ? QStringLiteral("Installation complete") : message;
    }
    if (type == QLatin1String("error"))
        return QStringLiteral("ERROR: ") + event.value(QStringLiteral("message")).toString();
    if (type == QLatin1String("recovery_key")) {
        // Kept in the log as well as on the done page: the log is what gets
        // pasted into a bug report, and a key that only ever existed on a
        // screen the user already dismissed is no better than one that was
        // never shown (#129).
        m_recoveryKey = event.value(QStringLiteral("key")).toString();
        Q_EMIT recoveryChanged();
        return QStringLiteral("Recovery key: ") + m_recoveryKey;
    }
    return QString();
}

void InstallerController::appendLine(const QString &line, bool parse)
{
    // The log PANE shows the event rendered for a person; the log FILE keeps
    // the raw protocol, because that is what gets attached to a bug report.
    // Only stdout carries the protocol: stderr is shown as it is.
    const QString shown = parse ? consumeProgress(line) : line;
    if (!shown.isEmpty()) {
        m_log += shown;
        if (!shown.endsWith(QLatin1Char('\n')))
            m_log += QLatin1Char('\n');
    }

    if (m_logFile) {
        m_logFile->write(line.toUtf8());
        if (!line.endsWith(QLatin1Char('\n')))
            m_logFile->write("\n");
        // Flushed per line: the interesting case is the one where the machine
        // is about to be rebooted or powered off by hand.
        m_logFile->flush();
    }

    Q_EMIT logChanged();
}

// stdout and stderr used to be appended to ONE buffer. A stdout JSON event
// that arrived in two reads, with a stderr chunk in between, came out as two
// broken lines: the head of the event glued to the stderr text (and labelled
// stderr), then the tail of the event with no leading '{' — so the progress
// event was lost. Each stream now keeps its own partial line. Buffers hold
// bytes, not text, so a UTF-8 sequence split across reads is decoded whole.
void InstallerController::consumeStdout(const QByteArray &data)
{
    m_stdoutBuffer += data;
    drainBuffer(m_stdoutBuffer, {}, true);
}

void InstallerController::consumeStderr(const QByteArray &data)
{
    m_stderrBuffer += data;
    drainBuffer(m_stderrBuffer, QStringLiteral("[stderr] "), false);
}

void InstallerController::flushStreams()
{
    if (!m_stdoutBuffer.isEmpty())
        appendLine(QString::fromUtf8(m_stdoutBuffer), true);
    if (!m_stderrBuffer.isEmpty())
        appendLine(QStringLiteral("[stderr] ") + QString::fromUtf8(m_stderrBuffer), false);
    m_stdoutBuffer.clear();
    m_stderrBuffer.clear();
}

void InstallerController::drainBuffer(QByteArray &buffer, const QString &prefix, bool parse)
{
    qsizetype nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
        appendLine(prefix + QString::fromUtf8(buffer.left(nl)), parse);
        buffer.remove(0, nl + 1);
    }
}

void InstallerController::fail(const QString &message)
{
    qCWarning(logInstaller) << "install failed:" << message;
    appendLine(QStringLiteral("\nERROR: %1").arg(message));
    closeLogFile();
    m_finished = true;
    m_exitCode = 1;
    Q_EMIT installCompleted(1);
}

void InstallerController::loadDemoState(const QString &log, int exitCode)
{
    // Through appendLine(), the path a real install takes, so the bar and the
    // step caption are the live code rather than something the harness paints
    // on. Assigning m_log directly, as this used to, is how a screen can be
    // photographed without running any of what it is supposed to show.
    m_log.clear();
    resetProgress();
    const QStringList lines = log.split(QLatin1Char('\n'));
    for (const QString &line : lines) {
        if (!line.trimmed().isEmpty())
            appendLine(line);
    }
    m_finished = true;
    m_exitCode = exitCode;
    Q_EMIT logChanged();
    Q_EMIT installCompleted(exitCode);
}

void InstallerController::startInstall()
{
    if (m_process)
        return;

    // Not live media and nothing chosen: the branding's default image. On
    // live media the image stays empty and fisherman installs the running
    // system; it rejects an empty image anywhere else (image_required). No
    // additionalImageStores: fisherman exposes the host's offline stores.
    if (m_recipe.image.isEmpty() && !m_recipe.liveMode)
        m_recipe.image = m_branding.defaultImage;

    m_log.clear();
    m_stdoutBuffer.clear();
    m_stderrBuffer.clear();
    m_finished = false;
    Q_EMIT logChanged();

    // Before the recipe is written, so the failures below are logged too.
    openLogFile();
    resetProgress();
    appendLine(QStringLiteral("Starting installation..."));

    // The recipe can hold a LUKS passphrase. It goes to fisherman's stdin
    // (`fisherman -`, tuna-os/fisherman#276) and never to a file: this used
    // to be a 0600 file in a QTemporaryDir, handed to root by path.
    const QByteArray recipeJson = QJsonDocument(m_recipe.toJson()).toJson(QJsonDocument::Compact);

#if !QT_CONFIG(process)
    // Qt for WebAssembly: there is no process to start. Only the browser
    // harness builds this, and nothing there presses Install; if something
    // ever does, it gets the ordinary failure path rather than a silent hang.
    Q_UNUSED(recipeJson);
    fail(QStringLiteral("This build cannot start fisherman"));
#else
    // flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -' in
    // Flatpak, sudo /usr/local/bin/fisherman - otherwise.
    QStringList cmd = offline::fishermanCommand();

    m_process = new QProcess(this);
    m_process->setProgram(cmd.takeFirst());
    m_process->setArguments(cmd);
    // Its own process group: the cancel contract is "kill your wrapper's
    // group". This frontend has no cancel UI, so nothing signals it yet.
    offline::startInOwnProcessGroup(*m_process);

    // Which escalation path was taken (pkexec via flatpak-spawn, or sudo) is
    // the first thing anyone reading a failed install needs to know.
    appendLine(QStringLiteral("Running: %1 %2")
                   .arg(m_process->program(), m_process->arguments().join(QLatin1Char(' '))));

    // Without this, a fisherman that never starts — no pkexec in the sandbox,
    // the polkit agent missing, the binary not installed — emitted no
    // finished() either. The wizard sat on the progress page with a spinner
    // and "Starting installation..." forever, saying nothing.
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        // Every other error is followed by finished(), which reports it below.
        if (error != QProcess::FailedToStart)
            return;
        const QString message = QStringLiteral("Could not start %1: %2")
                                    .arg(m_process->program(), m_process->errorString());
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        fail(message);
    });

    connect(m_process, &QProcess::readyReadStandardOutput, this, [this]() {
        consumeStdout(m_process->readAllStandardOutput());
    });
    connect(m_process, &QProcess::readyReadStandardError, this, [this]() {
        consumeStderr(m_process->readAllStandardError());
    });
    connect(m_process, &QProcess::finished, this,
            [this](int exitCode, QProcess::ExitStatus status) {
        flushStreams();

        if (status == QProcess::CrashExit) {
            qCWarning(logInstaller) << "fisherman crashed";
            appendLine(QStringLiteral("\nERROR: fisherman crashed"));
            m_exitCode = 1;
        } else {
            m_exitCode = exitCode;
            if (exitCode != 0)
                qCWarning(logInstaller) << "fisherman exited with" << exitCode;
            appendLine(exitCode == 0
                           ? QStringLiteral("\n✓ Installation complete!")
                           : QStringLiteral("\n✗ Installation failed (exit code %1)").arg(exitCode));
        }
        if (!m_logPath.isEmpty())
            appendLine(QStringLiteral("Log: %1").arg(m_logPath));
        closeLogFile();
        m_finished = true;
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        Q_EMIT installCompleted(m_exitCode);
    });

    m_process->start();
    // Buffered until the process starts, then written; closing the channel
    // is the EOF fisherman reads to.
    m_process->write(recipeJson);
    m_process->closeWriteChannel();
    Q_EMIT installingChanged();
#endif
}

void InstallerController::reboot()
{
    // Same host path as the install: flatpak-spawn --host when sandboxed.
    QStringList argv = offline::hostCommand({QStringLiteral("systemctl"), QStringLiteral("reboot")});
    const QString program = argv.takeFirst();
#if QT_CONFIG(process)
    QProcess::startDetached(program, argv);
#else
    qCWarning(logInstaller) << "this build cannot start processes, not running" << program;
#endif
}

#include "offline.h"
#include "branding.h"
#include "branding_defaults.h"
#include "readiness.h"
#include "recipe.h"
#include "installercontroller.h"
#include "probe.h"
#include "diskmodel.h"
#include "validate.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QUrl>

#include <csignal>
#include <unistd.h>

class BackendTest : public QObject
{
    Q_OBJECT

private slots:
    void recipeDefaults();
    void recipeJsonOmitsOptionalValues();
    void recipeJsonIncludesConfiguredValues();
    void recipeValidation_data();
    void recipeValidation();
    void recipeJsonRoundTrip();
    void recipeUserBlock();
    void recipeUserOmittedWithoutUsername();
    void controllerAccountFields();
    void validateUsernameProblem();
    void brandingFixtures();
    void brandingLogoFixtures();
    void brandingLogoSourceEscapesFilenames();
    void brandingLogoReachesController();
    void brandingText();
    void brandingNothingReadableIsNeutral();
    void encryptionChoicesReadTheCopyLayer();
    void offlineCommandHelpers();
    void readinessWriteStampFailsWithEmptyRuntimeDir();
    void readinessWriteStampWritesExpectedFields();
    void readinessWriteStampBlankPageBecomesUnknown();

    // `fisherman probe --json` (shared/probe/README.md): the same fixtures
    // and expected renderings every frontend is tested against.
    void probeFixtures_data();
    void probeFixtures();
    void probeFakeEnvReachesTheController();
    void probeFailureOffersNothingAndSaysWhy();
    void probeCommandIsUnprivileged();

    // fisherman's progress protocol (shared/progress/README.md). KDE had no
    // progress bar; these pin the parse that now drives one.
    void progressStepEventMovesTheBar();
    void progressUsesCumulativePctNotStepOverTotal();
    void progressSubstepInterpolatesInsideTheLongStep();
    void progressReproducesTheSharedFractionCases();
    // fisherman's overall_pct and step_id (tuna-os/fisherman#270).
    void progressReproducesTheSharedOverallPctCases();
    void progressOverallPctDrivesTheBar();
    void progressStepIdReadsTheCopyLayer();
    void progressCompleteFillsTheBar();
    void progressIgnoresNonProtocolLines();
    void progressRejectsTheInventedStepPrefix();
    void progressUnknownStepNameFallsBackToTheRawName();

    // Recovery key (#129). The event used to be formatted into a log line
    // and dropped, so nothing could show it after the install.
    void recoveryKeyIsKeptNotJustPrinted();
    void recoveryKeyHoldsRestartUntilAcknowledged();
    void recoveryKeyAbsentMeansNoGate();
    void progressRendersEventsForTheLogPane();

    // stdout and stderr shared one line buffer, so a stdout event split
    // across two reads merged with stderr output and lost its leading '{'.
    void streamsKeepSeparatePartialLines();

    // The wrapper runs pkexec under a host bash and leads its own process
    // group, the shared cancel contract.
    void flatpakWrapperPassesStdinOutputAndStatusThrough();
    void wrapperLeadsItsOwnProcessGroup();
    void validateAnswersBecomeCopyLines();
    void validateSendsAPartialRecipeOnStdin();
    void liveMediaComesFromTheProbe();
};

void BackendTest::recipeDefaults()
{
    const Recipe recipe;

    QCOMPARE(recipe.filesystem, QStringLiteral("xfs"));
    QCOMPARE(recipe.encryption.type, QStringLiteral("none"));
    // Neutral until InstallerController fills them from the branding contract.
    QVERIFY(recipe.distroID.isEmpty());
    QVERIFY(recipe.hostname.isEmpty());
    QVERIFY(!recipe.selinuxDisabled);
    QVERIFY(!recipe.liveMode);
}

void BackendTest::recipeJsonOmitsOptionalValues()
{
    const QJsonObject json = Recipe{}.toJson();

    // "image" is not one of the optional keys for a normal install: fisherman
    // is always handed it, and rejects an empty one off live media
    // (image_required). Only on live media (probe's live.is_live) may it be
    // omitted — see the liveMode branch in Recipe::toJson().
    QVERIFY(json.contains(QStringLiteral("image")));

    Recipe live;
    live.liveMode = true;
    QVERIFY(!live.toJson().contains(QStringLiteral("image")));

    QVERIFY(!json.contains(QStringLiteral("targetImgref")));
    QVERIFY(!json.contains(QStringLiteral("bootloader")));
    QVERIFY(!json.contains(QStringLiteral("composeFsBackend")));
    QVERIFY(!json.contains(QStringLiteral("flatpaks")));
    QVERIFY(!json.contains(QStringLiteral("additionalImageStores")));
    QCOMPARE(json.value(QStringLiteral("encryption")).toObject()
                 .value(QStringLiteral("type")).toString(),
             QStringLiteral("none"));
}

void BackendTest::recipeJsonIncludesConfiguredValues()
{
    Recipe recipe;
    recipe.disk = QStringLiteral("/dev/nvme0n1");
    recipe.image = QStringLiteral("ghcr.io/tuna-os/tunaos:latest");
    recipe.targetImgref = QStringLiteral("ghcr.io/tuna-os/tunaos:stable");
    recipe.bootloader = QStringLiteral("systemd");
    recipe.composeFsBackend = true;
    recipe.flatpaks = {QStringLiteral("org.mozilla.firefox")};
    recipe.additionalImageStores = {QStringLiteral("/run/media/oci")};
    recipe.encryption.type = QStringLiteral("luks-passphrase");
    recipe.encryption.passphrase = QStringLiteral("secret");

    const QJsonObject json = recipe.toJson();
    QCOMPARE(json.value(QStringLiteral("disk")).toString(), recipe.disk);
    QCOMPARE(json.value(QStringLiteral("image")).toString(), recipe.image);
    QCOMPARE(json.value(QStringLiteral("targetImgref")).toString(), recipe.targetImgref);
    QCOMPARE(json.value(QStringLiteral("bootloader")).toString(), recipe.bootloader);
    QVERIFY(json.value(QStringLiteral("composeFsBackend")).toBool());
    QCOMPARE(json.value(QStringLiteral("flatpaks")).toArray().first().toString(),
             recipe.flatpaks.first());
    QCOMPARE(json.value(QStringLiteral("additionalImageStores")).toArray().first().toString(),
             recipe.additionalImageStores.first());
    QCOMPARE(json.value(QStringLiteral("encryption")).toObject()
                 .value(QStringLiteral("passphrase")).toString(),
             recipe.encryption.passphrase);
}

void BackendTest::recipeValidation_data()
{
    QTest::addColumn<QString>("disk");
    QTest::addColumn<QString>("image");
    QTest::addColumn<bool>("liveMode");
    QTest::addColumn<QString>("hostname");
    QTest::addColumn<QString>("encryptionType");
    QTest::addColumn<QString>("passphrase");
    QTest::addColumn<QString>("expectedError");

    QTest::newRow("valid-image") << "/dev/vda" << "example/image" << false << "tunaos" << "none" << "" << "";
    QTest::newRow("valid-live") << "/dev/vda" << "" << true << "tunaos" << "none" << "" << "";
    QTest::newRow("missing-disk") << "" << "example/image" << false << "tunaos" << "none" << "" << "No disk selected";
    // The image, hostname and encryption rules are fisherman's
    // (`validate --json`, the install runs them before touching a disk):
    // this frontend no longer keeps a copy of them.
    QTest::newRow("image-is-fishermans") << "/dev/vda" << "" << false << "tunaos" << "none" << "" << "";
    QTest::newRow("hostname-is-fishermans") << "/dev/vda" << "example/image" << false << "" << "none" << "" << "";
    QTest::newRow("encryption-is-fishermans") << "/dev/vda" << "example/image" << false << "tunaos" << "plain" << "" << "";
    QTest::newRow("passphrase-is-fishermans") << "/dev/vda" << "example/image" << false << "tunaos" << "luks-passphrase" << "" << "";
    QTest::newRow("valid-passphrase") << "/dev/vda" << "example/image" << false << "tunaos" << "luks-passphrase" << "secret" << "";
}

void BackendTest::recipeValidation()
{
    QFETCH(QString, disk);
    QFETCH(QString, image);
    QFETCH(bool, liveMode);
    QFETCH(QString, hostname);
    QFETCH(QString, encryptionType);
    QFETCH(QString, passphrase);
    QFETCH(QString, expectedError);

    Recipe recipe;
    recipe.disk = disk;
    recipe.image = image;
    recipe.liveMode = liveMode;
    recipe.hostname = hostname;
    recipe.encryption.type = encryptionType;
    recipe.encryption.passphrase = passphrase;

    QCOMPARE(recipe.validationError(), expectedError);
    QCOMPARE(recipe.isValid(), expectedError.isEmpty());
}

void BackendTest::recipeJsonRoundTrip()
{
    Recipe original;
    original.disk = QStringLiteral("/dev/sda");
    original.filesystem = QStringLiteral("ext4");
    original.image = QStringLiteral("ghcr.io/tuna-os/yellowfin:gnome");
    original.targetImgref = QStringLiteral("ghcr.io/tuna-os/yellowfin:stable");
    original.bootloader = QStringLiteral("systemd");
    original.composeFsBackend = true;
    original.flatpaks = {QStringLiteral("org.gnome.TextEditor"), QStringLiteral("org.kde.kcalc")};
    original.additionalImageStores = {QStringLiteral("/run/media/store")};
    original.distroID = QStringLiteral("tunaos");
    original.hostname = QStringLiteral("custom-host");
    original.encryption.type = QStringLiteral("luks-passphrase");
    original.encryption.passphrase = QStringLiteral("pass");

    const QJsonObject json = original.toJson();
    const Recipe restored = Recipe::fromJson(json);

    QCOMPARE(restored.disk, original.disk);
    QCOMPARE(restored.filesystem, original.filesystem);
    QCOMPARE(restored.image, original.image);
    QCOMPARE(restored.targetImgref, original.targetImgref);
    QCOMPARE(restored.bootloader, original.bootloader);
    QCOMPARE(restored.composeFsBackend, original.composeFsBackend);
    QCOMPARE(restored.flatpaks, original.flatpaks);
    QCOMPARE(restored.additionalImageStores, original.additionalImageStores);
    QCOMPARE(restored.distroID, original.distroID);
    QCOMPARE(restored.hostname, original.hostname);
    QCOMPARE(restored.encryption.type, original.encryption.type);
    QCOMPARE(restored.encryption.passphrase, original.encryption.passphrase);

    Recipe withUser = original;
    withUser.user.username = QStringLiteral("alex");
    withUser.user.fullname = QStringLiteral("Alex Example");
    withUser.user.password = QStringLiteral("pw");
    const Recipe restoredUser = Recipe::fromJson(withUser.toJson());
    QCOMPARE(restoredUser.user.username, withUser.user.username);
    QCOMPARE(restoredUser.user.fullname, withUser.user.fullname);
    QCOMPARE(restoredUser.user.password, withUser.user.password);
    QCOMPARE(restoredUser.user.groups, QStringList{QStringLiteral("wheel")});
}

// The schema's `user` block, the way XFCE's build_recipe writes it:
// username, fullname, password and groups ["wheel"].
void BackendTest::recipeUserBlock()
{
    Recipe recipe;
    recipe.disk = QStringLiteral("/dev/vda");
    recipe.user.username = QStringLiteral("alex");
    recipe.user.fullname = QStringLiteral("Alex Example");
    recipe.user.password = QStringLiteral("s3cret");

    const QJsonObject json = recipe.toJson();
    QVERIFY(json.contains(QStringLiteral("user")));
    const QJsonObject user = json.value(QStringLiteral("user")).toObject();
    QCOMPARE(user.keys(), (QStringList{QStringLiteral("fullname"), QStringLiteral("groups"),
                                       QStringLiteral("password"), QStringLiteral("username")}));
    QCOMPARE(user.value(QStringLiteral("username")).toString(), QStringLiteral("alex"));
    QCOMPARE(user.value(QStringLiteral("fullname")).toString(), QStringLiteral("Alex Example"));
    QCOMPARE(user.value(QStringLiteral("password")).toString(), QStringLiteral("s3cret"));
    QCOMPARE(user.value(QStringLiteral("groups")).toArray(), QJsonArray{QStringLiteral("wheel")});

    // An empty full name is still written (the schema allows it, and XFCE
    // writes it the same way); fisherman then leaves the GECOS field empty.
    recipe.user.fullname.clear();
    QVERIFY(recipe.toJson().value(QStringLiteral("user")).toObject()
                .value(QStringLiteral("fullname")).toString().isEmpty());
}

void BackendTest::recipeUserOmittedWithoutUsername()
{
    // No username, no block: fisherman reads an absent `user` as "create no
    // account", and a block with an empty username the same way, so the
    // recipe carries neither the block nor a stray password.
    QVERIFY(!Recipe{}.toJson().contains(QStringLiteral("user")));

    Recipe recipe;
    recipe.user.fullname = QStringLiteral("Alex Example");
    recipe.user.password = QStringLiteral("left over");
    const QJsonObject json = recipe.toJson();
    QVERIFY(!json.contains(QStringLiteral("user")));
    QVERIFY(!QJsonDocument(json).toJson().contains("left over"));

    QCOMPARE(Recipe::fromJson(QJsonObject{}).user.groups, QStringList{QStringLiteral("wheel")});
}

void BackendTest::controllerAccountFields()
{
    InstallerController c;
    QVERIFY(c.username().isEmpty());
    QSignalSpy changed(&c, &InstallerController::recipeChanged);
    c.setUsername(QStringLiteral("alex"));
    c.setFullname(QStringLiteral("Alex Example"));
    c.setUserPassword(QStringLiteral("pw"));
    QCOMPARE(changed.count(), 3);
    c.setUsername(QStringLiteral("alex"));
    QCOMPARE(changed.count(), 3);
    QCOMPARE(c.username(), QStringLiteral("alex"));
    QCOMPARE(c.fullname(), QStringLiteral("Alex Example"));
    QCOMPARE(c.userPassword(), QStringLiteral("pw"));

    // The account step's field goes to `validate --json --partial`: the
    // username only. fisherman has no rule for the rest, and the password
    // has no business on a validate call.
    const QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("user")).toObject(),
             (QJsonObject{{QStringLiteral("username"), QStringLiteral("alex")}}));
    QVERIFY(!c.partialRecipe().contains("pw\""));
}

void BackendTest::validateUsernameProblem()
{
#ifndef VALIDATE_GOLDENS_DIR
    QSKIP("no goldens");
#else
    QFile golden(QStringLiteral(VALIDATE_GOLDENS_DIR) + QStringLiteral("/partial-user.golden"));
    if (!golden.open(QIODevice::ReadOnly))
        QSKIP("the fisherman submodule is not checked out");
    const QByteArray answer = golden.readAll();

    InstallerController c;
    QVERIFY(c.usernameProblem().isEmpty());
    c.applyValidateAnswer(answer);
    QCOMPARE(c.usernameProblem(), c.text(QStringLiteral("validate_username_reserved")));
    QVERIFY(!c.usernameProblem().isEmpty());
    // A username problem is the account step's alone.
    QVERIFY(c.hostnameProblem().isEmpty());
    QVERIFY(c.encryptionProblem().isEmpty());

    // Every username code fisherman has reads a copy line.
    for (const char *code : {"username_too_long", "username_invalid_start",
                             "username_invalid_char", "username_reserved"}) {
        c.applyValidateAnswer(QStringLiteral(
            R"({"protocol_version":1,"valid":false,"errors":[{"field":"user.username","code":"%1","message":"m"}]})")
                                  .arg(QLatin1String(code)).toUtf8());
        QVERIFY2(c.usernameProblem() != QStringLiteral("m"), code);
        QCOMPARE(c.usernameProblem(), c.text(QStringLiteral("validate_") + QLatin1String(code)));
    }
    c.applyValidateAnswer(R"({"protocol_version":1,"valid":true,"errors":[]})");
    QVERIFY(c.usernameProblem().isEmpty());
#endif
}

static QJsonObject readJsonObject(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QJsonDocument::fromJson(f.readAll()).object();
}

static QString readText(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};
    return QString::fromUtf8(f.readAll());
}

// shared/branding/fixtures/expected.json: the same cases the Python, Go and
// Rust resolvers are checked against.
void BackendTest::brandingFixtures()
{
    const QString dir = QStringLiteral(BRANDING_FIXTURES_DIR);
    const QJsonObject expected = readJsonObject(dir + QStringLiteral("/expected.json"));
    if (expected.isEmpty())
        QSKIP("shared branding fixtures not available");

    for (auto it = expected.begin(); it != expected.end(); ++it) {
        if (it.key().startsWith(QLatin1Char('_')))
            continue;
        const QJsonObject spec = it.value().toObject();
        QJsonObject file;
        if (spec.value(QStringLiteral("branding")).isString())
            file = readJsonObject(dir + QLatin1Char('/') + spec.value(QStringLiteral("branding")).toString());
        QString osRelease;
        if (spec.value(QStringLiteral("os_release")).isString())
            osRelease = readText(dir + QLatin1Char('/') + spec.value(QStringLiteral("os_release")).toString());
        const branding::Branding got = branding::fromSources(
            file, osRelease, spec.value(QStringLiteral("name_override")).toString());

        const QHash<QString, QString> gotMap = {
            {QStringLiteral("name"), got.name},
            {QStringLiteral("id"), got.id},
            {QStringLiteral("vendor"), got.vendor},
            {QStringLiteral("home_url"), got.homeUrl},
            {QStringLiteral("docs_url"), got.docsUrl},
            {QStringLiteral("support_url"), got.supportUrl},
            {QStringLiteral("logo"), got.logo},
            {QStringLiteral("default_hostname"), got.defaultHostname},
            {QStringLiteral("default_image"), got.defaultImage},
        };
        const QJsonObject expect = spec.value(QStringLiteral("expect")).toObject();
        for (auto e = expect.begin(); e != expect.end(); ++e) {
            QVERIFY2(gotMap.value(e.key()) == e.value().toString(),
                     qPrintable(it.key() + QStringLiteral(": ") + e.key() + QStringLiteral(" got '")
                                + gotMap.value(e.key()) + QStringLiteral("' want '")
                                + e.value().toString() + QStringLiteral("'")));
        }
        if (spec.contains(QStringLiteral("expect_name")))
            QCOMPARE(got.name, spec.value(QStringLiteral("expect_name")).toString());
        const QJsonObject expectCopy = spec.value(QStringLiteral("expect_copy")).toObject();
        for (auto e = expectCopy.begin(); e != expectCopy.end(); ++e) {
            QVERIFY2(got.copy.value(e.key()) == e.value().toString(),
                     qPrintable(it.key() + QStringLiteral(": copy.") + e.key() + QStringLiteral(" got '")
                                + got.copy.value(e.key()) + QStringLiteral("'")));
        }
        const QJsonObject expectAssets = spec.value(QStringLiteral("expect_assets")).toObject();
        for (auto e = expectAssets.begin(); e != expectAssets.end(); ++e)
            QCOMPARE(got.assets.value(e.key()), e.value().toString());
        if (spec.contains(QStringLiteral("expect_store_url")))
            QCOMPARE(got.storeUrl, spec.value(QStringLiteral("expect_store_url")).toString());
    }

    // The compiled-in defaults are the shared file, verbatim.
    QCOMPARE(QString::fromUtf8(kCopyDefaultsJson), readText(dir + QStringLiteral("/../copy-defaults.json")));
    QVERIFY(!branding::copyDefaults().value(QStringLiteral("welcome_title")).isEmpty());
}

void BackendTest::brandingLogoFixtures()
{
    const QString path = QStringLiteral(BRANDING_FIXTURES_DIR) + QStringLiteral("/logo-paths.json");
    const QJsonArray cases = readJsonObject(path).value(QStringLiteral("cases")).toArray();
    QVERIFY2(!cases.isEmpty(), qPrintable(QStringLiteral("Missing logo fixtures: ") + path));
    for (const QJsonValue &entry : cases) {
        const QJsonObject spec = entry.toObject();
        const branding::Logo got = branding::resolveLogo(
            spec.value(QStringLiteral("spec")).toString(), spec.value(QStringLiteral("in_flatpak")).toBool());
        const QString kind = got.kind == branding::Logo::Kind::File ? QStringLiteral("file")
            : got.kind == branding::Logo::Kind::Theme ? QStringLiteral("theme") : QStringLiteral("none");
        QCOMPARE(kind, spec.value(QStringLiteral("kind")).toString());
        QCOMPARE(got.value, spec.value(QStringLiteral("value")).toString());
        if (got.kind == branding::Logo::Kind::File)
            QCOMPARE(QUrl(got.source()).toLocalFile(), got.value);
        else
            QCOMPARE(got.source(), got.value);
    }
}

void BackendTest::brandingLogoSourceEscapesFilenames()
{
    const QString path = QStringLiteral("/tmp/logo with spaces #1%20?.png");
    const branding::Logo logo = branding::resolveLogo(path, false);
    QCOMPARE(logo.source(), QStringLiteral("file:///tmp/logo%20with%20spaces%20%231%2520%3F.png"));
    QCOMPARE(QUrl(logo.source()).toLocalFile(), path);
    QVERIFY(branding::resolveLogo(QStringLiteral("  "), true).source().isEmpty());
    QCOMPARE(branding::resolveLogo(QStringLiteral(" example-logo "), true).source(),
             QStringLiteral("example-logo"));
    QCOMPARE(branding::resolveLogo(QStringLiteral("/usr-local/logo.svg"), true).value,
             QStringLiteral("/usr-local/logo.svg"));
    QVERIFY(branding::resolveLogo(QStringLiteral("https://example.com/logo.png"), false).source().isEmpty());
}

void BackendTest::brandingLogoReachesController()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"logo": "/usr/share/example/logo with spaces #1.svg"})");
    f.close();
    const QByteArray previous = qgetenv("BOOTC_INSTALLER_BRANDING");
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController controller;
    if (previous.isNull())
        qunsetenv("BOOTC_INSTALLER_BRANDING");
    else
        qputenv("BOOTC_INSTALLER_BRANDING", previous);
    QCOMPARE(controller.logoSource(), branding::resolveLogo(
        QStringLiteral("/usr/share/example/logo with spaces #1.svg"), offline::inFlatpak()).source());
    QCOMPARE(controller.property("logoSource").toString(), controller.logoSource());
}

void BackendTest::encryptionChoicesReadTheCopyLayer()
{
    // The ids and their order are fisherman's encryption-choices.json,
    // compiled in from frontends/kde/encryption-choices.json.
    const QStringList types = {QStringLiteral("none"), QStringLiteral("luks-passphrase"),
                               QStringLiteral("tpm2-luks"), QStringLiteral("tpm2-luks-passphrase")};
    QCOMPARE(Recipe::encryptionTypes(), types);
    QVERIFY(Recipe::needsPassphrase(QStringLiteral("tpm2-luks-passphrase")));
    QVERIFY(!Recipe::needsPassphrase(QStringLiteral("tpm2-luks")));
    QVERIFY(!Recipe::needsPassphrase(QString()));
    QVERIFY(Recipe::needsTpm2(QStringLiteral("tpm2-luks")));
    QVERIFY(!Recipe::needsTpm2(QStringLiteral("luks-passphrase")));

    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"name": "Marlin", "copy": {"encryption_tpm2_luks_label": "Hardware key"}})");
    f.close();
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController c;
    qunsetenv("BOOTC_INSTALLER_BRANDING");

    QCOMPARE(c.encryptionTypes(), types);
    for (const QString &type : types) {
        QVERIFY2(!c.encryptionLabel(type).isEmpty(), qPrintable(type));
        QVERIFY2(!c.encryptionDescription(type).isEmpty(), qPrintable(type));
    }
    // The confirm step used to say "None" and "Passphrase (LUKS)" here while
    // the encryption step said "No encryption" and "Passphrase".
    QCOMPARE(c.encryptionLabel(QStringLiteral("none")), QStringLiteral("No encryption"));
    QCOMPARE(c.encryptionLabel(QString()), QStringLiteral("No encryption"));
    QCOMPARE(c.encryptionLabel(QStringLiteral("luks-passphrase")), QStringLiteral("Passphrase"));
    QCOMPARE(c.encryptionDescription(QStringLiteral("luks-passphrase")),
             QStringLiteral("You'll type it at every boot."));
    // A product renames a choice once, in its branding file.
    QCOMPARE(c.encryptionLabel(QStringLiteral("tpm2-luks")), QStringLiteral("Hardware key"));
}

void BackendTest::brandingText()
{
    QJsonObject file;
    file.insert(QStringLiteral("name"), QStringLiteral("Marlin"));
    const branding::Branding b = branding::fromSources(file, QString());
    QCOMPARE(b.text(QStringLiteral("welcome_title")), QStringLiteral("Welcome to Marlin"));
    QCOMPARE(b.text(QStringLiteral("confirm_warning"), {{QStringLiteral("disk"), QStringLiteral("/dev/sda")}}),
             QStringLiteral("Everything on /dev/sda will be erased. This cannot be undone."));
}

void BackendTest::brandingNothingReadableIsNeutral()
{
    const branding::Branding b = branding::resolveFrom(
        {QStringLiteral("/nonexistent/branding.json")}, {QStringLiteral("/nonexistent/os-release")}, QString());
    QCOMPARE(b.name, QStringLiteral("Linux"));
    QCOMPARE(b.id, QStringLiteral("linux"));
    QCOMPARE(b.defaultHostname, QStringLiteral("linux"));
    QVERIFY(b.defaultImage.isEmpty());
}

void BackendTest::offlineCommandHelpers()
{
    const QStringList cmd = offline::fishermanCommand();
    QVERIFY(!cmd.isEmpty());

    const QStringList raw = {QStringLiteral("echo"), QStringLiteral("test")};
    const QStringList hostWrapped = offline::hostCommand(raw);
    QVERIFY(!hostWrapped.isEmpty());

    // Flatpak: pkexec inside a host bash, so fisherman's parent is a process
    // this frontend owns (fisherman cancels when its parent dies). Not
    // `flatpak-spawn --host pkexec`, whose parent is the session helper.
    // `-`: the recipe goes on stdin (fisherman#276), never as a path.
    QCOMPARE(offline::fishermanCommand(true),
             (QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host"),
                          QStringLiteral("bash"), QStringLiteral("-c"),
                          QStringLiteral("pkexec /usr/local/bin/fisherman -; exit $?")}));
    QCOMPARE(offline::fishermanCommand(false),
             (QStringList{QStringLiteral("sudo"), QStringLiteral("/usr/local/bin/fisherman"),
                          QStringLiteral("-")}));

    if (offline::inFlatpak()) {
        QCOMPARE(hostWrapped.first(), QStringLiteral("flatpak-spawn"));
        QCOMPARE(hostWrapped.at(1), QStringLiteral("--host"));
    } else {
        QCOMPARE(hostWrapped, raw);
    }
}

// readiness::writeStamp() was split out from armStamp() specifically so the
// stamp format -- which tunaOS's installer-smoke.yml parses over SSH -- is
// reachable from a test without standing up a window (see readiness.h). It
// was never linked into this test target, so nothing checked that promise.
// armStamp() itself still needs a real QQuickWindow and stays untested here.

void BackendTest::readinessWriteStampFailsWithEmptyRuntimeDir()
{
    QVERIFY(!readiness::writeStamp(QString(), QStringLiteral("welcome"), 1000));
}

void BackendTest::readinessWriteStampWritesExpectedFields()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    QVERIFY(readiness::writeStamp(dir.path(), QStringLiteral("disk"), 1234567));

    QFile stamp(QDir(dir.path()).filePath(QStringLiteral("tuna-installer-ready")));
    QVERIFY(stamp.open(QIODevice::ReadOnly | QIODevice::Text));
    const QString body = QString::fromUtf8(stamp.readAll());

    QVERIFY(body.contains(QStringLiteral("app_id=org.tunaos.InstallerKde")));
    QVERIFY(body.contains(QStringLiteral("window=ApplicationWindow")));
    QVERIFY(body.contains(QStringLiteral("signal=frame-swapped")));
    QVERIFY(body.contains(QStringLiteral("mapped_at=1234.567")));
    QVERIFY(body.contains(QStringLiteral("page=disk")));
}

void BackendTest::readinessWriteStampBlankPageBecomesUnknown()
{
    // A bare "page=" would parse downstream as a real page named "" --
    // readiness.cpp's own comment on this fallback is what this test pins.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    QVERIFY(readiness::writeStamp(dir.path(), QString(), 0));

    QFile stamp(QDir(dir.path()).filePath(QStringLiteral("tuna-installer-ready")));
    QVERIFY(stamp.open(QIODevice::ReadOnly | QIODevice::Text));
    QVERIFY(QString::fromUtf8(stamp.readAll()).contains(QStringLiteral("page=unknown")));
}


// ---------------------------------------------------------------------------
// fisherman progress protocol
//
// fisherman writes newline-delimited JSON to stdout and nothing else. These
// tests exist because two other frontends shipped parsers for a "[n/9] "
// prefix it has never written: their bars sat at zero for every real install
// while their fixtures, written in the same invented shape, showed one
// moving. progressRejectsTheInventedStepPrefix() is that case, pinned.

static QString stepEvent(int step, int total, const char *name, int cumulative, int weight)
{
    return QStringLiteral(
        "{\"type\":\"step\",\"step\":%1,\"total_steps\":%2,\"step_name\":\"%3\","
        "\"cumulative_pct\":%4,\"weight_pct\":%5}")
        .arg(step).arg(total).arg(QString::fromLatin1(name)).arg(cumulative).arg(weight);
}

// Every test below drives the controller through loadDemoState(), its public
// harness hook, which splits the text on newlines and runs each line through
// the same appendLine() the live QProcess path uses. Feeding the real entry
// point matters here more than usual: the bug this replaces survived because
// harnesses wrote to the frontend's state instead of through its code.
static void feed(InstallerController &c, const QStringList &lines)
{
    c.loadDemoState(lines.join(QLatin1Char('\n')), 0);
}

void BackendTest::progressStepEventMovesTheBar()
{
    InstallerController c;
    QVERIFY(qFuzzyIsNull(c.installFraction()));

    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QCOMPARE(c.installStep(), 5);
    QCOMPARE(c.installTotalSteps(), 8);
    QCOMPARE(c.installFraction(), 0.01);
}

void BackendTest::progressUsesCumulativePctNotStepOverTotal()
{
    // step/total would put step 5 of 8 at 62%. The real position is 1%:
    // "Installing OS" has not started yet and carries 87% of the time.
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QVERIFY(c.installFraction() < 0.5);
    QCOMPARE(c.installFraction(), 0.01);
}

void BackendTest::progressSubstepInterpolatesInsideTheLongStep()
{
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});
    const qreal atStepStart = c.installFraction();

    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87),
             QStringLiteral(
                 "{\"type\":\"substep\",\"message\":\"Pulling image: layer 47/71\"}")});

    // Without this the bar freezes for 87% of the install.
    QVERIFY(c.installFraction() > atStepStart);
    QVERIFY(c.installFraction() < 1.0);
}

// shared/progress/fraction-cases.json is generated from the canonical
// parser and pins the bar after every event; every frontend's parser must
// reproduce it. It exists because #115's deploy-phase weighting was first
// written in Python only, leaving this bar on the old formula.
static void replayProgressCases(const QString &file, int minCases)
{
    QFile f(QStringLiteral(PROGRESS_FIXTURES_DIR "/") + file);
    if (!f.exists())
        QSKIP("shared/progress is not present (tree checked out alone)");
    QVERIFY(f.open(QIODevice::ReadOnly));
    const QJsonArray cases = QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("cases")).toArray();
    QVERIFY(cases.size() >= minCases);
    for (const QJsonValue &cv : cases) {
        const QJsonObject kase = cv.toObject();
        const QString name = kase.value(QStringLiteral("name")).toString();
        const QJsonArray events = kase.value(QStringLiteral("events")).toArray();
        const QJsonArray bars = kase.value(QStringLiteral("bar")).toArray();
        QCOMPARE(events.size(), bars.size());
        QStringList lines;
        for (int i = 0; i < events.size(); ++i) {
            lines << QString::fromUtf8(QJsonDocument(events.at(i).toObject()).toJson(QJsonDocument::Compact));
            // Fresh controller fed every event so far: loadDemoState() resets
            // and replays through appendLine(), the live entry point.
            InstallerController c;
            feed(c, lines);
            const double want = bars.at(i).toDouble();
            if (qAbs(c.installFraction() - want) > 1e-6)
                QFAIL(qPrintable(QStringLiteral("%1 event %2: bar %3 want %4")
                                     .arg(name).arg(i).arg(c.installFraction()).arg(want)));
        }
    }
}

void BackendTest::progressReproducesTheSharedFractionCases()
{
    replayProgressCases(QStringLiteral("fraction-cases.json"), 5);
}

// shared/progress/overall-pct-cases.json: fisherman's overall_pct is the
// bar; an event without it falls back to the derivation above.
void BackendTest::progressReproducesTheSharedOverallPctCases()
{
    replayProgressCases(QStringLiteral("overall-pct-cases.json"), 3);
}

void BackendTest::progressOverallPctDrivesTheBar()
{
    InstallerController c;
    const QString flatpaks = QStringLiteral(
        "{\"type\":\"step\",\"step\":6,\"total_steps\":8,\"step_name\":\"Copying system Flatpaks\","
        "\"step_id\":\"flatpaks\",\"cumulative_pct\":88,\"weight_pct\":11,\"overall_pct\":88}");
    // The derivation holds the bar through the Flatpak copy; overall_pct
    // moves it.
    feed(c, {flatpaks, QStringLiteral(
                 "{\"type\":\"substep\",\"message\":\"Copying Flatpak data: 50%\",\"overall_pct\":93.5}")});
    QCOMPARE(c.installFraction(), 0.935);

    // Never backwards, even if an event said so.
    feed(c, {flatpaks,
             QStringLiteral("{\"type\":\"substep\",\"message\":\"a\",\"overall_pct\":93.5}"),
             QStringLiteral("{\"type\":\"substep\",\"message\":\"b\",\"overall_pct\":90}")});
    QCOMPARE(c.installFraction(), 0.935);

    // Without overall_pct the bar is derived, as before.
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87),
             QStringLiteral("{\"type\":\"substep\",\"message\":\"Pulling image: layer 2/4\"}")});
    QVERIFY(qAbs(c.installFraction() - (1 + 0.5 * 0.6 * 87) / 100.0) < 1e-9);
}

void BackendTest::progressStepIdReadsTheCopyLayer()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"name": "Marlin", "copy": {"step_flatpaks": "Adding apps to {name}"}})");
    f.close();
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController c;
    qunsetenv("BOOTC_INSTALLER_BRANDING");

    const auto step = [](const char *name, const char *id) {
        return QStringLiteral(
                   "{\"type\":\"step\",\"step\":3,\"total_steps\":8,\"step_name\":\"%1\","
                   "\"step_id\":\"%2\",\"cumulative_pct\":1,\"weight_pct\":0,\"overall_pct\":1}")
            .arg(QString::fromLatin1(name), QString::fromLatin1(id));
    };
    // A product's branding.json renames the step.
    feed(c, {step("Copying system Flatpaks", "flatpaks")});
    QCOMPARE(c.installStepName(), QStringLiteral("Adding apps to Marlin"));
    // The neutral default for an id the product left alone.
    feed(c, {step("Installing OS", "install_os")});
    QCOMPARE(c.installStepName(), QStringLiteral("Installing Marlin…"));
    // An id the copy does not know shows fisherman's step name.
    feed(c, {step("Polishing the hull", "polish_hull")});
    QCOMPARE(c.installStepName(), QStringLiteral("Polishing the hull"));
}

void BackendTest::progressCompleteFillsTheBar()
{
    InstallerController c;
    // cumulative_pct only ever reaches 99; `complete` is what fills the bar.
    const QString last = stepEvent(8, 8, "Finalizing installation", 99, 1);
    feed(c, {last});
    QCOMPARE(c.installFraction(), 0.99);

    feed(c, {last, QStringLiteral(
                 "{\"type\":\"complete\",\"message\":\"Installation complete\"}")});
    QCOMPARE(c.installFraction(), 1.0);
}

void BackendTest::progressIgnoresNonProtocolLines()
{
    // fisherman's stderr is interleaved into the same stream.
    InstallerController c;
    feed(c, {QStringLiteral("fisherman: warning: something"),
             QStringLiteral("{ not json")});

    QVERIFY(qFuzzyIsNull(c.installFraction()));
    QCOMPARE(c.installStep(), 0);
    // A line that is not an event is shown as it stands.
    QVERIFY(c.log().contains(QStringLiteral("fisherman: warning: something")));
}

void BackendTest::progressRejectsTheInventedStepPrefix()
{
    // The exact bug this parse replaces. "[9/9] Finalizing" is not something
    // fisherman writes, so it must move nothing -- a parser that accepts it
    // is reading its own fixtures.
    InstallerController c;
    feed(c, {QStringLiteral("[1/9] Partitioning /dev/nvme0n1"),
             QStringLiteral("[9/9] Finalizing")});

    QVERIFY(qFuzzyIsNull(c.installFraction()));
    QCOMPARE(c.installStep(), 0);
}

void BackendTest::progressUnknownStepNameFallsBackToTheRawName()
{
    // A step added to fisherman later should show its real name, not nothing.
    InstallerController c;
    feed(c, {stepEvent(2, 8, "Polishing the hull", 10, 5)});

    QCOMPARE(c.installStepName(), QStringLiteral("Polishing the hull"));
}

void BackendTest::progressRendersEventsForTheLogPane()
{
    // The protocol is machine-readable and the pane is not: a log pane fed
    // raw stdout renders as a wall of JSON.
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QVERIFY(c.log().contains(QStringLiteral("[5/8] Installing OS")));
    QVERIFY(!c.log().contains(QStringLiteral("cumulative_pct")));
}

static QString recoveryEvent(const QString &key)
{
    return QStringLiteral(
        R"({"type":"recovery_key","key":"%1",)"
        R"("timestamp":"2026-01-01T00:00:00Z","elapsed_ms":1000})").arg(key);
}

void BackendTest::recoveryKeyIsKeptNotJustPrinted()
{
    InstallerController c;
    QVERIFY(c.recoveryKey().isEmpty());

    feed(c, {recoveryEvent(QStringLiteral("abcd-efgh"))});

    QCOMPARE(c.recoveryKey(), QStringLiteral("abcd-efgh"));
    // Still in the log, which is what gets pasted into a bug report.
    QVERIFY(c.log().contains(QStringLiteral("abcd-efgh")));
}

void BackendTest::recoveryKeyHoldsRestartUntilAcknowledged()
{
    InstallerController c;
    // exitCode 0: loadDemoState() marks the install finished, so succeeded()
    // is true and the gate is live.
    feed(c, {recoveryEvent(QStringLiteral("abcd-efgh"))});

    QVERIFY2(c.recoveryKeyPending(), "an unacknowledged key must hold restart");
    c.setRecoveryAck(true);
    QVERIFY2(!c.recoveryKeyPending(), "ticking the box must release restart");
}

void BackendTest::recoveryKeyAbsentMeansNoGate()
{
    // No key means no panel and no gate: a non-TPM install must not be asked
    // to tick a box about a key it was never given.
    InstallerController c;
    c.loadDemoState(QStringLiteral("some log line"), 0);
    QVERIFY(c.succeeded());
    QVERIFY(!c.recoveryKeyPending());

    // A failed install enrolled nothing, so there is nothing to write down.
    InstallerController failed;
    failed.loadDemoState(recoveryEvent(QStringLiteral("abcd-efgh")), 1);
    QCOMPARE(failed.recoveryKey(), QStringLiteral("abcd-efgh"));
    QVERIFY(!failed.succeeded());
    QVERIFY(!failed.recoveryKeyPending());
}

void BackendTest::probeFixtures_data()
{
    QTest::addColumn<QString>("name");
    QTest::newRow("laptop") << QStringLiteral("laptop");
    QTest::newRow("container") << QStringLiteral("container");
    QTest::newRow("vm") << QStringLiteral("vm");
    QTest::newRow("pure-live-oci") << QStringLiteral("pure-live-oci");
}

void BackendTest::probeFixtures()
{
    QFETCH(QString, name);
    const QDir dir(QStringLiteral(PROBE_FIXTURES_DIR));
    QFile input(dir.filePath(name + QStringLiteral(".json")));
    QFile expectedFile(dir.filePath(name + QStringLiteral(".expected.json")));
    if (!input.open(QIODevice::ReadOnly) || !expectedFile.open(QIODevice::ReadOnly))
        QSKIP("shared/probe/fixtures is absent; this tree is checked out alone");
    const QJsonObject expected = QJsonDocument::fromJson(expectedFile.readAll()).object();

    const probe::Result result = probe::parse(input.readAll());
    QVERIFY2(result.ok, qPrintable(result.error));

    // What the disk step's rows carry, through the model the QML reads.
    DiskModel model;
    model.setResult(result);
    const QJsonArray want = expected.value(QStringLiteral("disks")).toArray();
    QCOMPARE(model.rowCount(), want.size());
    const QHash<int, QByteArray> roles = model.roleNames();
    auto role = [&](const QByteArray &n) { return roles.key(n); };
    for (int i = 0; i < want.size(); ++i) {
        const QJsonObject w = want.at(i).toObject();
        const QModelIndex idx = model.index(i);
        QCOMPARE(model.data(idx, role("device")).toString(), w.value(QStringLiteral("path")).toString());
        QCOMPARE(model.data(idx, role("title")).toString(), w.value(QStringLiteral("title")).toString());
        QCOMPARE(model.data(idx, role("model")).toString(), w.value(QStringLiteral("model")).toString());
        QCOMPARE(model.data(idx, role("size")).toString(), w.value(QStringLiteral("size_label")).toString());
        QCOMPARE(model.data(idx, role("transport")).toString(),
                 w.value(QStringLiteral("transport_label")).toString());
        QCOMPARE(model.data(idx, role("removable")).toBool(), w.value(QStringLiteral("removable")).toBool());
    }
    QCOMPARE(result.tpmUsable, expected.value(QStringLiteral("tpm_usable")).toBool());
    QStringList unmet;
    for (const QJsonValue &v : expected.value(QStringLiteral("unmet")).toArray())
        unmet << v.toString();
    QCOMPARE(result.unmet, unmet);
}

void BackendTest::probeFakeEnvReachesTheController()
{
    const QString vm = QDir(QStringLiteral(PROBE_FIXTURES_DIR)).filePath(QStringLiteral("vm.json"));
    if (!QFileInfo::exists(vm))
        QSKIP("shared/probe/fixtures is absent; this tree is checked out alone");
    qputenv(probe::FAKE_ENV, vm.toLocal8Bit());
    InstallerController c;
    qunsetenv(probe::FAKE_ENV);
    QVERIFY(!c.hasTpm());
    QCOMPARE(c.unmetRequirements(), (QStringList{QStringLiteral("ram"), QStringLiteral("cpu"),
                                                 QStringLiteral("uefi")}));
    const QStringList lines = c.requirementsWarning().split(QLatin1Char('\n'));
    QCOMPARE(lines, (QStringList{c.text(QStringLiteral("requirements_title")),
                                 c.text(QStringLiteral("requirements_ram")),
                                 c.text(QStringLiteral("requirements_cpu")),
                                 c.text(QStringLiteral("requirements_uefi"))}));

    const QString laptop = QDir(QStringLiteral(PROBE_FIXTURES_DIR)).filePath(QStringLiteral("laptop.json"));
    qputenv(probe::FAKE_ENV, laptop.toLocal8Bit());
    InstallerController met;
    qunsetenv(probe::FAKE_ENV);
    QVERIFY(met.hasTpm());
    QVERIFY(met.requirementsWarning().isEmpty());
}

void BackendTest::probeFailureOffersNothingAndSaysWhy()
{
    const probe::Result old = probe::parse(QByteArrayLiteral("{\"protocol_version\": 2}"));
    QVERIFY(!old.ok);
    QVERIFY(old.error.contains(QStringLiteral("protocol_version")));
    QVERIFY(!probe::parse(QByteArrayLiteral("not json")).ok);

    qputenv(probe::FAKE_ENV, QByteArrayLiteral("/nonexistent/probe.json"));
    DiskModel model;
    model.refresh();
    InstallerController c;
    qunsetenv(probe::FAKE_ENV);
    QCOMPARE(model.rowCount(), 0);
    QVERIFY(model.error().contains(QStringLiteral("/nonexistent/probe.json")));
    QVERIFY(!c.hasTpm());
    QVERIFY(c.requirementsWarning().isEmpty());
}

void BackendTest::probeCommandIsUnprivileged()
{
    const QStringList host{QStringLiteral("/usr/local/bin/fisherman"), QStringLiteral("probe"),
                           QStringLiteral("--json")};
    QCOMPARE(probe::command(false), host);
    QCOMPARE(probe::command(true),
             QStringList({QStringLiteral("flatpak-spawn"), QStringLiteral("--host")}) + host);
}

void BackendTest::streamsKeepSeparatePartialLines()
{
    InstallerController c;
    const QString event = stepEvent(5, 8, "Installing OS", 1, 87);
    const QByteArray bytes = event.toUtf8();
    const qsizetype half = bytes.size() / 2;

    // What a pipe really delivers: half an event on stdout, then a complete
    // stderr line, then the rest of the event.
    c.consumeStdout(bytes.left(half));
    c.consumeStderr("pkexec: some warning\n");
    c.consumeStdout(bytes.mid(half) + "\n");
    c.consumeStderr("trailing stderr without a newline");
    c.flushStreams();

    // The event parsed: under the shared buffer it never did.
    QCOMPARE(c.installStep(), 5);
    QCOMPARE(c.installTotalSteps(), 8);
    QCOMPARE(c.installFraction(), 0.01);

    const QString log = c.log();
    // stderr still reaches the pane, intact and on its own line.
    QVERIFY(log.contains(QStringLiteral("[stderr] pkexec: some warning\n")));
    QVERIFY(log.contains(QStringLiteral("[stderr] trailing stderr without a newline")));
    QVERIFY(log.contains(QStringLiteral("[5/8] Installing OS")));
    // No fragment of the event leaked into the pane as raw text.
    QVERIFY(!log.contains(QStringLiteral("\"type\"")));
}

void BackendTest::flatpakWrapperPassesStdinOutputAndStatusThrough()
{
#if !QT_CONFIG(process)
    QSKIP("QProcess is not available on this platform (wasm)");
#else
    // Run the wrapper's bash for real (everything after flatpak-spawn
    // --host) with pkexec stubbed on PATH: what is written to the wrapper's
    // stdin is what fisherman reads, and `-` is its argument.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString stub = dir.filePath(QStringLiteral("pkexec"));
    const QString seen = dir.filePath(QStringLiteral("stdin"));
    QFile f(stub);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > \"" + seen.toUtf8()
            + "\"\necho to-stderr >&2\nexit 7\n");
    f.close();
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);

    QStringList cmd = offline::fishermanCommand(true);
    cmd.removeFirst(); // flatpak-spawn
    cmd.removeFirst(); // --host

    QProcess p;
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert(QStringLiteral("PATH"), dir.path() + QLatin1Char(':') + env.value(QStringLiteral("PATH")));
    p.setProcessEnvironment(env);
    p.setWorkingDirectory(dir.path());
    p.start(cmd.takeFirst(), cmd);
    const QByteArray recipe = R"({"encryption":{"type":"luks-passphrase","passphrase":"s3cret"}})";
    p.write(recipe);
    p.closeWriteChannel();
    QVERIFY(p.waitForFinished(10000));
    QCOMPARE(p.exitCode(), 7);
    QCOMPARE(QString::fromUtf8(p.readAllStandardOutput()), QStringLiteral("/usr/local/bin/fisherman|-\n"));
    QCOMPARE(p.readAllStandardError(), QByteArray("to-stderr\n"));
    QFile got(seen);
    QVERIFY(got.open(QIODevice::ReadOnly));
    QCOMPARE(got.readAll(), recipe);
#endif
}

void BackendTest::validateAnswersBecomeCopyLines()
{
#ifndef VALIDATE_GOLDENS_DIR
    QSKIP("no goldens");
#else
    const QString dir = QStringLiteral(VALIDATE_GOLDENS_DIR);
    QFile golden(dir + QStringLiteral("/partial-hostname.golden"));
    if (!golden.open(QIODevice::ReadOnly))
        QSKIP("the fisherman submodule is not checked out");
    const QByteArray answer = golden.readAll();
    const validate::Result r = validate::parse(answer);
    QVERIFY(r.ok);
    QCOMPARE(r.problems.size(), 1);
    QCOMPARE(r.problems.first().code, QStringLiteral("hostname_label_hyphen"));

    InstallerController c;
    QVERIFY(c.hostnameProblem().isEmpty());
    c.applyValidateAnswer(answer);
    QCOMPARE(c.hostnameProblem(), c.text(QStringLiteral("validate_hostname_label_hyphen")));
    QVERIFY(!c.hostnameProblem().isEmpty());
    QVERIFY(c.encryptionProblem().isEmpty());

    // An unknown code shows fisherman's message; no answer clears it.
    c.applyValidateAnswer(R"({"protocol_version":1,"valid":false,"errors":[{"field":"encryption.passphrase","code":"brand_new","message":"say why"}]})");
    QCOMPARE(c.encryptionProblem(), QStringLiteral("say why"));
    c.applyValidateAnswer("not json");
    QVERIFY(c.encryptionProblem().isEmpty());
    QVERIFY(!validate::parse(R"({"protocol_version":2,"errors":[]})").ok);
#endif
}

void BackendTest::validateSendsAPartialRecipeOnStdin()
{
    QCOMPARE(validate::command(false),
             (QStringList{QStringLiteral("/usr/local/bin/fisherman"), QStringLiteral("validate"),
                          QStringLiteral("--json"), QStringLiteral("--partial"), QStringLiteral("-")}));
    QCOMPARE(validate::command(true).mid(0, 2),
             (QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")}));
    InstallerController c;
    c.setHostname(QStringLiteral("box"));
    c.setEncryptionType(QStringLiteral("tpm2-luks"));
    QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("hostname")).toString(), QStringLiteral("box"));
    QVERIFY(!partial.value(QStringLiteral("encryption")).toObject().contains(QStringLiteral("passphrase")));
    c.setEncryptionType(QStringLiteral("luks-passphrase"));
    c.setPassphrase(QStringLiteral("s3cret"));
    partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("encryption")).toObject().value(QStringLiteral("passphrase")).toString(),
             QStringLiteral("s3cret"));
}

void BackendTest::liveMediaComesFromTheProbe()
{
    const QString dir = QStringLiteral(PROBE_FIXTURES_DIR);
    for (const QString &name : {QStringLiteral("laptop"), QStringLiteral("container"), QStringLiteral("vm"), QStringLiteral("pure-live-oci")}) {
        QFile in(dir + QLatin1Char('/') + name + QStringLiteral(".json"));
        QFile want(dir + QLatin1Char('/') + name + QStringLiteral(".expected.json"));
        if (!in.open(QIODevice::ReadOnly) || !want.open(QIODevice::ReadOnly))
            QSKIP("shared/probe/fixtures is absent");
        const probe::Result r = probe::parse(in.readAll());
        const QJsonObject expected = QJsonDocument::fromJson(want.readAll()).object();
        QCOMPARE(r.liveImage, expected.value(QStringLiteral("live_image")).toString());
        QStringList images;
        for (const QJsonValue &v : expected.value(QStringLiteral("offline_images")).toArray())
            images << v.toString();
        QCOMPARE(r.offlineImages, images);
        QCOMPARE(r.isLive, name != QStringLiteral("container"));
    }
    // The controller takes it in: the laptop booted from live media.
    qputenv("BOOTC_INSTALLER_FAKE_PROBE", (dir + QStringLiteral("/laptop.json")).toUtf8());
    InstallerController live;
    qputenv("BOOTC_INSTALLER_FAKE_PROBE", (dir + QStringLiteral("/container.json")).toUtf8());
    InstallerController installed;
    qunsetenv("BOOTC_INSTALLER_FAKE_PROBE");
    QVERIFY(live.isLive());
    QCOMPARE(live.liveImage(), QStringLiteral("ghcr.io/example/os:stable"));
    QVERIFY(!installed.isLive());
}

void BackendTest::wrapperLeadsItsOwnProcessGroup()
{
#if !QT_CONFIG(process) || !defined(Q_OS_UNIX)
    QSKIP("needs QProcess and POSIX process groups");
#else
    QProcess p;
    offline::startInOwnProcessGroup(p);
    p.start(QStringLiteral("sleep"), {QStringLiteral("30")});
    QVERIFY(p.waitForStarted(5000));
    const pid_t pid = static_cast<pid_t>(p.processId());
    QCOMPARE(::getpgid(pid), pid);
    QVERIFY(::getpgid(pid) != ::getpgrp());
    // Signalling that group reaches the wrapper, not this process.
    QCOMPARE(::killpg(pid, SIGTERM), 0);
    QVERIFY(p.waitForFinished(5000));
    QCOMPARE(p.exitStatus(), QProcess::CrashExit);
#endif
}

QTEST_APPLESS_MAIN(BackendTest)

#include "test_backend.moc"

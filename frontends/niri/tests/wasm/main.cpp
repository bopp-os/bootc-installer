// QML host for the Niri wizard in a browser (Qt for WebAssembly).
//
// This is tests/gui/capture-screens.py without PyQt6, which cannot come to
// the browser. It loads the same unmodified ui/installer.qml with the same
// Quickshell stubs, steps the same pages in the same way, and feeds the
// install screen the same fisherman transcript through appendLog().
//
// The page asks for a wizard page through niriShow(name) and reads back
// niriState(), a JSON string. That replaces the two files shared/browser/
// present.py negotiates through, because there is no filesystem here.
// `current` changes only after Qt has drawn a frame of the requested page,
// so the browser never screenshots a page mid-transition.
//
// The state also carries the text of the visible page and the checks the
// capture harness makes on the install and recovery screens. Unlike GTK
// Broadway, which ships text as pixels, this process can read its own scene.

#include <QFile>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QQmlApplicationEngine>
#include <QQuickItem>
#include <QQuickWindow>
#include <QTimer>

#include <string>

#ifdef Q_OS_WASM
#include <emscripten/bind.h>
#endif

namespace {

struct Page {
    const char *name;
    int index;
};

// The same list, in the same order, as PAGES in capture-screens.py.
const Page kPages[] = {
    {"01-welcome", 0}, {"02-disk", 1},     {"03-encryption", 2},
    {"04-account", 3}, {"05-confirm", 4},  {"06-progress", 5},
    {"07-done", 6},    {"08-recovery", 6},
};

// Page positions by role, as PROGRESS_PAGE / DONE_PAGE in capture-screens.py.
constexpr int kProgressPage = 5;
constexpr int kDonePage = 6;

// The account fields, filled as ACCOUNT in capture-screens.py, so the
// account and confirm frames show a user.
void fillAccount(QObject *root)
{
    root->setProperty("username", QStringLiteral("alex"));
    root->setProperty("fullname", QStringLiteral("Alex Example"));
    root->setProperty("userPassword", QStringLiteral("capture"));
    root->setProperty("userPasswordConfirm", QStringLiteral("capture"));
}

// The event fisherman emits after TPM enrolment, as in capture-screens.py.
// It goes in through appendLog(), so the frame exercises the parse.
const char kRecoveryEvent[] =
    R"({"type": "recovery_key", "key": "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf",)"
    R"( "timestamp": "2026-01-01T00:00:00Z", "elapsed_ms": 1000})";

QPointer<QQuickWindow> g_window;
QString g_current;
QString g_error;
QJsonObject g_checks;
int g_generation = 0;

// Transcript lines up to the middle of the image pull, so the bar sits part
// of the way along. Same cut as fixture_lines() in capture-screens.py.
QStringList fixtureLines()
{
    QFile f(QStringLiteral(":/fixtures/dry-run-transcript.ndjson"));
    if (!f.open(QIODevice::ReadOnly))
        return {};
    QStringList out;
    for (const QByteArray &raw : f.readAll().split('\n')) {
        const QString line = QString::fromUtf8(raw).trimmed();
        if (line.isEmpty())
            continue;
        out << line;
        if (line.contains(QLatin1String("47/71")))
            break;
    }
    return out;
}

// Down the VISUAL tree, for the reason find_item() in capture-screens.py
// gives: findChild() does not reach items parented visually.
QQuickItem *findItem(QQuickItem *root, const QString &name)
{
    if (!root)
        return nullptr;
    if (root->objectName() == name)
        return root;
    for (QQuickItem *child : root->childItems())
        if (QQuickItem *hit = findItem(child, name))
            return hit;
    return nullptr;
}

// Every string on the visible page. isVisible() is effective visibility, so
// the pages the StackLayout hides drop out, as in page_text().
void pageText(QQuickItem *item, QStringList &acc)
{
    for (QQuickItem *child : item->childItems()) {
        if (!child->isVisible())
            continue;
        const QVariant text = child->property("text");
        if (text.typeId() == QMetaType::QString && !text.toString().trimmed().isEmpty())
            acc << text.toString();
        pageText(child, acc);
    }
}

void appendLog(QObject *root, const QString &line)
{
    QMetaObject::invokeMethod(root, "appendLog", Q_ARG(QVariant, QVariant(line)));
}

// The geometry half of assert_progress_bar_drawn(). The pixel half is the
// browser's job, because the pixels are in the browser's screenshot.
QJsonObject progressCheck()
{
    QQuickItem *fill = findItem(g_window->contentItem(), QStringLiteral("installProgressFill"));
    if (!fill)
        return {{"ok", false}, {"why", "no item named installProgressFill in the visual tree"}};
    QQuickItem *track = fill->parentItem();
    const double share = track && track->width() > 0 ? fill->width() / track->width() : 0.0;
    const bool ok = fill->width() > 0 && fill->height() > 0 && fill->isVisible();
    return {{"ok", ok},
            {"share", share},
            {"why", ok ? "" : "the progress bar's fill has no drawable geometry"}};
}

QJsonObject recoveryCheck(QObject *root, const QString &text)
{
    const QString key = root->property("recoveryKey").toString();
    if (key.isEmpty())
        return {{"ok", false}, {"why", "the recovery_key event did not parse"}};
    if (!text.contains(key))
        return {{"ok", false}, {"why", "the recovery key is not in the rendered text"}};
    QQuickItem *restart = findItem(g_window->contentItem(), QStringLiteral("doneRestartButton"));
    if (!restart)
        return {{"ok", false}, {"why", "no doneRestartButton in the visual tree"}};
    if (restart->property("enabled").toBool())
        return {{"ok", false}, {"why", "Restart is live before the recovery key was acknowledged"}};
    return {{"ok", true}, {"why", ""}};
}

// Mark `name` as current once a frame of it has been drawn. The settle delay
// covers the animations, as settle() does in capture-screens.py. The fill's
// width animation is the longest, hence the longer wait on the install page.
void confirmAfterFrame(const QString &name, int settleMs)
{
    const int generation = ++g_generation;
    QTimer::singleShot(settleMs, g_window, [name, generation] {
        if (generation != g_generation || !g_window)
            return;
        auto conn = std::make_shared<QMetaObject::Connection>();
        *conn = QObject::connect(g_window, &QQuickWindow::afterFrameEnd, g_window,
                                 [name, generation, conn] {
            QObject::disconnect(*conn);
            if (generation == g_generation)
                g_current = name;
        });
        g_window->update();
    });
}

} // namespace

std::string niriShow(const std::string &wanted)
{
    if (!g_window)
        return "not ready";
    const QString name = QString::fromStdString(wanted);
    const Page *page = nullptr;
    for (const Page &p : kPages)
        if (name == QLatin1String(p.name))
            page = &p;
    if (!page)
        return "unknown page";

    QObject *root = g_window;
    g_current.clear();
    fillAccount(root);
    root->setProperty("currentPage", page->index);
    int settleMs = 300;
    if (page->index == kProgressPage) {
        // Through appendLog(), the function a real install calls.
        for (const QString &line : fixtureLines())
            appendLog(root, line);
        settleMs = 1000;
    }
    if (page->index == kDonePage)
        root->setProperty("installSuccess", true);
    if (name == QLatin1String("08-recovery"))
        appendLog(root, QString::fromLatin1(kRecoveryEvent));
    confirmAfterFrame(name, settleMs);
    return "ok";
}

std::string niriState()
{
    QJsonArray pages;
    for (const Page &p : kPages)
        pages.append(QLatin1String(p.name));
    QJsonObject state{{"pages", pages}, {"error", g_error}};
    state.insert("current", g_current.isEmpty() ? QJsonValue() : QJsonValue(g_current));
    if (g_window && !g_current.isEmpty()) {
        QStringList acc;
        pageText(g_window->contentItem(), acc);
        const QString text = acc.join(QLatin1Char(' '));
        state.insert("text", text);
        QJsonObject checks;
        if (g_current == QLatin1String("06-progress"))
            checks.insert("progress-bar", progressCheck());
        if (g_current == QLatin1String("08-recovery"))
            checks.insert("recovery-key", recoveryCheck(g_window, text));
        state.insert("checks", checks);
    }
    return QJsonDocument(state).toJson(QJsonDocument::Compact).toStdString();
}

#ifdef Q_OS_WASM
EMSCRIPTEN_BINDINGS(niri)
{
    emscripten::function("niriShow", &niriShow);
    emscripten::function("niriState", &niriState);
}
#endif

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);

    QQmlApplicationEngine engine;
    engine.addImportPath(QStringLiteral("qrc:/niri/tests/qml-stubs"));
    engine.load(QUrl(QStringLiteral("qrc:/niri/ui/installer.qml")));
    if (engine.rootObjects().isEmpty()) {
        g_error = QStringLiteral("installer.qml did not load; see the QML errors in the console");
        qCritical("FAIL: %s", qPrintable(g_error));
        return app.exec();   // stay up so niriState() can report the error
    }
    g_window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    if (!g_window)
        g_error = QStringLiteral("the root object is not a window");
    return app.exec();
}

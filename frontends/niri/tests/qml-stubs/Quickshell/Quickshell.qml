pragma Singleton
import QtQuick

// Stub of the Quickshell singleton, for running ui/installer.qml under a plain
// Qt Quick runtime. A missing theme icon keeps the neutral glyph.
QtObject {
    function iconPath(icon, check) { return "" }
    function env(name) {
        return ""   // fall through to the QML's own default
    }
}

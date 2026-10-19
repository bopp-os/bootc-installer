// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    // A plain Item, not a ScrollView. These two steps are short enough never to
    // scroll, and inside a ScrollView the content item collapses to its
    // implicit height — which is why the first CI render came out hard against
    // the top of the page with the whole lower half empty. The Control sizes
    // this to the full step rect, so centring on it actually centres.
    contentItem: Item {

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                objectName: "doneLogo"
                source: InstallerController.succeeded
                    ? (InstallerController.logoSource || "checkmark")
                    : "dialog-error"
                fallback: InstallerController.succeeded ? "checkmark" : "dialog-error"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.gridUnit
            }

            Kirigami.Heading {
                text: InstallerController.succeeded
                    ? InstallerController.text("done_title")
                    : InstallerController.text("done_failed_title")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.succeeded
                    ? InstallerController.text("done_subtitle")
                    : "The installation did not finish. The log above has the details — exit code "
                      + InstallerController.exitCode + "."
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // store_label -> store_url, on every frontend when the branding
            // sets a store (docs/PARITY.md).
            Label {
                text: "<a href=\"" + InstallerController.storeUrl + "\">" + InstallerController.text("store_label") + "</a>"
                visible: InstallerController.succeeded && InstallerController.storeUrl.length > 0
                textFormat: Text.RichText
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true

                onLinkActivated: link => Qt.openUrlExternally(link)
            }

            // Recovery key (#129). fisherman emits it once, after TPM
            // enrolment, and for a tpm2-luks install it is the only way back
            // into the disk if the TPM state changes. It used to go to the
            // log pane and nowhere else: the log scrolls, nothing pauses, and
            // a user could reach this page and restart having never seen it.
            //
            // A panel rather than a dialog, as on the other frontends: a
            // dialog is dismissed and then the key is gone, while this stays
            // on screen for as long as it takes to write down.
            ColumnLayout {
                objectName: "recoveryPanel"
                visible: InstallerController.succeeded
                    && InstallerController.recoveryKey.length > 0
                spacing: Kirigami.Units.smallSpacing

                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    text: InstallerController.text("recovery_key_title")
                    level: 3
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    text: InstallerController.text("recovery_key_body")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    objectName: "recoveryKeyLabel"
                    text: InstallerController.recoveryKey
                    font.family: "monospace"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WrapAnywhere
                    Layout.fillWidth: true
                }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: Kirigami.Units.smallSpacing

                    Button {
                        text: InstallerController.text("recovery_key_copy")
                        icon.name: "edit-copy-symbolic"
                        onClicked: recoveryClip.selectAll(),
                                   recoveryClip.copy(),
                                   recoveryClip.deselect()
                    }
                    CheckBox {
                        objectName: "recoveryAckCheck"
                        text: InstallerController.text("recovery_key_ack")
                        checked: InstallerController.recoveryAck
                        onToggled: InstallerController.recoveryAck = checked
                    }
                }
                // QtQuick has no clipboard object; a hidden TextEdit is the
                // standard way to reach one.
                TextEdit {
                    id: recoveryClip
                    visible: false
                    text: InstallerController.recoveryKey
                }
            }

            // Restart is the primary action after a successful install, the
            // same as on the other frontends; Close stays in the footer.
            Button {
                objectName: "doneRestartButton"
                text: InstallerController.text("done_restart")
                icon.name: "system-reboot-symbolic"
                visible: InstallerController.succeeded
                highlighted: true
                // Held until the key is acknowledged.
                enabled: !InstallerController.recoveryKeyPending

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing

                onClicked: InstallerController.reboot()
            }

            // The log shown on the previous step dies with this window; this
            // is where the copy on disk is. Hidden when the file could not be
            // opened, rather than pointing at a path that does not exist.
            Label {
                text: "Log saved to " + InstallerController.logPath
                visible: InstallerController.logPath.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font: Kirigami.Theme.smallFont
                opacity: 0.8

                Layout.fillWidth: true
            }

        }
    }
}

// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    // A recovery key takes the room the hero icon would have; the icon
    // shrinks so the key, its copy button and the acknowledgement fit the
    // page without scrolling.
    readonly property bool showRecovery: InstallerController.succeeded
        && InstallerController.recoveryKey.length > 0

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

            // Success shows the product's artwork from the branding resolver
            // (assets.complete_image, then the logo) with a themed check as
            // the fallback; a failure keeps the error icon.
            Kirigami.Icon {
                objectName: "doneLogo"
                source: InstallerController.succeeded
                    ? (InstallerController.completeImageSource
                       || InstallerController.logoSource
                       || "checkmark")
                    : "dialog-error"
                fallback: InstallerController.succeeded ? "checkmark" : "dialog-error"
                implicitWidth: root.showRecovery ? Kirigami.Units.iconSizes.huge
                                                 : Kirigami.Units.iconSizes.enormous
                implicitHeight: implicitWidth

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // "<product> is installed": the one heading on this page. The
            // header shows only the step indicator here (Wizard.heroStep).
            Kirigami.Heading {
                text: InstallerController.succeeded
                    ? InstallerController.text("done_title")
                    : InstallerController.text("done_failed_title")
                level: 1
                type: Kirigami.Heading.Type.Primary
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
            // on screen for as long as it takes to write down. A FormCard, the
            // way Plasma System Settings groups a value with its actions: the
            // explanation, the key in a monospace, selectable field beside its
            // copy button, then the acknowledgement that releases Restart.
            ColumnLayout {
                objectName: "recoveryPanel"
                visible: root.showRecovery
                spacing: 0

                Layout.fillWidth: true

                FormCard.FormHeader {
                    title: InstallerController.text("recovery_key_title")
                    maximumWidth: root.cardWidth
                }

                FormCard.FormCard {
                    maximumWidth: root.cardWidth

                    FormCard.FormTextDelegate {
                        text: InstallerController.text("recovery_key_body")
                        textItem.wrapMode: Text.Wrap
                    }

                    FormCard.FormDelegateSeparator {}

                    FormCard.AbstractFormDelegate {
                        background: null
                        focusPolicy: Qt.NoFocus

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing

                            TextField {
                                objectName: "recoveryKeyLabel"
                                text: InstallerController.recoveryKey
                                readOnly: true
                                selectByMouse: true
                                font.family: Kirigami.Theme.fixedWidthFont.family
                                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                                horizontalAlignment: Text.AlignHCenter
                                Accessible.name: InstallerController.text("recovery_key_title")

                                Layout.fillWidth: true
                            }

                            // Icon-only so the field keeps the width the
                            // whole key needs; the copy key is the tooltip
                            // and the accessible name.
                            Button {
                                objectName: "recoveryCopyButton"
                                text: InstallerController.text("recovery_key_copy")
                                icon.name: "edit-copy-symbolic"
                                display: AbstractButton.IconOnly
                                ToolTip.text: text
                                ToolTip.visible: hovered
                                ToolTip.delay: Kirigami.Units.toolTipDelay
                                onClicked: recoveryClip.selectAll(),
                                           recoveryClip.copy(),
                                           recoveryClip.deselect()
                            }
                        }
                    }

                    FormCard.FormDelegateSeparator {}

                    FormCard.FormCheckDelegate {
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

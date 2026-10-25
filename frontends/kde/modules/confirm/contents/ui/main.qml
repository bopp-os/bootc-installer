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

    // fisherman's hostname rule (`validate --json --partial`) holds Install
    // while it reports a problem, and so does a missing or rejected account:
    // without one the installed system has nobody to sign in as.
    nextEnabled: InstallerController.disk.length > 0 && InstallerController.hostnameProblem === ""
        && InstallerController.username.length > 0 && InstallerController.usernameProblem === ""

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: true
                position: Kirigami.InlineMessage.Header
                // "begins" is deliberately avoided: the screen contract
                // matches a welcome screen on the keyword "begin", so that word
                // here credited a welcome screen off the confirm page in run
                // 31143012730 — and would keep crediting one if the welcome
                // step were ever removed. Same sentence, one word different.
                text: InstallerController.text("confirm_warning", InstallerController.disk)

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // fisherman's problem with the hostname, in the copy's words.
            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Error
                visible: text !== ""
                text: InstallerController.hostnameProblem

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // The product's own lines (a quote, a tagline) from the branding
            // copy; empty in the neutral defaults, so hidden.
            Label {
                text: InstallerController.text("confirm_subtitle")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.italic: true

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormTextDelegate {
                    text: "Target disk"
                    description: InstallerController.disk
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Filesystem"
                    description: InstallerController.filesystem
                        + (InstallerController.btrfsSubvolumes ? " (with subvolumes)" : "")
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Encryption"
                    description: InstallerController.encryptionLabel(InstallerController.encryptionType)
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Hostname"
                    description: InstallerController.hostname
                }

                FormCard.FormDelegateSeparator {}

                // The account step's username (and full name, when given);
                // never the password.
                FormCard.FormTextDelegate {
                    objectName: "confirmUsername"
                    text: "Username"
                    description: InstallerController.fullname.length > 0
                        ? InstallerController.username + " (" + InstallerController.fullname + ")"
                        : InstallerController.username
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Image"
                    // Empty on live media: bootc installs the running container,
                    // so the recipe legitimately omits `image`.
                    description: InstallerController.image.length > 0
                        ? InstallerController.image
                        : "the running live system"
                }
            }
            Label {
                text: InstallerController.text("confirm_body")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }
        }
    }
}

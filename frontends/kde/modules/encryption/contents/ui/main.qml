// Disk encryption choice.
//
// The recipe has carried encryption.type and encryption.passphrase since the
// beginning and fisherman honours both, but nothing ever set them until this
// step existed (tunaOS#734). The choice labels and descriptions are the
// shared branding copy keys, so every frontend words them the same.
//
// SPDX-License-Identifier: GPL-3.0-only

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    // needs_passphrase from encryption-choices.json, not the type's name.
    readonly property bool needsPassphrase: InstallerController.needsPassphrase(InstallerController.encryptionType)
    readonly property bool passphrasesMatch: passphraseField.text === confirmField.text

    // fisherman's rules (an empty passphrase, `validate --json --partial`)
    // and this page's (the confirmation matches) both hold Next, so the user
    // finds out while they can still fix it, not mid-install.
    nextEnabled: InstallerController.encryptionProblem === "" && (!needsPassphrase || passphrasesMatch)

    // Keep the recipe in step with the field fisherman checks, but never
    // leave a passphrase in it for a type that does not take one.
    function commitPassphrase(): void {
        InstallerController.passphrase = needsPassphrase ? passphraseField.text : "";
    }

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: "Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without reinstalling."
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                // One row per recipe type, in the shared order
                // (Recipe::encryptionTypes()); the words are branding copy.
                // TPM options are hidden, not disabled, on a machine without
                // a TPM: offering them there only fails at install time.
                Repeater {
                    model: InstallerController.encryptionTypes

                    delegate: FormCard.FormRadioDelegate {
                        required property string modelData

                        visible: !InstallerController.needsTpm2(modelData) || InstallerController.hasTpm
                        text: InstallerController.encryptionLabel(modelData)
                        description: InstallerController.encryptionDescription(modelData)
                        checked: InstallerController.encryptionType === modelData
                        onToggled: if (checked) {
                            InstallerController.encryptionType = modelData;
                            root.commitPassphrase();
                        }
                    }
                }
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth
                visible: root.needsPassphrase

                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.alignment: Qt.AlignHCenter

                FormCard.FormPasswordFieldDelegate {
                    id: passphraseField

                    label: "Passphrase"

                    onTextChanged: {
                        showPasswordQuality = text.length > 0;
                        root.commitPassphrase();
                    }
                }

                FormCard.FormPasswordFieldDelegate {
                    id: confirmField

                    label: "Confirm passphrase"

                    status: (text.length > 0 && text !== passphraseField.text)
                        ? Kirigami.MessageType.Error : Kirigami.MessageType.Information
                    statusMessage: (text.length > 0 && text !== passphraseField.text)
                        ? "Passphrases do not match." : ""

                    onTextChanged: root.commitPassphrase()
                }
            }

            // fisherman's problem with the choice, in the copy's words.
            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Error
                visible: text !== ""
                text: InstallerController.encryptionProblem

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }
        }
    }
}

// The account the installed system gets: the recipe's `user` block.
//
// This frontend wrote no `user` at all, so an image that does not create its
// own first user (needs_user_creation) installed with nobody to sign in as
// (docs/PARITY.md, user account). There is no image catalog here to say an
// image creates one itself, so the account is required, as it is on XFCE
// without a catalog. fisherman owns the username rule (`validate --json
// --partial`); the password confirmation is the only rule of this page.
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

    readonly property bool passwordsMatch: passwordField.text === confirmPasswordField.text

    // A username and a password, typed the same twice, and no problem from
    // fisherman with the username. Without the user block fisherman creates
    // no account, and the installed system has nobody to sign in as.
    nextEnabled: InstallerController.username.length > 0
        && InstallerController.usernameProblem === ""
        && passwordField.text.length > 0
        && passwordsMatch

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: "Create the account you will sign in with. It can also administer this computer."
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

                FormCard.FormTextFieldDelegate {
                    id: fullnameField
                    objectName: "accountFullname"

                    label: "Full name (optional)"
                    text: InstallerController.fullname

                    onTextChanged: InstallerController.fullname = text
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextFieldDelegate {
                    id: usernameField
                    objectName: "accountUsername"

                    label: "Username"
                    text: InstallerController.username
                    inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhPreferLowercase | Qt.ImhNoPredictiveText

                    // fisherman's problem with the username, in the copy's
                    // words (validate_username_*).
                    status: InstallerController.usernameProblem !== ""
                        ? Kirigami.MessageType.Error : Kirigami.MessageType.Information
                    statusMessage: InstallerController.usernameProblem

                    onTextChanged: InstallerController.username = text
                }
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.alignment: Qt.AlignHCenter

                FormCard.FormPasswordFieldDelegate {
                    id: passwordField
                    objectName: "accountPassword"

                    label: "Password"
                    text: InstallerController.userPassword

                    onTextChanged: {
                        showPasswordQuality = text.length > 0;
                        InstallerController.userPassword = text;
                    }
                }

                FormCard.FormPasswordFieldDelegate {
                    id: confirmPasswordField
                    objectName: "accountPasswordConfirm"

                    label: "Confirm password"

                    status: (text.length > 0 && text !== passwordField.text)
                        ? Kirigami.MessageType.Error : Kirigami.MessageType.Information
                    statusMessage: (text.length > 0 && text !== passwordField.text)
                        ? "Passwords do not match." : ""
                }
            }
        }
    }
}

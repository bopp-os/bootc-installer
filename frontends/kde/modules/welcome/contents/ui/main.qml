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
                objectName: "welcomeLogo"
                source: InstallerController.logoSource || "drive-harddisk-symbolic"
                fallback: "drive-harddisk-symbolic"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.gridUnit
            }

            // Flavour text is branding copy (shared/branding): the product's
            // welcome line and, when it sets one, a subtitle. Nothing here
            // names a product.
            Kirigami.Heading {
                text: InstallerController.text("welcome_title")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.text("welcome_subtitle")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: "This wizard will guide you through installing " + InstallerController.productName + " onto this computer."
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: "You will choose a target disk and how it should be encrypted. Everything after that is handled by the installer."
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
            }

            // fisherman's minimum requirements (RAM, CPU cores, UEFI). A
            // warning, not a gate: shared/probe/README.md.
            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: text.length > 0
                text: InstallerController.requirementsWarning

                Layout.fillWidth: true
            }

        }
    }
}

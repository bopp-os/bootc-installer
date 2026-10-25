// The step runner.
//
// Modelled on KDE KISS's src/qml/Wizard.qml (https://github.com/KDE/kiss):
// each step is a self-contained SetupModule under modules/<name>/contents/ui,
// and the wizard slides between them with hand-rolled NumberAnimations rather
// than a SwipeView — KISS's comment is that a SwipeView is less performant and
// glitchy on window resize, and this inherits both the technique and the reason.
//
// SPDX-License-Identifier: GPL-3.0-only

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

Kirigami.Page {
    id: root

    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0

    property int currentIndex: 0
    readonly property int stepCount: stepsRepeater.count
    readonly property string currentStepId: (currentIndex >= 0 && currentIndex < stepsModel.count)
        ? stepsModel.get(currentIndex).stepId : ""

    // Filled in by the delegates.
    property Control currentStepItem: null
    property Control nextStepItem: null
    property Control previousStepItem: null
    property TunaComponents.SetupModule currentModule: null

    readonly property bool onFinalPage: currentIndex === stepCount - 1

    // The heading over each step. The confirm step's is the branding
    // contract's confirm_title, so a product can word the last page before
    // the disk is written; the others are structural step names.
    function stepTitle(index) {
        const step = stepsModel.get(index)
        return step.stepId === "confirm" ? InstallerController.text("confirm_title") : step.name
    }

    ListModel {
        id: stepsModel

        ListElement { stepId: "welcome";    name: "Welcome";               url: "modules/welcome/main.qml" }
        ListElement { stepId: "disk";       name: "Target Disk";           url: "modules/disk/main.qml" }
        ListElement { stepId: "encryption"; name: "Disk Encryption";       url: "modules/encryption/main.qml" }
        ListElement { stepId: "confirm";    name: "Confirm Installation";  url: "modules/confirm/main.qml" }
        ListElement { stepId: "progress";   name: "Installing";            url: "modules/progress/main.qml" }
        ListElement { stepId: "done";       name: "Finished";              url: "modules/done/main.qml" }
    }

    // Step animation. Manually animating is more performant and less glitchy
    // with window resize than a SwipeView.
    property real previousStepItemX: 0
    property real currentStepItemX: 0
    property real nextStepItemX: 0

    NumberAnimation on previousStepItemX {
        id: previousStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
        onFinished: if (root.previousStepItemX !== 0 && root.previousStepItem) {
            root.previousStepItem.visible = false;
        }
    }

    NumberAnimation on currentStepItemX {
        id: currentStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
    }

    NumberAnimation on nextStepItemX {
        id: nextStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
        onFinished: if (root.nextStepItemX !== 0 && root.nextStepItem) {
            root.nextStepItem.visible = false;
        }
    }

    readonly property bool animating: previousStepAnim.running || currentStepAnim.running || nextStepAnim.running

    function activate(index: int): void {
        const item = stepsRepeater.itemAt(index);
        if (item && item.module && typeof item.module.onPageActivated === "function") {
            item.module.onPageActivated();
        }
    }

    function requestNextPage(): void {
        if (animating || currentIndex + 1 >= stepCount) {
            return;
        }

        previousStepItemX = 0;
        activate(currentIndex + 1);

        currentIndex++;
        stepHeading.changeText(stepTitle(currentIndex));

        currentStepItemX = root.width;
        currentStepItem.visible = true;

        previousStepAnim.to = -root.width;
        previousStepAnim.restart();
        currentStepAnim.to = 0;
        currentStepAnim.restart();
    }

    function requestPreviousPage(): void {
        if (animating || currentIndex === 0) {
            return;
        }

        nextStepItemX = 0;
        activate(currentIndex - 1);

        currentIndex--;
        stepHeading.changeText(stepTitle(currentIndex));

        currentStepItemX = -root.width;
        currentStepItem.visible = true;

        nextStepAnim.to = root.width;
        nextStepAnim.restart();
        currentStepAnim.to = 0;
        currentStepAnim.restart();
    }

    /*!
     * Jump straight to a step, with no animation and no side effects beyond the
     * target module's onPageActivated().
     *
     * This exists for the screenshot harness. It is safe to walk every step
     * with it because nothing here — and nothing in any module's
     * onPageActivated() — can start an install: the only caller of
     * InstallerController.startInstall() is the Install button's onClicked
     * below. Worth stating, because the sibling XFCE installer *does* kick off
     * an install from its page-enter hook.
     */
    function goToStep(index: int): void {
        if (index < 0 || index >= stepCount) {
            return;
        }
        previousStepAnim.stop();
        currentStepAnim.stop();
        nextStepAnim.stop();

        activate(index);
        currentIndex = index;

        previousStepItemX = 0;
        nextStepItemX = 0;
        currentStepItemX = 0;

        for (let i = 0; i < stepsRepeater.count; ++i) {
            const item = stepsRepeater.itemAt(i);
            if (item) {
                item.visible = (i === index);
            }
        }
        stepHeading.text = stepTitle(index);
        stepHeading.opacity = 1;
    }

    // The install runs on the progress step and hands over to the done step by
    // itself — the same handover the Widgets wizard did in its finished() slot.
    Connections {
        target: InstallerController

        function onInstallCompleted(exitCode: int): void {
            if (root.currentStepId === "progress") {
                root.requestNextPage();
            }
        }
    }

    // Welcome and done are hero pages that carry their own heading
    // ("Welcome to <product>", "<product> is installed"); a header title
    // over them only repeated it. The step indicator still names them.
    readonly property bool heroStep: currentStepId === "welcome" || currentStepId === "done"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Step indicator: "Step N of 6 · Name" and one dot per step, the
        // shared six-step contract as COSMIC's header and Niri's dots show
        // it. Colours come from Kirigami.Theme, sizes from Kirigami.Units.
        RowLayout {
            objectName: "stepIndicator"
            spacing: Kirigami.Units.largeSpacing

            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.gridUnit
            Layout.rightMargin: Kirigami.Units.gridUnit

            Label {
                objectName: "stepCounter"
                text: "Step " + (root.currentIndex + 1) + " of " + root.stepCount
                    + " · " + stepsModel.get(root.currentIndex).name
                color: Kirigami.Theme.disabledTextColor
                elide: Text.ElideRight

                Layout.fillWidth: true
            }

            Row {
                spacing: Kirigami.Units.smallSpacing

                Accessible.role: Accessible.ProgressBar
                Accessible.name: "Step " + (root.currentIndex + 1) + " of " + root.stepCount

                Repeater {
                    model: root.stepCount

                    delegate: Rectangle {
                        required property int index

                        readonly property bool current: index === root.currentIndex

                        anchors.verticalCenter: parent.verticalCenter
                        width: current ? Kirigami.Units.gridUnit * 1.5 : Kirigami.Units.smallSpacing * 2
                        height: Kirigami.Units.smallSpacing * 2
                        radius: height / 2
                        color: index <= root.currentIndex
                            ? Kirigami.Theme.highlightColor
                            : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                      Kirigami.Theme.textColor.b, 0.2)

                        Behavior on width {
                            NumberAnimation { duration: Kirigami.Units.shortDuration }
                        }
                    }
                }
            }
        }

        Label {
            id: stepHeading

            opacity: 0
            visible: !root.heroStep
            text: "Welcome"
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.6

            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.gridUnit
            Layout.rightMargin: Kirigami.Units.gridUnit

            property string toText: ""

            function changeText(text: string): void {
                toText = text;
                toHidden.restart();
            }

            NumberAnimation on opacity {
                id: toHidden
                duration: Kirigami.Units.shortDuration
                to: 0
                onFinished: {
                    stepHeading.text = stepHeading.toText;
                    toShown.restart();
                }
            }

            NumberAnimation on opacity {
                id: toShown
                running: true
                duration: Kirigami.Units.shortDuration
                to: 1
            }
        }

        Item {
            id: stepsContainer

            // Looked up by the screenshot harness, which audits the pixels of
            // the step area specifically: the heading and the button row draw
            // on every step, so a whole-window audit would still find ink on a
            // step whose module rendered nothing at all.
            objectName: "stepsContainer"

            clip: true

            Layout.fillWidth: true
            Layout.fillHeight: true

            Repeater {
                id: stepsRepeater
                model: stepsModel
                delegate: PageDelegate {}
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit

            Button {
                text: "Back"
                icon.name: "arrow-left-symbolic"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                // No going back once fisherman has been handed the disk.
                visible: root.currentIndex > 0
                    && root.currentStepId !== "progress"
                    && root.currentStepId !== "done"

                onClicked: root.requestPreviousPage()
            }

            Item {
                Layout.fillWidth: true
            }

            Button {
                id: nextButton

                readonly property bool isInstall: root.currentStepId === "confirm"
                readonly property bool isClose: root.currentStepId === "done"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                // Nicer to have the arrow on the side it's pointing to.
                LayoutMirroring.enabled: !isInstall && !isClose
                    && Qt.application.layoutDirection === Qt.LeftToRight

                // Hidden while fisherman runs: the progress step advances itself.
                visible: root.currentStepId !== "progress"

                readonly property bool isWelcome: root.currentStepId === "welcome"

                // Branding copy on the two buttons that carry a product's voice:
                // leaving the welcome page and starting the install.
                text: isInstall ? InstallerController.text("confirm_button")
                    : isWelcome ? InstallerController.text("welcome_button")
                    : (isClose ? "Close" : "Next")
                icon.name: isInstall ? "install-symbolic"
                    : (isClose ? "window-close-symbolic" : "arrow-right-symbolic")

                enabled: root.currentModule ? root.currentModule.nextEnabled : false

                // The one and only place an install is started.
                onClicked: {
                    if (isClose) {
                        Qt.quit();
                    } else if (isInstall) {
                        InstallerController.startInstall();
                        root.requestNextPage();
                    } else {
                        root.requestNextPage();
                    }
                }
            }
        }
    }

    /*!
     * Delegate that represents each step in the wizard.
     */
    component PageDelegate: Control {
        id: item

        required property int index
        required property string url

        property TunaComponents.SetupModule module: null

        visible: index === 0 // the binding is broken later

        width: stepsContainer.width
        height: stepsContainer.height

        topPadding: Kirigami.Units.gridUnit
        bottomPadding: Kirigami.Units.gridUnit
        leftPadding: Kirigami.Units.gridUnit
        rightPadding: Kirigami.Units.gridUnit

        contentItem: module ? module.contentItem : null

        Component.onCompleted: {
            const component = Qt.createComponent(Qt.resolvedUrl(url));
            if (component.status === Component.Error) {
                console.error("failed to load step", url, component.errorString());
                return;
            }
            module = component.createObject(item) as TunaComponents.SetupModule;
            updateRootItems();
        }

        Binding {
            target: item.module
            property: "cardWidth"
            value: Math.min(Kirigami.Units.gridUnit * 30,
                            item.width - Kirigami.Units.gridUnit * 4)
            when: item.module !== null
        }

        transform: Translate {
            x: {
                if (item.index === root.currentIndex - 1) {
                    return root.previousStepItemX;
                } else if (item.index === root.currentIndex + 1) {
                    return root.nextStepItemX;
                } else if (item.index === root.currentIndex) {
                    return root.currentStepItemX;
                }
                return 0;
            }
        }

        function updateRootItems(): void {
            if (index === root.currentIndex) {
                root.currentStepItem = item;
                root.currentModule = module;
            } else if (index === root.currentIndex - 1) {
                root.previousStepItem = item;
            } else if (index === root.currentIndex + 1) {
                root.nextStepItem = item;
            }
        }

        Connections {
            target: root

            function onCurrentIndexChanged(): void {
                item.updateRootItems();
            }
        }
    }
}

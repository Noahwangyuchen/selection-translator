pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid
import org.kde.plasma.workspace.dbus as DBus
import "StateTransitions.js" as StateTransitions

PlasmoidItem {
    id: root

    readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("../tools/selection_translator.py").toString()).replace(/^file:\/\//, "")
    readonly property string dbPath: decodeURIComponent(Qt.resolvedUrl("../data/ecdict.sqlite3").toString()).replace(/^file:\/\//, "")
    readonly property string dbusService: "org.local.SelectionTranslator"
    readonly property string dbusPath: "/org/local/SelectionTranslator"
    readonly property string dbusInterface: "org.local.SelectionTranslator"
    readonly property int compactMaxWidth: Kirigami.Units.gridUnit * 16
    property string currentWord: ""
    property string phonetic: ""
    property string translation: ""
    property string definition: ""
    property string exchange: ""
    property string statusText: "请选择英文单词"
    property string lastDaemonCommand: ""
    property string sentenceText: ""
    property string sentenceTranslation: ""
    property string sentenceEngine: ""
    property bool stateRequestPending: false
    property bool hasResult: false
    property bool sentenceCandidate: false
    property bool translatingSentence: false
    readonly property bool compactIdle: !hasResult && !sentenceCandidate && !translatingSentence
        && sentenceTranslation.length === 0 && currentWord.length === 0
    readonly property string compactText: translatingSentence
        ? "翻译中..."
        : (sentenceTranslation.length > 0
            ? sentenceTranslation
            : (sentenceCandidate ? "翻译整句" : (hasResult ? translation.split(/[;\n]/)[0] : currentWord)))

    Plasmoid.icon: "accessories-dictionary"
    Plasmoid.status: hasResult || sentenceCandidate || translatingSentence || sentenceTranslation.length > 0 ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    toolTipMainText: currentWord.length > 0 ? currentWord : "划词翻译"
    toolTipSubText: hasResult ? translation : statusText

    property DBus.dbusMessage getStateMessage: ({
        service: dbusService,
        path: dbusPath,
        iface: dbusInterface,
        member: "GetState"
    })
    property DBus.dbusMessage refreshMessage: ({
        service: dbusService,
        path: dbusPath,
        iface: dbusInterface,
        member: "Refresh"
    })
    property DBus.dbusMessage translateMessage: ({
        service: dbusService,
        path: dbusPath,
        iface: dbusInterface,
        member: "TranslateCurrent"
    })

    Component.onCompleted: startListener()

    function startListener() {
        if (serviceWatcher.registered || lastDaemonCommand.length > 0) {
            return
        }

        const command = "python3 " + shellQuote(scriptPath) + " --start-daemon --db " + shellQuote(dbPath) + " --stamp " + Date.now()
        lastDaemonCommand = command
        executableSource.connectSource(command)
    }

    function replyValue(reply) {
        if (reply && reply.value && reply.value.value !== undefined) {
            return reply.value.value
        }
        return reply ? reply.value : ""
    }

    function requestState() {
        if (!serviceWatcher.registered) {
            startListener()
            return
        }
        if (stateRequestPending) {
            return
        }
        stateRequestPending = true
        const reply = DBus.SessionBus.asyncCall(getStateMessage) as DBus.DBusPendingReply
        reply.finished.connect(function() {
            root.stateRequestPending = false
            if (!reply.isError) {
                root.applyResult(String(root.replyValue(reply)))
            }
            reply.destroy()
        })
    }

    function refresh() {
        if (!serviceWatcher.registered) {
            startListener()
            return
        }
        const reply = DBus.SessionBus.asyncCall(refreshMessage) as DBus.DBusPendingReply
        reply.finished.connect(function() { reply.destroy() })
    }

    function translateSentence() {
        if (sentenceText.length === 0 || translatingSentence) {
            return
        }

        if (!serviceWatcher.registered) {
            startListener()
            statusText = "翻译服务正在启动..."
            return
        }
        sentenceTranslation = ""
        sentenceEngine = ""
        translatingSentence = true
        const reply = DBus.SessionBus.asyncCall(translateMessage) as DBus.DBusPendingReply
        reply.finished.connect(function() {
            if (reply.isError) {
                root.translatingSentence = false
                root.statusText = "整句翻译服务暂时不可用"
            }
            reply.destroy()
        })
    }

    function shellQuote(value) {
        return "'" + String(value).replace(/'/g, "'\\''") + "'"
    }

    function firstValue(data, names) {
        for (let i = 0; i < names.length; i++) {
            if (data[names[i]] !== undefined) {
                return data[names[i]]
            }
        }
        return ""
    }

    function stateSnapshot() {
        return {
            currentWord: currentWord,
            phonetic: phonetic,
            translation: translation,
            definition: definition,
            exchange: exchange,
            statusText: statusText,
            sentenceText: sentenceText,
            sentenceTranslation: sentenceTranslation,
            sentenceEngine: sentenceEngine,
            hasResult: hasResult,
            sentenceCandidate: sentenceCandidate,
            translatingSentence: translatingSentence
        }
    }

    function applyState(state) {
        currentWord = state.currentWord
        phonetic = state.phonetic
        translation = state.translation
        definition = state.definition
        exchange = state.exchange
        statusText = state.statusText
        sentenceText = state.sentenceText
        sentenceTranslation = state.sentenceTranslation
        sentenceEngine = state.sentenceEngine
        hasResult = state.hasResult
        sentenceCandidate = state.sentenceCandidate
        translatingSentence = state.translatingSentence
    }

    function applyResult(rawText) {
        if (!rawText || rawText.length === 0) {
            return
        }

        let payload
        try {
            payload = JSON.parse(rawText)
        } catch (error) {
            statusText = i18n("Translator output was not readable")
            hasResult = false
            return
        }

        applyState(StateTransitions.reduce(stateSnapshot(), payload))
    }

    Timer {
        id: listenerRestartTimer
        interval: 2000
        repeat: true
        running: !serviceWatcher.registered
        onTriggered: root.startListener()
    }

    DBus.DBusServiceWatcher {
        id: serviceWatcher
        busType: DBus.BusType.Session
        watchedService: root.dbusService
        onRegisteredChanged: {
            if (registered) {
                root.requestState()
            } else {
                root.startListener()
            }
        }
    }

    DBus.SignalWatcher {
        busType: DBus.BusType.Session
        service: root.dbusService
        path: root.dbusPath
        iface: root.dbusInterface

        function dbusStateChanged(state) {
            root.applyResult(String(state))
        }
    }

    P5Support.DataSource {
        id: executableSource
        engine: "executable"

        onNewData: function(sourceName, data) {
            if (sourceName === root.lastDaemonCommand) {
                root.lastDaemonCommand = ""
            }
            disconnectSource(sourceName)
        }
    }

    compactRepresentation: Item {
        id: compact
        clip: true
        readonly property int horizontalPadding: Kirigami.Units.smallSpacing * 2
        readonly property int actionWidth: actionItem.visible ? actionItem.Layout.preferredWidth + compactRow.spacing : 0
        readonly property int textWidth: Math.ceil(Math.max(compactTextMetrics.advanceWidth, compactTextMetrics.boundingRect.width))
            + Kirigami.Units.smallSpacing
        readonly property int textMaximumWidth: root.compactMaxWidth
            - horizontalPadding
            - Kirigami.Units.iconSizes.smallMedium
            - compactRow.spacing
            - actionWidth
        readonly property int naturalWidth: horizontalPadding
            + Kirigami.Units.iconSizes.smallMedium
            + (compactLabel.visible ? compactRow.spacing + textWidth : 0)
            + actionWidth
        readonly property int idleWidth: Kirigami.Units.iconSizes.smallMedium + horizontalPadding
        implicitWidth: root.compactIdle ? idleWidth : Math.min(root.compactMaxWidth, Math.max(Kirigami.Units.gridUnit * 5, naturalWidth))
        implicitHeight: Math.max(Kirigami.Units.gridUnit * 2, Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing * 2)
        Layout.minimumWidth: root.compactIdle
            ? idleWidth
            : (root.sentenceCandidate ? implicitWidth : Math.min(implicitWidth, Kirigami.Units.gridUnit * 5))
        Layout.preferredWidth: implicitWidth
        Layout.maximumWidth: root.compactMaxWidth
        Layout.minimumHeight: implicitHeight
        Layout.preferredHeight: implicitHeight

        TextMetrics {
            id: compactTextMetrics
            font: compactLabel.font
            text: root.compactText
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.expanded = !root.expanded
        }

        RowLayout {
            id: compactRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.rightMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "accessories-dictionary"
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                Layout.alignment: Qt.AlignVCenter
            }

            PlasmaComponents3.Label {
                id: compactLabel
                visible: root.compactText.length > 0
                text: root.compactText
                elide: Text.ElideRight
                wrapMode: Text.Wrap
                maximumLineCount: compact.height >= Kirigami.Units.gridUnit * 2.5 ? 2 : 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: Math.min(compact.textWidth, compact.textMaximumWidth)
                Layout.maximumWidth: compact.textMaximumWidth
                Layout.alignment: Qt.AlignVCenter
                verticalAlignment: Text.AlignVCenter
            }

            Item {
                id: actionItem
                visible: root.sentenceCandidate || root.translatingSentence
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.smallSpacing * 2
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                z: 2

                Kirigami.Icon {
                    anchors.centerIn: parent
                    source: root.translatingSentence ? "view-refresh" : "internet-services"
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                    opacity: translateButton.enabled ? 1 : 0.55
                }

                MouseArea {
                    id: translateButton
                    anchors.fill: parent
                    enabled: root.sentenceCandidate && !root.translatingSentence
                    hoverEnabled: true
                    onClicked: function(mouse) {
                        mouse.accepted = true
                        root.translateSentence()
                    }

                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.text: root.translatingSentence ? "翻译中" : "翻译整句"
                }
            }
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 22
        Layout.minimumHeight: Kirigami.Units.gridUnit * 16
        collapseMarginsHint: true

        contentItem: PlasmaComponents3.ScrollView {
            anchors.fill: parent
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    PlasmaComponents3.Label {
                        text: root.currentWord.length > 0 ? root.currentWord : "划词翻译"
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.4
                        font.bold: true
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.phonetic.length > 0
                        text: "/" + root.phonetic + "/"
                        opacity: 0.72
                        Layout.fillWidth: true
                    }
                }

                PlasmaExtras.PlaceholderMessage {
                    visible: !root.hasResult && !root.sentenceCandidate && root.sentenceTranslation.length === 0
                    Layout.fillWidth: true
                    iconName: "edit-select-text"
                    text: root.statusText
                }

                ColumnLayout {
                    visible: root.hasResult
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    PlasmaComponents3.Label {
                        text: root.translation
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.definition.length > 0
                        text: root.definition
                        wrapMode: Text.Wrap
                        opacity: 0.78
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.exchange.length > 0
                        text: "词形：" + root.exchange
                        wrapMode: Text.Wrap
                        opacity: 0.62
                        Layout.fillWidth: true
                    }
                }

                ColumnLayout {
                    visible: root.sentenceCandidate || root.sentenceTranslation.length > 0 || root.translatingSentence
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    PlasmaComponents3.Label {
                        text: "选中的句子"
                        font.bold: true
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        text: root.sentenceText
                        wrapMode: Text.Wrap
                        opacity: 0.78
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.sentenceTranslation.length > 0
                        text: root.sentenceTranslation
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.sentenceEngine.length > 0
                        text: "来源：" + root.sentenceEngine
                        opacity: 0.62
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Label {
                        visible: root.statusText.length > 0 && !root.sentenceCandidate
                        text: root.statusText
                        wrapMode: Text.Wrap
                        opacity: 0.78
                        Layout.fillWidth: true
                    }

                    PlasmaComponents3.Button {
                        visible: root.sentenceCandidate
                        text: root.translatingSentence ? "翻译中..." : "翻译整句"
                        icon.name: "internet-services"
                        enabled: !root.translatingSentence
                        onClicked: root.translateSentence()
                    }
                }
            }
        }

        footer: PlasmaExtras.PlasmoidHeading {
            contentItem: RowLayout {
                PlasmaComponents3.ToolButton {
                    text: "刷新"
                    icon.name: "view-refresh"
                    onClicked: root.refresh()
                }
            }
        }
    }
}

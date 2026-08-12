pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.kirigamiaddons.formcard as FormCard

KCM.SimpleKCM {
    id: root

    property string cfg_serviceOrder: "deepseek,openai,google"
    property alias cfg_deepseekApiKey: deepseekApiKey.text
    property alias cfg_deepseekModel: deepseekModel.text
    property alias cfg_deepseekBaseUrl: deepseekBaseUrl.text
    property alias cfg_openaiApiKey: openaiApiKey.text
    property alias cfg_openaiModel: openaiModel.text
    property alias cfg_openaiBaseUrl: openaiBaseUrl.text
    readonly property alias configContent: contentColumn
    property bool advancedVisible: false

    function serviceName(serviceId) {
        if (serviceId === "deepseek") return "DeepSeek"
        if (serviceId === "openai") return "OpenAI"
        return "Google Translate"
    }

    function serviceDescription(serviceId) {
        if (serviceId === "deepseek") return "使用 DeepSeek API Key"
        if (serviceId === "openai") return "使用 OpenAI API Key"
        return "无需配置，可能受到请求频率限制"
    }

    function saveServiceOrder() {
        const order = []
        for (let index = 0; index < priorityModel.count; ++index) {
            order.push(priorityModel.get(index).serviceId)
        }
        cfg_serviceOrder = order.join(",")
    }

    function moveService(index, offset) {
        const target = index + offset
        if (target < 0 || target >= priorityModel.count) return
        priorityModel.move(index, target, 1)
        saveServiceOrder()
    }

    Component.onCompleted: {
        const known = ["deepseek", "openai", "google"]
        const configured = cfg_serviceOrder.split(",")
        const order = []
        for (const serviceId of configured) {
            const cleanId = serviceId.trim().toLowerCase()
            if (known.indexOf(cleanId) >= 0 && order.indexOf(cleanId) < 0) {
                order.push(cleanId)
            }
        }
        for (const serviceId of known) {
            if (order.indexOf(serviceId) < 0) order.push(serviceId)
        }
        for (const serviceId of order) priorityModel.append({serviceId: serviceId})
        saveServiceOrder()
    }

    ListModel {
        id: priorityModel
    }

    ColumnLayout {
        id: contentColumn
        spacing: 0

        FormCard.FormHeader {
            title: "服务优先级"
        }

        FormCard.FormCard {
            Repeater {
                model: priorityModel

                delegate: QQC2.ItemDelegate {
                    id: serviceDelegate
                    required property int index
                    required property string serviceId
                    width: parent ? parent.width : implicitWidth

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing

                        Kirigami.Icon {
                            source: serviceDelegate.serviceId === "google" ? "web-browser" : "internet-services"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            QQC2.Label {
                                text: root.serviceName(serviceDelegate.serviceId)
                                Layout.fillWidth: true
                            }

                            QQC2.Label {
                                text: root.serviceDescription(serviceDelegate.serviceId)
                                color: Kirigami.Theme.disabledTextColor
                                font: Kirigami.Theme.smallFont
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }

                        QQC2.ToolButton {
                            icon.name: "go-up"
                            enabled: serviceDelegate.index > 0
                            display: QQC2.AbstractButton.IconOnly
                            onClicked: root.moveService(serviceDelegate.index, -1)
                            QQC2.ToolTip.visible: hovered
                            QQC2.ToolTip.text: "提高优先级"
                        }

                        QQC2.ToolButton {
                            icon.name: "go-down"
                            enabled: serviceDelegate.index < priorityModel.count - 1
                            display: QQC2.AbstractButton.IconOnly
                            onClicked: root.moveService(serviceDelegate.index, 1)
                            QQC2.ToolTip.visible: hovered
                            QQC2.ToolTip.text: "降低优先级"
                        }
                    }
                }
            }
        }

        FormCard.FormSectionText {
            text: "整句翻译和单词的在线翻译都会按此顺序尝试，成功后停止。"
        }

        FormCard.FormHeader {
            title: "DeepSeek"
        }

        FormCard.FormCard {
            FormCard.FormPasswordFieldDelegate {
                id: deepseekApiKey
                label: "API Key"
                placeholderText: "sk-..."
            }

            FormCard.FormDelegateSeparator {}

            FormCard.FormTextFieldDelegate {
                id: deepseekModel
                label: "模型"
                placeholderText: "deepseek-v4-flash"
            }
        }

        FormCard.FormHeader {
            title: "OpenAI"
        }

        FormCard.FormCard {
            FormCard.FormPasswordFieldDelegate {
                id: openaiApiKey
                label: "API Key"
                placeholderText: "sk-..."
            }

            FormCard.FormDelegateSeparator {}

            FormCard.FormTextFieldDelegate {
                id: openaiModel
                label: "模型"
                placeholderText: "gpt-5-nano"
            }
        }

        FormCard.FormHeader {
            title: "高级设置"
        }

        FormCard.FormCard {
            FormCard.FormButtonDelegate {
                text: root.advancedVisible ? "隐藏服务地址" : "显示服务地址"
                description: "仅在使用兼容接口或代理时需要修改"
                icon.name: "configure"
                trailingLogo.direction: root.advancedVisible ? Qt.UpArrow : Qt.DownArrow
                onClicked: root.advancedVisible = !root.advancedVisible
            }
        }

        FormCard.FormCard {
            visible: root.advancedVisible
            Layout.topMargin: Kirigami.Units.smallSpacing

            FormCard.FormTextFieldDelegate {
                id: deepseekBaseUrl
                label: "DeepSeek Base URL"
                placeholderText: "https://api.deepseek.com"
            }

            FormCard.FormDelegateSeparator {}

            FormCard.FormTextFieldDelegate {
                id: openaiBaseUrl
                label: "OpenAI Base URL"
                placeholderText: "https://api.openai.com/v1"
            }
        }
    }
}

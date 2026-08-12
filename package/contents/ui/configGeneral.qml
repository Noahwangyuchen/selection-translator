import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_deepseekApiKey: deepseekApiKey.text
    property alias cfg_deepseekModel: deepseekModel.text
    property alias cfg_deepseekBaseUrl: deepseekBaseUrl.text
    property alias cfg_openaiApiKey: openaiApiKey.text
    property alias cfg_openaiModel: openaiModel.text
    property alias cfg_openaiBaseUrl: openaiBaseUrl.text

    Kirigami.FormLayout {
        anchors.fill: parent

        QQC2.Label {
            text: "整句翻译会优先使用 DeepSeek，其次 OpenAI，最后 Google Translate。API key 会保存到 Plasma 小组件配置文件中。"
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            Kirigami.FormData.isSection: true
        }

        QQC2.TextField {
            id: deepseekApiKey
            Kirigami.FormData.label: "DeepSeek API Key:"
            echoMode: TextInput.Password
            placeholderText: "sk-..."
            Layout.fillWidth: true
        }

        QQC2.TextField {
            id: deepseekModel
            Kirigami.FormData.label: "DeepSeek 模型:"
            placeholderText: "deepseek-v4-flash"
            Layout.fillWidth: true
        }

        QQC2.TextField {
            id: deepseekBaseUrl
            Kirigami.FormData.label: "DeepSeek Base URL:"
            placeholderText: "https://api.deepseek.com"
            Layout.fillWidth: true
        }

        QQC2.TextField {
            id: openaiApiKey
            Kirigami.FormData.label: "OpenAI API Key:"
            echoMode: TextInput.Password
            placeholderText: "sk-..."
            Layout.fillWidth: true
        }

        QQC2.TextField {
            id: openaiModel
            Kirigami.FormData.label: "OpenAI 模型:"
            placeholderText: "gpt-5-nano"
            Layout.fillWidth: true
        }

        QQC2.TextField {
            id: openaiBaseUrl
            Kirigami.FormData.label: "OpenAI Base URL:"
            placeholderText: "https://api.openai.com/v1"
            Layout.fillWidth: true
        }
    }
}

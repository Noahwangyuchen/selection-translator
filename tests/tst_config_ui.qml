import QtQuick
import QtTest

TestCase {
    name: "SelectionTranslatorConfig"
    when: windowShown

    Loader {
        id: configLoader
        width: 640
        height: 480
        source: "../package/contents/ui/configGeneral.qml"
    }

    function test_configurationPageLoads() {
        tryCompare(configLoader, "status", Loader.Ready)
        compare(configLoader.item.cfg_serviceOrder, "deepseek,openai,google")
    }

    function verifyVisibleSectionsDoNotOverlap() {
        const sections = configLoader.item.configContent.children
        let previousBottom = 0
        for (const section of sections) {
            if (!section.visible || section.height <= 0) continue
            verify(section.y >= previousBottom,
                "配置区块发生重叠：y=" + section.y + "，上一项底部=" + previousBottom)
            previousBottom = section.y + section.height
        }
    }

    function test_visibleSectionsDoNotOverlap() {
        verifyVisibleSectionsDoNotOverlap()
        configLoader.item.advancedVisible = true
        wait(0)
        verifyVisibleSectionsDoNotOverlap()
        configLoader.item.advancedVisible = false
    }

    function test_serviceOrderCanBeChanged() {
        configLoader.item.moveService(0, 1)
        compare(configLoader.item.cfg_serviceOrder, "openai,deepseek,google")
        configLoader.item.moveService(1, -1)
        compare(configLoader.item.cfg_serviceOrder, "deepseek,openai,google")
    }
}

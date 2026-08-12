import QtQuick
import QtTest

TestCase {
    name: "SelectionTranslatorConfig"
    when: windowShown

    Loader {
        id: configLoader
        source: "../package/contents/ui/configGeneral.qml"
    }

    function test_configurationPageLoads() {
        tryCompare(configLoader, "status", Loader.Ready)
        compare(configLoader.item.cfg_serviceOrder, "deepseek,openai,google")
    }

    function test_serviceOrderCanBeChanged() {
        configLoader.item.moveService(0, 1)
        compare(configLoader.item.cfg_serviceOrder, "openai,deepseek,google")
        configLoader.item.moveService(1, -1)
        compare(configLoader.item.cfg_serviceOrder, "deepseek,openai,google")
    }
}

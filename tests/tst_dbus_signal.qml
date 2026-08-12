import QtQuick
import QtTest
import org.kde.plasma.workspace.dbus as DBus

TestCase {
    id: testCase
    name: "SelectionTranslatorDbusSignal"

    property int receivedCount: 0
    property string payload: ""
    property var pendingReply

    DBus.SignalWatcher {
        id: stateWatcher
        busType: DBus.BusType.Session
        service: "org.local.SelectionTranslator"
        path: "/org/local/SelectionTranslator"
        iface: "org.local.SelectionTranslator"

        function dbusStateChanged(state) {
            testCase.payload = String(state)
            testCase.receivedCount += 1
        }
    }

    DBus.SignalWatcher {
        busType: DBus.BusType.Session
        service: "org.local.SelectionTranslator"
        path: "/org/local/SelectionTranslator"
        iface: "org.local.SelectionTranslator"

        function dbusStateChanged(state) {
            testCase.receivedCount += 1
        }
    }

    function test_stateChanged() {
        pendingReply = DBus.SessionBus.asyncCall({
            service: "org.local.SelectionTranslator",
            path: "/org/local/SelectionTranslator",
            iface: "org.local.SelectionTranslator",
            member: "Refresh"
        })
        tryVerify(function() { return pendingReply.isFinished }, 2000)
        verify(!pendingReply.isError, pendingReply.error.message)
        tryCompare(testCase, "receivedCount", 2, 2000)
        verify(payload.length > 0)
        pendingReply.destroy()
    }
}

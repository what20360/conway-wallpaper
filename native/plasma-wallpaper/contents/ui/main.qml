import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

WallpaperItem {
    id: root
    // Source dimensions are physical pixels, independent of Plasma's logical DPI.
    readonly property real ratio: Screen.devicePixelRatio || 1
    readonly property int pixelWidth: Math.min(2560, Math.max(640, Math.round(width * ratio)))
    readonly property int pixelHeight: Math.min(1440, Math.max(360, Math.round(height * ratio)))
    property bool frontIsA: true
    property bool fetching: false
    property bool connected: false
    property bool sending: false
    property int sequence: 0
    property int lastRevision: -1
    property int lastWidth: 0
    property int lastHeight: 0
    property var inputQueue: []
    Connection { id: connection }
    contextualActions: [
        PlasmaCore.Action {
            text: "生命场：打开控制窗口"; icon.name: "applications-graphics"
            onTriggered: root.command("window")
        },
        PlasmaCore.Action {
            text: "生命场：暂停／继续"; icon.name: "media-playback-start"
            onTriggered: root.command("run")
        },
        PlasmaCore.Action {
            text: "生命场：打开日志"; icon.name: "document-open"
            onTriggered: root.command("logs")
        }
    ]
    function command(name) {
        if (inputQueue.length < 64) inputQueue.push({kind: "command", name: name})
        sendNext()
    }

    Rectangle { anchors.fill: parent; color: "#0a1218" }
    function frameReady(image) {
        if (image.status === Image.Ready) {
            frontIsA = image === a
            connected = true
            lastRevision = image.revision
            fetching = false
        } else if (image.status === Image.Error) {
            connected = false
            lastRevision = -1
            fetching = false
        }
    }
    // Two buffers keep the last complete frame visible during a download or error.
    Image {
        id: a
        property int revision: -1
        width: root.pixelWidth / root.ratio; height: root.pixelHeight / root.ratio
        visible: root.frontIsA; cache: false; asynchronous: true; smooth: false
        onStatusChanged: root.frameReady(a)
    }
    Image {
        id: b
        property int revision: -1
        width: root.pixelWidth / root.ratio; height: root.pixelHeight / root.ratio
        visible: !root.frontIsA; cache: false; asynchronous: true; smooth: false
        onStatusChanged: root.frameReady(b)
    }
    Text {
        visible: !root.connected
        anchors.centerIn: parent
        text: "请启动“生命场壁纸后台”\n若已启动，请打开后台日志检查连接。"
        color: "#91bbd6"; horizontalAlignment: Text.AlignHCenter
    }
    Timer {
        interval: root.connected ? 63 : 1500; repeat: true; running: root.visible
        triggeredOnStart: true
        onTriggered: {
            if (root.fetching || !connection.token) return
            root.fetching = true
            const request = new XMLHttpRequest()
            request.open("GET",connection.endpoint + "/status")
            request.setRequestHeader("Authorization","Bearer " + connection.token)
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE) return
                if (request.status !== 200) { root.connected = false; root.fetching = false; return }
                const revision = JSON.parse(request.responseText).revision
                if (revision === root.lastRevision && root.lastWidth === root.pixelWidth && root.lastHeight === root.pixelHeight) {
                    root.connected = true; root.fetching = false; return
                }
                root.lastWidth = root.pixelWidth; root.lastHeight = root.pixelHeight
                const target = root.frontIsA ? b : a
                target.revision = revision
                target.source = connection.endpoint + "/frame?token=" + connection.token
                    + "&w=" + root.pixelWidth + "&h=" + root.pixelHeight + "&seq=" + (++root.sequence)
            }
            request.send()
        }
    }
    // Serialize input: an asynchronous HTTP release must never overtake a press.
    function enqueue(kind, x, y, shift) {
        const event = {kind: kind, x: Math.max(0, Math.min(pixelWidth-1, Math.round(x*ratio))),
            y: Math.max(0, Math.min(pixelHeight-1, Math.round(y*ratio))),
            w: pixelWidth, h: pixelHeight, shift: shift}
        if (kind === "move" && inputQueue.length && inputQueue[inputQueue.length-1].kind === "move")
            inputQueue[inputQueue.length-1] = event
        else if (inputQueue.length < 64) inputQueue.push(event)
        else if (kind === "release" || kind === "cancel") inputQueue = [event]
        sendNext()
    }
    function sendNext() {
        if (sending || !inputQueue.length) return
        sending = true
        const request = new XMLHttpRequest()
        request.open("POST", connection.endpoint + "/input")
        request.setRequestHeader("Content-Type", "application/json")
        request.setRequestHeader("Authorization", "Bearer " + connection.token)
        request.onreadystatechange = function() {
            if (request.readyState === XMLHttpRequest.DONE) {
                root.sending = false
                if (request.status !== 200) { root.inputQueue = []; root.connected = false }
                root.sendNext()
            }
        }
        request.send(JSON.stringify(inputQueue.shift()))
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton // Reserve right-click for the Plasma desktop menu.
        onPressed: function(mouse) {
            if (!root.connected) { mouse.accepted = false; return }
            root.enqueue("press",mouse.x,mouse.y,!!(mouse.modifiers & Qt.ShiftModifier))
        }
        onPositionChanged: function(mouse) {
            if (pressed) root.enqueue("move",mouse.x,mouse.y,!!(mouse.modifiers & Qt.ShiftModifier))
        }
        onReleased: function(mouse) { root.enqueue("release",mouse.x,mouse.y,false) }
        onCanceled: root.enqueue("cancel",0,0,false)
        Timer {
            interval: 1000; repeat: true; running: parent.pressed
            onTriggered: root.enqueue("move",parent.mouseX,parent.mouseY,false)
        }
    }
}

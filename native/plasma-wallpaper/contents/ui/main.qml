import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

WallpaperItem {
    id: root
    readonly property string frontendVersion: "0.3.2"
    // Source resolution and the Item's logical display size are separate contracts.
    readonly property real ratio: Screen.devicePixelRatio || 1
    readonly property real renderScale: Math.min(Math.max(ratio, 640 / Math.max(1,width), 360 / Math.max(1,height)),
                                                2560 / Math.max(1,width), 1440 / Math.max(1,height))
    // Fractional Wayland geometry can round 2K to 2560x1439. That would make
    // the native integer cell scale fall from 8 to 7. Snap near-16:9 surfaces
    // to one of our supported canvases, rather than flooring one short axis.
    readonly property bool widescreen: height > 0 && Math.abs(width / height - 16/9) < 0.01
    readonly property int targetWidth: width*ratio > 1958 || height*ratio > 1102 ? 2560 : 1920
    readonly property int pixelWidth: widescreen ? targetWidth : Math.min(2560, Math.max(640, Math.round(width * renderScale)))
    readonly property int pixelHeight: widescreen ? targetWidth*9/16 : Math.min(1440, Math.max(360, Math.round(height * renderScale)))
    property bool frontIsA: true
    property bool fetching: false
    property bool connected: false
    property bool reloadRequired: false
    property bool editing: false
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
        },
        PlasmaCore.Action {
            text: "生命场：桌面绘制模式"; icon.name: "draw-freehand"
            checkable: true; checked: root.editing
            onTriggered: root.command("edit")
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
        objectName: "frameA"
        property int revision: -1
        property int frameWidth: 0
        property int frameHeight: 0
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        visible: root.frontIsA; cache: false; asynchronous: true; smooth: false
        onStatusChanged: root.frameReady(a)
    }
    Image {
        id: b
        objectName: "frameB"
        property int revision: -1
        property int frameWidth: 0
        property int frameHeight: 0
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        visible: !root.frontIsA; cache: false; asynchronous: true; smooth: false
        onStatusChanged: root.frameReady(b)
    }
    Text {
        visible: !root.connected || root.reloadRequired
        anchors.centerIn: parent
        text: root.reloadRequired ? "生命场前端与后台版本不一致\n请重载 Plasma 桌面外壳。" : "请启动“生命场壁纸后台”\n若已启动，请打开后台日志检查连接。"
        color: "#91bbd6"; horizontalAlignment: Text.AlignHCenter
    }
    Timer {
        interval: root.connected ? 63 : 1500; repeat: true; running: root.visible
        triggeredOnStart: true
        onTriggered: {
            if (root.fetching || !connection.token) return
            root.fetching = true
            const request = new XMLHttpRequest()
            const image = root.frontIsA ? a : b
            request.open("GET",connection.endpoint + "/status?frontend=" + root.frontendVersion
                + "&logicalW=" + root.width + "&logicalH=" + root.height
                + "&parentW=" + (root.parent ? root.parent.width : 0) + "&parentH=" + (root.parent ? root.parent.height : 0)
                + "&screenDpr=" + root.ratio + "&sourceW=" + root.pixelWidth + "&sourceH=" + root.pixelHeight
                + "&imageW=" + image.width + "&imageH=" + image.height + "&editing=" + (root.editing ? 1 : 0))
            request.setRequestHeader("Authorization","Bearer " + connection.token)
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE) return
                if (request.status !== 200) { root.connected = false; root.fetching = false; return }
                const status = JSON.parse(request.responseText)
                const revision = status.revision
                root.reloadRequired = !!status.reloadRequired || status.backendVersion !== root.frontendVersion
                root.editing = !!status.editing
                if (revision === root.lastRevision && root.lastWidth === root.pixelWidth && root.lastHeight === root.pixelHeight) {
                    root.connected = true; root.fetching = false; return
                }
                root.lastWidth = root.pixelWidth; root.lastHeight = root.pixelHeight
                const target = root.frontIsA ? b : a
                target.revision = revision
                target.frameWidth = root.pixelWidth; target.frameHeight = root.pixelHeight
                target.source = connection.endpoint + "/frame?token=" + connection.token
                    + "&w=" + root.pixelWidth + "&h=" + root.pixelHeight + "&seq=" + (++root.sequence)
            }
            request.send()
        }
    }
    // Serialize input: an asynchronous HTTP release must never overtake a press.
    function enqueue(kind, x, y, shift) {
        // Map into the frame actually on screen, including letterboxing and a resize
        // while a new frame is loading. A capped source must not shrink the display.
        const image = root.frontIsA ? a : b
        const w = image.frameWidth || pixelWidth, h = image.frameHeight || pixelHeight
        const paintedW = image.paintedWidth || root.width, paintedH = image.paintedHeight || root.height
        const offsetX = (root.width-paintedW)/2, offsetY = (root.height-paintedH)/2
        if (kind === "press" && (x < offsetX || y < offsetY || x >= offsetX+paintedW || y >= offsetY+paintedH)) return
        const event = {kind: kind, x: Math.max(0, Math.min(w-1, Math.round((x-offsetX)*w/paintedW))),
            y: Math.max(0, Math.min(h-1, Math.round((y-offsetY)*h/paintedH))),
            w: w, h: h, shift: shift}
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
        id: pointer
        objectName: "wallpaperInput"
        // A wallpaper is below Folder View, which consumes blank-desktop clicks.
        // Lift only this transparent input area to the same desktop window's
        // content layer; the wallpaper image remains behind icons and widgets.
        parent: root.Window.window ? root.Window.window.contentItem : root.parent
        z: 10000
        property rect surfaceRect: parent ? root.mapToItem(parent,Qt.rect(0,0,root.width,root.height)) : Qt.rect(0,0,0,0)
        x: surfaceRect.x + (root.editing ? 0 : surfaceRect.width*.8)
        y: surfaceRect.y
        width: surfaceRect.width*(root.editing ? 1 : .2)
        height: surfaceRect.height
        visible: root.visible
        enabled: root.connected
        cursorShape: root.editing ? Qt.CrossCursor : Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton // Reserve right-click for the Plasma desktop menu.
        onPressed: function(mouse) {
            if (!root.connected) { mouse.accepted = false; return }
            const point = mapToItem(root,mouse.x,mouse.y)
            root.enqueue("press",point.x,point.y,!!(mouse.modifiers & Qt.ShiftModifier))
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                const point = mapToItem(root,mouse.x,mouse.y)
                root.enqueue("move",point.x,point.y,!!(mouse.modifiers & Qt.ShiftModifier))
            }
        }
        onReleased: function(mouse) {
            const point = mapToItem(root,mouse.x,mouse.y)
            root.enqueue("release",point.x,point.y,false)
        }
        onCanceled: root.enqueue("cancel",0,0,false)
        Timer {
            interval: 1000; repeat: true; running: parent.pressed
            onTriggered: {
                const point = pointer.mapToItem(root,pointer.mouseX,pointer.mouseY)
                root.enqueue("move",point.x,point.y,false)
            }
        }
    }
    Component.onDestruction: { pointer.enabled = false; pointer.visible = false; pointer.parent = null }
}

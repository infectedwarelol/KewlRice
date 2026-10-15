import QtQuick
import QtQuick.Controls.Basic
import QtMultimedia
import QtQml.Models
import QtQuick.Effects

Rectangle {
    id: root

    readonly property real scaleFactor: Math.min(width / 1920, height / 1080)
    property color textColor: "#2e1a47"
    property color mutedColor: "#6b5a85"
    property color accentColor: "#9b59ff"
    property color accentLightColor: "#d090ff"
    property color errorColor: "#d0457a"
    property color cardColor: Qt.rgba(248 / 255, 240 / 255, 255 / 255, 0.62)
    property string backgroundSource: "assets/background.png"
    property var swatchColors: ["#2e1a47", "#4b2d7f", "#6a45a8", "#7e4fd6", "#9b59ff", "#b277ff", "#d090ff", "#e4c4ff"]
    property var blobColors: []
    property color cardBorderColor: Qt.rgba(1, 1, 1, 0.45)
    property color frameColor: Qt.rgba(1, 1, 1, 0.16)
    property color frameBorderColor: Qt.rgba(1, 1, 1, 0.4)
    property color glassColor: Qt.rgba(1, 1, 1, 0.45)
    property color fieldColor: Qt.rgba(1, 1, 1, 0.6)
    readonly property string textFont: "Noto Sans"
    readonly property string iconFont: "JetBrainsMono Nerd Font"

    property string fallbackUserName: ""
    readonly property string userName: userModel.lastUser !== "" ? userModel.lastUser : fallbackUserName
    property var sessionNames: []
    property int sessionIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0

    property real cpuUsage: 0
    property real cpuTemperature: -1
    property real memoryUsage: 0
    property real headsetBattery: -1
    property string uptimeText: ""
    property string kernelVersion: ""
    property string hostName: ""
    property string temperaturePath: ""
    property string headsetBatteryPath: ""
    property int headsetScanCountdown: 0
    property string headsetName: ""
    property string osName: ""
    property string systemKeyboardLayout: ""
    property var capsLockLedPaths: []
    property bool capsLockLedOn: false
    readonly property bool capsLockOn: capsLockLedPaths.length > 0 ? capsLockLedOn : keyboard.capsLock
    property var previousCpuTimes: null

    property string weatherIcon: "\u{f0590}"
    property string weatherDescription: "Loading weather"
    property string weatherTemperature: ""
    property string weatherHumidity: ""
    property string weatherFeelsLike: ""
    property var forecast: []
    property bool passwordVisible: false
    property string networkIcon: "\u{f0318}"
    property string networkLabel: "Offline"
    readonly property string keyboardLayoutName: {
        try {
            const layout = keyboard.layouts ? keyboard.layouts[keyboard.currentLayout] : null
            if (layout && layout.shortName) {
                return layout.shortName.toUpperCase()
            }
        } catch (error) {
        }
        return systemKeyboardLayout
    }
    readonly property var tips: [
        "Tip: Super + Q opens a terminal",
        "Tip: Super + R opens the app launcher",
        "Tip: Super + A toggles the overview",
        "Tip: Alt + Tab cycles through your windows",
        "Tip: pacman -Qdt lists orphaned packages",
        "Tip: paccache -r keeps only the last 3 versions of each package",
        "Tip: journalctl -b -p err shows this boot's errors",
        "Tip: systemd-analyze blame shows what slows down your boot",
        "Tip: checkupdates shows pending updates without syncing the database",
        "Tip: read the Arch news before big updates",
        "Simplicity, modernity, pragmatism, user centrality, versatility"
    ]
    readonly property string tipOfTheDay: tips[Math.floor(Math.random() * tips.length)]
    readonly property string greeting: clockTimer.now.getHours() < 12 ? "Good morning" : (clockTimer.now.getHours() < 18 ? "Good afternoon" : "Good evening")

    property int soundIndex: 0
    property bool loginFailed: false
    property bool loginInProgress: false

    width: 1920
    height: 1080
    color: textColor

    function readFile(path) {
        const request = new XMLHttpRequest()
        try {
            request.open("GET", "file://" + path, false)
            request.send()
            return request.responseText || ""
        } catch (error) {
            return ""
        }
    }

    function loadTheme() {
        const text = readFile("/var/lib/kewlrice-sddm/theme.json")
        if (text.trim() === "") {
            return
        }
        try {
            const theme = JSON.parse(text)
            textColor = theme.text
            mutedColor = theme.muted
            accentColor = theme.accent
            accentLightColor = theme.accentLight
            errorColor = theme.error
            cardColor = theme.card
            cardBorderColor = theme.cardBorder
            frameColor = theme.frame
            frameBorderColor = theme.frameBorder
            glassColor = theme.glass
            fieldColor = theme.field
            swatchColors = theme.swatches
            blobColors = theme.blobs
            if (theme.background) {
                backgroundSource = "file://" + theme.background
            }
        } catch (error) {
        }
    }

    function findSensorPaths() {
        for (let index = 0; index < 16; index++) {
            const name = readFile("/sys/class/hwmon/hwmon" + index + "/name").trim()
            if (name === "coretemp" || name === "k10temp" || name === "zenpower") {
                temperaturePath = "/sys/class/hwmon/hwmon" + index + "/temp1_input"
                break
            }
        }
        const ledPaths = []
        for (let index = 0; index < 64; index++) {
            const path = "/sys/class/leds/input" + index + "::capslock/brightness"
            if (readFile(path).trim() !== "") {
                ledPaths.push(path)
            }
        }
        capsLockLedPaths = ledPaths
    }

    function findHeadsetBattery() {
        for (let index = 0; index < 8; index++) {
            const directory = "/sys/class/power_supply/hidpp_battery_" + index
            if (readFile(directory + "/capacity").trim() !== "") {
                headsetBatteryPath = directory + "/capacity"
                headsetName = readFile(directory + "/model_name").trim()
                return
            }
        }
        headsetBatteryPath = ""
        headsetName = ""
    }

    function readSystemInfo() {
        kernelVersion = readFile("/proc/sys/kernel/osrelease").trim()
        hostName = readFile("/proc/sys/kernel/hostname").trim()

        const prettyName = readFile("/etc/os-release").match(/^PRETTY_NAME="?([^"\n]*)"?/m)
        osName = prettyName ? prettyName[1] : "Linux"

        const xkbLayout = readFile("/etc/X11/xorg.conf.d/00-keyboard.conf").match(/Option\s+"XkbLayout"\s+"([^"]+)"/)
        const consoleKeymap = readFile("/etc/vconsole.conf").match(/^KEYMAP=("?)([^"\n]+)\1/m)
        const layout = xkbLayout ? xkbLayout[1].split(",")[0] : (consoleKeymap ? consoleKeymap[2].split("-")[0] : "")
        systemKeyboardLayout = layout.trim().toUpperCase()
    }

    function refreshCapsLock() {
        capsLockLedOn = capsLockLedPaths.some(path => Number(readFile(path).trim()) > 0)
    }

    function refreshStats() {
        const cpuFields = readFile("/proc/stat").split("\n")[0].trim().split(/\s+/).slice(1).map(Number)
        if (cpuFields.length >= 4) {
            const idle = cpuFields[3] + (cpuFields[4] || 0)
            const total = cpuFields.reduce((sum, value) => sum + value, 0)
            if (previousCpuTimes !== null && total > previousCpuTimes.total) {
                cpuUsage = 1 - (idle - previousCpuTimes.idle) / (total - previousCpuTimes.total)
            }
            previousCpuTimes = { idle: idle, total: total }
        }

        const memoryInfo = readFile("/proc/meminfo")
        const totalMatch = memoryInfo.match(/MemTotal:\s+(\d+)/)
        const availableMatch = memoryInfo.match(/MemAvailable:\s+(\d+)/)
        if (totalMatch && availableMatch) {
            memoryUsage = 1 - Number(availableMatch[1]) / Number(totalMatch[1])
        }

        const temperatureText = temperaturePath !== "" ? readFile(temperaturePath).trim() : ""
        cpuTemperature = temperatureText !== "" ? Number(temperatureText) / 1000 : -1

        let batteryText = headsetBatteryPath !== "" ? readFile(headsetBatteryPath).trim() : ""
        if (batteryText === "") {
            if (headsetScanCountdown <= 0) {
                findHeadsetBattery()
                headsetScanCountdown = 15
                batteryText = headsetBatteryPath !== "" ? readFile(headsetBatteryPath).trim() : ""
            } else {
                headsetScanCountdown--
            }
        }
        headsetBattery = batteryText !== "" ? Number(batteryText) : -1

        const uptimeSeconds = Math.floor(Number(readFile("/proc/uptime").split(" ")[0]) || 0)
        const hours = Math.floor(uptimeSeconds / 3600)
        const minutes = Math.floor((uptimeSeconds % 3600) / 60)
        refreshNetwork()
        uptimeText = (hours > 0 ? hours + (hours === 1 ? " hour, " : " hours, ") : "") + minutes + (minutes === 1 ? " minute" : " minutes")
    }

    function refreshNetwork() {
        const wireless = readFile("/proc/net/wireless")
        const interfaces = readFile("/proc/net/dev").split("\n").slice(2)
            .map(line => line.split(":")[0].trim())
            .filter(name => name !== "" && name !== "lo" && !/^(docker|veth|br-|virbr|tun|tap)/.test(name))
        for (const name of interfaces) {
            if (readFile("/sys/class/net/" + name + "/operstate").trim() === "up") {
                const isWireless = wireless.indexOf(name + ":") !== -1
                networkIcon = isWireless ? "\u{f05a9}" : "\u{f0200}"
                networkLabel = isWireless ? "Wi-Fi" : "Ethernet"
                return
            }
        }
        networkIcon = "\u{f0318}"
        networkLabel = "Offline"
    }

    function weatherIconForCode(code) {
        if (code === 113) return "\u{f0599}"
        if (code === 116) return "\u{f0595}"
        if ([119, 122].includes(code)) return "\u{f0590}"
        if ([143, 248, 260].includes(code)) return "\u{f0591}"
        if ([200, 386, 389, 392, 395].includes(code)) return "\u{f0593}"
        if ([179, 182, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377].includes(code)) return "\u{f0598}"
        return "\u{f0597}"
    }

    function refreshWeather() {
        const request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            try {
                const weather = JSON.parse(request.responseText)
                const current = weather.current_condition[0]
                weatherIcon = weatherIconForCode(Number(current.weatherCode))
                weatherDescription = current.weatherDesc[0].value
                weatherTemperature = current.temp_C + "°C"
                weatherHumidity = "Humidity: " + current.humidity + "%"
                weatherFeelsLike = "Feels like: " + current.FeelsLikeC + "°C"
                forecast = weather.weather.slice(0, 3).map(day => ({ name: Qt.formatDate(new Date(day.date + "T12:00:00"), "dddd"), high: day.maxtempC, low: day.mintempC, icon: weatherIconForCode(Number(day.hourly[4].weatherCode)) }))
            } catch (error) {
                weatherIcon = "\u{f0590}"
                weatherDescription = "Weather unavailable"
                weatherTemperature = ""
                weatherHumidity = ""
                weatherFeelsLike = ""
            }
        }
        const location = readFile(Qt.resolvedUrl("weather-location").toString().replace("file://", "")).trim().replace(/\s+/g, "+")
        request.open("GET", "https://wttr.in/" + location + "?format=j1")
        request.send()
    }

    function playTypingSound(isBackspace) {
        const pool = isBackspace ? backspaceSounds : keySounds
        const effect = pool.objectAt(soundIndex % pool.count)
        soundIndex++
        if (effect) {
            effect.play()
        }
    }

    function attemptLogin() {
        if (loginInProgress || passwordField.text === "" || userName === "") return
        loginInProgress = true
        loginFailed = false
        sddm.login(userName, passwordField.text, sessionIndex)
    }

    component Card: Rectangle {
        color: root.cardColor
        radius: 12 * root.scaleFactor
        border.color: root.cardBorderColor
        border.width: 1
    }

    component Gauge: Item {
        id: gauge

        property real value: 0
        property bool available: true
        property string icon: ""
        property string label: ""
        property string valueText: ""

        Canvas {
            id: gaugeCanvas
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -12 * root.scaleFactor
            width: Math.min(parent.width, parent.height) * 0.72
            height: width
            antialiasing: true

            onPaint: {
                const context = getContext("2d")
                const lineWidth = 7 * root.scaleFactor
                const radius = width / 2 - lineWidth
                const startAngle = Math.PI * 0.75
                const sweep = Math.PI * 1.5
                context.reset()
                context.lineCap = "round"
                context.lineWidth = lineWidth
                context.strokeStyle = Qt.rgba(root.textColor.r, root.textColor.g, root.textColor.b, 0.12)
                context.beginPath()
                context.arc(width / 2, height / 2, radius, startAngle, startAngle + sweep)
                context.stroke()
                if (gauge.available && gauge.value > 0) {
                    context.strokeStyle = root.accentColor
                    context.beginPath()
                    context.arc(width / 2, height / 2, radius, startAngle, startAngle + sweep * Math.min(1, gauge.value))
                    context.stroke()
                }
            }

            Connections {
                target: gauge
                function onValueChanged() { gaugeCanvas.requestPaint() }
                function onAvailableChanged() { gaugeCanvas.requestPaint() }
            }
        }

        Text {
            anchors.centerIn: gaugeCanvas
            anchors.verticalCenterOffset: -8 * root.scaleFactor
            text: gauge.icon
            color: root.textColor
            font.family: root.iconFont
            font.pixelSize: 44 * root.scaleFactor
        }

        Text {
            anchors.horizontalCenter: gaugeCanvas.horizontalCenter
            anchors.bottom: gaugeCanvas.bottom
            anchors.bottomMargin: gaugeCanvas.height * 0.12
            text: gauge.available ? gauge.valueText : "--"
            color: root.textColor
            font.family: root.textFont
            font.pixelSize: 17 * root.scaleFactor
            font.bold: true
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10 * root.scaleFactor
            text: gauge.label
            color: root.mutedColor
            font.family: root.textFont
            font.pixelSize: 14 * root.scaleFactor
        }
    }

    component PowerButton: Rectangle {
        id: powerButton

        property string icon: ""
        property string label: ""
        signal clicked

        radius: 10 * root.scaleFactor
        color: buttonArea.containsMouse ? Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.25) : root.glassColor
        border.color: root.cardBorderColor
        border.width: 1

        Behavior on color { ColorAnimation { duration: 120 } }

        Column {
            anchors.centerIn: parent
            spacing: 4 * root.scaleFactor

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: powerButton.icon
                color: root.textColor
                font.family: root.iconFont
                font.pixelSize: 26 * root.scaleFactor
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: powerButton.label
                color: root.mutedColor
                font.family: root.textFont
                font.pixelSize: 13 * root.scaleFactor
            }
        }

        MouseArea {
            id: buttonArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: powerButton.clicked()
        }
    }

    Repeater {
        model: userModel
        delegate: Item {
            Component.onCompleted: {
                if (index === 0 && root.fallbackUserName === "") {
                    root.fallbackUserName = model.name
                }
            }
        }
    }

    Repeater {
        model: sessionModel
        delegate: Item {
            Component.onCompleted: {
                const names = root.sessionNames.slice()
                names[index] = model.name
                root.sessionNames = names
            }
        }
    }

    Instantiator {
        id: keySounds
        model: 6
        delegate: SoundEffect {
            source: Qt.resolvedUrl("assets/key.wav")
        }
    }

    Instantiator {
        id: backspaceSounds
        model: 6
        delegate: SoundEffect {
            source: Qt.resolvedUrl("assets/backspace.wav")
        }
    }

    Connections {
        target: sddm
        function onLoginSucceeded() {
            loginAnimation.start()
        }

        function onLoginFailed() {
            root.loginInProgress = false
            root.loginFailed = true
            passwordField.text = ""
            passwordField.forceActiveFocus()
            shakeAnimation.restart()
        }
    }

    Timer {
        interval: 200
        running: root.capsLockLedPaths.length > 0
        repeat: true
        onTriggered: root.refreshCapsLock()
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refreshStats()
    }

    Timer {
        interval: 1800000
        running: true
        repeat: true
        onTriggered: root.refreshWeather()
    }

    Timer {
        id: clockTimer
        property date now: new Date()
        interval: 1000
        running: true
        repeat: true
        onTriggered: now = new Date()
    }

    Component.onCompleted: {
        loadTheme()
        readSystemInfo()
        findSensorPaths()
        refreshCapsLock()
        refreshStats()
        refreshWeather()
        passwordField.forceActiveFocus()
    }

    Image {
        anchors.fill: parent
        source: root.backgroundSource
        fillMode: Image.PreserveAspectCrop
        smooth: true
    }

    Item {
        id: blobLayer
        anchors.fill: parent

        Repeater {
            model: [
                { source: "assets/blob-purple.png", size: 0.55, startX: 0.05, startY: 0.10, endX: 0.45, endY: 0.45, duration: 26000 },
                { source: "assets/blob-pink.png", size: 0.45, startX: 0.60, startY: 0.55, endX: 0.25, endY: 0.15, duration: 31000 },
                { source: "assets/blob-blue.png", size: 0.40, startX: 0.70, startY: 0.05, endX: 0.50, endY: 0.60, duration: 37000 }
            ]

            delegate: Image {
                id: blob
                required property var modelData
                required property int index
                readonly property bool tinted: root.blobColors.length > index
                source: modelData.source
                layer.enabled: tinted
                layer.effect: MultiEffect {
                    colorization: 1.0
                    colorizationColor: blob.tinted ? root.blobColors[blob.index] : "white"
                }
                width: blobLayer.width * modelData.size
                height: width
                opacity: 0.45
                smooth: true

                SequentialAnimation on x {
                    loops: Animation.Infinite
                    NumberAnimation { from: blobLayer.width * blob.modelData.startX; to: blobLayer.width * blob.modelData.endX; duration: blob.modelData.duration; easing.type: Easing.InOutSine }
                    NumberAnimation { from: blobLayer.width * blob.modelData.endX; to: blobLayer.width * blob.modelData.startX; duration: blob.modelData.duration; easing.type: Easing.InOutSine }
                }

                SequentialAnimation on y {
                    loops: Animation.Infinite
                    NumberAnimation { from: blobLayer.height * blob.modelData.startY; to: blobLayer.height * blob.modelData.endY; duration: blob.modelData.duration * 0.8; easing.type: Easing.InOutSine }
                    NumberAnimation { from: blobLayer.height * blob.modelData.endY; to: blobLayer.height * blob.modelData.startY; duration: blob.modelData.duration * 0.8; easing.type: Easing.InOutSine }
                }
            }
        }
    }

    ParallelAnimation {
        id: loginAnimation
        NumberAnimation { target: frame; property: "opacity"; to: 0; duration: 450; easing.type: Easing.InCubic }
        NumberAnimation { target: frame; property: "scale"; to: 1.08; duration: 450; easing.type: Easing.InCubic }
        NumberAnimation { target: tipText; property: "opacity"; to: 0; duration: 300 }
    }

    Text {
        id: tipText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: parent.height * 0.028
        text: root.tipOfTheDay
        color: root.textColor
        opacity: 0.75
        font.family: root.textFont
        font.pixelSize: 16 * root.scaleFactor
        font.italic: true
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.leftMargin: parent.width * 0.055
        anchors.rightMargin: parent.width * 0.055
        anchors.topMargin: parent.height * 0.06
        anchors.bottomMargin: parent.height * 0.08
        radius: 16 * root.scaleFactor
        color: root.frameColor
        border.color: root.frameBorderColor
        border.width: 1

        readonly property real gap: 10 * root.scaleFactor
        readonly property real sideWidth: (width - gap * 4) * 0.29

        Column {
            id: leftColumn
            x: frame.gap
            y: frame.gap
            width: frame.sideWidth
            height: frame.height - frame.gap * 2
            spacing: frame.gap

            Card {
                id: weatherCard
                width: parent.width
                height: parent.height * 0.40

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 16 * root.scaleFactor
                    text: "Weather"
                    color: root.textColor
                    font.family: root.textFont
                    font.pixelSize: 26 * root.scaleFactor
                }

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 22 * root.scaleFactor
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -45 * root.scaleFactor
                    spacing: 14 * root.scaleFactor

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.weatherIcon
                        color: root.accentColor
                        font.family: root.iconFont
                        font.pixelSize: 64 * root.scaleFactor
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            text: root.weatherDescription
                            color: root.textColor
                            font.family: root.textFont
                            font.pixelSize: 20 * root.scaleFactor
                        }

                        Text {
                            text: root.weatherHumidity
                            visible: text !== ""
                            color: root.mutedColor
                            font.family: root.textFont
                            font.pixelSize: 14 * root.scaleFactor
                        }
                    }
                }

                Column {
                    anchors.right: parent.right
                    anchors.rightMargin: 22 * root.scaleFactor
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -45 * root.scaleFactor

                    Text {
                        anchors.right: parent.right
                        text: root.weatherTemperature
                        color: root.textColor
                        font.family: root.textFont
                        font.pixelSize: 36 * root.scaleFactor
                    }

                    Text {
                        anchors.right: parent.right
                        text: root.weatherFeelsLike
                        visible: text !== ""
                        color: root.mutedColor
                        font.family: root.textFont
                        font.pixelSize: 13 * root.scaleFactor
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 16 * root.scaleFactor
                    spacing: 10 * root.scaleFactor

                    Repeater {
                        model: root.forecast
                        delegate: Rectangle {
                            required property var modelData
                            width: 150 * root.scaleFactor
                            height: 118 * root.scaleFactor
                            radius: 10 * root.scaleFactor
                            color: root.glassColor
                            border.color: root.cardBorderColor

                            Column {
                                anchors.centerIn: parent
                                spacing: 2 * root.scaleFactor
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.name; color: root.mutedColor; font.family: root.textFont; font.pixelSize: 14 * root.scaleFactor }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.icon; color: root.accentColor; font.family: root.iconFont; font.pixelSize: 36 * root.scaleFactor }
                                Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.high + "° / " + modelData.low + "°"; color: root.textColor; font.family: root.textFont; font.pixelSize: 15 * root.scaleFactor; font.bold: true }
                            }
                        }
                    }
                }
            }

            Card {
                width: parent.width
                height: parent.height - weatherCard.height - parent.spacing

                Row {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 20 * root.scaleFactor
                    spacing: 8 * root.scaleFactor

                    Rectangle {
                        width: 24 * root.scaleFactor
                        height: width
                        radius: 4 * root.scaleFactor
                        color: root.textColor

                        Text {
                            anchors.centerIn: parent
                            text: ">"
                            color: "white"
                            font.family: root.iconFont
                            font.pixelSize: 14 * root.scaleFactor
                            font.bold: true
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "fastfetch"
                        color: root.textColor
                        font.family: root.iconFont
                        font.pixelSize: 16 * root.scaleFactor
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 60 * root.scaleFactor
                    spacing: 30 * root.scaleFactor

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: ""
                        color: root.accentColor
                        font.family: root.iconFont
                        font.pixelSize: 80 * root.scaleFactor
                    }

                    Grid {
                        anchors.verticalCenter: parent.verticalCenter
                        columns: 2
                        columnSpacing: 10 * root.scaleFactor
                        rowSpacing: 6 * root.scaleFactor

                        Repeater {
                            model: [
                                "OS", root.osName,
                                "WM", root.sessionNames[root.sessionIndex] || "",
                                "USER", root.userName,
                                "HOST", root.hostName,
                                "KERNEL", root.kernelVersion,
                                "UP", root.uptimeText
                            ]

                            delegate: Text {
                                required property string modelData
                                required property int index
                                text: modelData
                                color: index % 2 === 0 ? root.accentColor : root.textColor
                                font.family: root.iconFont
                                font.pixelSize: 16 * root.scaleFactor
                                font.bold: index % 2 === 0
                            }
                        }
                    }
                }

                Column {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 70 * root.scaleFactor
                    spacing: 6 * root.scaleFactor

                    readonly property date today: clockTimer.now
                    readonly property int firstWeekday: (new Date(today.getFullYear(), today.getMonth(), 1).getDay() + 6) % 7
                    readonly property int dayCount: new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Qt.formatDate(parent.today, "MMMM yyyy")
                        color: root.textColor
                        font.family: root.textFont
                        font.pixelSize: 15 * root.scaleFactor
                        font.bold: true
                    }

                    Grid {
                        id: calendarGrid
                        columns: 7
                        spacing: 4 * root.scaleFactor
                        readonly property var calendarColumn: parent

                        Repeater {
                            model: 7 + 42
                            delegate: Rectangle {
                                required property int index
                                readonly property int dayNumber: index - 7 - calendarGrid.calendarColumn.firstWeekday + 1
                                readonly property bool isHeader: index < 7
                                readonly property bool isToday: dayNumber === calendarGrid.calendarColumn.today.getDate()
                                width: 30 * root.scaleFactor
                                height: 24 * root.scaleFactor
                                radius: 6 * root.scaleFactor
                                visible: isHeader || (dayNumber >= 1 && dayNumber <= calendarGrid.calendarColumn.dayCount) || index < 7 + 35
                                color: isToday && !isHeader ? root.accentColor : "transparent"

                                Text {
                                    anchors.centerIn: parent
                                    text: parent.isHeader ? ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"][parent.index] : (parent.dayNumber >= 1 && parent.dayNumber <= calendarGrid.calendarColumn.dayCount ? parent.dayNumber : "")
                                    color: parent.isHeader ? root.accentColor : (parent.isToday ? "white" : root.textColor)
                                    font.family: root.textFont
                                    font.pixelSize: 12 * root.scaleFactor
                                    font.bold: parent.isHeader || parent.isToday
                                }
                            }
                        }
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 22 * root.scaleFactor
                    spacing: 6 * root.scaleFactor

                    Repeater {
                        model: root.swatchColors
                        delegate: Rectangle {
                            required property string modelData
                            width: 22 * root.scaleFactor
                            height: width
                            radius: 3 * root.scaleFactor
                            color: modelData
                        }
                    }
                }
            }
        }

        Item {
            id: centerColumn
            anchors.left: leftColumn.right
            anchors.right: rightColumn.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: frame.gap
            anchors.rightMargin: frame.gap

            Column {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -10 * root.scaleFactor
                spacing: 18 * root.scaleFactor

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.greeting + ", " + root.userName
                    color: root.accentColor
                    font.family: root.textFont
                    font.pixelSize: 24 * root.scaleFactor
                    font.bold: true
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatTime(clockTimer.now, "hh:mm")
                    color: root.textColor
                    font.family: root.iconFont
                    font.pixelSize: 110 * root.scaleFactor
                    font.weight: Font.ExtraBold
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatDate(clockTimer.now, "dddd, d MMMM yyyy")
                    color: root.mutedColor
                    font.family: root.textFont
                    font.pixelSize: 26 * root.scaleFactor
                    font.bold: true
                }

                Item {
                    width: 1
                    height: 8 * root.scaleFactor
                }

                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 200 * root.scaleFactor
                    height: width
                    source: "assets/avatar.png"
                    sourceSize.width: 460
                    sourceSize.height: 460
                    smooth: true
                    mipmap: true
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.userName
                    color: root.textColor
                    font.family: root.textFont
                    font.pixelSize: 22 * root.scaleFactor
                    font.bold: true
                }

                Item {
                    id: passwordRow
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 340 * root.scaleFactor
                    height: 42 * root.scaleFactor

                    SequentialAnimation {
                        id: shakeAnimation
                        loops: 2
                        NumberAnimation { target: passwordRow; property: "anchors.horizontalCenterOffset"; to: -10 * root.scaleFactor; duration: 50 }
                        NumberAnimation { target: passwordRow; property: "anchors.horizontalCenterOffset"; to: 10 * root.scaleFactor; duration: 50 }
                        NumberAnimation { target: passwordRow; property: "anchors.horizontalCenterOffset"; to: 0; duration: 50 }
                    }

                    TextField {
                        id: passwordField
                        anchors.fill: parent
                        echoMode: root.passwordVisible ? TextInput.Normal : TextInput.Password
                        passwordCharacter: "•"
                        leftPadding: 42 * root.scaleFactor
                        rightPadding: 76 * root.scaleFactor
                        horizontalAlignment: TextInput.AlignHCenter
                        verticalAlignment: TextInput.AlignVCenter
                        color: root.textColor
                        selectionColor: root.accentLightColor
                        placeholderText: "Enter your password"
                        placeholderTextColor: root.mutedColor
                        font.family: root.textFont
                        font.pixelSize: 15 * root.scaleFactor

                        background: Rectangle {
                            radius: height / 2
                            color: root.fieldColor
                            border.color: root.loginFailed ? root.errorColor : (passwordField.activeFocus ? root.accentColor : root.cardBorderColor)
                            border.width: passwordField.activeFocus || root.loginFailed ? 2 : 1
                        }

                        Keys.onPressed: event => {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                event.accepted = true
                                if (!event.isAutoRepeat) {
                                    root.attemptLogin()
                                }
                            } else if (event.key === Qt.Key_Backspace) {
                                root.playTypingSound(true)
                            } else if (event.text.length > 0 && event.text.charCodeAt(0) >= 32 && event.text.charCodeAt(0) !== 127) {
                                root.playTypingSound(false)
                            }
                        }

                        onActiveFocusChanged: {
                            if (!activeFocus) {
                                Qt.callLater(forceActiveFocus)
                            }
                        }
                        onTextEdited: root.loginFailed = false
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 16 * root.scaleFactor
                        anchors.verticalCenter: parent.verticalCenter
                        text: ""
                        color: root.mutedColor
                        font.family: root.iconFont
                        font.pixelSize: 16 * root.scaleFactor
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 46 * root.scaleFactor
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.passwordVisible ? "\uf070" : "\uf06e"
                        color: root.mutedColor
                        font.family: root.iconFont
                        font.pixelSize: 16 * root.scaleFactor

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -6
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.passwordVisible = !root.passwordVisible
                        }
                    }

                    Rectangle {
                        anchors.right: parent.right
                        anchors.rightMargin: 5 * root.scaleFactor
                        anchors.verticalCenter: parent.verticalCenter
                        width: 32 * root.scaleFactor
                        height: width
                        radius: width / 2
                        color: submitArea.containsMouse ? root.accentLightColor : root.accentColor

                        Text {
                            anchors.centerIn: parent
                            text: ""
                            color: "white"
                            font.family: root.iconFont
                            font.pixelSize: 15 * root.scaleFactor
                        }

                        MouseArea {
                            id: submitArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.attemptLogin()
                        }
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.loginFailed ? "Wrong password" : " "
                    color: root.loginFailed ? root.errorColor : root.mutedColor
                    font.family: root.textFont
                    font.pixelSize: 14 * root.scaleFactor
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8 * root.scaleFactor

                    Repeater {
                        model: [
                            { label: root.networkIcon + "  " + root.networkLabel, active: false },
                            { label: "\uf11c  " + root.keyboardLayoutName, active: false },
                            { label: "\u{f0632}  " + (root.capsLockOn ? "Caps on" : "Caps off"), active: root.capsLockOn }
                        ].filter(chip => !chip.label.endsWith("  "))
                        delegate: Rectangle {
                            required property var modelData
                            width: chipText.implicitWidth + 24 * root.scaleFactor
                            height: 28 * root.scaleFactor
                            radius: height / 2
                            color: modelData.active ? root.accentColor : root.glassColor
                            border.color: root.cardBorderColor

                            Text {
                                id: chipText
                                anchors.centerIn: parent
                                text: modelData.label
                                color: modelData.active ? "white" : root.textColor
                                font.family: root.iconFont
                                font.pixelSize: 13 * root.scaleFactor
                            }
                        }
                    }
                }
            }
        }

        Column {
            id: rightColumn
            x: frame.width - frame.gap - width
            y: frame.gap
            width: frame.sideWidth
            height: frame.height - frame.gap * 2
            spacing: frame.gap

            Card {
                id: statsCard
                width: parent.width
                height: parent.height * 0.66

                Grid {
                    anchors.fill: parent
                    anchors.margins: frame.gap
                    columns: 2
                    spacing: frame.gap

                    readonly property real cellWidth: (width - spacing) / 2
                    readonly property real cellHeight: (height - spacing) / 2

                    Gauge {
                        width: parent.cellWidth
                        height: parent.cellHeight
                        icon: ""
                        label: "CPU"
                        value: root.cpuUsage
                        valueText: Math.round(root.cpuUsage * 100) + "%"
                    }

                    Gauge {
                        width: parent.cellWidth
                        height: parent.cellHeight
                        icon: ""
                        label: "Temperature"
                        available: root.cpuTemperature >= 0
                        value: root.cpuTemperature / 100
                        valueText: Math.round(root.cpuTemperature) + "°C"
                    }

                    Gauge {
                        width: parent.cellWidth
                        height: parent.cellHeight
                        icon: "\uefc5"
                        label: "Memory"
                        value: root.memoryUsage
                        valueText: Math.round(root.memoryUsage * 100) + "%"
                    }

                    Gauge {
                        width: parent.cellWidth
                        height: parent.cellHeight
                        icon: "\u{f0079}"
                        label: root.headsetName !== "" ? root.headsetName : "Battery"
                        available: root.headsetBattery >= 0
                        value: root.headsetBattery / 100
                        valueText: Math.round(root.headsetBattery) + "%"
                    }
                }
            }

            Card {
                width: parent.width
                height: parent.height - statsCard.height - parent.spacing

                Column {
                    anchors.fill: parent
                    anchors.margins: 16 * root.scaleFactor
                    spacing: 12 * root.scaleFactor

                    Text {
                        text: "Session"
                        color: root.mutedColor
                        font.family: root.textFont
                        font.pixelSize: 13 * root.scaleFactor
                    }

                    Rectangle {
                        width: parent.width
                        height: 40 * root.scaleFactor
                        radius: 10 * root.scaleFactor
                        color: root.glassColor
                        border.color: root.cardBorderColor
                        border.width: 1

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 14 * root.scaleFactor
                            anchors.verticalCenter: parent.verticalCenter
                            text: ""
                            color: root.accentColor
                            font.family: root.iconFont
                            font.pixelSize: 16 * root.scaleFactor
                        }

                        Text {
                            anchors.centerIn: parent
                            text: root.sessionNames[root.sessionIndex] || "Default"
                            color: root.textColor
                            font.family: root.textFont
                            font.pixelSize: 16 * root.scaleFactor
                            font.bold: true
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 14 * root.scaleFactor
                            anchors.verticalCenter: parent.verticalCenter
                            text: ""
                            color: root.accentColor
                            font.family: root.iconFont
                            font.pixelSize: 16 * root.scaleFactor
                        }

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: mouse => {
                                const count = Math.max(1, sessionModel.rowCount())
                                const step = mouse.button === Qt.RightButton || mouse.x < width / 2 ? -1 : 1
                                root.sessionIndex = (root.sessionIndex + step + count) % count
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        height: parent.height - y
                        spacing: 10 * root.scaleFactor

                        readonly property int buttonCount: sddm.canSuspend ? 3 : 2
                        readonly property real buttonWidth: (width - spacing * (buttonCount - 1)) / buttonCount

                        PowerButton {
                            width: parent.buttonWidth
                            height: parent.height
                            icon: "\u{f0904}"
                            label: "Suspend"
                            visible: sddm.canSuspend
                            onClicked: sddm.suspend()
                        }

                        PowerButton {
                            width: parent.buttonWidth
                            height: parent.height
                            icon: "\u{f0709}"
                            label: "Restart"
                            onClicked: sddm.reboot()
                        }

                        PowerButton {
                            width: parent.buttonWidth
                            height: parent.height
                            icon: ""
                            label: "Shut down"
                            onClicked: sddm.powerOff()
                        }
                    }
                }
            }
        }
    }
}

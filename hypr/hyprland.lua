hl.monitor({
    output   = "DP-1",
    mode     = "1920x1080@180",
    position = "auto",
    scale    = 1,
})

local terminal    = "kitty"
local fileManager = "dolphin"
local menu = "wofi --show drun"

hl.on("hyprland.start", function ()
    hl.exec_cmd("waybar")
    hl.exec_cmd("mako")
    hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
    hl.exec_cmd("swaybg -i " .. os.getenv("HOME") .. "/.config/hypr/wallpapers/spirited-away-chihiro.png -m fill")
end)

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORMTHEME", "kde")

hl.config({
    general = {
        gaps_in  = 5,
        gaps_out = 20,

        border_size = 2,

        col = {
            active_border   = { colors = {"rgba(33ccffee)", "rgba(00ff99ee)"}, angle = 45 },
            inactive_border = "rgba(595959aa)",
        },

        resize_on_border = false,

        allow_tearing = false,

        layout = "dwindle",
    },

    decoration = {
        rounding       = 10,
        rounding_power = 2,

        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        shadow = {
            enabled      = true,
            range        = 4,
            render_power = 3,
            color        = 0xee1a1a1a,
        },

        blur = {
            enabled   = true,
            size      = 1,
            passes    = 3,
            vibrancy  = 0.1696,
        },
    },

    animations = {
        enabled = true,
    },
})

hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1}    } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1}    } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}       } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1}    } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}     } })

hl.curve("easy",           { type = "spring", mass = 1, stiffness = 238.1191, dampening = 24.21279333 })

hl.animation({ leaf = "global",        enabled = true,  speed = 10,   bezier = "default" })
hl.animation({ leaf = "border",        enabled = true,  speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows",       enabled = true,  speed = 4.79, spring = "easy" })
hl.animation({ leaf = "windowsIn",     enabled = true,  speed = 4.1,  spring = "easy",         style = "popin 87%" })
hl.animation({ leaf = "windowsOut",    enabled = true,  speed = 1.49, bezier = "linear",       style = "popin 87%" })
hl.animation({ leaf = "fadeIn",        enabled = true,  speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut",       enabled = true,  speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade",          enabled = true,  speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers",        enabled = true,  speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn",      enabled = true,  speed = 4,    bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut",     enabled = true,  speed = 1.5,  bezier = "linear",       style = "fade" })
hl.animation({ leaf = "fadeLayersIn",  enabled = true,  speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true,  speed = 1.39, bezier = "almostLinear" })
hl.animation({ leaf = "workspaces",    enabled = true,  speed = 1.94, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesIn",  enabled = true,  speed = 1.21, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesOut", enabled = true,  speed = 1.94, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "zoomFactor",    enabled = true,  speed = 7,    bezier = "quick" })

hl.config({
    dwindle = {
        preserve_split = true,
    },
})

hl.config({
    master = {
        new_status = "master",
    },
})

hl.config({
    scrolling = {
        fullscreen_on_one_column = true,
    },
})

hl.config({
    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
        vrr                     = 1,  -- adaptive sync always on (DP-1: 48-180 Hz)
    },
})

hl.config({
    input = {
        kb_layout  = "fr",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        follow_mouse = 1,

        sensitivity = 0,

        touchpad = {
            natural_scroll = false,
        },
    },
})

hl.gesture({
    fingers = 3,
    direction = "horizontal",
    action = "workspace"
})

hl.device({
    name        = "epic-mouse-v1",
    sensitivity = -0.5,
})

local mainMod = "SUPER"

hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal))
local closeWindowBind = hl.bind(mainMod .. " + C", hl.dsp.window.close())
hl.bind("ALT + F4", hl.dsp.window.close())
hl.bind(mainMod .. " + M", hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(menu))
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo())
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"))
hl.bind(mainMod .. " + F", hl.dsp.window.fullscreen())
hl.bind(mainMod .. " + N",         hl.dsp.window.move({ workspace = "special:minimized", follow = false }))
hl.bind(mainMod .. " + SHIFT + N", hl.dsp.workspace.toggle_special("minimized"))

hl.bind("F11", hl.dsp.window.fullscreen())

local showDesktopState = nil
function ShowDesktopToggle()
    local hidden = hl.get_windows({ workspace = "special:desktop" })
    if #hidden > 0 then
        local target = (showDesktopState and showDesktopState.workspace) or hl.get_active_workspace().name
        for _, w in ipairs(hidden) do
            hl.dispatch(hl.dsp.window.move({ workspace = target, window = "address:" .. w.address, follow = false }))
        end
        if showDesktopState and showDesktopState.focused then
            hl.dispatch(hl.dsp.focus({ window = "address:" .. showDesktopState.focused }))
        end
        showDesktopState = nil
    else
        local ws = hl.get_active_workspace()
        if not ws then return end
        local active = hl.get_active_window()
        showDesktopState = { workspace = ws.name, focused = active and active.address }
        for _, w in ipairs(ws:get_windows()) do
            hl.dispatch(hl.dsp.window.move({ workspace = "special:desktop", window = "address:" .. w.address, follow = false }))
        end
    end
end
hl.bind(mainMod .. " + D", ShowDesktopToggle)

local overviewState = nil
local overviewClickBind = nil
local overviewEscapeBind = nil
local overviewGap = 20

local function overviewGeometry(address)
    for _, w in ipairs(hl.get_windows()) do
        if w.address == address then
            return { x = w.at.x, y = w.at.y, w = w.size.x, h = w.size.y, floating = w.floating }
        end
    end
    return nil
end

local function overviewMoved(a, b)
    if not a or not b then
        return false
    end
    return math.abs(a.x - b.x) > 3 or math.abs(a.y - b.y) > 3 or math.abs(a.w - b.w) > 3 or math.abs(a.h - b.h) > 3
end

local function overviewPlace(address, g)
    local target = "address:" .. address
    hl.dispatch(hl.dsp.window.resize({ x = math.floor(g.w), y = math.floor(g.h), window = target }))
    hl.dispatch(hl.dsp.window.move({ x = math.floor(g.x), y = math.floor(g.y), window = target }))
end

local function overviewSpread(total, sizes, gap)
    local used = 0
    for _, size in ipairs(sizes) do
        used = used + size
    end
    local spacing = gap
    if #sizes > 1 then
        spacing = math.min(gap, (total - used) / (#sizes - 1))
    end
    local start = math.max(0, (total - used - spacing * (#sizes - 1)) / 2)
    return start, spacing
end

local function overviewPack(windows, area, scale)
    local rowList, heights, width = {}, {}, 0
    for _, w in ipairs(windows) do
        local size = w.fixed and w.actual or { w = math.floor(w.actual.w * scale), h = math.floor(w.actual.h * scale) }
        w.target = size
        local row = rowList[#rowList]
        if not row or width + overviewGap + size.w > area.w then
            row = {}
            table.insert(rowList, row)
            table.insert(heights, 0)
            width = -overviewGap
        end
        table.insert(row, w)
        width = width + overviewGap + size.w
        heights[#heights] = math.max(heights[#heights], size.h)
    end
    local total = (#heights - 1) * overviewGap
    for _, height in ipairs(heights) do
        total = total + height
    end
    return rowList, heights, total <= area.h
end

function OverviewArrange()
    local state = overviewState
    if not state then
        return
    end
    local area = state.area
    local placed = {}
    for i, w in ipairs(state.windows) do
        local g = overviewGeometry(w.address)
        if g then
            w.actual = g
            w.order = i
            w.fixed = w.requested and (g.w > w.requested.w + 3 or g.h > w.requested.h + 3)
            table.insert(placed, w)
        end
    end
    table.sort(placed, function(a, b)
        if a.actual.h ~= b.actual.h then
            return a.actual.h > b.actual.h
        end
        return a.order < b.order
    end)
    local rowList, heights, fits
    local scale = 1.0
    while true do
        rowList, heights, fits = overviewPack(placed, area, scale)
        if fits or scale <= 0.3 then
            break
        end
        scale = scale - 0.05
    end
    for _, row in ipairs(rowList) do
        table.sort(row, function(a, b) return a.order < b.order end)
    end
    local top, rowGap = overviewSpread(area.h, heights, overviewGap)
    local y = area.y + top
    for i, row in ipairs(rowList) do
        local widths = {}
        for _, w in ipairs(row) do
            table.insert(widths, w.target.w)
        end
        local left, columnGap = overviewSpread(area.w, widths, overviewGap)
        local x = area.x + left
        for _, w in ipairs(row) do
            overviewPlace(w.address, { x = x, y = y + (heights[i] - w.target.h) / 2, w = w.target.w, h = w.target.h })
            x = x + w.target.w + columnGap
        end
        y = y + heights[i] + rowGap
    end
    hl.exec_cmd("sleep 0.25; hyprctl dispatch OverviewRecord")
end

function OverviewRecord()
    if not overviewState then
        return
    end
    for _, w in ipairs(overviewState.windows) do
        w.shown = overviewGeometry(w.address)
    end
end

function OverviewClose(chosen)
    if not overviewState then
        return
    end
    local state = overviewState
    overviewState = nil
    overviewClickBind:set_enabled(false)
    overviewEscapeBind:set_enabled(false)
    for _, w in ipairs(state.windows) do
        w.arranged = overviewMoved(w.shown, overviewGeometry(w.address))
        hl.dispatch(hl.dsp.window.move({ workspace = w.workspace, window = "address:" .. w.address, follow = false }))
    end
    for _, w in ipairs(hl.get_windows({ workspace = "special:overview" })) do
        hl.dispatch(hl.dsp.window.move({ workspace = state.workspace, window = "address:" .. w.address, follow = false }))
    end
    local special = hl.get_active_special_workspace()
    if special and special.name == "special:overview" then
        hl.dispatch(hl.dsp.workspace.toggle_special("overview"))
    end
    for _, w in ipairs(state.windows) do
        if not w.arranged then
            if w.floating then
                overviewPlace(w.address, w.original)
            else
                local now = overviewGeometry(w.address)
                if now and now.floating then
                    hl.dispatch(hl.dsp.focus({ window = "address:" .. w.address }))
                    hl.dispatch(hl.dsp.window.float({ action = "toggle" }))
                end
            end
            if w.fullscreen > 0 then
                hl.dispatch(hl.dsp.focus({ window = "address:" .. w.address }))
                hl.dispatch(hl.dsp.window.fullscreen({ action = "set" }))
            end
        end
    end
    local target = chosen or state.focused
    if target then
        hl.dispatch(hl.dsp.focus({ window = "address:" .. target }))
    end
end

function OverviewToggle()
    hl.exec_cmd("pw-play " .. os.getenv("HOME") .. "/.config/hypr/sounds/overview.mp3")
    if overviewState then
        OverviewClose(nil)
        return
    end
    local windows = {}
    for _, w in ipairs(hl.get_windows()) do
        if w.mapped and w.workspace then
            table.insert(windows, {
                address = w.address,
                workspace = w.workspace.name,
                fullscreen = w.fullscreen,
                floating = w.floating,
                original = { x = w.at.x, y = w.at.y, w = w.size.x, h = w.size.y },
            })
        end
    end
    if #windows == 0 then
        return
    end
    local active = hl.get_active_window()
    local monitor = hl.get_active_monitor()
    overviewState = { windows = windows, focused = active and active.address, workspace = hl.get_active_workspace().name }

    local reserved = monitor.reserved
    local areaX = monitor.x + reserved.left + overviewGap
    local areaY = monitor.y + reserved.top + overviewGap
    local areaW = monitor.width / monitor.scale - reserved.left - reserved.right - 2 * overviewGap
    local areaH = monitor.height / monitor.scale - reserved.top - reserved.bottom - 2 * overviewGap
    local columns, rows, best = 1, #windows, -1
    for c = 1, #windows do
        local r = math.ceil(#windows / c)
        local w = (areaW - (c - 1) * overviewGap) / c
        local h = (areaH - (r - 1) * overviewGap) / r
        local tile = math.min(w, h * 1.6)
        if tile > best then
            columns, rows, best = c, r, tile
        end
    end
    local cellW = (areaW - (columns - 1) * overviewGap) / columns
    local cellH = (areaH - (rows - 1) * overviewGap) / rows
    overviewState.area = { x = areaX, y = areaY, w = areaW, h = areaH }
    overviewState.rows = rows

    for i, w in ipairs(windows) do
        local target = "address:" .. w.address
        if w.fullscreen > 0 then
            hl.dispatch(hl.dsp.focus({ window = target }))
            hl.dispatch(hl.dsp.window.fullscreen({ action = "unset" }))
        end
        hl.dispatch(hl.dsp.window.move({ workspace = "special:overview", window = target, follow = false }))
        hl.dispatch(hl.dsp.window.float({ action = "set", window = target }))
        local column = (i - 1) % columns
        local row = math.floor((i - 1) / columns)
        w.row = row + 1
        local ratio = math.max(0.75, math.min(1.9, w.original.w / math.max(1, w.original.h)))
        local tileW, tileH = cellW * 0.94, cellW * 0.94 / ratio
        if tileH > cellH * 0.94 then
            tileH = cellH * 0.94
            tileW = tileH * ratio
        end
        w.requested = { w = math.floor(tileW), h = math.floor(tileH) }
        overviewPlace(w.address, {
            x = areaX + column * (cellW + overviewGap) + (cellW - tileW) / 2,
            y = areaY + row * (cellH + overviewGap) + (cellH - tileH) / 2,
            w = tileW,
            h = tileH,
        })
    end
    hl.dispatch(hl.dsp.workspace.toggle_special("overview"))
    hl.exec_cmd("sleep 0.25; hyprctl dispatch OverviewArrange")
    overviewClickBind:set_enabled(true)
    overviewEscapeBind:set_enabled(true)
end

function OverviewPick()
    local picked = hl.get_active_window()
    OverviewClose(picked and picked.address)
end

hl.bind(mainMod .. " + A", OverviewToggle)
hl.bind(mainMod .. " + Z", hl.dsp.exec_cmd(os.getenv("HOME") .. "/.config/hypr/snap-layouts/snap_layouts.py"))
overviewClickBind = hl.bind("mouse:272", OverviewPick)
overviewEscapeBind = hl.bind("Escape", function() OverviewClose(nil) end)
overviewClickBind:set_enabled(false)
overviewEscapeBind:set_enabled(false)

hl.config({ binds = { disable_keybind_grabbing = true } })
hl.bind("ALT + Tab", hl.dsp.exec_cmd(os.getenv("HOME") .. "/.config/hypr/window-switcher/window_switcher.py $(date +%s.%N)"), { non_consuming = true, dont_inhibit = true })
hl.on("input.keyboard.key", function(keycode, _, state)
    if keycode == 64 and state == 0 then
        local released = io.open(os.getenv("XDG_RUNTIME_DIR") .. "/alttab-released", "w")
        if released then
            released:close()
        end
    end
end)

hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

for i = 1, 10 do
    local key = i % 10
    hl.bind(mainMod .. " + " .. key,             hl.dsp.focus({ workspace = i}))
    hl.bind(mainMod .. " + SHIFT + " .. key,     hl.dsp.window.move({ workspace = i }))
end

hl.bind(mainMod .. " + S",         hl.dsp.workspace.toggle_special("magic"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd(os.getenv("HOME") .. "/.config/hypr/snipping-tool/snipping_tool.py snip"))

hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),                  { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),                  { locked = true, repeating = true })

hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

local suppressMaximizeRule = hl.window_rule({
    name  = "suppress-maximize-events",
    match = { class = ".*" },

    suppress_event = "maximize",
})
suppressMaximizeRule:set_enabled(false)

hl.window_rule({
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = true,
})

hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },

    move  = "20 monitor_h-120",
    float = true,
})

hl.window_rule({
    name  = "transparent-apps",
    match = { class = "negative:^(kitty|org\\.kde\\.konsole|Minecraft.*|snipping-tool)$" },

    opacity = "0.7 0.7 0.7",
})

hl.layer_rule({
    name  = "blur-wofi",
    match = { namespace = "^wofi$" },

    blur         = true,
    ignore_alpha = 0.2,
})

hl.window_rule({
    name  = "pavucontrol-popup",
    match = { class = "^org\\.pulseaudio\\.pavucontrol$" },

    float = true,
    size  = "700 500",
    move  = "monitor_w-720 40",
})

hl.layer_rule({
    name  = "blur-waybar-rofi",
    match = { namespace = "^(waybar|rofi)$" },

    blur         = true,
    ignore_alpha = 0.2,
})

local clickSound        = "pw-play " .. os.getenv("HOME") .. "/.config/hypr/sounds/click.mp3"
local clickReverseSound = "pw-play " .. os.getenv("HOME") .. "/.config/hypr/sounds/click-reverse.mp3"
local function isSnipOverlay(window)
    return window and window.title == "Snipping overlay"
end
local function quietSnipEditor(window)
    if not window or window.class ~= "snipping-tool" then
        return false
    end
    local marker = os.getenv("XDG_RUNTIME_DIR") .. "/snipping-tool-quiet-open"
    if os.remove(marker) then
        return true
    end
    return false
end
hl.on("window.open", function(window)
    if not isSnipOverlay(window) and not quietSnipEditor(window) then
        hl.exec_cmd(clickSound)
    end
end)
hl.on("window.close", function(window)
    if not isSnipOverlay(window) then
        hl.exec_cmd(clickReverseSound)
    end
end)
hl.on("window.fullscreen", function(window)
    if window and window.fullscreen > 0 and not isSnipOverlay(window) then
        hl.exec_cmd(clickSound)
    end
end)

hl.window_rule({
    name  = "snip-editor",
    match = { class = "^snipping-tool$", title = "^Snip & Sketch$" },

    float = true,
})

hl.window_rule({
    name  = "snip-overlay",
    match = { class = "^snipping-tool$", title = "^Snipping overlay$" },

    no_anim = true,
})

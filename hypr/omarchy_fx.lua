local plugin = os.getenv("HOME") .. "/.local/share/hyprland/plugins/omarchy-fx.so"

local pluginFile = io.open(plugin, "r")
if not pluginFile then
    return
end
pluginFile:close()

hl.permission({ binary = plugin, type = "plugin", mode = "allow" })
hl.plugin.load(plugin)

local _, missing = hl.get_config("plugin.omarchy_fx.wobbly_wobbliness")
if not missing then
    hl.config({
        plugin = {
            omarchy_fx = {
                wobbly_enabled      = true,
                wobbly_on_move      = true,
                wobbly_on_resize    = true,
                wobbly_wobbliness   = 2,
                wobbly_tessellation = 20,
                wobbly_stiffness    = -1,
                wobbly_drag         = -1,
                wobbly_move_factor  = -1,

                elastic_enabled = false,
                pulse_enabled   = false,
                shake_enabled   = false,
            },
        },
    })
end

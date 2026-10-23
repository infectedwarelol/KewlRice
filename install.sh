#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

sudo pacman -S --needed git base-devel waybar wofi rofi kitty konsole dolphin mako wtype pipewire-audio pavucontrol python otf-font-awesome noto-fonts grim wl-clipboard python-cairo python-gobject gtk-layer-shell hyprlock plasma-integration btop cmatrix fastfetch playerctl curl ttf-jetbrains-mono-nerd cliphist wl-clip-persist fish swaybg unzip libayatana-appindicator cava

mkdir -p ~/rice-backup
cp -r ~/.config/hypr ~/.config/waybar ~/.config/wofi ~/.config/rofi ~/.config/kitty ~/.config/mako ~/.config/btop ~/.config/fastfetch ~/rice-backup/ 2>/dev/null || true
cp ~/.bashrc ~/rice-backup/bashrc 2>/dev/null || true
cp -r ~/.config/fish ~/rice-backup/ 2>/dev/null || true

mkdir -p ~/.config/fish ~/.config/kewlrice ~/.config/fastfetch ~/.config/btop ~/.config/hypr ~/.config/waybar ~/.config/wofi ~/.config/rofi ~/.config/kitty ~/.config/mako ~/.local/share/konsole ~/.local/share/applications
cp -r hypr/* ~/.config/hypr/
cp waybar/* ~/.config/waybar/
cp wofi/* ~/.config/wofi/
cp rofi/* ~/.config/rofi/
cp kitty/* ~/.config/kitty/
cp mako/* ~/.config/mako/
cp btop/* ~/.config/btop/
cp fastfetch/* ~/.config/fastfetch/
cp fish/config.fish ~/.config/fish/config.fish
chsh -s /usr/bin/fish
cp konsole/Transparent.colorscheme konsole/Transparent.profile ~/.local/share/konsole/
cp konsole/konsolerc dolphin/dolphinrc ~/.config/
cp applications/snipping-tool.desktop ~/.local/share/applications/
cp -r themes templates ~/.config/kewlrice/
cp -r hypr/sounds ~/.config/kewlrice/sounds
mkdir -p ~/.config/hypr/wallpapers
cp wallpapers/* ~/.config/hypr/wallpapers/

chmod +x ~/.config/hypr/window-switcher/window_switcher.py ~/.config/hypr/window-switcher/ui_daemon.py
chmod +x ~/.config/hypr/snap-layouts/snap_layouts.py
chmod +x ~/.config/hypr/snipping-tool/snipping_tool.py
chmod +x ~/.config/fastfetch/spinning_logo.py
chmod +x ~/.config/waybar/weather.py ~/.config/waybar/visualizer.py
chmod +x ~/.config/waybar/memory.sh ~/.config/waybar/now-playing.sh ~/.config/waybar/album-art.sh
chmod +x ~/.config/hypr/popups/popups.py ~/.config/hypr/popups/popup_request.py
chmod +x ~/.config/hypr/window-frame/window_frame.py
make -C ~/.config/hypr/window-grab install || echo "window-grab plugin build failed (needs hyprland headers)"
chmod +x ~/.config/hypr/brave-video/brave_video.py
chmod +x ~/.config/hypr/launcher.sh ~/.config/hypr/minimize.sh ~/.config/hypr/spotify-tray/spotify_tray.py ~/.config/hypr/terminal-key-repeat.sh ~/.config/hypr/clipboard/clipboard_menu.py
chmod +x ~/.config/hypr/theme-switch/theme_switch.py ~/.config/hypr/theme-switch/theme_transition.py ~/.config/hypr/lock/*.sh ~/.config/hypr/power-menu/power_menu.py ~/.config/hypr/control-center/control_center.py
~/.config/hypr/theme-switch/theme_switch.py default

git clone --depth 1 https://github.com/vinceliuice/WhiteSur-icon-theme.git /tmp/WhiteSur-icon-theme
/tmp/WhiteSur-icon-theme/install.sh -d ~/.local/share/icons
rm -rf /tmp/WhiteSur-icon-theme

mkdir -p ~/.cache/kewlrice/geodata
curl -Lo ~/.cache/kewlrice/geodata/ne_50m_land.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
curl -Lo ~/.cache/kewlrice/geodata/ne_50m_populated_places_simple.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places_simple.geojson

sudo cp -r sddm/kewlrice /usr/share/sddm/themes/
sudo install -d -m 755 -o "$USER" -g "$USER" /var/lib/kewlrice-sddm
printf '[Theme]\nCurrent=kewlrice\n' | sudo tee /etc/sddm.conf.d/30-kewlrice.conf
~/.config/hypr/theme-switch/theme_switch.py "$(cat ~/.local/state/kewlrice/current-theme 2>/dev/null || echo default)"

plasma-apply-colorscheme BreezeDark

echo "Done. Log out and log back in for everything to take effect."

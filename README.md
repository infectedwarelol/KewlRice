# KewlRice

My Hyprland setup on Arch Linux. Everything is see-through with a soft blur, the colors are purple, and there's a little sound when apps open and close. Alt+Tab shows your open apps on a little planet.

## Screenshots

| Desktop | Terminal |
| --- | --- |
| ![Desktop](screenshots/desktop.png) | ![Terminal opening with the spinning Arch logo](screenshots/terminal-spin.gif) |
| **Launcher** | **Alt+Tab** |
| ![App launcher](screenshots/launcher.png) | ![Alt+Tab spinning the globe of open apps](screenshots/alttab.gif) |

These are in the `slate` theme. Here are all five with cmatrix, fastfetch and btop:

![All five themes with cmatrix, fastfetch and btop](screenshots/themes.gif)

| default | burgundy | arctic |
| --- | --- | --- |
| ![default](screenshots/themes/default.gif) | ![burgundy](screenshots/themes/burgundy.gif) | ![arctic](screenshots/themes/arctic.gif) |
| ![default](screenshots/themes/default.png) | ![burgundy](screenshots/themes/burgundy.png) | ![arctic](screenshots/themes/arctic.png) |

| slate | meadow |
| --- | --- |
| ![slate](screenshots/themes/slate.gif) | ![meadow](screenshots/themes/meadow.gif) |
| ![slate](screenshots/themes/slate.png) | ![meadow](screenshots/themes/meadow.png) |

The wallpaper in the screenshots isn't included, so pick your own.

## What you get

- A floating Waybar at the top made of rounded pills in your theme's colors: the Arch logo (opens the launcher), control center, volume and media buttons on the left, and tray, network, CPU, memory, temperature, headset battery, clock (click for the date, hover for a calendar) and power on the right
- Every app see-through at 80%, and new apps you install get it too
- Kitty and Konsole with a purple background and clear text, and btop and cmatrix see-through in kitty too. cmatrix rains in your theme's accent color
- A launcher on Super+R (press it again to close it)
- An Alt+Tab switcher where your open apps sit on a glowing Earth in your theme's colors (real coastlines, relief, clouds, shiny oceans and a soft atmosphere) floating in a starfield, with Mac style app icons. Keep tapping Tab to spin it, it goes round forever, and it slowly turns on its own when you wait. The sun follows the real time of day: sunrise and sunset glow orange, and at night the city lights come on ([every theme, day and night](screenshots/alttab-themes.jpg))
- A clipboard history on Super+V
- A sound when an app opens or goes fullscreen, and another when it closes
- A sound when you log in, its own sound when you open the terminal, and a little click for every key you type in the terminal (with a deeper one for Backspace, and it keeps clicking while you hold a key)
- Notifications that go away after 5 seconds
- System apps like Settings and the volume mixer dark and see-through too
- Brave turns solid on YouTube and whenever a video is playing, so videos look sharp
- Discord turns solid while you watch a video in it, then goes back to see-through
- Steam, Steam games and Minecraft stay solid, so games look the way they should
- A snipping tool like on Windows, with drawing, blur and crop
- fastfetch with a spinning Arch logo and a spin sound every time you open a terminal or run it
- A purple terminal prompt with your name, the folder you are in and the time
- French keyboard layout (easy to change, see below)

## What you need

Arch Linux with Hyprland 0.56 or newer. This config uses the new Lua config file, so older versions won't work.

Install the packages:

```bash
sudo pacman -S --needed hyprland waybar wofi rofi kitty konsole dolphin mako wtype pipewire-audio pavucontrol python otf-font-awesome noto-fonts grim wl-clipboard python-cairo python-gobject gtk-layer-shell hyprlock plasma-integration btop cmatrix fastfetch playerctl ttf-jetbrains-mono-nerd cliphist wl-clip-persist fish
```

## Install

1. Get the files:

```bash
git clone https://gitlab.com/infectedware/KewlRice.git
cd KewlRice
```

Or, if a friend sent you `KewlRice.zip`, save it to your Downloads folder, then unzip it and go into the folder:

```bash
cd ~/Downloads
unzip KewlRice.zip
cd KewlRice
```

If `unzip` is missing, install it with `sudo pacman -S unzip`. Every step below works the same from inside that folder.

2. Back up your old configs, because the next step replaces them:

```bash
mkdir -p ~/rice-backup
cp -r ~/.config/hypr ~/.config/waybar ~/.config/wofi ~/.config/rofi ~/.config/kitty ~/.config/mako ~/.config/btop ~/.config/fastfetch ~/rice-backup/ 2>/dev/null
cp ~/.bashrc ~/rice-backup/bashrc 2>/dev/null
cp -r ~/.config/fish ~/rice-backup/ 2>/dev/null
```

To go back to your old setup later, copy those files back from `~/rice-backup`.

3. Copy everything into place:

```bash
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
chmod +x ~/.config/hypr/window-switcher/window_switcher.py
chmod +x ~/.config/hypr/snap-layouts/snap_layouts.py
chmod +x ~/.config/hypr/snipping-tool/snipping_tool.py
chmod +x ~/.config/fastfetch/spinning_logo.py
chmod +x ~/.config/waybar/weather.py
chmod +x ~/.config/hypr/window-frame/window_frame.py
chmod +x ~/.config/hypr/brave-video/brave_video.py
chmod +x ~/.config/hypr/launcher.sh ~/.config/hypr/terminal-key-repeat.sh ~/.config/hypr/clipboard/clipboard_menu.py
chmod +x ~/.config/hypr/theme-switch/theme_switch.py ~/.config/hypr/lock/*.sh ~/.config/hypr/power-menu/power_menu.py ~/.config/hypr/control-center/control_center.py
~/.config/hypr/theme-switch/theme_switch.py default
```

4. For the Mac style icons in Alt+Tab, install the WhiteSur icons (no sudo needed, they go in `~/.local/share/icons`):

```bash
git clone --depth 1 https://github.com/vinceliuice/WhiteSur-icon-theme.git /tmp/WhiteSur-icon-theme
/tmp/WhiteSur-icon-theme/install.sh -d ~/.local/share/icons
```

Apps that WhiteSur doesn't know get a white Mac style tile around their normal icon.

The Alt+Tab globe is drawn from real map data (public domain, from Natural Earth). Download it once:

```bash
mkdir -p ~/.cache/kewlrice/geodata
curl -Lo ~/.cache/kewlrice/geodata/ne_50m_land.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
curl -Lo ~/.cache/kewlrice/geodata/ne_50m_populated_places_simple.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places_simple.geojson
```

The globe for each theme gets built in the background the first time you switch to it (a few seconds). It's drawn live by a tiny C program that gets compiled the first time, so you need a C compiler (`sudo pacman -S --needed base-devel`). Until it's ready, Alt+Tab shows a plain sphere.

5. For the themed login screen (it follows whatever theme you used last):

```bash
sudo cp -r sddm/kewlrice /usr/share/sddm/themes/
sudo install -d -m 755 -o "$USER" -g "$USER" /var/lib/kewlrice-sddm
printf '[Theme]\nCurrent=kewlrice\n' | sudo tee /etc/sddm.conf.d/30-kewlrice.conf
~/.config/hypr/theme-switch/theme_switch.py "$(cat ~/.local/state/kewlrice/current-theme 2>/dev/null || echo default)"
```

6. Make KDE and Qt apps dark so they match the rest:

```bash
plasma-apply-colorscheme BreezeDark
```

7. Log out and log back in. That's it.

## Keyboard layout

The setup uses a French keyboard. If you want something else, open `~/.config/hypr/hyprland.lua`, find `kb_layout = "fr"` and change `fr` to your layout, for example `us`.

If you also want French on the login screen and in the text consoles:

```bash
sudo localectl set-keymap fr
sudo localectl set-x11-keymap fr
```

## Shortcuts

| Keys | What it does |
|---|---|
| Super + Q | Open the terminal |
| Super + R | Open the app launcher |
| Super + E | Open the file manager |
| Super + C or Alt + F4 | Close the window |
| Super + F or F11 | Fullscreen on and off |
| Alt + Tab | Switch apps, hold Alt and tap Tab to pick one (Shift + Tab or the arrows go back), or click it with the mouse, works in fullscreen games too |
| Super + D | Show the desktop, press again to get your windows back |
| Super + A | Show all your open apps at once, click one to jump to it, works in fullscreen games too |
| Super + Z | Snap layouts, pick a layout and which app goes where |
| Super + Shift + S | Take a snip, then draw on it, blur it or crop it |
| Super + N | Hide the window |
| Super + Shift + N | Show the hidden windows |
| Super + V | Clipboard history, pick something to paste it |
| Super + Shift + V | Make the window float |
| Super + 1 to 0 | Go to a workspace |
| Super + Shift + 1 to 0 | Move the window to a workspace |
| Super + M | Log out of Hyprland |
| Super + Tab | Pick a theme from the wallpaper cards, press it again to close |
| Super + L | Lock the screen |
| Super + Esc | Power menu: lock, log out, restart, shut down |

Click the volume in the bar to change the volume of each app on its own.

After a snip, right click the image to copy it or save it. Nothing gets saved unless you choose Save as. You can also open the Snipping Tool app from the launcher.

In the Super + A view you can hold Super and drag an app with the left mouse button to move it, or with the right button to resize it. When you close the view, the apps you moved stay where you put them.

## Themes

Press Super + Tab to pick a theme. The colors of the borders, bar, launcher, Alt+Tab menu, clipboard, terminal, prompt, cmatrix, notifications, snipping tool and GTK apps change right away, and so does the wallpaper. The theme you pick stays after a reboot.

You can also switch from a terminal:

```bash
~/.config/hypr/theme-switch/theme_switch.py burgundy
```

Five themes come with the rice: `default` (the purple look), `burgundy`, `arctic` (icy blue, with calm crystal chime sounds), `slate` (blue-gray space station, with sonar and console sounds) and `meadow` (light green countryside, with kalimba, marimba and bird sounds). They use `~/.config/hypr/wallpapers/arch-waifu-purple.png`, `burgundy-stairs.png`, `arctic-sky.png`, `slate-station.png` and `meadow-hills.png`. Eight more are wallpaper themes: `stardust`, `highland`, `ember`, `dusk`, `lilac`, `citypop`, `blush` and `daydream`, each using a picture of the same name in that folder (from wallhaven.cc). `daydream` is special: it draws an ornate pink frame with name tags around every terminal window and swaps fastfetch for a dotted bar layout. These pictures aren't included, so put your own there or the theme falls back to a plain color.

To add a theme, make a folder in `~/.config/kewlrice/themes/` with two files:

- `palette`, with one `name=#rrggbb` per line. Copy `themes/burgundy/palette` and change the colors. It needs `background`, `foreground`, `surface`, `primary`, `secondary`, `accent`, `urgent`, `border_active`, `border_inactive` and `color0` to `color15` for the terminal.
- `wallpaper.png` (or `.jpg`). You can also point to a picture somewhere else with a `wallpaper=` line in `palette`.
- Optionally `style=ornate` for the terminal frames and `terminal_padding=18` to keep text inside them.
- Optional: a `sounds` folder with any of the files from `hypr/sounds` (same names, for example `sounds/login.mp3` or `sounds/keys/terminal-key.wav`). Sounds you leave out use the normal ones.

The new theme shows up in the Super + Tab menu right away. The files in `templates/` decide which color goes where in each app.

## Lock screen, power menu and control center

- Super + L locks the screen: your wallpaper blurred, a big clock, the date and the song that's playing.
- Super + Esc opens the power menu. Log out, restart and shut down ask you to press a second time so you can't hit them by accident. Each one has its own sound.
- The gear button at the left of the bar opens the control center: volume and microphone, network, do not disturb, the song that's playing with its cover and controls, and lock and power buttons.
- The login screen, the lock screen, the power menu and the control center all follow the theme you picked last, by themselves.

## Changing things

- How see-through apps are: look for `opacity = "0.8 0.8 0.8"` in `hyprland.lua`. Lower is more see-through.
- How strong the blur is: change `size` in the `blur` part of `hyprland.lua`.
- The app sounds: swap `~/.config/hypr/sounds/app-open.mp3` and `app-close.mp3` for your own sounds with the same names.
- The login and terminal sounds: swap `~/.config/hypr/sounds/login.mp3`, `terminal-open.mp3` and `terminal-ready.mp3`.
- The typing sounds: swap `~/.config/hypr/sounds/keys/terminal-key.wav` and `terminal-backspace.wav`.
- The spin sound: swap `~/.config/hypr/sounds/spin.wav`.
- Apps that stay solid: add their class to the `negative:` list next to the `opacity` rule in `hyprland.lua`. Run `hyprctl clients` to find an app's class.
- Kitty and Konsole stay out of the see-through rule because they already make only their background see-through, so the text stays sharp.

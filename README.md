# KewlRice

My Hyprland setup on Arch Linux. Everything is see-through with a soft blur, the colors are purple, and there's a little sound when apps open and close. Alt+Tab works like on Windows 10.

## Screenshots

![Desktop](screenshots/desktop.png)

![Terminal opening with the spinning Arch logo](screenshots/terminal-spin.gif)

![Terminal with fastfetch](screenshots/terminal.png)

![Tiled windows with cmatrix](screenshots/tiled.gif)

![Terminal, cmatrix and Dolphin side by side](screenshots/tiled.png)

![App launcher](screenshots/launcher.png)

The wallpaper in the screenshots isn't included, so pick your own.

## What you get

- Waybar at the top, fully transparent, with the clock on the left (click it to see the date, hover for a calendar)
- Every app see-through at 80%, and new apps you install get it too
- Kitty and Konsole with a purple background and clear text, and btop and cmatrix see-through in kitty too
- A launcher on Super+R (press it again to close it) and a Windows style Alt+Tab menu that look the same
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
sudo pacman -S --needed hyprland waybar wofi rofi kitty konsole dolphin mako wtype pipewire-audio pavucontrol python otf-font-awesome noto-fonts grim wl-clipboard python-cairo plasma-integration btop cmatrix fastfetch playerctl ttf-jetbrains-mono-nerd cliphist wl-clip-persist
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
```

To go back to your old setup later, copy those files back from `~/rice-backup`.

3. Copy everything into place:

```bash
mkdir -p ~/.config/fastfetch ~/.config/btop ~/.config/hypr ~/.config/waybar ~/.config/wofi ~/.config/rofi ~/.config/kitty ~/.config/mako ~/.local/share/konsole ~/.local/share/applications
cp -r hypr/* ~/.config/hypr/
cp waybar/* ~/.config/waybar/
cp wofi/* ~/.config/wofi/
cp rofi/* ~/.config/rofi/
cp kitty/* ~/.config/kitty/
cp mako/* ~/.config/mako/
cp btop/* ~/.config/btop/
cp fastfetch/* ~/.config/fastfetch/
cp bash/bashrc ~/.bashrc
cp konsole/Transparent.colorscheme konsole/Transparent.profile ~/.local/share/konsole/
cp konsole/konsolerc dolphin/dolphinrc ~/.config/
cp applications/snipping-tool.desktop ~/.local/share/applications/
chmod +x ~/.config/hypr/window-switcher/window_switcher.py
chmod +x ~/.config/hypr/snap-layouts/snap_layouts.py
chmod +x ~/.config/hypr/snipping-tool/snipping_tool.py
chmod +x ~/.config/fastfetch/spinning_logo.py
chmod +x ~/.config/hypr/brave-video/brave_video.py
chmod +x ~/.config/hypr/launcher.sh ~/.config/hypr/terminal-key-repeat.sh ~/.config/hypr/clipboard/clipboard_menu.py
```

4. Make KDE and Qt apps dark so they match the rest:

```bash
plasma-apply-colorscheme BreezeDark
```

5. Log out and log back in. That's it.

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
| Alt + Tab | Switch apps, hold Alt and tap Tab to pick one or click it with the mouse, works in fullscreen games too |
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

Click the volume in the bar to change the volume of each app on its own.

After a snip, right click the image to copy it or save it. Nothing gets saved unless you choose Save as. You can also open the Snipping Tool app from the launcher.

In the Super + A view you can hold Super and drag an app with the left mouse button to move it, or with the right button to resize it. When you close the view, the apps you moved stay where you put them.

## Changing things

- How see-through apps are: look for `opacity = "0.8 0.8 0.8"` in `hyprland.lua`. Lower is more see-through.
- How strong the blur is: change `size` in the `blur` part of `hyprland.lua`.
- The app sounds: swap `~/.config/hypr/sounds/app-open.mp3` and `app-close.mp3` for your own sounds with the same names.
- The login and terminal sounds: swap `~/.config/hypr/sounds/login.mp3`, `terminal-open.mp3` and `terminal-ready.mp3`.
- The typing sounds: swap `~/.config/hypr/sounds/keys/terminal-key.wav` and `terminal-backspace.wav`.
- The spin sound: swap `~/.config/fastfetch/spin.wav`.
- Apps that stay solid: add their class to the `negative:` list next to the `opacity` rule in `hyprland.lua`. Run `hyprctl clients` to find an app's class.
- Kitty and Konsole stay out of the see-through rule because they already make only their background see-through, so the text stays sharp.

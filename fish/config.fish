set -gx MAVEN_OPTS -Xmx1g
fish_add_path -g $HOME/.local/bin $HOME/.npm-global/bin

status is-interactive; or return

set -g fish_greeting
set -g _primary '155;89;255'
set -g _foreground '230;237;243'
set -g _on_primary '20;16;30'
set -g _accent '#d090ff'
set -g _directory $_primary
test -r $HOME/.config/kewlrice/colors.fish; and source $HOME/.config/kewlrice/colors.fish

alias grep 'grep --color=auto'

function fish_prompt
    set -l directory (string replace -r "^$HOME" '~' -- $PWD)
    printf '\e[0;38;2;%sm\e[1;38;2;%s;48;2;%sm  %s ' $_primary $_on_primary $_primary $USER
    printf '\e[22;38;2;%s;48;2;%sm\e[1;38;2;%s;48;2;%sm %s ' $_primary $_foreground $_directory $_foreground $directory
    printf '\e[22;38;2;%s;48;2;%sm\e[1;38;2;%s;48;2;%sm  %s ' $_foreground $_primary $_on_primary $_primary (date +%H:%M)
    printf '\e[0;38;2;%sm\e[0m ' $_primary
end

function fastfetch
    set -l config
    if string match -q ornate -- (cat $HOME/.config/kewlrice/style 2>/dev/null)
        set config -c $HOME/.config/fastfetch/ornate.jsonc
    end
    if test (count $argv) -eq 0; and isatty stdout
        python3 $HOME/.config/fastfetch/spinning_logo.py (command fastfetch $config --pipe false --logo none | string collect) 2>/dev/null
        or command fastfetch $config
    else
        command fastfetch $config $argv
    end
end

function cmatrix
    printf '\e]4;2;%s\a\e]4;10;%s\a' $_accent $_accent
    command cmatrix $argv
    set -l result $status
    printf '\e]104;2;10\a'
    return $result
end

function ani-cli
    if set -q KITTY_LISTEN_ON
        kitty @ set-background-opacity 1 >/dev/null 2>&1
        command ani-cli $argv
        set -l result $status
        kitty @ set-background-opacity 0.8 >/dev/null 2>&1
        return $result
    end
    command ani-cli $argv
end

if not set -q FASTFETCH_SHOWN
    set -gx FASTFETCH_SHOWN 1
    sleep 1.0
    fastfetch
end

#!/bin/sh
# Installs (or updates) Pelagic for the current user from the unpacked Linux tarball. No root needed.
#   ./install.sh            install into ~/.local
#   ./install.sh --remove   uninstall (your browsing data in ~/.local/share/AtlasBrowser is kept)
set -e
here="$(cd "$(dirname "$0")" && pwd)"
share="${XDG_DATA_HOME:-$HOME/.local/share}"
app="$HOME/.local/opt/Pelagic"
bin="$HOME/.local/bin"
icon="$share/icons/hicolor/256x256/apps/pelagic.png"
desktop="$share/applications/pelagic.desktop"

if [ "$1" = "--remove" ]; then
    rm -rf "$app"
    rm -f "$bin/pelagic" "$icon" "$desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$share/applications" || true
    echo "Pelagic removed."
    exit 0
fi

mkdir -p "$app" "$bin" "$(dirname "$icon")" "$(dirname "$desktop")"
rm -rf "$app"
cp -R "$here/Pelagic" "$app"
ln -sf "$app/Pelagic" "$bin/pelagic"
cp "$here/pelagic.png" "$icon"
sed "s|^Exec=pelagic|Exec=$bin/pelagic|" "$here/pelagic.desktop" > "$desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$share/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q "$share/icons/hicolor" || true
echo "Pelagic installed. Open it from your applications menu or run: $bin/pelagic"
command -v ffmpeg >/dev/null 2>&1 || echo "Tip: install ffmpeg (for example: sudo apt install ffmpeg) for HD and MP3 YouTube downloads."

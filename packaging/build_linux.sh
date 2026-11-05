#!/bin/sh
# Builds dist/Pelagic (one folder, ./Pelagic) and dist/Pelagic-<version>-linux-x86_64.tar.gz on Linux.
# Needs Python 3.10+ with venv. PySide6 comes from requirements.txt; ffmpeg is not bundled (install it from your
# distribution for HD and MP3 YouTube downloads). Like build.ps1, this is not a pinned, reproducible build.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
venv="$here/.venv-linux"
version="$(sed -n "s/.*StringStruct('ProductVersion', '\([^']*\)').*/\1/p" "$here/version_info.txt")"
version="${version:-dev}"

if [ ! -x "$venv/bin/python" ]; then
    python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install -q -U pip
"$venv/bin/python" -m pip install -q -r "$root/requirements.txt" pyinstaller
# yt-dlp for the YouTube downloader; upgraded on every build because YouTube changes often
"$venv/bin/python" -m pip install -q -U "yt-dlp[default]"

"$venv/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$root/dist" --workpath "$root/build" "$here/pelagic.spec"

stage="$root/dist/Pelagic-$version-linux-x86_64"
rm -rf "$stage"
mkdir -p "$stage"
cp -R "$root/dist/Pelagic" "$stage/Pelagic"
cp "$here/linux/pelagic.desktop" "$here/linux/install.sh" "$stage/"
cp "$root/atlasbrowser/assets/pelagic.png" "$stage/pelagic.png"
chmod +x "$stage/install.sh" "$stage/Pelagic/Pelagic"
tar -C "$root/dist" -czf "$stage.tar.gz" "$(basename "$stage")"
rm -rf "$stage"
echo "Built $stage.tar.gz"

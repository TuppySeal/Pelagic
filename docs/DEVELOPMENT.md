# Development and repository guide

## Run from source

Use Python 3.10 or newer on Windows. From this repository's root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m atlasbrowser
```

On Linux (Python 3.10+, with the `python3-venv` package on Debian/Ubuntu):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

Qt WebEngine needs some system libraries that desktop installs usually have but minimal installs (servers, containers, WSL) may lack. Without `libxcb-cursor0` Pelagic stops with *Could not load the Qt platform plugin "xcb"*. On Debian/Ubuntu:

```sh
sudo apt install libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2t64 libgbm1
```

Before Ubuntu 24.04, use `libasound2` instead of `libasound2t64`. Saved passwords, cards and API keys need a running keyring (gnome-keyring or KWallet), or `PELAGIC_PASSWORD_STORE=basic`. `ffmpeg` is optional (HD and MP3 YouTube downloads).

The source package retains its historical name, atlasbrowser. The public application is Pelagic. API keys belong in the app's encrypted settings or the documented environment variables, never in source files.

## Organization

| Path | Contents |
| --- | --- |
| atlasbrowser/ | Browser, AI providers/agent, UI and application assets |
| tests/ | Standalone regression scripts; each script documents its purpose |
| launcher/ | Windows launcher source and resource definitions (Linux uses run.sh or the packaged ./Pelagic) |
| packaging/ | PyInstaller specifications, Inno Setup scripts, version metadata, and the Linux build (build_linux.sh, linux/) |
| playground/ | Standalone AI playground page |
| website/ | Static installer download website, deployed to the Cloudflare Worker `download` (https://pelagicbrowser.app) on every push to main (see wrangler.jsonc) |

The existing feature guide is README.md. Legacy Wayfinder-named launcher/build definitions remain for compatibility. Generated binaries, environments and personal app data are excluded.

## Verify changes

```powershell
python -m compileall -q atlasbrowser tests packaging/entry.py
python tests/selftest.py
```

Run other tests relevant to the feature being changed; README.md lists the major suites. UI tests use temporary browser data and mock/local sites. Some require a working Qt WebEngine graphics environment.

## Build Windows installers

Install the requirements into the Python environment used for the build, then run:

```powershell
powershell -File packaging/build.ps1
```

The build script uses a packaging virtual environment with access to installed system packages, installs PyInstaller and yt-dlp, downloads FFmpeg, and builds dist/Pelagic. Install Inno Setup 6 to produce the installer as well. (The separate PelagicUpdate updater is no longer built; `ISCC /DUpdater packaging/pelagic.iss` still makes one if ever needed.) This build has network dependencies and is not a pinned reproducible build.

## Build for Linux

On an x86_64 Linux machine (build on the oldest distribution you want to support, because the bundle uses that system's glibc):

```sh
sh packaging/build_linux.sh
```

It makes a packaging virtual environment (`packaging/.venv-linux`), installs the requirements, PyInstaller and yt-dlp, builds dist/Pelagic with `packaging/pelagic.spec`, and packs `dist/Pelagic-<version>-linux-x86_64.tar.gz` with `packaging/linux/install.sh` and `pelagic.desktop`. FFmpeg is not bundled on Linux; Pelagic uses the system's `ffmpeg`. The release tarball is built on Ubuntu 24.04 (glibc 2.39) and needs a distribution at least that new; older distributions should build from source with this script. The build machine needs the same system libraries as running from source (above).

Linux-specific behaviour: data is in `$XDG_DATA_HOME/AtlasBrowser` (normally `~/.local/share/AtlasBrowser`; an existing `~/AtlasBrowser` is still used). Secrets use `atlasbrowser/secretbox.py`: a random key in the system keyring through the `keyring` package, or with `PELAGIC_PASSWORD_STORE=basic` a mode-600 key file. Tests set `PELAGIC_PASSWORD_STORE=basic` so they never touch your keyring; `python tests/secretbox_test.py` checks this on any system.

## Version numbers

Releases use three-part versions, x.y.z, for both Windows and Linux: `PelagicSetup-x.y.z.exe` and `Pelagic-x.y.z-linux-x86_64.tar.gz`, under the release tag `vx.y.z`. To set a new version, change it in `atlasbrowser/__init__.py` and in `packaging/version_info.txt` (the `FileVersion` and `ProductVersion` strings, and `filevers`/`prodvers` as `(x, y, z, 0)`); both build scripts read the version from there. Add the release to CHANGELOG.md. The first release (v1.0.0.0) is the only four-part one.

Publish generated installers as GitHub release assets. The current full installer is:

https://github.com/TuppySeal/Pelagic/releases/download/v1.0.0.0/PelagicSetup-1.0.0.0.exe

## Claude commits

Open this checkout as Claude's working folder and keep CLAUDE.md in the repository root. Git identity is configured locally from the authenticated GitHub account, with its GitHub noreply address. Git Credential Manager handles authentication outside source control.

```powershell
git status --short
git diff
# Run the relevant checks, then stage the files that belong to your change.
git add path/to/changed-file
git diff --cached
git commit -m "Describe the resulting change"
git push origin main
```

If the linked Claude environment can edit files but cannot execute local Git, it cannot use Windows Credential Manager directly. Use Claude's supported local shell or GitHub connection; do not pass a token through chat. A source export alone does not grant Claude shell or GitHub access.

## Source import

The initial source import came from the existing local AtlasBrowser project identified by Claude, plus the current download website from Documents/Wayfinder. It preserves code and tests rather than reconstructing source from the installer. Installer binaries remain separately versioned release assets; the imported source can contain changes made after the original installer build.

# PyInstaller spec: one-folder, windowed Pelagic.exe. Build with packaging\build.ps1 (Windows) or
# packaging/build_linux.sh (Linux, where it makes ./Pelagic).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
ASSETS = os.path.join(ROOT, 'atlasbrowser', 'assets')

a = Analysis(
    [os.path.join(SPECPATH, 'entry.py')],
    pathex=[ROOT],
    datas=[(ASSETS, 'atlasbrowser/assets')],
    # yt-dlp (the YouTube downloader) loads its site extractors by name, so list them all
    # off Windows, saved secrets use the system keyring (see atlasbrowser/secretbox.py); its backends load by name too
    hiddenimports=['PySide6.QtTest', 'PySide6.QtWebChannel'] + collect_submodules('yt_dlp')
                  + ([] if sys.platform == 'win32' else collect_submodules('keyring')),
    excludes=['tkinter', 'PySide6.Qt3DCore', 'PySide6.QtQuick3D', 'PySide6.QtCharts',
              'PySide6.QtDataVisualization', 'PySide6.QtMultimedia', 'PySide6.QtBluetooth'],
    noarchive=False,
)
# Pelagic is a widgets app: QML plugins and the debug DevTools pak are dead weight (~100 MB).
# Charts, DataVisualization, Graphs and VirtualKeyboard are GPL-only and unused; they only ride in
# as dependencies of QML plugins, so drop them too.
GPL_ONLY = ('Qt6Charts', 'Qt6DataVisualization', 'Qt6Graphs', 'Qt6VirtualKeyboard', 'qtvirtualkeyboardplugin')


def _keep(entry):
    dest = entry[0].replace('\\', '/')
    name = dest.rsplit('/', 1)[-1]
    return not (dest.startswith('PySide6/qml/') or dest.endswith('.debug.pak') or name.startswith(GPL_ONLY))


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Pelagic',
    icon=os.path.join(ASSETS, 'pelagic.ico') if sys.platform == 'win32' else None,
    version=os.path.join(SPECPATH, 'version_info.txt') if sys.platform == 'win32' else None,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Pelagic', upx=False)

# PyInstaller spec: one-folder, windowed Wayfinder.exe. Build with packaging\build.ps1.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
ASSETS = os.path.join(ROOT, 'atlasbrowser', 'assets')

a = Analysis(
    [os.path.join(SPECPATH, 'entry.py')],
    pathex=[ROOT],
    datas=[(ASSETS, 'atlasbrowser/assets')],
    hiddenimports=['PySide6.QtTest', 'PySide6.QtWebChannel'],
    excludes=['tkinter', 'PySide6.Qt3DCore', 'PySide6.QtQuick3D', 'PySide6.QtCharts',
              'PySide6.QtDataVisualization', 'PySide6.QtMultimedia', 'PySide6.QtBluetooth'],
    noarchive=False,
)
# Wayfinder is a widgets app: QML plugins and the debug DevTools pak are dead weight (~100 MB).
def _keep(entry):
    dest = entry[0].replace('\\', '/')
    return not (dest.startswith('PySide6/qml/') or dest.endswith('.debug.pak'))


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Wayfinder',
    icon=os.path.join(ASSETS, 'wayfinder.ico'),
    version=os.path.join(SPECPATH, 'version_info.txt'),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Wayfinder', upx=False)

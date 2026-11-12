# Builds dist\Pelagic\Pelagic.exe, then dist\PelagicSetup-<version>.exe if Inno Setup is installed.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path $here
$venv = Join-Path $here '.venv'
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    python -m venv --system-site-packages $venv
    & "$venv\Scripts\python.exe" -m pip install -q pyinstaller
}
# yt-dlp for the YouTube downloader; upgraded on every build because YouTube changes often
& "$venv\Scripts\python.exe" -m pip install -q -U "yt-dlp[default]"
if ($LASTEXITCODE) { throw 'Installing yt-dlp failed' }

# ffmpeg (LGPL build) for HD video and MP3: downloaded once into packaging\cache, copied next to Pelagic.exe
$cache = Join-Path $here 'cache'
$ffmpeg = Join-Path $cache 'ffmpeg.exe'
if (-not (Test-Path $ffmpeg)) {
    New-Item -ItemType Directory -Force $cache | Out-Null
    $zip = Join-Path $cache 'ffmpeg.zip'
    $ProgressPreference = 'SilentlyContinue'   # the progress bar makes downloads very slow
    Invoke-WebRequest 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip' -OutFile $zip
    $unz = Join-Path $cache 'ffmpeg-unzip'
    Expand-Archive $zip $unz -Force
    Copy-Item (Get-ChildItem $unz -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName $ffmpeg
    Remove-Item $zip, $unz -Recurse -Force
}

& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean `
    --distpath "$root\dist" --workpath "$root\build" "$here\pelagic.spec"
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
New-Item -ItemType Directory -Force "$root\dist\Pelagic\ffmpeg" | Out-Null
Copy-Item $ffmpeg "$root\dist\Pelagic\ffmpeg\ffmpeg.exe" -Force

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "$here\pelagic.iss"
    if ($LASTEXITCODE) { throw 'Inno Setup failed' }
} else {
    Write-Host 'Inno Setup 6 not found; skipped the installer step.'
}

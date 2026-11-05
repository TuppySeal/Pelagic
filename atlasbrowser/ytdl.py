"""YouTube and YouTube Music downloader (menu → Download video or audio…), using yt-dlp.

Video: the best quality up to the size you pick, as .mp4. Audio: .mp3 (or .m4a when ffmpeg isn't there).
Full HD and up, and MP3, need ffmpeg: it's looked for next to Pelagic (ffmpeg\\ffmpeg.exe, or ffmpeg/ffmpeg on Linux) and on PATH. Without it
YouTube only offers single-file videos (often 360p).

Downloading from YouTube is against YouTube's terms of service; this is for personal use.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton, QVBoxLayout)

YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be")
QUALITIES = [("Best available", None), ("4K (2160p)", 2160), ("1440p", 1440), ("1080p", 1080), ("720p", 720),
             ("480p", 480), ("360p", 360)]


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def ffmpeg_path() -> str | None:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (here / "ffmpeg" / "ffmpeg.exe", Path(sys.executable).parent / "ffmpeg" / "ffmpeg.exe",
              here / "ffmpeg" / "ffmpeg", Path(sys.executable).parent / "ffmpeg" / "ffmpeg"):
        if p.exists():
            return str(p)
    return shutil.which("ffmpeg")


def is_youtube(url: str | QUrl) -> bool:
    u = QUrl(url) if isinstance(url, str) else url
    host = u.host().lower()
    if host not in YT_HOSTS:
        return False
    if host.endswith("youtu.be"):
        return len(u.path()) > 1
    path, q = u.path(), u.query()
    if path == "/watch":
        return "v=" in q
    if path == "/playlist":
        return "list=" in q
    return path.startswith(("/shorts/", "/live/")) and len(path.rstrip("/").split("/")) >= 3


def is_music(url: str) -> bool:
    return QUrl(url).host().lower() == "music.youtube.com"


def downloads_folder() -> str:
    d = Path.home() / "Downloads"
    return str(d if d.exists() else Path.home())


def options(kind: str, height: int | None, folder: str, ffmpeg: str | None, playlist: bool) -> dict:
    """yt-dlp settings for one download."""
    opts = {"outtmpl": os.path.join(folder, "%(title).150B [%(id)s].%(ext)s"), "noplaylist": not playlist,
            "quiet": True, "no_warnings": True, "noprogress": True, "restrictfilenames": False,
            "windowsfilenames": True, "overwrites": False, "continuedl": True}
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if playlist:
        opts["outtmpl"] = os.path.join(folder, "%(playlist_title).80B", "%(playlist_index)03d %(title).120B.%(ext)s")
    if kind == "audio":
        if ffmpeg:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                                      {"key": "FFmpegMetadata"}]
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        cap = f"[height<={height}]" if height else ""
        if ffmpeg:
            opts["format"] = f"bestvideo{cap}+bestaudio/best{cap}/best"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = f"best{cap}[vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]"
    return opts


class _Worker(QObject):
    progress = Signal(float, str)        # 0-100 (or -1 when unknown), status text
    finished = Signal(bool, str, str)    # ok, message, file

    def __init__(self, url, opts):
        super().__init__()
        self.url, self.opts, self.cancelled, self.last_file = url, opts, False, ""

    def run(self):
        try:
            import yt_dlp
        except ImportError:
            self.finished.emit(False, "The downloader (yt-dlp) isn't installed.", "")
            return

        def hook(d):
            if self.cancelled:
                raise yt_dlp.utils.DownloadCancelled("Cancelled")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = done * 100 / total if total else -1
                info = d.get("info_dict") or {}
                name = info.get("title") or ""
                n, of = info.get("playlist_index"), info.get("n_entries")
                where = f" ({n} of {of})" if n and of else ""
                speed = d.get("_speed_str", "").strip()
                self.progress.emit(pct, f"Downloading{where}: {name[:60]}  {speed}".rstrip())
            elif d.get("status") == "finished":
                self.last_file = d.get("filename") or self.last_file
                self.progress.emit(100, "Finishing…")

        def pp_hook(d):
            if d.get("status") == "finished":
                self.last_file = (d.get("info_dict") or {}).get("filepath") or self.last_file
        opts = {**self.opts, "progress_hooks": [hook], "postprocessor_hooks": [pp_hook]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                code = ydl.download([self.url])
            if self.cancelled:
                self.finished.emit(False, "Cancelled.", "")
            else:
                self.finished.emit(code == 0, "Done." if code == 0 else "Some items couldn't be downloaded.",
                                   self.last_file)
        except Exception as e:   # noqa: BLE001 - shown to the user
            msg = "Cancelled." if self.cancelled else _friendly(str(e))
            self.finished.emit(False, msg, "")


def _friendly(err: str) -> str:
    err = re.sub(r"\x1b\[[0-9;]*m", "", err).replace("ERROR: ", "")
    if "Sign in to confirm" in err or "age" in err.lower() and "restrict" in err.lower():
        return "YouTube wants you signed in for this one (age-restricted or bot check), so it can't be downloaded."
    if "Private video" in err or "unavailable" in err.lower():
        return "This video is private or unavailable."
    if "ffmpeg" in err.lower():
        return "This needs ffmpeg, which isn't installed. Try 720p or lower, or the audio as .m4a."
    return "Couldn't download: " + err[:300]


class DownloadDialog(QDialog):
    def __init__(self, url: str = "", store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Download from YouTube")
        self.resize(560, 300)
        self.thread: QThread | None = None
        self.worker: _Worker | None = None
        self.file = ""
        self.ffmpeg = ffmpeg_path()
        v = QVBoxLayout(self)
        self.url = QLineEdit(url if is_youtube(url) else "")
        self.url.setPlaceholderText("YouTube or YouTube Music link")
        v.addWidget(QLabel("Link"))
        v.addWidget(self.url)

        kind_row = QHBoxLayout()
        self.video = QRadioButton("Video (.mp4)")
        self.audio = QRadioButton("Audio only (" + (".mp3" if self.ffmpeg else ".m4a") + ")")
        group = QButtonGroup(self)
        group.addButton(self.video)
        group.addButton(self.audio)
        (self.audio if is_music(url) else self.video).setChecked(True)
        self.quality = QComboBox()
        for label, h in QUALITIES:
            self.quality.addItem(label, h)
        self.quality.setCurrentIndex(0 if self.ffmpeg else QUALITIES.index(("720p", 720)))
        self.video.toggled.connect(self.quality.setEnabled)
        self.quality.setEnabled(self.video.isChecked())
        kind_row.addWidget(self.video)
        kind_row.addWidget(self.quality)
        kind_row.addSpacing(16)
        kind_row.addWidget(self.audio)
        kind_row.addStretch(1)
        v.addLayout(kind_row)
        self.playlist = QCheckBox("Download the whole playlist")
        self.playlist.setVisible("list=" in self.url.text())
        self.url.textChanged.connect(lambda t: self.playlist.setVisible("list=" in t))
        v.addWidget(self.playlist)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit((store.get("ytdl_folder") if store else None) or downloads_folder())
        browse = QPushButton("Change…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(QLabel("Save to"))
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        v.addLayout(folder_row)

        if not self.ffmpeg:
            note = QLabel("Without ffmpeg, YouTube only offers lower-quality single-file videos, and audio is .m4a.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            v.addWidget(note)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.bar)
        v.addWidget(self.status)
        v.addStretch(1)

        btns = QHBoxLayout()
        self.show_btn = QPushButton("Show in folder")
        self.show_btn.clicked.connect(self._show)
        self.show_btn.hide()
        self.go = QPushButton("Download")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        btns.addWidget(self.show_btn)
        btns.addStretch(1)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.go)
        v.addLayout(btns)
        if not available():
            self.go.setEnabled(False)
            self.status.setText("The downloader (yt-dlp) isn't installed in this copy of Pelagic.")

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save downloads to", self.folder.text())
        if d:
            self.folder.setText(d)

    def chosen_options(self) -> dict:
        return options("audio" if self.audio.isChecked() else "video", self.quality.currentData(),
                       self.folder.text().strip() or downloads_folder(), self.ffmpeg,
                       self.playlist.isVisible() and self.playlist.isChecked())

    def start(self):
        url = self.url.text().strip()
        if not is_youtube(url):
            self.status.setText("Paste a YouTube or YouTube Music video, Short or playlist link.")
            return
        folder = self.folder.text().strip() or downloads_folder()
        os.makedirs(folder, exist_ok=True)
        if self.store:
            self.store.set("ytdl_folder", folder)
        self.go.setEnabled(False)
        self.show_btn.hide()
        self.cancel_btn.setText("Cancel")
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText("Starting…")
        self.thread = QThread(self)
        self.worker = _Worker(url, self.chosen_options())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._done)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def _progress(self, pct, text):
        if pct < 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(pct))
        self.status.setText(text)

    def _done(self, ok, msg, file):
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if ok else 0)
        self.status.setText(msg + (f"\n{os.path.basename(file)}" if ok and file else ""))
        self.file = file
        self.show_btn.setVisible(ok)
        self.go.setEnabled(True)
        self.go.setText("Download another")
        self.cancel_btn.setText("Close")

    def _show(self):
        folder = os.path.dirname(self.file) if self.file else self.folder.text()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _cancel_or_close(self):
        if self.thread is not None and self.thread.isRunning():
            self.worker.cancelled = True
            self.status.setText("Cancelling…")
            return
        self.close()

    def closeEvent(self, ev):
        if self.thread is not None and self.thread.isRunning():
            self.worker.cancelled = True
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(ev)

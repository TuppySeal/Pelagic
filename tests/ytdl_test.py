"""YouTube downloader: which links count, the yt-dlp settings for each choice, and the dialog's progress, finish
and cancel (with a stand-in for yt-dlp, so no network is used).

Run:  python tests/ytdl_test.py
"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_ytdl_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, ms=6000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def fake_yt_dlp(slow=False):
    """A stand-in yt_dlp module: reports progress, then 'writes' the file."""
    mod = types.ModuleType("yt_dlp")
    mod.utils = types.SimpleNamespace(DownloadCancelled=type("DownloadCancelled", (Exception,), {}))
    mod.seen = []

    class YoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            mod.seen.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            out = self.opts["outtmpl"].replace("%(title).150B [%(id)s].%(ext)s", "Song [abc].mp3")
            for n in range(1, 11):
                for h in self.opts["progress_hooks"]:
                    h({"status": "downloading", "total_bytes": 1000, "downloaded_bytes": n * 100,
                       "info_dict": {"title": "Song"}, "_speed_str": "1MiB/s"})
                time.sleep(0.3 if slow else 0.01)
            for h in self.opts["progress_hooks"]:
                h({"status": "finished", "filename": out})
            Path(out).write_text("x")
            return 0
    mod.YoutubeDL = YoutubeDL
    return mod


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import ytdl
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    yes = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ",
           "https://music.youtube.com/watch?v=abc123&list=RDAMVM", "https://www.youtube.com/shorts/abc123",
           "https://www.youtube.com/playlist?list=PL123", "https://m.youtube.com/watch?v=x1"]
    no = ["https://www.youtube.com/", "https://www.youtube.com/@channel", "https://youtu.be/",
          "https://example.com/watch?v=abc", "https://www.youtube.com/playlist", "https://notyoutube.com/watch?v=1"]
    check("video, Short, Music and playlist links are recognised", all(ytdl.is_youtube(u) for u in yes),
          str([u for u in yes if not ytdl.is_youtube(u)]))
    check("other pages aren't", not any(ytdl.is_youtube(u) for u in no), str([u for u in no if ytdl.is_youtube(u)]))

    o = ytdl.options("video", 1080, "/d", "/ff/ffmpeg", False)
    check("video with ffmpeg: best video up to 1080p plus best audio, as mp4",
          o["format"].startswith("bestvideo[height<=1080]+bestaudio") and o["merge_output_format"] == "mp4"
          and o["ffmpeg_location"] == "/ff/ffmpeg" and o["noplaylist"] is True)
    o = ytdl.options("video", None, "/d", None, False)
    check("video without ffmpeg: a single file with sound", "+" not in o["format"]
          and "acodec!=none" in o["format"] and "merge_output_format" not in o)
    o = ytdl.options("audio", None, "/d", "/ff/ffmpeg", False)
    check("audio with ffmpeg becomes mp3", o["postprocessors"][0]["preferredcodec"] == "mp3")
    o = ytdl.options("audio", None, "/d", None, False)
    check("audio without ffmpeg stays m4a", "m4a" in o["format"] and "postprocessors" not in o)
    o = ytdl.options("audio", None, "/d", None, True)
    check("a playlist goes in its own folder, numbered", o["noplaylist"] is False and "playlist_title" in o["outtmpl"])

    store = Store()
    folder = tempfile.mkdtemp(prefix="yt out ")
    store.set("ytdl_folder", folder)
    sys.modules["yt_dlp"] = fake_yt_dlp()
    dlg = ytdl.DownloadDialog("https://music.youtube.com/watch?v=abc123", store)
    dlg.show()
    check("opened on a YouTube page, the link is filled in", dlg.url.text().startswith("https://music.youtube.com"))
    check("YouTube Music starts on audio", dlg.audio.isChecked() and not dlg.quality.isEnabled())
    check("the folder is remembered", dlg.folder.text() == folder)
    dlg2 = ytdl.DownloadDialog("https://example.com/", store)
    check("on another page the link starts empty", dlg2.url.text() == "" and dlg2.video.isChecked())
    dlg2.start()
    check("a non-YouTube link is explained, not started", "YouTube" in dlg2.status.text() and dlg2.thread is None)
    dlg2.close()

    dlg.start()
    check("downloading shows progress", wait(lambda: dlg.bar.isVisible() and "Downloading" in dlg.status.text()
                                             or dlg.status.text().startswith("Done")))
    check("then says it's done and offers the folder",
          wait(lambda: dlg.status.text().startswith("Done") and dlg.show_btn.isVisible()), dlg.status.text())
    check("the file is in the chosen folder", any(Path(folder).iterdir()))
    check("the chosen options reached yt-dlp", sys.modules["yt_dlp"].seen[-1]["outtmpl"].startswith(folder))

    sys.modules["yt_dlp"] = fake_yt_dlp(slow=True)
    dlg.start()
    wait(lambda: "Downloading" in dlg.status.text(), 3000)
    dlg._cancel_or_close()
    check("Cancel stops it", wait(lambda: dlg.status.text().startswith("Cancelled"), 6000), dlg.status.text())
    check("and the dialog stays open to try again", dlg.isVisible() and dlg.go.isEnabled())
    dlg.close()

    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID)
    labels = [a.text() for a in win.menu_btn.menu().actions()]
    check("it's in the menu, not the toolbar", "Download video or audio…" in labels, str(labels))

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    os._exit(main())

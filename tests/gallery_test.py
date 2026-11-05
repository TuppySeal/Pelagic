"""Extension gallery: the bundled extensions parse, install with one click, update and remove.

Run:  python tests/gallery_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from atlasbrowser import extensions_gallery as g  # noqa: E402
from atlasbrowser.extensions import Extensions  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


class FakeWin(QWidget):
    private = False

    def __init__(self, exts):
        super().__init__()
        self.ctx = type("Ctx", (), {"extensions": exts})()
        self.reloads = 0

    def _cur(self, fn):
        self.reloads += 1


app = QApplication.instance() or QApplication([])
exts = Extensions(Path(tempfile.mkdtemp(prefix="pelagic_gallery_test_")))

entries = g.entries()
check("nine bundled extensions", len(entries) == 9, [e["file"] for e in entries])
check("every one has a name, description and version",
      all(e["name"] and e["description"] and e["version"] for e in entries))
check("every catalog file exists", all((g.GALLERY_DIR / f).exists() for f, _i, _t in g.CATALOG))
yt = next(e for e in entries if e["file"] == "youtube-enhancer.user.js")
check("site list is readable", yt["sites"] == "youtube.com", yt["sites"])
check("all-sites extensions say so", next(e for e in entries if e["file"] == "auto-scroll.user.js")["sites"] == "Every site")

ext = g.install(exts, yt)
check("install adds it", g.installed(exts, yt) is not None and ext["name"] == "YouTube Enhancer")
check("installed with its match patterns", "*://*.youtube.com/*" in ext["sites"], ext["sites"])
check("script file written", (exts.folder / f"{ext['id']}.user.js").read_text(encoding="utf-8") == yt["code"])
g.install(exts, yt)
check("installing twice keeps one copy", len(exts.items) == 1)
check("no update when versions match", not g.has_update(exts, yt))
newer = dict(yt, version="9.0", code=yt["code"].replace("@version     1.0", "@version     9.0"))
check("newer bundled version offers an update", g.has_update(exts, newer))
g.install(exts, newer)
check("update replaces in place", len(exts.items) == 1 and exts.items[0]["version"] == "9.0" and exts.items[0]["id"] == ext["id"])
g.uninstall(exts, yt)
check("remove", g.installed(exts, yt) is None and not exts.items)

win = FakeWin(exts)
d = g.GalleryDialog(win)
check("dialog has a card per extension", len(d.cards) == 9)
d._install_all()
check("install all", len(exts.items) == 9 and all(g.installed(exts, e) for e in entries))
check("buttons show installed", all(c.button.text().startswith("Installed") and not c.button.isEnabled() for c in d.cards))
check("install-all button turns off", not d.all.isEnabled())
d.cards[0]._remove()
check("remove from a card", len(exts.items) == 8 and d.cards[0].button.text() == "Install" and d.all.isEnabled())
d.reject()
check("closing reloads the tab after changes", win.reloads == 1)
check("reopened index has them", len(Extensions(exts.folder.parent).items) == 8)

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (": FAILED " + ", ".join(failed) if failed else ""))
sys.exit(1 if failed else 0)

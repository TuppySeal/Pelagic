"""Address bar autocomplete: inline completion, history/bookmark rows, search suggestions, and the on/off setting.

Run:  python tests/autocomplete_test.py          (add --visible to show the window)
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_autocomplete_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser import omnibox  # noqa: E402
from atlasbrowser.omnibox import VALUE, inline_completion, parse_suggestions, strip_url  # noqa: E402


class Suggest(BaseHTTPRequestHandler):
    def do_GET(self):
        q = self.path.split("q=", 1)[-1]
        body = json.dumps([q, [q + " weather", q + " recipes", "unrelated"]]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def rows(win):
    m = win.omnibox.model
    return [(m.item(i).text(), m.item(i).data(VALUE)) for i in range(m.rowCount())]


def main():
    # pure helpers
    check("strip_url drops scheme and www", strip_url("https://www.github.com/x") == "github.com/x")
    urls = ["https://github.com/anthropics/claude", "https://www.google.com/"]
    check("completes to the end of the host", inline_completion("git", urls) == "hub.com")
    check("then to the next path segment", inline_completion("github.com/", urls) == "anthropics")
    check("www and scheme are skipped", inline_completion("goo", urls) == "gle.com")
    check("no completion for searches with spaces", inline_completion("git hub", urls) == "")
    check("no completion when nothing matches", inline_completion("zzz", urls) == "")
    check("parses OpenSearch suggestions", parse_suggestions(b'["a",["ab","ac"]]') == ["ab", "ac"])
    check("bad suggestion data is ignored", parse_suggestions(b"<html>") == [])

    server = HTTPServer(("127.0.0.1", 0), Suggest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for k in list(omnibox.SUGGEST):
        omnibox.SUGGEST[k] = f"http://127.0.0.1:{server.server_port}/?q=%s"

    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    store.add_history("https://github.com/anthropics/claude", "Anthropic on GitHub")
    store.add_history("https://github.com/anthropics/claude", "Anthropic on GitHub")
    store.add_history("https://news.ycombinator.com/", "Hacker News")
    store.toggle_bookmark("https://gitlab.com/", "GitLab")
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, ["about:blank"])
    win.activateWindow()
    pump(800)
    addr = win.addr

    check("autocomplete is on by default", store.get("autocomplete") is True)
    addr.setFocus()
    addr.clear()
    QTest.keyClicks(addr, "git")
    pump(100)
    check("inline completion fills in the most visited site", addr.text() == "github.com", addr.text())
    check("the completed part is selected so typing replaces it", addr.selectedText() == "hub.com", addr.selectedText())
    r = rows(win)
    check("first row is what you typed", r and r[0][1] == "github.com", str(r))
    check("history row shown with its title", any("Anthropic on GitHub" in t for t, _ in r), str(r))
    check("bookmark row shown", any(v == "https://gitlab.com/" for _, v in r), str(r))
    check("drop-down is open", win.omnibox.completer.popup().isVisible())

    QTest.keyClick(addr, Qt.Key_Backspace)
    pump(50)
    check("Backspace removes the completion instead of re-adding it", addr.text() == "git", addr.text())

    addr.clear()
    QTest.keyClicks(addr, "pasta")
    pump(600)
    r = rows(win)
    check("first row offers a search", r and "Search" in r[0][0], str(r))
    check("search engine suggestions appear", any(v == "pasta recipes" for _, v in r), str(r))
    popup = win.omnibox.completer.popup()
    idx = next(i for i, (_, v) in enumerate(r) if v == "pasta recipes")
    popup.setCurrentIndex(win.omnibox.model.index(idx, 0))
    pump(50)
    check("highlighting a row puts it in the address bar", addr.text() == "pasta recipes", addr.text())
    loads = []
    tab = win.current_tab()
    orig = tab.load
    tab.load = lambda url: loads.append(url.toString())
    QTest.keyClick(popup, Qt.Key_Return)
    pump(100)
    check("Enter on a suggestion searches it once", len(loads) == 1 and "pasta recipes" in loads[0].replace("%20", " "), str(loads))
    check("drop-down closes after picking", not popup.isVisible())
    tab.load = orig

    # turned off
    store.set("autocomplete", False)
    addr.setFocus()
    addr.clear()
    QTest.keyClicks(addr, "git")
    pump(600)
    check("off: no inline completion", addr.text() == "git", addr.text())
    check("off: no drop-down", not popup.isVisible())
    store.set("autocomplete", True)

    from atlasbrowser.dialogs import SettingsDialog
    dlg = SettingsDialog(store, win, win=win)
    check("Settings has the autocomplete checkbox, ticked", dlg.autocomplete.isChecked())
    dlg.autocomplete.setChecked(False)
    dlg._accept()
    check("unticking it saves the setting", store.get("autocomplete") is False)
    store.set("autocomplete", True)

    win.close()
    hub.stop_all()
    server.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

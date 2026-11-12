"""The agent's type action without an id: typing a whole answer into the field that has the keyboard, such as a
rich text editor (TinyMCE-style) inside another site's frame, which has no id in the element list. Password and card
fields stay refused, and press_key explains how to enter text.

Run:  python tests/focused_typing_test.py          (add --visible to show the window)
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_typing_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OTHER = {"port": 0}
PAGES = {
    "/": lambda: (f"<title>Lesson</title><body style='margin:0'><p>Part C</p>"
                  f"<iframe id=ed src='http://localhost:{OTHER['port']}/editor' width=500 height=150></iframe>"
                  f"<iframe id=pw src='http://localhost:{OTHER['port']}/pw' width=300 height=60></iframe>"
                  f"<iframe id=cc src='http://localhost:{OTHER['port']}/card' width=300 height=60></iframe>"
                  f"<br><textarea id=plain style='width:300px;height:60px'></textarea></body>"),
    # what TinyMCE puts in its frame: an editable body
    "/editor": lambda: "<body id=tinymce contenteditable=true aria-label='Rich Text Area' "
                       "style='margin:0;height:140px'><p><br></p></body>",
    "/pw": lambda: "<body style='margin:0'><input id=p type=password style='width:280px;height:40px'></body>",
    "/card": lambda: "<body style='margin:0'><input id=c autocomplete=cc-number style='width:280px;height:40px'></body>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], lambda: "nothing")().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, secs=10):
    for _ in range(int(secs * 20)):
        if cond():
            return True
        pump(50)
    return cond()


def frame_js(tab, path, code):
    """Runs code in the child frame whose address ends with path."""
    frame = next(f for f in tab.page().mainFrame().children() if f.url().path() == path)
    out = []
    frame.runJavaScript(code, 0, lambda v: out.append(v))
    wait_until(lambda: out, 5)
    return out[0] if out else None


def centre(tab, el_id):
    out = []
    tab.page().runJavaScript(f"(r => JSON.stringify([r.left + r.width / 2, r.top + r.height / 2]))"
                             f"(document.getElementById('{el_id}').getBoundingClientRect())", 0, out.append)
    wait_until(lambda: out, 5)
    x, y = json.loads(out[0])
    return int(x), int(y)


def main():
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    OTHER["port"] = servers[1].server_port
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.agent import Agent
    from atlasbrowser.webview import BrowserTab, make_profile
    profile = make_profile(None, None, app)
    tab = BrowserTab(profile)
    tab.resize(900, 500)
    tab.show()
    tab.load(QUrl(f"http://127.0.0.1:{servers[0].server_port}/"))
    wait_until(lambda: tab.title() == "Lesson" and len(tab.page().mainFrame().children()) == 3
               and all(f.url().path() for f in tab.page().mainFrame().children()), 15)
    pump(800)

    results = []
    state = SimpleNamespace(_token=1, running=True, humanize=False, _int=lambda args: Agent._int(None, args),
                            _result=lambda text, **kw: results.append(text),
                            _finish_nav=lambda t, text: results.append(text))
    state._type_focused = lambda t, text, submit: Agent._type_focused(state, t, text, submit)
    state._type_chars = lambda t, text, done: Agent._type_chars(state, t, text, done)

    def type_text(text):
        results.clear()
        Agent._do_type(state, tab, {"text": text})
        wait_until(lambda: results, 5)
        pump(300)
        return results[-1] if results else ""

    answer = "I would not play, since my doctor said to wait a week. Café ✓"
    tab.real_click(*centre(tab, 'ed'))   # into the editor in the other site's frame
    pump(400)
    out = type_text(answer)
    got = frame_js(tab, "/editor", "document.body.innerText")
    check("typing without an id fills a rich text editor in another site's frame in one action",
          out.startswith("Typed") and (got or "").strip() == answer, f"{out!r} {got!r}")
    check("the result names the field", "Rich Text Area" in out, out)

    tab.real_click(*centre(tab, 'pw'))   # the password box
    pump(400)
    out = type_text("hunter2")
    check("a focused password box is refused", "never type passwords" in out, out)
    check("and nothing was typed into it", frame_js(tab, "/pw", "document.getElementById('p').value") == "")

    tab.real_click(*centre(tab, 'cc'))  # the card number box
    pump(400)
    out = type_text("4111111111111111")
    check("a focused card field is refused", "never type card" in out, out)
    check("and nothing was typed into it", frame_js(tab, "/card", "document.getElementById('c').value") == "")

    tab.real_click(800, 450)  # empty page area: nothing has the keyboard
    pump(400)
    out = type_text("lost words")
    check("with nothing focused it says to click the field first", "Click into the field first" in out, out)

    state.humanize = True
    tab.real_click(*centre(tab, 'ed'))
    pump(400)
    frame_js(tab, "/editor", "document.body.innerHTML='<p><br></p>'")
    tab.real_click(*centre(tab, 'ed'))
    pump(300)
    results.clear()
    Agent._do_type(state, tab, {"text": "word by word"})
    wait_until(lambda: results, 15)
    got = frame_js(tab, "/editor", "document.body.innerText")
    check("humanize mode types it letter by letter into the same editor", (got or "").strip() == "word by word",
          repr(got))

    # formatted text: pasted with its formatting, without using the user's clipboard
    state.humanize = False
    QApplication.clipboard().setText("the user's own clipboard")
    frame_js(tab, "/editor", "document.body.innerHTML='<p><br></p>'")
    tab.real_click(*centre(tab, 'ed'))
    pump(400)
    results.clear()
    state._paste_formatted = lambda t, i, text, fmt, submit: Agent._paste_formatted(state, t, i, text, fmt, submit)
    Agent._do_type(state, tab, {"text": "**Bold start** and *italic*\n\n- first point\n- second point",
                                "format": "markdown"})
    wait_until(lambda: results, 5)
    pump(300)
    got = frame_js(tab, "/editor", "document.body.innerHTML") or ""
    check("markdown is pasted with its formatting into the editor in another site's frame",
          results and results[-1].startswith("Pasted") and "markdown formatting" in results[-1] and ("<strong>Bold start</strong>" in got or "<b>Bold start</b>" in got)
          and ("<em>italic</em>" in got or "<i>italic</i>" in got) and got.count("<li") == 2, f"{results} {got[:300]}")
    check("the user's clipboard isn't touched", QApplication.clipboard().text() == "the user's own clipboard",
          QApplication.clipboard().text())
    tab.real_click(*centre(tab, 'plain'))
    pump(300)
    results.clear()
    Agent._do_type(state, tab, {"text": "<p>Hello <b>there</b></p>", "format": "html"})
    wait_until(lambda: results, 5)
    pump(300)
    out = []
    tab.page().runJavaScript("document.getElementById('plain').value", 0, out.append)
    wait_until(lambda: out, 5)
    check("a plain text box gets the text without the markup", out and out[0].strip() == "Hello there", out)
    tab.real_click(*centre(tab, 'pw'))
    pump(300)
    results.clear()
    Agent._do_type(state, tab, {"text": "**secret**", "format": "markdown"})
    wait_until(lambda: results, 5)
    check("formatted paste into a password box is refused", results and "never type passwords" in results[-1]
          and frame_js(tab, "/pw", "document.getElementById('p').value") == "", results)

    results.clear()
    Agent._do_press_key(state, SimpleNamespace(press_key=lambda k: False), {"key": "ince my doctor"})
    check("press_key with a word explains how to type text", results and 'type {"text"' in results[-1], results)

    tab.close()
    for s in servers:
        s.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

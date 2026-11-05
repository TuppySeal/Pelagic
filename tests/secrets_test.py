"""Passwords stay away from the AI: password boxes switched to plain text by a "show password" eye, code and PIN
fields, the agent's screenshots, and messages typed into the AI box that look like they hold a password.

Run:  python tests/secrets_test.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_secrets_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PAGE = """<!doctype html><title>Sign in</title><body style="background:#fff;margin:20px">
<input id=user name=username value="bob">
<input id=pw type=password name=pass value="hunter2secret" style="width:300px;height:40px;font-size:24px">
<button id=eye onclick="pw.type = pw.type == 'password' ? 'text' : 'password'">Show</button>
<input id=code name=otp value="492013">
<input id=pin aria-label="Enter your PIN" value="4821">
<input id=key autocomplete="one-time-code" value="777111">
<input id=city name=city value="Leeds">
<input id=passenger name=passenger value="Ann">
</body>"""


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, ms=8000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def js(tab, code):
    out = []
    tab.run_js(code, out.append)
    wait(lambda: out, 4000)
    return out[0] if out else None


def main():
    from atlasbrowser import pagejs, pwguard

    # ---- the message check, on its own
    flagged = ["my password is hunter2", "Password: Tr0ub4dor&3", "my pin is 4821", "the 2fa code is 492013",
               "the wifi password for home is BlueFish99", "my password is: correct horse", "pwd=abc123",
               "use this key sk-ant-api03-abcdefghijklmnopqrstuv", "open https://bob:s3cret@example.com/admin"]
    fine = ["how do I change my password?", "my password is wrong, how do I reset it?", "what is a strong password?",
            "my password is not working", "Password is case sensitive", "summarize this page", "pin this tab",
            "find me a passport photo booth", "is my password safe in Pelagic?", "the pin for the tab is at the top"]
    check("messages with a password in them are caught", all(pwguard.check(t) for t in flagged),
          str([t for t in flagged if not pwguard.check(t)]))
    check("ordinary questions about passwords are not", not any(pwguard.check(t) for t in fine),
          str([(t, pwguard.check(t)) for t in fine if pwguard.check(t)]))
    why = pwguard.check("my password is hunter2")
    check("the warning doesn't repeat the password", "hunter2" not in why and "h•" in why, why)

    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    page = Path(tempfile.mkdtemp(prefix="pelagic secrets ")) / "signin.html"
    page.write_text(PAGE, encoding="utf-8")
    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID)
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    tab.load(QUrl.fromLocalFile(str(page)))
    wait(lambda: tab.title() == "Sign in" and not tab.loading)
    pump(300)

    def snap():
        return json.loads(js(tab, pagejs.SNAPSHOT))

    def item(s, text):
        return next((it for it in s["items"] if text in it["text"]), {})

    s = snap()
    raw = json.dumps(s)
    check("the password box shows no value", "hunter2secret" not in raw and item(s, "pass").get("secret"), raw[:300])
    check("code, PIN and one-time-code fields hide their values too",
          not any(v in raw for v in ("492013", "4821", "777111")), raw[:600])
    check("ordinary fields still show theirs", '"Leeds"' in raw and '"bob"' in raw and '"Ann"' in raw)
    check("code and PIN fields are covered in screenshots (a dotted password box needs nothing)",
          len(s["masks"]) == 3, str(s["masks"]))

    js(tab, "document.getElementById('pw').type = 'text'; 1")   # the "show password" eye
    s = snap()
    raw = json.dumps(s)
    check("after Show password the password still isn't shown", "hunter2secret" not in raw, raw[:300])
    check("and it's marked to be covered in screenshots", len(s["masks"]) == 4, str(s["masks"]))
    pw_id = item(s, "pass")["i"]
    for name, tpl in (("typed into", pagejs.TYPE_TEXT), ("cleared", pagejs.FOCUS_CLEAR)):
        args = (pw_id, "x", True) if tpl is pagejs.TYPE_TEXT else (pw_id,)
        res = json.loads(js(tab, pagejs.call(tpl, *args)))
        check(f"the shown password box can't be {name} by the agent", res.get("err") == "password", str(res))
    res = json.loads(js(tab, pagejs.call(pagejs.ELEMENT_RECT, pw_id)))
    check("or aimed at", res.get("err") == "password", str(res))
    code_id = item(s, "otp")["i"]
    check("nor can a code field", json.loads(js(tab, pagejs.call(pagejs.TYPE_TEXT, code_id, "1", True))).get("err")
          == "password")
    city_id = item(s, "Leeds")["i"] if item(s, "Leeds") else item(s, "city")["i"]
    check("ordinary fields can still be typed into",
          json.loads(js(tab, pagejs.call(pagejs.TYPE_TEXT, city_id, "York", True))).get("ok") is True)
    js(tab, "document.getElementById('pw').focus(); 1")
    check("reading the focused field gives nothing for a password", js(tab, pagejs.READ_VALUE) == "")

    # the agent's screenshot: the shown password is painted over
    import base64
    b64 = tab.grab_png_b64(masks=s["masks"])
    img = QImage.fromData(base64.b64decode(b64))
    x, y, w, h = max(s["masks"], key=lambda m: m[2])   # the big password box
    scale = img.width() / tab.width()
    z = tab.zoomFactor() * scale
    centre = img.pixelColor(int((x + w / 2) * z), int((y + h / 2) * z))
    check("the agent's screenshot blacks out the shown password", centre.red() < 10 and centre.green() < 10,
          str(centre.getRgb()))
    plain = QImage.fromData(base64.b64decode(tab.grab_png_b64()))
    check("(without the mask that spot isn't black)",
          plain.pixelColor(int((x + w / 2) * z), int((y + h / 2) * z)).red() > 10)

    from atlasbrowser.agent import Agent
    from types import SimpleNamespace
    lines = Agent._format(SimpleNamespace(token_saver=False, win=win), s, tab)
    check("the agent is told to ask the user for secret fields", "use ask_user" in lines and "hunter2" not in lines)

    # ---- the AI box
    panel = win.panel
    started = []
    panel._start_agent = started.append
    panel._start_chat = started.append
    panel.input.setPlainText("log in to my bank, my password is Hunter2Secret!")
    panel.send()
    check("a message with a password isn't sent", started == [] and panel.pw_block.isVisible(), str(started))
    check("it stays in the box to edit", "Hunter2Secret" in panel.input.toPlainText())
    check("the warning hides the password", "Hunter2Secret" not in panel.pw_block_text.text(),
          panel.pw_block_text.text())
    check("there's a Send anyway button", panel.pw_send_anyway.isVisible())
    panel.pw_send_anyway.click()
    check("Send anyway sends it as written", started == ["log in to my bank, my password is Hunter2Secret!"]
          and not panel.pw_block.isVisible() and panel.input.toPlainText() == "", str(started))
    panel.busy = False
    started.clear()
    panel.input.setPlainText("pin: 4821")
    panel.send()
    panel.input.setPlainText("what's my account balance?")
    check("editing the message takes the warning away", not panel.pw_block.isVisible())
    panel.send()
    check("and a normal message sends straight away", started == ["what's my account balance?"], str(started))
    panel.busy = False
    started.clear()
    panel.send("Explain this text:\n\n> password: s3cr3tpass")
    check("text sent from the page (Ask about selection) is checked too", started == [] and panel.pw_block.isVisible())
    panel.pw_send_anyway.click()
    check("and can be sent anyway", started == ["Explain this text:\n\n> password: s3cr3tpass"], str(started))

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    os._exit(code)

"""The AI panel's "No context" option (Options and usage): only the request and the always-on instructions are
sent. Chat leaves out earlier messages, the page and notes; the agent still sees its page but keeps only its last
step. Turning it off brings everything back.

Run:  python tests/no_context_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_nocontext_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")

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


def wait_until(cond, secs=10):
    for _ in range(int(secs * 20)):
        if cond():
            return True
        pump(50)
    return cond()


def agent_checks():
    from atlasbrowser.agent import Agent
    turns = [(f'{{"action": "click", "args": {{"id": {n}}}}}', f"Clicked [{n}] \"Next\".") for n in range(1, 9)]
    turns.insert(2, ('{"action": "ask_user", "args": {}}', "The user replied: use the blue form"))
    state = SimpleNamespace(task="answer each question then press Next", turns=turns, no_context=True,
                            token_saver=True)
    state._minimal_messages = lambda obs: Agent._minimal_messages(state, obs)
    state._compact_messages = lambda obs: Agent._compact_messages(state, obs)
    msgs = Agent._messages(state, "CURRENT PAGE: question 9")
    text = "\n".join(m["content"] for m in msgs)
    check("agent with No context: task, the last step and the page only",
          len(msgs) == 4 and "TASK: answer each question" in msgs[0]["content"] and "[8]" in text
          and "[7]" not in text and msgs[-1]["content"] == "CURRENT PAGE: question 9", text)
    check("agent with No context still keeps the user's decisions", "use the blue form" in msgs[0]["content"])
    state.no_context = False
    full = "\n".join(m["content"] for m in Agent._messages(state, "CURRENT PAGE: question 9"))
    check("agent without it keeps earlier steps", "[7]" in full and len(full) > len(text))


def main():
    agent_checks()
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import providers
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    store = Store()
    store.set("core_instructions", "Always answer in French.")
    sent = []

    def fake_chat(p, key, msgs, system="", **kw):
        sent.append((list(msgs), system))
        return f"answer {len(sent)}"
    providers.chat = fake_chat
    hub = ProfileHub(app, store, Browser)
    page = Path(tempfile.mkdtemp()) / "page.html"
    page.write_text("<title>Quiz</title><p>SECRET-PAGE-TEXT about vectors</p>", encoding="utf-8")
    win = hub.open_profile(DEFAULT_ID, [page.as_uri()])
    win.resize(1200, 750)
    win.show()
    tab = win.current_tab()
    wait_until(lambda: not tab.loading and tab.title() == "Quiz", 10)
    panel = win.panel
    panel.provider_box.setCurrentIndex(panel.provider_box.findData("ollama"))   # needs no key
    panel.set_mode("chat")

    def ask(text):
        n = len(sent)
        panel.input.setPlainText(text)
        panel.send()
        wait_until(lambda: len(sent) > n and not panel.busy, 10)
        return sent[-1] if len(sent) > n else ([], "")

    ask("first question")
    msgs, system = ask("second question")
    check("normally chat sends earlier messages and the page",
          len(msgs) >= 3 and "SECRET-PAGE-TEXT" in system, f"{len(msgs)} {system[-200:]}")

    panel.no_context.setChecked(True)
    check("the option is saved", store.get("no_context") is True)
    check("page and notes options are greyed out while it's on",
          not panel.page_ctx.isEnabled() and not panel.use_memory.isEnabled())
    msgs, system = ask("third question")
    check("No context: only my message is sent", [m["content"] for m in msgs] == ["third question"], msgs)
    check("No context: no page text", "SECRET-PAGE-TEXT" not in system)
    check("No context: always-on instructions still sent", "Always answer in French." in system)

    panel.no_context.setChecked(False)
    msgs, system = ask("fourth question")
    check("turned off, context comes back", len(msgs) >= 3 and "SECRET-PAGE-TEXT" in system)

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Always-on instruction sets (one per activity, switched and paused from the AI panel) and the agent's tab group
actions (group_tabs, group_by_site, ungroup_tabs).

Run:  python tests/instruction_sets_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_sets_test_")
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


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import context
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    store = Store()
    store.set("core_instructions", "Old single instructions.")
    check("an existing single text becomes the first set",
          [s["name"] for s in context.instruction_sets(store)] == ["My instructions"]
          and "Old single instructions." in context.core_system(store))
    context.save_sets(store, [{"name": "Homework", "text": "Show your working."},
                              {"name": "Shopping", "text": "Compare prices in GBP."}], "Homework")
    check("the active set is sent", "Show your working." in context.core_system(store)
          and "Compare prices" not in context.core_system(store))

    hub = ProfileHub(app, store, Browser)
    page = Path(tempfile.mkdtemp())
    urls = []
    for n, title in enumerate(["Maths", "Physics", "Shoes", "Socks"]):
        f = page / f"p{n}.html"
        f.write_text(f"<title>{title}</title><p>{title}</p>", encoding="utf-8")
        urls.append(f.as_uri())
    win = hub.open_profile(DEFAULT_ID, urls)
    win.resize(1200, 750)
    win.show()
    wait_until(lambda: [t.title() for t in win.tab_list()] == ["Maths", "Physics", "Shoes", "Socks"], 10)
    panel = win.panel

    check("the panel shows the sets with the active one picked",
          [panel.core_box.itemText(i) for i in range(panel.core_box.count())] == ["Homework", "Shopping"]
          and panel.core_box.currentText() == "Homework" and panel.core_on.isChecked())
    panel.core_box.setCurrentIndex(1)
    panel._core_picked(1)
    check("switching sets in the panel changes what's sent", store.get("core_active") == "Shopping"
          and "Compare prices in GBP." in context.core_system(store) and "Show your working" not in context.core_system(store))
    panel.core_on.setChecked(False)
    check("unticking Always-on pauses them", context.core_system(store) == "" and store.get("core_enabled") is False)
    check("but keeps the sets", len(context.instruction_sets(store)) == 2)
    panel.core_on.setChecked(True)
    check("ticking it again brings them back", "Compare prices in GBP." in context.core_system(store))

    from atlasbrowser.panel import CoreSetsDialog
    dlg = CoreSetsDialog(store, panel)
    dlg._add("Reading")
    dlg.editor.setPlainText("Summarise in three bullet points.")
    dlg.commit()
    panel._refresh_core()
    check("a new set from the editor is saved and used",
          store.get("core_active") == "Reading" and "three bullet points" in context.core_system(store)
          and panel.core_box.count() == 3 and panel.core_box.currentText() == "Reading")
    check("older versions still see the set in use", store.get("core_instructions") == "Summarise in three bullet points.")

    # ---------------------------------------------------------------- the agent groups tabs
    from atlasbrowser.agent import Agent
    results = []

    class A:
        pass
    ag = A()
    ag.win = win
    ag._int = lambda args, key="id": Agent._int(None, args, key)
    ag._result = lambda text, **kw: results.append(text)
    Agent._do_group_tabs(ag, win.current_tab(), {"tabs": [0, 1], "name": "School", "color": "green"})
    strip = win.strip
    gid = next((g for g, v in strip.groups.items() if v["name"] == "School"), None)
    tabs = win.tab_list()
    check("group_tabs makes a named group", gid and [getattr(t, "_group", None) for t in tabs[:2]] == [gid, gid]
          and strip.groups[gid]["color"] == "#4fae6e", results)
    Agent._do_group_tabs(ag, win.current_tab(), {"tabs": [2, 3], "name": "Shopping"})
    Agent._do_group_tabs(ag, win.current_tab(), {"tabs": [3], "name": "school"})
    check("an existing group name adds to it", getattr(win.tab_list()[-1], "_group", None) == gid
          or sum(getattr(t, "_group", None) == gid for t in win.tab_list()) == 3, results)
    Agent._do_ungroup_tabs(ag, win.current_tab(), {"name": "Shopping"})
    check("ungroup_tabs dissolves a group", not any(v["name"] == "Shopping" for v in strip.groups.values()))
    Agent._do_group_tabs(ag, win.current_tab(), {"tabs": [], "name": "x"})
    check("group_tabs without tabs explains itself", "needs" in results[-1])

    ag2 = Agent.__new__(Agent)
    ag2.win = win
    obs = Agent._format(ag2, None, win.current_tab())
    check("the agent sees which group each tab is in", "{group: School}" in obs, obs[:300])

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

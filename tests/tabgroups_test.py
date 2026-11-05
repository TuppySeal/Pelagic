"""Sorting tabs into groups by site ("Group tabs by site", and "Keep tabs grouped by site" in the menu).

Run:  python tests/tabgroups_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_tabgroups_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.tabstrip import site_name, site_of
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    check("sites are matched by their main address", site_of(QUrl("https://classroom.google.com/u/0"))
          == site_of(QUrl("https://docs.google.com/x")) == "google.com"
          and site_of(QUrl("https://www.bbc.co.uk/news")) == "bbc.co.uk" and site_of(QUrl("about:blank")) == "")
    check("and get readable names", site_name("github.com") == "GitHub" and site_name("google.com") == "Google")

    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID)
    win.show()
    strip = win.strip
    pages = {"a": "https://classroom.google.com/", "b": "https://github.com/x", "c": "https://docs.google.com/d",
             "d": "https://www.wikipedia.org/", "e": "https://github.com/y", "f": "https://mail.google.com/"}
    tabs = {}
    for k, u in pages.items():
        t = win.open_tab()
        t.url = lambda u=u: QUrl(u)   # no network here: each tab just says which site it's on
        tabs[k] = t
    pump(200)
    first = win.tab_list()[0]
    first.url = lambda: QUrl("about:blank")

    labels = [a.text() for a in win.menu_btn.menu().actions()]
    check("the menu has Group tabs by site and the keep-grouped switch",
          "Group tabs by site" in labels and "Keep tabs grouped by site" in labels, str(labels))
    check("so does a tab's right-click menu",
          "Group tabs by site" in [a.text() for a in strip.tab_menu(tabs["a"]).actions()])

    moved = strip.group_by_site()
    groups = {g["name"]: gid for gid, g in strip.groups.items()}
    check("tabs from the same site end up in one group", set(groups) == {"Google", "GitHub"}
          and moved == 5, str((groups, moved)))
    check("all three Google tabs are together", [getattr(tabs[k], "_group", None) for k in "acf"]
          == [groups.get("Google")] * 3)
    order = win.tab_list()
    g = [order.index(tabs[k]) for k in "acf"]
    check("next to each other in the tab bar", max(g) - min(g) == 2, str(g))
    check("a site with only one tab stays ungrouped", getattr(tabs["d"], "_group", None) is None)
    check("pages that aren't websites stay ungrouped", getattr(first, "_group", None) is None)

    mine = strip.new_group([tabs["d"]], name="Homework")
    strip.add_to_group(tabs["b"], mine)
    strip.group_by_site()
    check("a group you made yourself is left alone", getattr(tabs["b"], "_group", None) == mine
          and strip.groups[mine]["name"] == "Homework")
    check("and a site group left with one tab goes away", "GitHub" not in [g["name"] for g in strip.groups.values()]
          and getattr(tabs["e"], "_group", None) is None, str([g["name"] for g in strip.groups.values()]))

    strip.leave_auto_group(tabs["f"])
    strip.group_by_site()
    check("a tab you take out of a site group isn't put back", getattr(tabs["f"], "_group", None) is None
          and getattr(tabs["a"], "_group", None) is not None)

    tabs["c"].url = lambda: QUrl("https://www.wikipedia.org/wiki/Tea")
    strip.group_by_site()
    check("a tab that moves to another site leaves its old site's group",
          strip.groups.get(getattr(tabs["c"], "_group", None), {}).get("auto") != "google.com")

    # keep grouped: a newly loaded page joins its site's group
    win.set_auto_group(True)
    g = win.open_tab()
    g.url = lambda: QUrl("https://sites.google.com/new")
    win._finished(g, True)
    pump(700)
    check("with Keep tabs grouped on, a new Google tab joins the Google group",
          getattr(g, "_group", None) is not None and getattr(g, "_group", None) == getattr(tabs["a"], "_group", None))
    check("the setting is remembered", store.get("auto_group_tabs") is True)
    win.set_auto_group(False)
    h = win.open_tab()
    h.url = lambda: QUrl("https://maps.google.com/")
    win._finished(h, True)
    pump(700)
    check("with it off, nothing moves by itself", getattr(h, "_group", None) is None)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    os._exit(code)

"""Profiles: separate history/bookmarks/passwords/cookies per profile, shared API keys and AI settings, switching.

Run:  python tests/profiles_test.py          (add --visible to show the windows)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_profiles_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser.profiles import DEFAULT_ID, Profiles  # noqa: E402
from atlasbrowser.store import Store  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _close(img, color):
    """Some pixel of the icon is (anti-aliased) the profile colour."""
    from PySide6.QtGui import QColor
    want = QColor(color)
    return any(abs(img.pixelColor(x, y).red() - want.red()) + abs(img.pixelColor(x, y).green() - want.green())
               + abs(img.pixelColor(x, y).blue() - want.blue()) < 12 and img.pixelColor(x, y).alpha() > 200
               for x in range(img.width()) for y in range(img.height()))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import ProfileHub
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    root = Store()
    root.set_key("openai", "shared-key")
    root.set("selected", "openai")
    root.add_history("https://personal.example/", "Personal page")
    root.set("session", ["https://personal.example/"])
    hub = ProfileHub(app, root, Browser)
    check("existing data becomes the first profile", [p["name"] for p in hub.profiles.items] == ["Personal"])
    personal = hub.open_profile(DEFAULT_ID, ["about:blank"])
    check("profile button shows icon", personal.profile_btn is not None and not personal.profile_btn.icon().isNull())
    check("single profile: plain title", personal.windowTitle().endswith("Pelagic"), personal.windowTitle())

    work_id = hub.profiles.add("Work")["id"]
    work = hub.open_profile(work_id, ["about:blank"])
    wctx, pctx = hub.context(work_id), hub.context(DEFAULT_ID)
    pump(200)
    check("work profile has its own folder", wctx.store.root == root.root / "profiles" / work_id)
    check("separate web engine storage (own cookies and sign-ins)",
          wctx.profile.persistentStoragePath() != pctx.profile.persistentStoragePath()
          and wctx.profile.storageName() != pctx.profile.storageName())
    check("first profile keeps its original engine storage", pctx.profile.storageName() == "AtlasBrowser")
    check("API keys shared", wctx.store.get_key("openai") == "shared-key")
    wctx.store.set_key("anthropic", "added-from-work")
    check("keys added in one profile reach the others", Store(root.root).get_key("anthropic") == "added-from-work")
    check("AI settings shared", wctx.store.get("selected") == "openai")
    wctx.store.set("max_steps", 77)
    check("AI setting changed in Work applies to Personal", root.get("max_steps") == 77)
    check("history separate", wctx.store.history() == [] and len(root.history()) == 1)
    wctx.store.toggle_bookmark("https://work.example/", "Work")
    check("bookmarks separate", wctx.store.bookmarks and not root.bookmarks)
    wctx.passwords.store.add("https://jira.example", "me@work", "w-pass")
    check("passwords separate", pctx.passwords.store.for_origin("https://jira.example") == []
          and wctx.passwords.store.find("https://jira.example", "me@work") is not None)
    wctx.store.set("search_engine", "google")
    check("browser settings separate", root.get("search_engine") == "duckduckgo")
    check("titles name the profile once there are two", "(Work)" in work.windowTitle() and
          "(Personal)" in (personal.refresh_profile() or personal.windowTitle()), work.windowTitle())

    # switching from the menu and the session restore
    personal._fill_profile_menu()
    labels = [a.text() for a in personal.profile_menu.actions()]
    check("switcher lists the other profile", "Open Work" in labels, str(labels))
    check("switcher offers add and manage", "Add profile…" in labels and "Manage profiles…" in labels)
    again = hub.open_profile(work_id)
    check("opening an open profile reuses its window", again is work)
    hub.window_activated(wctx)
    check("last used profile remembered", Profiles(root.root).last == work_id)

    # rename / recolor
    hub.profiles.update(work_id, name="Job", color="#2f9e6e")
    work.refresh_profile()
    check("rename updates the button", "Job" in work.profile_btn.toolTip() and
          _close(work.profile_btn.icon().pixmap(20, 20).toImage(), "#2f9e6e"))

    # restart: profiles persist, sessions restore per profile
    work.close()
    pump(100)
    check("work session saved in its own folder", Store(root.root / "profiles" / work_id).get("session") is not None)

    # delete
    folder = root.root / "profiles" / work_id
    hub.delete_profile(work_id)
    pump(200)
    check("deleted profile disappears", hub.profiles.get(work_id) is None)
    Profiles(root.root).purge_pending()
    # On Windows this same run still holds the deleted profile's browser files open, so its folder can't go yet;
    # it then has to stay queued until the next start. A folder nothing has open is erased straight away.
    check("its folder is erased on next start, or stays queued while it's still open",
          not folder.exists() or work_id in Profiles(root.root).pending_delete)
    idle = root.root / "profiles" / "idle-test"
    (idle / "sub").mkdir(parents=True)
    (idle / "sub" / "file.txt").write_text("x")
    queued = Profiles(root.root)
    queued.pending_delete.append("idle-test")
    queued._save()
    Profiles(root.root).purge_pending()
    check("a queued folder nothing has open is erased on start", not idle.exists()
          and "idle-test" not in Profiles(root.root).pending_delete)
    try:
        hub.profiles.remove(DEFAULT_ID)
        check("first profile can't be deleted", False)
    except ValueError:
        check("first profile can't be deleted", True)

    # private windows still work per profile
    pw = pctx.new_window(private=True)
    check("private window is off the record", pw.profile.isOffTheRecord())
    pw.close()
    personal.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

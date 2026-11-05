"""Folder sync between two computers (two profile folders sharing one sync folder).

Run:  python tests/sync_test.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_sync_home_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from atlasbrowser import sync  # noqa: E402
from atlasbrowser.autofill import AutofillStore  # noqa: E402
from atlasbrowser.passwords import PasswordStore  # noqa: E402
from atlasbrowser.store import Store  # noqa: E402


def computer(shared: Path, name: str):
    root = Path(tempfile.mkdtemp(prefix=f"atlas_sync_{name}_"))
    st = Store(root)
    st.set("sync_folder", str(shared))
    ps, af = PasswordStore(root), AutofillStore(root)
    fs = sync.FolderSync(st, "default", sync.Collections(st, ps, af))
    return st, ps, af, fs


def main():
    # -------- encryption
    key = sync.derive_key("correct horse", b"0123456789abcdef")
    blob = sync.seal(b"secret stuff" * 100, key)
    check("sealed data opens with the right key", sync.unseal(blob, key) == b"secret stuff" * 100)
    check("the sealed data doesn't contain the plain text", b"secret" not in blob.encode())
    try:
        sync.unseal(blob, sync.derive_key("wrong", b"0123456789abcdef"))
        check("a wrong passphrase is refused", False)
    except ValueError:
        check("a wrong passphrase is refused", True)
    raw = bytearray(__import__("base64").b64decode(blob))
    raw[-1] ^= 1
    try:
        sync.unseal(__import__("base64").b64encode(bytes(raw)).decode(), key)
        check("tampering is detected", False)
    except ValueError:
        check("tampering is detected", True)

    # -------- two computers
    shared = Path(tempfile.mkdtemp(prefix="atlas_sync_drive_"))
    a, pa, fa, sa = computer(shared, "a")
    b, pb, fb, sb = computer(shared, "b")
    a.add_bookmark("https://a.example/", "A site", "Work")
    a.add_folder("Work")
    a.add_to_reading_list("https://read.example/", "To read")
    a.add_history("https://visited.example/", "Visited on A")
    b.add_bookmark("https://b.example/", "B site")
    sa.run()
    report = sb.run()
    check("B gets A's bookmarks and folders", b.is_bookmarked("https://a.example/") and "Work" in b.all_folders()
          and b.bookmarks_in("Work")[0]["url"] == "https://a.example/", str(b.bookmarks))
    check("and its reading list and history", b.reading_list()[0]["url"] == "https://read.example/"
          and b.history("visited")[0][0] == "https://visited.example/")
    check("the report says what happened", "1 other computer" in report and "brought in" in report, report)
    sa.run()
    check("A gets B's bookmark", a.is_bookmarked("https://b.example/"))
    check("each computer writes only its own file", len(list((shared / "Pelagic Sync" / "default").glob("*.json"))) == 2)

    # edits and deletions travel; the newest change wins
    time.sleep(0.01)
    b.edit_bookmark("https://a.example/", title="Renamed on B")
    b.update_reading_list("https://read.example/", read=True)
    a.remove_bookmark("https://b.example/")
    a.delete_history(["https://visited.example/"])
    sb.run()
    sa.run()
    sb.run()
    check("a rename on B shows on A", next(x for x in a.bookmarks if x["url"] == "https://a.example/")["title"]
          == "Renamed on B")
    check("marking read on B shows on A", a.reading_list()[0]["read"] is True)
    check("a deleted bookmark is deleted on both", not a.is_bookmarked("https://b.example/")
          and not b.is_bookmarked("https://b.example/"))
    check("deleted history is deleted on both", not b.history("visited"))
    sa.run()
    sb.run()
    check("deleted things don't come back", not a.is_bookmarked("https://b.example/") and not b.history("visited"))
    b.add_bookmark("https://b.example/", "B again")
    sb.run()
    sa.run()
    check("re-adding after a delete works", a.is_bookmarked("https://b.example/"))

    # -------- passwords and cards only with the passphrase
    pa.add("https://bank.example", "ada", "pa55-word-A")
    fa.save("cards", {"cc_number": "4242424242424242", "cc_name": "Ada", "cc_month": "7", "cc_year": "2029"})
    fa.save("addresses", {"name": "Ada Lovelace", "street": "12 Analytical St", "city": "Springfield"})
    sa.run()
    sb.run()
    check("without a passphrase passwords don't sync", not pb.logins() and not fb.items("cards"))
    files = "".join(p.read_text() for p in (shared / "Pelagic Sync" / "default").glob("*"))
    check("and never appear in the sync folder", "pa55-word-A" not in files and "4242424242424242" not in files)
    a.set("sync_secrets", True)
    check("setting the passphrase on A", sa.set_passphrase("our shared phrase") == "")
    b.set("sync_secrets", True)
    check("a different passphrase on B is refused",
          sb.set_passphrase("something else") != "" and sb.vault_key() is None)
    check("the same one is accepted", sb.set_passphrase("our shared phrase") == "")
    sa.run()
    sb.run()
    check("then passwords sync", [(x["username"], x["password"]) for x in pb.logins()] == [("ada", "pa55-word-A")])
    check("and cards and addresses", fb.items("cards")[0]["cc_number"] == "4242424242424242"
          and fb.items("addresses")[0]["street"] == "12 Analytical St")
    files = "".join(p.read_text() for p in (shared / "Pelagic Sync" / "default").glob("*"))
    check("still encrypted in the folder", "pa55-word-A" not in files and "4242424242424242" not in files
          and "Analytical" not in files)
    check("the passphrase isn't stored in the folder", "our shared phrase" not in files)
    pb.update(pb.logins()[0]["id"], password="changed-on-B")
    sb.run()
    sa.run()
    check("a password changed on B updates A", pa.logins()[0]["password"] == "changed-on-B")
    pa.delete(pa.logins()[0]["id"])
    sa.run()
    sb.run()
    check("a deleted password is deleted on B", not pb.logins())
    check("no duplicates after many rounds", (sa.run(), sb.run(), len(b.bookmarks), len(fb.items("cards")))[2:]
          == (len(a.bookmarks), 1))

    # a half-written file from the cloud drive is skipped, not fatal
    (shared / "Pelagic Sync" / "default" / "zzz.json").write_text("{not json")
    try:
        sa.run()
        check("a broken file in the folder is skipped", True)
    except Exception as e:
        check("a broken file in the folder is skipped", False, str(e))
    state = json.loads((a.root / "sync_state.json").read_text())
    check("local sync state is kept per profile", "bookmarks" in state and "logins" in state)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

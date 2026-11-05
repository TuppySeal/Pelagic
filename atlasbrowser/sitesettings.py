"""Site permissions page: every site you've allowed or blocked (location, camera, microphone, notifications,
clipboard…), with a switch to allow, block or ask again next time. Answers to the permission prompt are remembered
by the browser engine; this page is where they can be changed."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePermission
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

T = QWebEnginePermission.PermissionType
S = QWebEnginePermission.State
NAMES = {
    T.Geolocation: "Location",
    T.MediaAudioCapture: "Microphone",
    T.MediaVideoCapture: "Camera",
    T.MediaAudioVideoCapture: "Camera and microphone",
    T.Notifications: "Notifications",
    T.ClipboardReadWrite: "Clipboard",
}
for _name, _label in (("DesktopVideoCapture", "Screen sharing"), ("DesktopAudioVideoCapture", "Screen and audio sharing"),
                      ("MouseLock", "Pointer lock"), ("LocalFontsAccess", "Local fonts")):
    if hasattr(T, _name):
        NAMES[getattr(T, _name)] = _label
CHOICES = [("Allow", S.Granted), ("Block", S.Denied), ("Ask", S.Ask)]


def site_of(perm) -> str:
    o = perm.origin()
    return o.host() or o.toString()


class SitePermissionsDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Site permissions")
        self.resize(620, 460)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sites")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Site / permission", "Setting"])
        self.tree.setColumnWidth(0, 380)
        reset = QPushButton("Reset this site")
        reset.setToolTip("Forget every choice for the selected site; it will ask again")
        reset.clicked.connect(self.reset_site)
        note = QLabel("Sites ask before using these. Your answers are remembered here.")
        note.setObjectName("muted")
        row = QHBoxLayout()
        row.addWidget(note, 1)
        row.addWidget(reset)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self.reload()

    def permissions(self) -> list:
        out = []
        for p in self.profile.listAllPermissions():
            if p.isValid() and p.permissionType() in NAMES and p.state() != S.Ask:
                out.append(p)
        return out

    def reload(self, *_):
        self.tree.clear()
        q = self.search.text().strip().lower()
        sites: dict[str, list] = {}
        for p in self.permissions():
            site = site_of(p)
            if not q or q in site.lower():
                sites.setdefault(site, []).append(p)
        for site in sorted(sites):
            head = QTreeWidgetItem([site])
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setData(0, 256, site)
            self.tree.addTopLevelItem(head)
            for p in sorted(sites[site], key=lambda p: NAMES[p.permissionType()]):
                it = QTreeWidgetItem([NAMES[p.permissionType()]])
                it.setData(0, 256, site)
                head.addChild(it)
                box = QComboBox()
                for label, state in CHOICES:
                    box.addItem(label, state)
                box.setCurrentIndex(next(i for i, (_l, s) in enumerate(CHOICES) if s == p.state()))
                box.currentIndexChanged.connect(lambda _i, b=box, perm=p: self.set_state(perm, b.currentData()))
                self.tree.setItemWidget(it, 1, box)
            head.setExpanded(True)
        if not sites:
            empty = QTreeWidgetItem(["No sites yet. When a site asks for your camera, location and so on, "
                                     "your answer shows here."])
            empty.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(empty)

    def set_state(self, perm, state):
        fresh = self.profile.queryPermission(QUrl(perm.origin()), perm.permissionType())
        if state == S.Granted:
            fresh.grant()
        elif state == S.Denied:
            fresh.deny()
        else:
            fresh.reset()

    def reset_site(self):
        it = self.tree.currentItem()
        site = it.data(0, 256) if it is not None else None
        if not site:
            return
        for p in self.permissions():
            if site_of(p) == site:
                self.profile.queryPermission(QUrl(p.origin()), p.permissionType()).reset()
        self.reload()

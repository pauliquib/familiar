# Editor familiárů (skinů) a jejich animací – záložka Editor v dialogu nastavení.
#
# Kreslí po pixelech do snímků všech vrstev skinu (postava a její efekty fx, výrazy nálad,
# klobouky, reakce, drony), spravuje animace (tagy: snímky, fps, jednorázovost, směr),
# palety, přiřazení animací ke stavům činnosti a nálady, kotvy obličeje a klobouku
# a metadata skinu. Živý náhled kreslí stejný kód jako daemon (skin_edit.SkinDoc.to_skin →
# skin.PackageSkin), takže co je v náhledu, to bude na postavičce.
#
# Data drží skin_edit (bez Qt); tady je jen rozhraní. Ukládá se tlačítkem „Uložit skin“
# do ~/.local/share/familiar/skins/<id>/ (skin z balíčku jako uživatelská kopie se stejným
# id); běžící familiar zvolený skin po uložení načte sám. Zpět/Znovu drží kopie dokumentu.
#
#   python3 -m familiar.editor [id]      # editor samostatně (bez dialogu nastavení)
import os, sys, time

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPen,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from familiar import paths, skin, skin_edit, sprites
from familiar.skin import NONE, SkinError
from familiar.skin_edit import LAYER_NAMES, LAYER_ORDER

TOOLS = [   # (klíč, text, zkratka, nápověda)
    ("pencil", "Tužka", "B", "kreslí zvolenou barvou; pravé tlačítko maže"),
    ("eraser", "Guma", "E", "maže do průhledna (u překryvných vrstev „nic“)"),
    ("fill", "Výplň", "G", "vyplní souvislou plochu stejné barvy"),
    ("picker", "Kapátko", "I", "vezme barvu z plátna"),
    ("line", "Čára", "L", "úsečka tažením"),
    ("rect", "Obdélník", "R", "obrys obdélníku tažením"),
    ("anchor", "Kotva", "K", "klik posadí levý horní roh řezu (oči, pusa, hlava) na snímku; "
                             "se Shiftem na všech snímcích animace"),
]
SLICE_COLORS = {"eyes": "#3fb8ff", "mouth": "#ff9f43", "head": "#4cd964"}
SLICE_NAMES = {"eyes": "oči", "mouth": "pusa", "head": "hlava (klobouk)"}
STATE_NAMES = {"idle": "nečinnost (idle)", "listening": "poslouchá (prompt)", "thinking": "přemýšlí",
               "waiting": "čeká na povolení", "success": "hotovo", "error": "chyba", "sleeping": "spí",
               "gone": "odchází", "walking": "procházka (chůze)"}
TOOL_NAMES = {"Bash": "práce – Bash", "Edit": "práce – Edit/Write", "Read": "práce – Read/Grep/web",
              "default": "práce – ostatní nástroje"}
MOOD_NAMES = {"klid": "klid", "radost": "radost", "zvedavost": "zvědavost", "frustrace": "frustrace",
              "zmatek": "zmatek", "unava": "únava"}
SUGGEST = {     # návrhy jmen nových animací podle vrstvy
    "body": ["idle", "listen", "think", "work_bash", "work_edit", "work_search", "wave", "hop", "stumble",
             "sleep", "walk"],
    "face": [f"eyes_{e}" for e in sprites.EYES] + [f"mouth_{m}" for m in ("smile", "o", "frown", "wave")],
    "acc": list(sprites.HATS),
    "emote": list(sprites.POPS),
    "drone": ["drone1", "drone2", "drone3"],
}
UNDO_MAX = 80
CHECKER = (QColor("#3b3b46"), QColor("#30303a"))


def obraz(px, colors, size, overlay=False):
    """QImage ze snímku (indexy palety); index 0 překryvné vrstvy (vyříznout) je poloprůhledná magenta."""
    w, h = size
    lut = [b"\0\0\0\0"] * 256
    for k, c in enumerate(colors):
        if k and c:
            r, g, b = bytes.fromhex(c[1:])
            lut[k] = bytes((b, g, r, 255))
    if overlay:
        lut[0] = bytes((255, 0, 255, 150))
    buf = b"".join(lut[v] for v in px)
    return QImage(buf, w, h, w * 4, QImage.Format.Format_ARGB32).copy()


def _checker(painter, rect, cell):
    pm = QPixmap(cell * 2, cell * 2)
    pm.fill(CHECKER[0])
    p = QPainter(pm)
    p.fillRect(0, 0, cell, cell, CHECKER[1])
    p.fillRect(cell, cell, cell, cell, CHECKER[1])
    p.end()
    painter.fillRect(rect, QBrush(pm))


# --- plátno --------------------------------------------------------------------------

class Platno(QWidget):
    """Zvětšený snímek, do kterého se kreslí; data a nástroj bere z editoru."""

    def __init__(self, ed):
        super().__init__()
        self.ed = ed
        self.zoom = 14
        self.grid = self.onion = self.underlay = True
        self._stroke = None         # (tlačítko, poslední bod, záloha pixelů pro čáru / obdélník, start)
        self.hover = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def obnov(self):
        w, h = self.ed.doc.size if self.ed.doc else (32, 32)
        self.setFixedSize(w * self.zoom, h * self.zoom)
        self.update()

    def _bod(self, ev):
        p = ev.position()
        return int(p.x() // self.zoom), int(p.y() // self.zoom)

    def paintEvent(self, _):
        ed, z = self.ed, self.zoom
        p = QPainter(self)
        _checker(p, self.rect(), max(4, z // 2))
        fr = ed.frame()
        if not fr:
            p.setPen(QColor("#aaa"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Žádný snímek.\nPřidej animaci vlevo.")
            return
        size, colors = ed.doc.size, ed.zobrazena_paleta()
        target = QRect(0, 0, size[0] * z, size[1] * z)
        if self.underlay:
            under = ed.podklad()
            if under is not None:
                px, dx, dy = under
                p.setOpacity(0.35)
                p.drawImage(target.translated(dx * z, dy * z), obraz(px, colors, size))
        if self.onion and ed.snimek > 0:
            prev = ed.anim().frames[ed.snimek - 1]
            p.setOpacity(0.3)
            p.drawImage(target, obraz(ed.cil(prev), colors, size, ed.overlay()))
        p.setOpacity(1.0)
        if ed.kreslim_fx():
            p.setOpacity(0.45)
            p.drawImage(target, obraz(fr.px, colors, size))
            p.setOpacity(1.0)
        p.drawImage(target, obraz(ed.cil(fr), colors, size, ed.overlay()))
        if ed.vrstva == "body" and not ed.kreslim_fx() and fr.fx is not None and ed.ukazat_fx.isChecked():
            p.setOpacity(0.6)
            p.drawImage(target, obraz(fr.fx, colors, size, True))
            p.setOpacity(1.0)
        if self.grid and z >= 6:
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            for x in range(1, size[0]):
                p.drawLine(x * z, 0, x * z, size[1] * z)
            for y in range(1, size[1]):
                p.drawLine(0, y * z, size[0] * z, y * z)
        lay = ed.layer()
        for s, (x, y) in fr.anchors.items():
            if s in lay.slices:
                sw, sh = lay.slices[s]
                c = QColor(SLICE_COLORS.get(s, "#ffffff"))
                p.setPen(QPen(c, 2 if s == ed.kotva.currentData() and ed.nastroj == "anchor" else 1,
                              Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(x * z, y * z, sw * z, sh * z)
        if ed.vrstva == "body":     # kotva skinu: bod, kterým postavička sedí na okně
            ax, ay = ed.doc.anchor
            p.setPen(QPen(QColor("#ff4d4d"), 2))
            cx, cy = ax * z + z // 2, ay * z + z // 2
            p.drawLine(cx - z, cy, cx + z, cy)
            p.drawLine(cx, cy - z, cx, cy + z)
        if self.hover and ed.nastroj not in ("picker", "anchor"):
            x, y = self.hover
            p.setPen(QPen(QColor(255, 255, 255, 160), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x * z, y * z, z - 1, z - 1)

    def _uvnitr(self, x, y):
        w, h = self.ed.doc.size
        return 0 <= x < w and 0 <= y < h

    def mousePressEvent(self, ev):
        ed = self.ed
        if not ed.frame() or not ed.upravitelny():
            return
        x, y = self._bod(ev)
        right = ev.button() == Qt.MouseButton.RightButton
        if ev.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton) or not self._uvnitr(x, y):
            return
        tool = ed.nastroj
        if tool == "picker":
            v = ed.cil(ed.frame())[y * ed.doc.size[0] + x]
            ed.vyber_barvu(v if v != NONE else 0)
            return
        if tool == "anchor":
            slot = ed.kotva.currentData()
            if slot:
                ed.nastav_kotvu(slot, x, y, vsechny=bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        ed.pred_upravou()
        px = ed.cil(ed.frame(), vytvorit=True)
        value = ed.mazani() if right or tool == "eraser" else ed.barva
        if tool == "fill":
            skin_edit.fill(px, ed.doc.size, x, y, value)
            ed.po_tahu()
            return
        self._stroke = (value, (x, y), bytearray(px), (x, y))
        self._kresli(px, [(x, y)], value)
        self.update()

    def mouseMoveEvent(self, ev):
        x, y = self._bod(ev)
        self.hover = (x, y) if self._uvnitr(x, y) else None
        self.ed.kurzor(self.hover)
        if self._stroke:
            value, last, backup, start = self._stroke
            px = self.ed.cil(self.ed.frame(), vytvorit=True)
            tool = self.ed.nastroj
            if tool in ("line", "rect"):
                px[:] = backup
                pts = (skin_edit.line if tool == "line" else skin_edit.rect)(*start, x, y)
                self._kresli(px, pts, value)
            else:
                self._kresli(px, skin_edit.line(*last, x, y), value)
                self._stroke = (value, (x, y), backup, start)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._stroke:
            self._stroke = None
            self.ed.po_tahu()

    def leaveEvent(self, _):
        self.hover = None
        self.ed.kurzor(None)
        self.update()

    def _kresli(self, px, pts, value):
        w, h = self.ed.doc.size
        for x, y in pts:
            if 0 <= x < w and 0 <= y < h:
                px[y * w + x] = value


# --- paleta a náhled -------------------------------------------------------------------

class Paleta(QWidget):
    """Políčka barev zvolené palety; klik vybere barvu, dvojklik ji změní."""
    CELL = 24

    def __init__(self, ed):
        super().__init__()
        self.ed = ed
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def obnov(self):
        n = len(self.ed.doc.colors()) if self.ed.doc else 2
        self.setFixedSize(8 * self.CELL + 2, ((n + 7) // 8) * self.CELL + 2)
        self.update()

    def _index(self, ev):
        p = ev.position()
        k = int(p.y() // self.CELL) * 8 + int(p.x() // self.CELL)
        return k if self.ed.doc and 0 <= k < len(self.ed.doc.colors()) else None

    def paintEvent(self, _):
        if not self.ed.doc:
            return
        p = QPainter(self)
        c = self.CELL
        for k, col in enumerate(self.ed.zobrazena_paleta()):
            r = QRect((k % 8) * c + 1, (k // 8) * c + 1, c - 2, c - 2)
            if k == 0:
                _checker(p, r, 4)
                if self.ed.overlay():
                    p.setPen(QPen(QColor("#ff00ff"), 2))
                    p.drawLine(r.topLeft(), r.bottomRight())
            else:
                p.fillRect(r, QColor(col))
            if k == self.ed.barva:
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(1, 1, -1, -1))

    def mouseMoveEvent(self, ev):
        k = self._index(ev)
        if k is None:
            self.setToolTip("")
        elif k == 0:
            self.setToolTip("0: průhledná" + (" – v této vrstvě vyřízne díru do postavy" if self.ed.overlay() else ""))
        else:
            self.setToolTip(f"{k}: {self.ed.zobrazena_paleta()[k]} (dvojklik = změnit)")

    def mousePressEvent(self, ev):
        k = self._index(ev)
        if k is not None:
            self.ed.vyber_barvu(k)

    def mouseDoubleClickEvent(self, ev):
        k = self._index(ev)
        if k:
            self.ed.uprav_barvu(self.ed.paleta_zobrazeni.currentData() or "base", k)


class Nahled(QWidget):
    """Přehrává animaci přes skin.render(), jak ji nakreslí daemon (nálada, klobouk, reakce, drony)."""

    def __init__(self):
        super().__init__()
        self.skin = None
        self.anim, self.look, self.hraje = None, skin.NO_LOOK, True
        self.t0, self.paused_at = time.monotonic(), 0.0
        self.setMinimumSize(160, 160)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(40)

    def nastav(self, s, anim, mood, hat, emote, drones):
        restart = anim != self.anim
        self.skin, self.anim = s, anim
        self.look = (mood, hat, emote, 0, drones, 0)
        if restart:
            self.t0 = time.monotonic()
        self.update()

    def prehravat(self, on):
        if on and not self.hraje:
            self.t0 = time.monotonic() - self.paused_at
        elif not on and self.hraje:
            self.paused_at = time.monotonic() - self.t0
        self.hraje = on

    def cas(self):
        return time.monotonic() - self.t0 if self.hraje else self.paused_at

    def snimek(self):
        s, anim = self.skin, self.anim
        if not s or not anim:
            return None
        t = self.cas()
        mood = self.look[0]
        if anim in s.anims and s.anims[anim].oneshot:
            t %= s.anims[anim].frames / max(s.anims[anim].fps, 1) + 1.0     # jednorázovou pořád dokola
        try:
            i = s.frame_at(anim, t, s.mood_tempo(mood))
            phase = int(t * 3) % 2
            look = (mood, self.look[1], self.look[2], phase, self.look[4], phase)
            return s.render(anim, i, look), i
        except Exception:
            return None

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#26262e"))
        got = self.snimek()
        if not got:
            p.setPen(QColor("#aaa"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "bez náhledu")
            return
        (px, colors), _ = got
        w, h = self.skin.size
        z = max(1, min(self.width() // w, self.height() // h))
        x0, y0 = (self.width() - w * z) // 2, (self.height() - h * z) // 2
        p.drawImage(QRect(x0, y0, w * z, h * z), obraz(px, colors, (w, h)))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        ay = y0 + (self.skin.anchor[1] + 1) * z
        p.drawLine(0, ay, self.width(), ay)       # hrana okna, na které postavička sedí


# --- malé dialogy ------------------------------------------------------------------------

class NovySkin(QDialog):
    """Id, název a předloha nového skinu."""

    def __init__(self, parent, skiny, aktualni=None):
        super().__init__(parent)
        self.setWindowTitle("Nový familiar")
        form = QFormLayout(self)
        self.id = QLineEdit()
        self.id.setPlaceholderText("muj-familiar")
        self.nazev = QLineEdit()
        self.predloha = QComboBox()
        self.predloha.addItem("prázdný (paleta, reakce a drony Robo-kuna)", None)
        for sid, name, _ in skiny:
            if sid != skin.BUILTIN:
                self.predloha.addItem(f"kopie: {name} ({sid})", sid)
        if aktualni:
            self.predloha.setCurrentIndex(max(0, self.predloha.findData(aktualni)))
        self.velikost = QComboBox()
        for v in ((32, 32), (48, 48), (64, 64)):
            self.velikost.addItem(f"{v[0]}×{v[1]} px", v)
        form.addRow("Id (jméno adresáře)", self.id)
        form.addRow("Název", self.nazev)
        form.addRow("Předloha", self.predloha)
        form.addRow("Plátno (u prázdného)", self.velikost)
        self.predloha.currentIndexChanged.connect(lambda: self.velikost.setEnabled(self.predloha.currentData() is None))
        self.velikost.setEnabled(self.predloha.currentData() is None)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def hodnoty(self):
        return self.id.text().strip(), self.nazev.text().strip(), self.predloha.currentData(), \
            self.velikost.currentData()


# --- editor ---------------------------------------------------------------------------

class EditorSkinu(QWidget):
    """Celý editor: výběr skinu, animace a snímky, palety, stavy a nálady, vlastnosti."""
    ulozeno = Signal(str)       # id uloženého (nového, smazaného) skinu: seznam skinů se změnil
    pouzit = Signal(str)        # „Použít jako vzhled“: id skinu pro klíč `skin` v configu

    def __init__(self, parent=None, skin_id=None):
        super().__init__(parent)
        self.doc = None
        self.vrstva, self.anim_name, self.snimek = "body", None, 0
        self.nastroj, self.barva = "pencil", 1
        self.dirty = False
        self._undo, self._redo = [], []
        self._plnim = False
        self._prvni = skin_id
        self._nahled_skin = None
        self.chyby = []

        self.nahled_timer = QTimer(self)
        self.nahled_timer.setSingleShot(True)
        self.nahled_timer.setInterval(120)
        self.nahled_timer.timeout.connect(self._sestav_nahled)
        self.fit_timer = QTimer(self)       # zvětšení plátna podle okna až po rozložení widgetů
        self.fit_timer.setSingleShot(True)
        self.fit_timer.setInterval(0)
        self.fit_timer.timeout.connect(self.prizpusobit)
        self._fronta = []                   # akce z dvojkliku a výběru, které přestaví widget, co je vyvolal
        self.fronta_timer = QTimer(self)
        self.fronta_timer.setSingleShot(True)
        self.fronta_timer.setInterval(0)
        self.fronta_timer.timeout.connect(self._spust_frontu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(self._lista())
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._zalozka_animace(), "Animace a kreslení")
        self.tabs.addTab(self._zalozka_stavy(), "Stavy a nálady")
        self.tabs.addTab(self._zalozka_palety(), "Palety")
        self.tabs.addTab(self._zalozka_vlastnosti(), "Vlastnosti")
        lay.addWidget(self.tabs, 1)
        self._zkratky()

    def _pozdeji(self, fn):
        """Až po návratu ze signálu (akce přestaví widget, který signál vyslal)."""
        self._fronta.append(fn)
        self.fronta_timer.start()

    def _spust_frontu(self):
        fronta, self._fronta = self._fronta, []
        for fn in fronta:
            fn()

    # --- horní lišta ---

    def _tlacitko(self, text, fn, tip=""):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _=False: fn())
        return b

    def _lista(self):
        h = QHBoxLayout()
        h.addWidget(QLabel("<b>Familiar:</b>"))
        self.skiny = QComboBox()
        self.skiny.setMinimumWidth(220)
        self.skiny.activated.connect(lambda i: self._pozdeji(lambda: self._vybran_skin(i)))
        h.addWidget(self.skiny)
        self.b_novy = self._tlacitko("Nový…", self.novy, "nový familiar: prázdný nebo kopie existujícího")
        self.b_jako = self._tlacitko("Uložit jako…", self.ulozit_jako, "uloží skin (i s neuloženými změnami) pod novým id")
        self.b_import = self._tlacitko("Import…", self.importovat,
                                       "postavička z Aseprite (.aseprite, .ase, JSON + PNG sheet); viz docs/skiny.md")
        self.b_smazat = self._tlacitko("Smazat", self.smazat, "smaže tvůj skin (u kopie balíčkového vrátí původní)")
        self.b_slozka = self._tlacitko("Složka", self.otevrit_slozku, "otevře adresář skinu ve správci souborů")
        for b in (self.b_novy, self.b_jako, self.b_import, self.b_smazat, self.b_slozka):
            h.addWidget(b)
        h.addStretch(1)
        self.b_undo = self._tlacitko("↶ Zpět", self.zpet, "Ctrl+Z")
        self.b_redo = self._tlacitko("↷ Znovu", self.znovu, "Ctrl+Y / Ctrl+Shift+Z")
        self.b_zahodit = self._tlacitko("Zahodit změny", self.zahodit, "načte skin znovu ze souborů")
        self.b_ulozit = self._tlacitko("Uložit skin", self.ulozit,
                                       "Ctrl+S; zapíše do ~/.local/share/familiar/skins/<id>/, běžící "
                                       "familiar ho načte sám")
        self.b_pouzit = self._tlacitko("Použít jako vzhled", lambda: self.doc and self.pouzit.emit(self.doc.id),
                                       "nastaví tento skin v nastavení (Obecné → Vzhled)")
        for b in (self.b_undo, self.b_redo, self.b_zahodit, self.b_ulozit, self.b_pouzit):
            h.addWidget(b)
        return h

    def _zkratky(self):
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for seq, fn in ((QKeySequence.StandardKey.Undo, self.zpet), (QKeySequence.StandardKey.Redo, self.znovu),
                        ("Ctrl+Y", self.znovu), (QKeySequence.StandardKey.Save, self.ulozit),
                        (",", lambda: self._krok(-1)), (".", lambda: self._krok(1))):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(ctx)
            s.activated.connect(fn)
        for key, _, short, _ in TOOLS:
            s = QShortcut(QKeySequence(short), self)
            s.setContext(ctx)
            s.activated.connect(lambda k=key: self.vyber_nastroj(k))

    # --- záložka Animace ---

    def _zalozka_animace(self):
        split = QSplitter(Qt.Orientation.Horizontal)

        # vlevo: vrstva a animace
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Vrstva"))
        self.vrstvy = QComboBox()
        for k in LAYER_ORDER:
            self.vrstvy.addItem(LAYER_NAMES[k], k)
        self.vrstvy.setToolTip("Postava = animace stavů (s efekty fx); obličej = záplaty očí a pusy pro nálady; "
                               "klobouky podle tématu; reakce nad hlavou; drony za subagenty")
        self.vrstvy.currentIndexChanged.connect(self._vybrana_vrstva)
        lv.addWidget(self.vrstvy)
        lv.addWidget(QLabel("Animace (tagy)"))
        self.animace = QListWidget()
        self.animace.currentRowChanged.connect(self._vybrana_animace)
        self.animace.itemDoubleClicked.connect(lambda _: self._pozdeji(self.prejmenovat_animaci))
        lv.addWidget(self.animace, 1)
        g = QGridLayout()
        for k, (text, fn, tip) in enumerate((
                ("Přidat…", self.pridat_animaci, "nová animace s prázdným snímkem"),
                ("Kopie…", self.kopie_animace, "kopie zvolené animace pod jiným jménem"),
                ("Přejmenovat…", self.prejmenovat_animaci, "přejmenuje i odkazy ve stavech a náladách"),
                ("Smazat", self.smazat_animaci, "smaže animaci (stav pak kreslí vestavěný Robo-kun)"),
                ("▲", lambda: self.posun_animaci(-1), "posunout v seznamu výš"),
                ("▼", lambda: self.posun_animaci(1), "posunout v seznamu níž"))):
            g.addWidget(self._tlacitko(text, fn, tip), k // 2, k % 2)
        lv.addLayout(g)
        form = QFormLayout()
        self.fps = QSpinBox()
        self.fps.setRange(1, skin_edit.MAX_FPS)
        self.fps.setSuffix(" fps")
        self.fps.setToolTip("snímků za sekundu (délka snímku v Aseprite: 250 ms = 4 fps)")
        self.fps.valueChanged.connect(lambda v: self._vlastnost_animace("fps", v))
        self.jednorazova = QCheckBox("jednorázová")
        self.jednorazova.setToolTip("přehraje se jednou a zůstane na posledním snímku (listen, hop, stumble)")
        self.jednorazova.toggled.connect(lambda v: self._vlastnost_animace("oneshot", v))
        self.smer = QComboBox()
        for d, t in zip(skin_edit.DIRECTIONS, ("dopředu", "pozpátku", "tam a zpět", "zpět a tam")):
            self.smer.addItem(t, d)
        self.smer.currentIndexChanged.connect(lambda: self._vlastnost_animace("direction", self.smer.currentData()))
        form.addRow("Rychlost", self.fps)
        form.addRow("", self.jednorazova)
        form.addRow("Směr", self.smer)
        lv.addLayout(form)
        self.pouziti = QLabel()
        self.pouziti.setWordWrap(True)
        self.pouziti.setStyleSheet("color: palette(placeholder-text);")
        lv.addWidget(self.pouziti)
        left.setMinimumWidth(190)

        # uprostřed: nástroje, plátno, snímky
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.nastroje = QButtonGroup(self)
        self.tl_nastroje = {}
        for key, text, short, tip in TOOLS:
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setToolTip(f"{tip} ({short})")
            b.clicked.connect(lambda _=False, k=key: self.vyber_nastroj(k))
            self.nastroje.addButton(b)
            self.tl_nastroje[key] = b
            tools.addWidget(b)
        self.tl_nastroje["pencil"].setChecked(True)
        self.kotva = QComboBox()
        self.kotva.setToolTip("řez, který nástroj Kotva posadí")
        tools.addWidget(self.kotva)
        tools.addStretch(1)
        mv.addLayout(tools)

        opts = QHBoxLayout()
        self.kreslit_do = QButtonGroup(self)
        self.do_postavy = QRadioButton("do postavy")
        self.do_fx = QRadioButton("do efektů (fx)")
        self.do_fx.setToolTip("efekty animace (klávesnice, lupa, „…“, Zzz) se kreslí přes klobouk")
        self.do_postavy.setChecked(True)
        for b in (self.do_postavy, self.do_fx):
            self.kreslit_do.addButton(b)
            opts.addWidget(b)
            b.toggled.connect(lambda _: self._obnov("platno", "paleta"))
        self.ukazat_fx = QCheckBox("ukázat fx")
        self.ukazat_fx.setChecked(True)
        self.ukazat_fx.toggled.connect(lambda _: self.platno.update())
        opts.addWidget(self.ukazat_fx)
        self.mrizka = QCheckBox("mřížka")
        self.cibule = QCheckBox("cibule")
        self.cibule.setToolTip("předchozí snímek prosvítá pod aktuálním")
        self.ch_podklad = QCheckBox("podklad")
        self.ch_podklad.setToolTip("postava pod obličejem, kloboukem, efekty, reakcí a dronem")
        for b in (self.mrizka, self.cibule, self.ch_podklad):
            b.setChecked(True)
            b.toggled.connect(self._volby_platna)
            opts.addWidget(b)
        opts.addStretch(1)
        opts.addWidget(QLabel("Zvětšení"))
        self.zoom = QSpinBox()
        self.zoom.setRange(2, 40)
        self.zoom.setValue(14)
        self.zoom.setSuffix("×")
        self.zoom.valueChanged.connect(self._volby_platna)
        opts.addWidget(self.zoom)
        opts.addWidget(self._tlacitko("Přizpůsobit", self.prizpusobit, "zvětšení podle velikosti okna"))
        mv.addLayout(opts)

        self.platno = Platno(self)
        area = self.area = QScrollArea()
        area.setWidget(self.platno)
        area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        area.setFrameShape(QFrame.Shape.NoFrame)
        mv.addWidget(area, 1)
        self.stav = QLabel(" ")
        self.stav.setStyleSheet("color: palette(placeholder-text);")
        mv.addWidget(self.stav)

        self.snimky = QListWidget()
        self.snimky.setViewMode(QListWidget.ViewMode.IconMode)
        self.snimky.setFlow(QListWidget.Flow.LeftToRight)
        self.snimky.setWrapping(False)
        self.snimky.setMovement(QListWidget.Movement.Static)
        self.snimky.setIconSize(QSize(48, 48))
        self.snimky.setFixedHeight(92)
        self.snimky.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.snimky.currentRowChanged.connect(self._vybran_snimek)
        mv.addWidget(self.snimky)
        fb = QHBoxLayout()
        for text, fn, tip in (
                ("+ prázdný", lambda: self.pridat_snimek(False), "nový prázdný snímek za aktuální"),
                ("+ kopie", lambda: self.pridat_snimek(True), "kopie aktuálního snímku za něj"),
                ("Smazat", self.smazat_snimek, "smaže aktuální snímek"),
                ("◀", lambda: self.posun_snimek(-1), "posunout snímek dřív"),
                ("▶", lambda: self.posun_snimek(1), "posunout snímek později"),
                ("←", lambda: self.posun_obsah(-1, 0), "posunout kresbu o pixel doleva"),
                ("→", lambda: self.posun_obsah(1, 0), "posunout kresbu o pixel doprava"),
                ("↑", lambda: self.posun_obsah(0, -1), "posunout kresbu o pixel nahoru"),
                ("↓", lambda: self.posun_obsah(0, 1), "posunout kresbu o pixel dolů"),
                ("Zrcadlit", self.zrcadlit, "převrátit kresbu vodorovně"),
                ("Vyčistit", self.vycistit, "smazat celou kresbu snímku (v kreslené vrstvě)")):
            b = self._tlacitko(text, fn, tip)
            if len(text) == 1:
                b.setFixedWidth(30)
            fb.addWidget(b)
        fb.addStretch(1)
        mv.addLayout(fb)
        kb = QHBoxLayout()
        self.drzi_oci = QCheckBox("oči určuje animace")
        self.drzi_pusu = QCheckBox("pusu určuje animace")
        for b, slot in ((self.drzi_oci, "eyes"), (self.drzi_pusu, "mouth")):
            b.setToolTip("na tomto snímku nálada nepřepíše výraz (mrknutí, spánek, X při zakopnutí); "
                         "[face] keep_" + slot + " ve skin.toml")
            b.toggled.connect(lambda on, s=slot: self._drzi(s, on))
            kb.addWidget(b)
        self.drzi_vse = self._tlacitko("na celou animaci", self._drzi_vse,
                                       "nastaví zámky obličeje z tohoto snímku všem snímkům animace")
        kb.addWidget(self.drzi_vse)
        kb.addStretch(1)
        self.zamky = QWidget()
        self.zamky.setLayout(kb)
        kb.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.zamky)

        # vpravo: paleta a náhled
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        ph = QHBoxLayout()
        ph.addWidget(QLabel("Paleta"))
        self.paleta_zobrazeni = QComboBox()
        self.paleta_zobrazeni.setToolTip("kterou paletou se plátno ukazuje (kreslí se indexy, platí ve všech)")
        self.paleta_zobrazeni.currentIndexChanged.connect(lambda: self._plnim or self._obnov("platno", "paleta"))
        ph.addWidget(self.paleta_zobrazeni, 1)
        rv.addLayout(ph)
        self.paleta = Paleta(self)
        rv.addWidget(self.paleta)
        self.barva_info = QLabel()
        rv.addWidget(self.barva_info)
        rv.addSpacing(8)
        rv.addWidget(QLabel("<b>Náhled</b> (jak ho nakreslí familiar)"))
        self.nahled = Nahled()
        self.nahled.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rv.addWidget(self.nahled, 1)
        nf = QFormLayout()
        self.n_anim = QComboBox()
        self.n_nalada = QComboBox()
        for m in skin_edit.MOODS:
            self.n_nalada.addItem(MOOD_NAMES.get(m, m), m)
        self.n_klobouk = QComboBox()
        self.n_reakce = QComboBox()
        self.n_drony = QSpinBox()
        self.n_drony.setRange(0, 3)
        for w in (self.n_anim, self.n_nalada, self.n_klobouk, self.n_reakce):
            w.currentIndexChanged.connect(lambda _: self._plnim or self._aktualizuj_nahled())
        self.n_drony.valueChanged.connect(lambda _: self._aktualizuj_nahled())
        nf.addRow("Animace", self.n_anim)
        nf.addRow("Nálada", self.n_nalada)
        nf.addRow("Klobouk", self.n_klobouk)
        nf.addRow("Reakce", self.n_reakce)
        nf.addRow("Drony", self.n_drony)
        rv.addLayout(nf)
        self.n_hraje = QCheckBox("přehrávat")
        self.n_hraje.setChecked(True)
        self.n_hraje.toggled.connect(self.nahled.prehravat)
        rv.addWidget(self.n_hraje)
        right.setMinimumWidth(230)

        split.addWidget(left)
        split.addWidget(mid)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 560, 260])
        return split

    # --- záložka Stavy a nálady ---

    def _zalozka_stavy(self):
        page = QWidget()
        v = QVBoxLayout(page)
        intro = QLabel("Která animace postavy se hraje v jakém stavu a co dělá nálada. Stav bez animace kreslí "
                       "vestavěný Robo-kun (ve tvé paletě ne – celý). Výrazy obličeje se berou z vrstvy Obličej "
                       "(tagy eyes_… a mouth_…), reakce z vrstvy Reakce.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        box = QGroupBox("Stavy činnosti → animace")
        self.stavy_form = QFormLayout(box)
        self.stavy = {}
        for st in skin_edit.STATES:
            c = self.stavy[("state", st)] = QComboBox()
            c.currentIndexChanged.connect(lambda _, k=("state", st): self._zmena_stavu(k))
            self.stavy_form.addRow(STATE_NAMES.get(st, st), c)
        for tool in skin_edit.TOOLS:
            c = self.stavy[("tool", tool)] = QComboBox()
            c.currentIndexChanged.connect(lambda _, k=("tool", tool): self._zmena_stavu(k))
            self.stavy_form.addRow(TOOL_NAMES.get(tool, tool), c)
        self.dalsi_nastroje = QLabel()
        self.dalsi_nastroje.setWordWrap(True)
        self.stavy_form.addRow(self.dalsi_nastroje)
        v.addWidget(box)

        box = QGroupBox("Nálady")
        box.setToolTip("paleta = přebarvení postavy, oči / pusa = záplata z vrstvy Obličej, reakce = emote při "
                       "změně na náladu, tempo = zrychlení / zpomalení animací (únava 0,6)")
        g = QGridLayout(box)
        for c, t in enumerate(("Nálada", "Paleta", "Oči", "Pusa", "Reakce", "Tempo")):
            g.addWidget(QLabel(f"<b>{t}</b>"), 0, c)
        self.nalady = {}
        for r, m in enumerate(skin_edit.MOODS, 1):
            g.addWidget(QLabel(MOOD_NAMES.get(m, m)), r, 0)
            row = {}
            for c, key in enumerate(("palette", "eyes", "mouth", "emote"), 1):
                w = row[key] = QComboBox()
                w.currentIndexChanged.connect(lambda _, m=m, k=key: self._zmena_nalady(m, k))
                g.addWidget(w, r, c)
            t = row["tempo"] = QDoubleSpinBox()
            t.setRange(0.1, 3.0)
            t.setSingleStep(0.1)
            t.setDecimals(2)
            t.valueChanged.connect(lambda _, m=m: self._zmena_nalady(m, "tempo"))
            g.addWidget(t, r, 5)
            self.nalady[m] = row
        v.addWidget(box)
        self.chybi = QLabel()
        self.chybi.setWordWrap(True)
        v.addWidget(self.chybi)
        v.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    # --- záložka Palety ---

    def _zalozka_palety(self):
        page = QWidget()
        v = QVBoxLayout(page)
        intro = QLabel("Řádek = paleta, sloupec = index barvy. Obrázky jsou nakreslené indexy, takže každá paleta "
                       "je jen jiné obarvení téže kresby; base je ta, ve které se ukládají PNG. Nálady si palety "
                       "vybírají na záložce Stavy a nálady. Dvojklik na barvu ji změní.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.tabulka = QTableWidget()
        self.tabulka.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabulka.cellDoubleClicked.connect(lambda r, c: self._pozdeji(lambda: self._bunka_palety(r, c)))
        self.tabulka.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.addWidget(self.tabulka, 1)
        g = QGridLayout()
        for k, (text, fn, tip) in enumerate((
                ("Nová paleta…", self.nova_paleta, "kopie palety base pod novým jménem"),
                ("Odvodit z base…", self.odvodit_paletu, "teplá / studená / vybledlá varianta barev postavy"),
                ("Přejmenovat…", self.prejmenovat_paletu, "přejmenuje i v náladách"),
                ("Smazat paletu", self.smazat_paletu, "nálady s touto paletou dostanou base"),
                ("Přidat barvu", self.pridat_barvu, "nový index ve všech paletách (nejvýš 16 i s průhlednou)"),
                ("Odebrat poslední barvu", self.odebrat_barvu, "jen když ji žádný snímek nepoužívá"),
                ("Přemalovat index…", self.premalovat, "ve všech snímcích nahradí jeden index jiným"))):
            g.addWidget(self._tlacitko(text, fn, tip), k // 4, k % 4)
        v.addLayout(g)
        return page

    # --- záložka Vlastnosti ---

    def _zalozka_vlastnosti(self):
        page = QWidget()
        form = QFormLayout(page)
        self.meta = {}
        for key, text, tip in (("name", "Název", "jak se skin jmenuje v nabídce"),
                               ("author", "Autor grafiky", ""), ("license", "Licence", "např. CC0-1.0"),
                               ("url", "Odkaz", "odkud grafika je")):
            w = self.meta[key] = QLineEdit()
            w.setToolTip(tip)
            w.editingFinished.connect(lambda k=key: self._zmena_meta(k))
            form.addRow(text, w)
        self.id_label = QLabel()
        self.id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Id", self.id_label)
        self.facing = QComboBox()
        for v, t in ((None, "zepředu (při chůzi se nezrcadlí)"), ("right", "doprava"), ("left", "doleva")):
            self.facing.addItem(t, v)
        self.facing.setToolTip("kam kouká animace chůze; na procházce opačným směrem se zrcadlí")
        self.facing.currentIndexChanged.connect(lambda _: self._zmena_meta("facing"))
        form.addRow("Chůze kouká", self.facing)
        h = QHBoxLayout()
        self.ax, self.ay = QSpinBox(), QSpinBox()
        for w, pre in ((self.ax, "x "), (self.ay, "y ")):
            w.setPrefix(pre)
            w.setRange(0, skin.MAX_SIZE - 1)
            w.valueChanged.connect(lambda _: self._zmena_kotvy())
            h.addWidget(w)
        h.addStretch(1)
        lab = QLabel("Kotva postavičky")
        lab.setToolTip("bod, kterým postavička sedí na hraně okna (na plátně červený křížek)")
        form.addRow(lab, h)
        h = QHBoxLayout()
        self.sw, self.sh = QSpinBox(), QSpinBox()
        for w in (self.sw, self.sh):
            w.setRange(sprites.W, skin.MAX_SIZE)
            w.setSuffix(" px")
            h.addWidget(w)
        h.addWidget(self._tlacitko("Změnit plátno", self.zmenit_platno,
                                   "obsah všech snímků zůstane na střed spodní hrany"))
        h.addStretch(1)
        form.addRow("Plátno (šířka × výška)", h)
        self.soubory = QLabel()
        self.soubory.setWordWrap(True)
        self.soubory.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Soubory", self.soubory)
        return page

    # --- načtení a výběr skinu ---

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.doc is None:
            self._obnov_skiny()
            sid = self._prvni or skin.DEFAULT
            self.nacti(sid if sid == skin.BUILTIN or skin.find(sid) else skin.DEFAULT)

    def _obnov_skiny(self, vybrat=None):
        self._plnim = True
        marks = {skin.USER: "tvůj", skin.PACKAGE: "z balíčku", skin.CODE: "kód"}
        items = [(f"{name} ({sid}, {marks.get(source, source)})", sid) for sid, name, source in skin.available()]
        if items != [(self.skiny.itemText(k), self.skiny.itemData(k)) for k in range(self.skiny.count())]:
            self.skiny.clear()       # jen když se seznam změnil (výběr ze seznamu ho nepřestavuje)
            for text, sid in items:
                self.skiny.addItem(text, sid)
        sid = vybrat or (self.doc.id if self.doc else None)
        if sid is not None:
            self.skiny.setCurrentIndex(max(0, self.skiny.findData(sid)))
        self._plnim = False

    def _vybran_skin(self, _):
        sid = self.skiny.currentData()
        if self.doc and sid == self.doc.id:
            return
        if not self.muze_zavrit():
            self._obnov_skiny()
            return
        self.nacti(sid)

    def nacti(self, sid):
        """Načte skin do editoru (zahodí undo); vestavěný kódem jen ukáže, upravit nejde."""
        try:
            if sid == skin.BUILTIN:
                doc = skin_edit.SkinDoc(skin.BUILTIN)
                doc.source = skin.CODE
                doc.meta["name"] = skin.builtin().name
            else:
                doc = skin_edit.load_id(sid)
        except SkinError as e:
            self.hlaska(f"Skin {sid} nejde načíst: {e}", chyba=True)
            return False
        self.doc, self.dirty = doc, False
        self._undo.clear()
        self._redo.clear()
        self.vrstva, self.anim_name, self.snimek = "body", None, 0
        self._obnov_skiny(sid)
        self._oprav_vyber()
        self._obnov()
        self.fit_timer.start()
        if doc.warnings:
            self.hlaska("; ".join(doc.warnings))
        return True

    # --- výběr ve vrstvě ---

    def layer(self):
        return self.doc.layers.get(self.vrstva) if self.doc else None

    def anim(self):
        lay = self.layer()
        return lay.get(self.anim_name) if lay and self.anim_name else None

    def frame(self):
        a = self.anim()
        return a.frames[self.snimek] if a and 0 <= self.snimek < len(a.frames) else None

    def overlay(self):
        return self.vrstva != "body" or self.kreslim_fx()

    def kreslim_fx(self):
        return self.vrstva == "body" and self.do_fx.isChecked()

    def upravitelny(self):
        return bool(self.doc) and self.doc.editable()

    def cil(self, fr, vytvorit=False):
        """Pixely, do kterých se kreslí (snímek postavy, nebo jeho fx)."""
        if self.kreslim_fx():
            if fr.fx is None:
                if not vytvorit:
                    return bytearray([NONE]) * len(fr.px)
                fr.fx = bytearray([NONE]) * len(fr.px)
            return fr.fx
        return fr.px

    def mazani(self):
        return NONE if self.overlay() else 0

    def zobrazena_paleta(self):
        return self.doc.colors(self.paleta_zobrazeni.currentData() or "base")

    def podklad(self):
        """(pixely postavy, dx, dy) pod kreslenou vrstvou, nebo None."""
        fr, body = self.frame(), self.doc.layers.get("body")
        if not fr or not body or not body.anims:
            return None
        if self.vrstva == "body":
            return (fr.px, 0, 0) if self.kreslim_fx() else None
        ref, slot = None, None
        name = self.anim_name or ""
        if self.vrstva == "acc":
            hat, _, anim = name.partition("@")
            ba = body.get(anim) if anim else None
            ref = ba.frames[self.snimek % len(ba.frames)] if ba and ba.frames else None
            slot = "head"
        elif self.vrstva == "face":
            slot = "eyes" if name.startswith("eyes_") else "mouth"
        base = body.get("idle") or body.anims[0]
        ref = ref or (base.frames[0] if base.frames else None)
        if ref is None:
            return None
        dx = dy = 0
        if slot and slot in fr.anchors and slot in ref.anchors:
            dx, dy = fr.anchors[slot][0] - ref.anchors[slot][0], fr.anchors[slot][1] - ref.anchors[slot][1]
        return ref.px, dx, dy

    def _oprav_vyber(self):
        lay = self.layer()
        names = lay.names() if lay else []
        if self.anim_name not in names:
            self.anim_name = names[0] if names else None
        a = self.anim()
        self.snimek = max(0, min(self.snimek, len(a.frames) - 1)) if a else 0
        if self.doc and self.barva >= len(self.doc.colors()):
            self.barva = 1

    # --- obnova widgetů ---

    def _obnov(self, *co):
        """Překreslí části editoru podle dokumentu; bez argumentů všechno."""
        if not self.doc:
            return
        every = not co
        self._plnim = True
        try:
            if every or "animace" in co:
                self._obnov_animace()
            elif "vlastnosti_animace" in co:
                self._obnov_vlastnosti_animace()
            if every or "snimky" in co:
                self._obnov_snimky()
            if every or "palety" in co:
                self._obnov_palety()
            if every or "stavy" in co:
                self._obnov_stavy()
            if every or "vlastnosti" in co:
                self._obnov_vlastnosti()
        finally:
            self._plnim = False
        if every or "platno" in co or "snimky" in co:
            self.platno.obnov()
        if every or "paleta" in co or "palety" in co:
            self.paleta.obnov()
            self._barva_info()
        self._obnov_tlacitka()
        self.nahled_timer.start()

    def _obnov_tlacitka(self):
        ok = self.upravitelny()
        user = self.doc.source == skin.USER
        found = skin.find(self.doc.id)
        self.b_ulozit.setEnabled(ok and (self.dirty or not user))
        self.b_zahodit.setEnabled(self.dirty)
        self.b_undo.setEnabled(bool(self._undo))
        self.b_redo.setEnabled(bool(self._redo))
        self.b_jako.setEnabled(ok)
        self.b_smazat.setEnabled(user and not self.dirty)
        shadow = os.path.isdir(os.path.join(skin.PACKAGE_DIR, self.doc.id))
        self.b_smazat.setText("Vrátit balíčkový" if user and shadow else "Smazat")
        self.b_slozka.setEnabled(bool(found))
        for w in (self.tabs.widget(k) for k in range(self.tabs.count())):
            w.setEnabled(ok)

    def _obnov_animace(self):
        if self.vrstvy.currentData() != self.vrstva:
            self.vrstvy.setCurrentIndex(self.vrstvy.findData(self.vrstva))
        lay, a = self.layer(), self.anim()
        texts = [f"{x.name}   ({len(x.frames)}× · {x.fps} fps{' · jednorázová' if x.oneshot else ''})"
                 for x in (lay.anims if lay else [])]
        if texts != [self.animace.item(k).text() for k in range(self.animace.count())]:
            self.animace.clear()
            self.animace.addItems(texts)
        if a:
            self.animace.setCurrentRow(lay.anims.index(a))
        self._obnov_vlastnosti_animace()

    def _obnov_vlastnosti_animace(self):
        lay, a = self.layer(), self.anim()
        self.fps.setEnabled(bool(a))
        self.jednorazova.setEnabled(bool(a))
        self.smer.setEnabled(bool(a))
        if a:
            self.fps.setValue(a.fps)
            self.jednorazova.setChecked(a.oneshot)
            self.smer.setCurrentIndex(max(0, self.smer.findData(a.direction)))
        self.pouziti.setText(self._pouziti(a))
        body = self.vrstva == "body"
        for w in (self.do_postavy, self.do_fx, self.ukazat_fx):
            w.setVisible(body)
        self.zamky.setVisible(body)
        slots = list(lay.slices) if lay else []
        self.kotva.clear()
        for s in slots:
            self.kotva.addItem(SLICE_NAMES.get(s, s), s)
        self.tl_nastroje["anchor"].setEnabled(bool(slots))
        self.kotva.setVisible(bool(slots))
        if not slots and self.nastroj == "anchor":
            self.vyber_nastroj("pencil")

    def _pouziti(self, a):
        if not a:
            return "Vrstva nemá animace." if self.vrstva == "body" or self.layer() else \
                "Skin tuto vrstvu nemá; přidáním animace vznikne."
        d = self.doc
        if self.vrstva == "body":
            st = [STATE_NAMES.get(k, k) for k, v in d.activity.items() if v == a.name]
            w = d.activity.get("working")
            if isinstance(w, dict):
                st += [TOOL_NAMES.get(t, f"práce – {t}") for t, v in w.items() if v == a.name]
            return "Hraje se: " + ", ".join(st) if st else "Nepřiřazená ke stavu (záložka Stavy a nálady)."
        if self.vrstva == "face":
            slot, _, val = a.name.partition("_")
            m = [MOOD_NAMES.get(k, k) for k, v in d.moods.items() if v.get(slot) == val]
            return "Nálady: " + ", ".join(m) if m else "Žádná nálada ho nepoužívá."
        if self.vrstva == "emote":
            m = [MOOD_NAMES.get(k, k) for k, v in d.moods.items() if v.get("emote") == a.name]
            return ("Při změně nálady: " + ", ".join(m) + ". " if m else "") + \
                "Reakce spouští i události (díky, testy, limit …), viz docs/skiny.md."
        if self.vrstva == "acc":
            hat, at, anim = a.name.partition("@")
            what = f"varianta klobouku {hat} v animaci {anim}" if at else f"klobouk {nazev_klobouku(hat)}"
            return what + ". Klobouk podle tématu rozhovoru nebo odemčený doplněk."
        return "Dron za subagenta (drone1 = první)."

    def _obnov_snimky(self):
        self._oprav_vyber()
        a = self.anim()
        self.snimky.clear()
        if not a:
            return
        for i, fr in enumerate(a.frames):
            it = QListWidgetItem(self._ikona(fr), str(i))
            self.snimky.addItem(it)
        self.snimky.setCurrentRow(self.snimek)
        fr = self.frame()
        self.drzi_oci.setChecked("eyes" in fr.keep)
        self.drzi_pusu.setChecked("mouth" in fr.keep)

    def _ikona(self, fr):
        size, colors = self.doc.size, self.zobrazena_paleta()
        img = obraz(fr.px, colors, size, self.vrstva != "body")
        if fr.fx is not None:
            p = QPainter(img)
            p.drawImage(0, 0, obraz(fr.fx, colors, size, True))
            p.end()
        pm = QPixmap(48, 48)
        pm.fill(CHECKER[0])
        p = QPainter(pm)
        z = max(1, 48 // max(size))
        p.drawImage(QRect((48 - size[0] * z) // 2, (48 - size[1] * z) // 2, size[0] * z, size[1] * z), img)
        p.end()
        return QIcon(pm)

    def _obnov_ikonu(self):
        it = self.snimky.item(self.snimek)
        if it and self.frame():
            it.setIcon(self._ikona(self.frame()))

    def _obnov_palety(self):
        d = self.doc
        cur = self.paleta_zobrazeni.currentData() or "base"
        self.paleta_zobrazeni.clear()
        for k in d.palettes:
            self.paleta_zobrazeni.addItem(k, k)
        self.paleta_zobrazeni.setCurrentIndex(max(0, self.paleta_zobrazeni.findData(cur)))
        n = len(d.palettes["base"])
        self.tabulka.setRowCount(len(d.palettes))
        self.tabulka.setColumnCount(n)
        self.tabulka.setVerticalHeaderLabels(list(d.palettes))
        self.tabulka.setHorizontalHeaderLabels([str(k) for k in range(n)])
        used = d.used_colors()
        for r, (name, cols) in enumerate(d.palettes.items()):
            for k in range(n):
                it = QTableWidgetItem("∅" if k == 0 else "")
                if k:
                    it.setBackground(QColor(cols[k]))
                    it.setToolTip(f"{name} {k}: {cols[k]}" + ("" if k in used else " (nepoužitá)"))
                else:
                    it.setToolTip("0: průhledná (v překryvných vrstvách vyřízne díru)")
                self.tabulka.setItem(r, k, it)
        self.tabulka.resizeColumnsToContents()

    def _obnov_stavy(self):
        d = self.doc
        body = d.layers.get("body")
        anims = body.names() if body else []
        w = d.activity.get("working")
        working = w if isinstance(w, dict) else ({"default": w} if isinstance(w, str) else {})
        for (kind, key), c in self.stavy.items():
            cur = d.activity.get(key) if kind == "state" else working.get(key)
            c.clear()
            none = "— bez chůze (poskakuje v klidu) —" if key == "walking" else \
                "— jako ostatní nástroje —" if kind == "tool" and key != "default" else "— vestavěný Robo-kun —"
            c.addItem(none, None)
            for a in anims:
                c.addItem(a, a)
            if cur and cur not in anims:
                c.addItem(f"{cur} (chybí – kreslí Robo-kun)", cur)
            c.setCurrentIndex(max(0, c.findData(cur)) if cur else 0)
        extra = {t: v for t, v in working.items() if t not in skin_edit.TOOLS}
        self.dalsi_nastroje.setText("Další nástroje ze skin.toml (upravíš v souboru): " +
                                    ", ".join(f"{t} → {v}" for t, v in extra.items()) if extra else "")
        self.dalsi_nastroje.setVisible(bool(extra))
        face = d.layers.get("face")
        faces = face.names() if face else []
        emotes = d.layers["emote"].names() if "emote" in d.layers else []
        for m, row in self.nalady.items():
            cfg = d.moods.get(m, {})
            for key, items in (("palette", [(p, p) for p in d.palettes]),
                               ("eyes", [(None, "—")] + [(n[5:], n[5:]) for n in faces if n.startswith("eyes_")]),
                               ("mouth", [(None, "—")] + [(n[6:], n[6:]) for n in faces if n.startswith("mouth_")]),
                               ("emote", [(None, "—")] + [(n, n) for n in emotes])):
                c = row[key]
                c.clear()
                for v, t in items:
                    c.addItem(t, v)
                cur = cfg.get(key, "base" if key == "palette" else None)
                if cur is not None and c.findData(cur) < 0:
                    c.addItem(f"{cur} (chybí)", cur)
                c.setCurrentIndex(max(0, c.findData(cur)))
            row["tempo"].setValue(float(cfg.get("tempo", 1.0)))

    def _obnov_vlastnosti(self):
        d = self.doc
        for k, w in self.meta.items():
            w.setText(str(d.meta.get(k, "") or ""))
        self.id_label.setText(d.id)
        self.facing.setCurrentIndex(max(0, self.facing.findData(d.meta.get("facing"))))
        self.ax.setRange(0, d.size[0] - 1)
        self.ay.setRange(0, d.size[1] - 1)
        self.ax.setValue(d.anchor[0])
        self.ay.setValue(d.anchor[1])
        self.sw.setValue(d.size[0])
        self.sh.setValue(d.size[1])
        where = d.path or "(zatím neuloženo)"
        dest = os.path.join(skin_edit.user_dir(), d.id)
        self.soubory.setText(f"načteno z {where}\nukládá se do {dest}")

    def _barva_info(self):
        cols = self.zobrazena_paleta()
        k = self.barva
        if k == 0:
            self.barva_info.setText("Barva 0: " + ("vyříznout (díra do postavy)" if self.overlay() else "průhledná"))
        elif k < len(cols):
            self.barva_info.setText(f"Barva {k}: {cols[k]}")

    def _info(self):
        d = self.doc
        parts = []
        if d.source == skin.CODE:
            parts.append("Vestavěný Robo-kun je kreslený kódem a upravit nejde. Uprav jeho kopii "
                         "<b>robokun</b>, nebo vytvoř nový familiar (Nový…).")
        elif d.source == skin.PACKAGE:
            parts.append(f"Skin z balíčku – uloží se jako tvoje kopie do "
                         f"<code>{_html(_short(os.path.join(skin_edit.user_dir(), d.id)))}</code> a přebije původní "
                         f"(ten vrátí tlačítko Vrátit balíčkový).")
        if self.dirty:
            parts.append("<b>Neuložené změny.</b>")
        if self.chyby:
            parts.append("<span style='color:#c0392b'><b>Nejde uložit:</b> " +
                         _html("; ".join(self.chyby)) + "</span>")
        miss = getattr(self._nahled_skin, "missing", None)
        if miss:
            parts.append("Chybí animace (kreslí vestavěný Robo-kun): " + _html(", ".join(miss)))
        if d.source != skin.CODE:
            unmapped = [STATE_NAMES[st] for st in skin_edit.STATES
                        if st not in ("walking", "gone") and st not in d.activity]
            if "working" not in d.activity:
                unmapped.append("práce")
            if unmapped:
                parts.append("Bez vlastní animace (kreslí Robo-kun, přiřaď na záložce Stavy a nálady): " +
                             _html(", ".join(unmapped)) + ".")
        self.info.setText(" ".join(parts))
        self.chybi.setText("Chybějící animace stavů kreslí vestavěný Robo-kun: " + ", ".join(miss) if miss else "")

    # --- náhled ---

    def _sestav_nahled(self):
        if not self.doc:
            return
        if self.doc.source == skin.CODE:
            self._nahled_skin, self.chyby = skin.builtin(), []
        else:
            self.chyby = self.doc.problems()
            try:
                self._nahled_skin = self.doc.to_skin()
            except SkinError:
                self._nahled_skin = None
        self._plnim = True
        s = self._nahled_skin
        cur = self.n_anim.currentData()
        self.n_anim.clear()
        for a in (s.anims if s else {}):
            self.n_anim.addItem(a, a)
        self.n_anim.setCurrentIndex(max(0, self.n_anim.findData(cur)))
        hat, emote = self.n_klobouk.currentData(), self.n_reakce.currentData()
        self.n_klobouk.clear()
        self.n_klobouk.addItem("bez klobouku", None)
        for h in (self.doc.layers["acc"].names() if "acc" in self.doc.layers else []):
            if "@" not in h:
                self.n_klobouk.addItem(nazev_klobouku(h), h)
        self.n_klobouk.setCurrentIndex(max(0, self.n_klobouk.findData(hat)))
        self.n_reakce.clear()
        self.n_reakce.addItem("bez reakce", None)
        for e in (self.doc.layers["emote"].names() if "emote" in self.doc.layers else []):
            self.n_reakce.addItem(e, e)
        self.n_reakce.setCurrentIndex(max(0, self.n_reakce.findData(emote)))
        self._plnim = False
        self._sleduj_vyber()
        self._aktualizuj_nahled()
        self._info()

    def _sleduj_vyber(self):
        """Náhled ukáže, co se právě kreslí: animaci postavy, výraz, klobouk, reakci nebo dron."""
        name, v = self.anim_name or "", self.vrstva
        self._plnim = True
        if v == "body" and name:
            self.n_anim.setCurrentIndex(max(0, self.n_anim.findData(name)))
        elif v == "face":
            slot, _, val = name.partition("_")
            mood = next((m for m, c in self.doc.moods.items() if c.get(slot) == val), None)
            if mood:
                self.n_nalada.setCurrentIndex(max(0, self.n_nalada.findData(mood)))
        elif v == "acc" and name:
            hat, at, anim = name.partition("@")
            self.n_klobouk.setCurrentIndex(max(0, self.n_klobouk.findData(hat)))
            if at:
                self.n_anim.setCurrentIndex(max(0, self.n_anim.findData(anim)))
        elif v == "emote" and name:
            self.n_reakce.setCurrentIndex(max(0, self.n_reakce.findData(name)))
        elif v == "drone" and name[5:].isdigit():
            self.n_drony.blockSignals(True)
            self.n_drony.setValue(min(3, int(name[5:])))
            self.n_drony.blockSignals(False)
        self._plnim = False

    def _aktualizuj_nahled(self):
        s = self._nahled_skin
        if s is None:
            self.nahled.nastav(None, None, "klid", None, None, 0)
            return
        anim = self.n_anim.currentData() or s.anim_for("idle")
        self.nahled.nastav(s, anim, self.n_nalada.currentData() or "klid", self.n_klobouk.currentData(),
                           self.n_reakce.currentData(), self.n_drony.value())

    # --- úpravy s historií ---

    def _stav(self):
        return self.vrstva, self.anim_name, self.snimek

    def pred_upravou(self):
        """Uloží stav pro Zpět; volá se před každou změnou dokumentu."""
        self._undo.append((self.doc.clone(), self._stav()))
        del self._undo[:-UNDO_MAX]
        self._redo.clear()
        self.dirty = True

    def zmena(self, fn, *co):
        """Úprava dokumentu: fn() smí vyhodit ValueError / SkinError (hláška, dokument beze změny)."""
        if not self.upravitelny():
            return None
        before = self.doc.clone()
        try:
            out = fn()
        except (ValueError, SkinError) as e:
            self.doc = before
            self.hlaska(str(e), chyba=True)
            return None
        self._undo.append((before, self._stav()))
        del self._undo[:-UNDO_MAX]
        self._redo.clear()
        self.dirty = True
        self._obnov(*co)
        return out

    def po_tahu(self):
        self.dirty = True
        self.platno.update()
        self._obnov_ikonu()
        self._obnov_tlacitka()
        self.nahled_timer.start()

    def zpet(self):
        if self._undo:
            self._redo.append((self.doc.clone(), self._stav()))
            self.doc, (self.vrstva, self.anim_name, self.snimek) = self._undo.pop()
            self.dirty = True
            self._obnov()

    def znovu(self):
        if self._redo:
            self._undo.append((self.doc.clone(), self._stav()))
            self.doc, (self.vrstva, self.anim_name, self.snimek) = self._redo.pop()
            self.dirty = True
            self._obnov()

    def hlaska(self, text, chyba=False):
        color = "#c0392b" if chyba else "#2d7d46"
        self.stav.setText(f"<span style='color:{color}'>{_html(text)}</span>")

    # --- výběr ---

    def _vybrana_vrstva(self, _):
        if self._plnim:
            return
        self.vrstva, self.anim_name, self.snimek = self.vrstvy.currentData(), None, 0
        if self.vrstva != "body":
            self.do_postavy.setChecked(True)
        self._oprav_vyber()
        self._obnov("animace", "snimky", "platno", "paleta")

    def _vybrana_animace(self, row):
        if self._plnim or row < 0 or not self.layer():
            return
        self.anim_name, self.snimek = self.layer().anims[row].name, 0
        self._obnov("vlastnosti_animace", "snimky", "platno")       # seznam se uvnitř svého signálu nepřestaví

    def _vybran_snimek(self, row):
        if self._plnim or row < 0:
            return
        self.snimek = row
        fr = self.frame()
        if fr:
            self._plnim = True
            self.drzi_oci.setChecked("eyes" in fr.keep)
            self.drzi_pusu.setChecked("mouth" in fr.keep)
            self._plnim = False
        self.platno.update()

    def _krok(self, d):
        a = self.anim()
        if a:
            self.snimek = (self.snimek + d) % len(a.frames)
            self._plnim = True
            self.snimky.setCurrentRow(self.snimek)
            self._plnim = False
            self._vybran_snimek(self.snimek)

    def vyber_nastroj(self, key):
        if key == "anchor" and not self.tl_nastroje["anchor"].isEnabled():
            return
        self.nastroj = key
        self.tl_nastroje[key].setChecked(True)
        self.platno.update()

    def vyber_barvu(self, k):
        self.barva = k
        if self.nastroj in ("eraser", "picker"):
            self.vyber_nastroj("pencil")
        self.paleta.update()
        self._barva_info()

    def kurzor(self, xy):
        if not xy or not self.frame():
            self.stav.setText(" ")
            return
        x, y = xy
        v = self.cil(self.frame())[y * self.doc.size[0] + x]
        what = "nic" if v == NONE else ("průhledná / vyříznout" if v == 0 else f"barva {v} {self.zobrazena_paleta()[v]}")
        self.stav.setText(f"{x}, {y} · {what} · levé tlačítko kreslí, pravé maže · , . = předchozí / další snímek")

    def prizpusobit(self):
        if self.doc:
            vp = self.area.viewport().size()
            w, h = self.doc.size
            self.zoom.setValue(max(2, min(24, (vp.width() - 8) // w, (vp.height() - 8) // h)))

    def _volby_platna(self, *_):
        self.platno.grid = self.mrizka.isChecked()
        self.platno.onion = self.cibule.isChecked()
        self.platno.underlay = self.ch_podklad.isChecked()
        self.platno.zoom = self.zoom.value()
        self.platno.obnov()

    # --- animace ---

    def _jmeno(self, title, label, items=(), text=""):
        if items:
            name, ok = QInputDialog.getItem(self, title, label, list(items), 0, True)
        else:
            name, ok = QInputDialog.getText(self, title, label, text=text)
        return name.strip() if ok else None

    def pridat_animaci(self):
        if not self.upravitelny():
            return
        lay = self.doc.layers.get(self.vrstva)
        have = set(lay.names()) if lay else set()
        items = [n for n in SUGGEST.get(self.vrstva, []) if n not in have]
        if self.vrstva == "acc":
            hats = [n for n in have if "@" not in n]
            body = self.doc.layers["body"].names()
            items += [f"{h}@{a}" for h in hats for a in body if f"{h}@{a}" not in have]
        name = self._jmeno("Nová animace", f"Jméno tagu ve vrstvě {LAYER_NAMES[self.vrstva]}:", items or [""])
        if not name:
            return

        def add():
            v = self.vrstva
            frames = 2 if v in ("emote", "drone") else 1
            a = self.doc.add_anim(v, name, frames=frames, fps=3 if v in ("emote", "drone") else 8,
                                  at=(self.layer().anims.index(self.anim()) + 1) if self.anim() else None)
            hat, at, anim = name.partition("@")
            body = self.doc.body.get(anim) if at else None
            base = self.doc.layers["acc"].get(hat) if at else None
            if body and base and base.frames:      # varianta klobouku: kopie klobouku na každý snímek animace
                a.frames = [skin_edit.Frame(bytearray(base.frames[0].px), anchors=dict(base.frames[0].anchors))
                            for _ in body.frames]
                a.fps = body.fps
            if v == "body":
                for st, an in sprites.STATE_ANIM.items():
                    if an == name and st not in self.doc.activity:
                        self.doc.activity[st] = name
            self.anim_name, self.snimek = name, 0
        self.zmena(add)

    def kopie_animace(self):
        a = self.anim()
        if not a:
            return
        name = self._jmeno("Kopie animace", "Jméno kopie:", text=a.name + "_2")
        if name:
            def dup():
                self.doc.duplicate_anim(self.vrstva, a.name, name)
                self.anim_name, self.snimek = name, 0
            self.zmena(dup)

    def prejmenovat_animaci(self):
        a = self.anim()
        if not a or not self.upravitelny():
            return
        name = self._jmeno("Přejmenovat animaci", "Nové jméno (odkazy ve stavech a náladách se upraví):",
                           text=a.name)
        if name and name != a.name:
            def ren():
                self.doc.rename_anim(self.vrstva, a.name, name)
                self.anim_name = name
            self.zmena(ren)

    def smazat_animaci(self):
        a = self.anim()
        if not a:
            return
        if self._potvrdit("Smazat animaci", f"Smazat animaci {a.name} ({len(a.frames)} snímků)?"):
            self.zmena(lambda: self.doc.delete_anim(self.vrstva, a.name))

    def posun_animaci(self, d):
        a = self.anim()
        if a:
            self.zmena(lambda: self.doc.move_anim(self.vrstva, a.name, d), "animace")

    def _vlastnost_animace(self, key, value):
        a = self.anim()
        if self._plnim or not a or getattr(a, key) == value:
            return
        self.zmena(lambda: setattr(self.anim(), key, value), "animace")

    # --- snímky ---

    def pridat_snimek(self, kopie):
        a = self.anim()
        if not a:
            return

        def add():
            self.snimek = self.doc.add_frame(self.vrstva, a.name, self.snimek + 1,
                                             copy_from=self.snimek if kopie else None)
        self.zmena(add, "animace", "snimky", "platno")

    def smazat_snimek(self):
        a = self.anim()
        if a:
            def rm():
                self.snimek = self.doc.delete_frame(self.vrstva, a.name, self.snimek)
            self.zmena(rm, "animace", "snimky", "platno")

    def posun_snimek(self, d):
        a = self.anim()
        if a:
            def mv():
                self.snimek = self.doc.move_frame(self.vrstva, a.name, self.snimek, d)
            self.zmena(mv, "snimky", "platno")

    def _uprav_pixely(self, fn):
        fr = self.frame()
        if fr:
            def do():
                px = self.cil(self.frame(), vytvorit=True)
                px[:] = fn(px)
            self.zmena(do, "snimky", "platno")

    def posun_obsah(self, dx, dy):
        self._uprav_pixely(lambda px: skin_edit.shift(px, self.doc.size, dx, dy, self.mazani()))

    def zrcadlit(self):
        self._uprav_pixely(lambda px: skin_edit.flip(px, self.doc.size))

    def vycistit(self):
        self._uprav_pixely(lambda px: bytearray([self.mazani()]) * len(px))

    def nastav_kotvu(self, slot, x, y, vsechny=False):
        def do():
            frames = self.anim().frames if vsechny else [self.frame()]
            for fr in frames:
                fr.anchors[slot] = (x, y)
        self.zmena(do, "platno")
        self.hlaska(f"kotva {SLICE_NAMES.get(slot, slot)}: {x}, {y}" + (" (celá animace)" if vsechny else ""))

    def _drzi(self, slot, on):
        fr = self.frame()
        if self._plnim or not fr or (slot in fr.keep) == on:
            return
        self.zmena(lambda: (self.frame().keep.add if on else self.frame().keep.discard)(slot))

    def _drzi_vse(self):
        fr, a = self.frame(), self.anim()
        if fr and a:
            def do():
                for f in a.frames:
                    f.keep = set(fr.keep)
            self.zmena(do)

    # --- palety ---

    def uprav_barvu(self, palette, k):
        if not self.upravitelny() or k == 0:
            return
        old = self.doc.palettes[palette][k]
        c = QColorDialog.getColor(QColor(old), self, f"Barva {k} v paletě {palette}")
        if c.isValid() and c.name() != old:
            self.zmena(lambda: self.doc.set_color(palette, k, c.name()), "palety", "snimky", "platno")

    def _bunka_palety(self, r, c):
        self.uprav_barvu(list(self.doc.palettes)[r], c)

    def _vybrana_paleta(self):
        r = self.tabulka.currentRow()
        names = list(self.doc.palettes)
        return names[r] if 0 <= r < len(names) else None

    def nova_paleta(self):
        name = self._jmeno("Nová paleta", "Jméno (např. warm, cold, faded, noc):")
        if name:
            self.zmena(lambda: self.doc.add_palette(name), "palety", "stavy")

    def odvodit_paletu(self):
        kinds = {"teplá – radost (warm)": ("warm", "warm"), "studená – frustrace (cold)": ("cold", "cold"),
                 "vybledlá – únava (faded)": ("faded", "faded")}
        pick, ok = QInputDialog.getItem(self, "Odvodit paletu", "Varianta barev postavy (přepíše paletu "
                                        "stejného jména):", list(kinds), 0, False)
        if ok:
            name, kind = kinds[pick]
            self.zmena(lambda: self.doc.derive_palette(name, kind), "palety", "stavy")

    def prejmenovat_paletu(self):
        old = self._vybrana_paleta()
        if not old:
            return self.hlaska("vyber paletu v tabulce", chyba=True)
        name = self._jmeno("Přejmenovat paletu", "Nové jméno:", text=old)
        if name:
            self.zmena(lambda: self.doc.rename_palette(old, name), "palety", "stavy")

    def smazat_paletu(self):
        name = self._vybrana_paleta()
        if not name:
            return self.hlaska("vyber paletu v tabulce", chyba=True)
        self.zmena(lambda: self.doc.delete_palette(name), "palety", "stavy", "platno")

    def pridat_barvu(self):
        def add():
            self.barva = self.doc.add_color()
        self.zmena(add, "palety")

    def odebrat_barvu(self):
        self.zmena(self.doc.remove_last_color, "palety")

    def premalovat(self):
        n = len(self.doc.colors())
        old, ok = QInputDialog.getInt(self, "Přemalovat index", "Index, který zmizí ze všech snímků:",
                                      self.barva, 1, n - 1)
        if not ok:
            return
        new, ok = QInputDialog.getInt(self, "Přemalovat index", f"Nahradit indexem (0 = průhledná):", 1, 0, n - 1)
        if ok and new != old:
            self.zmena(lambda: self.doc.replace_color(old, new), "palety", "snimky", "platno")

    # --- stavy, nálady, vlastnosti ---

    def _zmena_stavu(self, key):
        if self._plnim:
            return
        kind, name = key
        value = self.stavy[key].currentData()

        def do():
            act = self.doc.activity
            if kind == "state":
                skin_edit._set(act, name, value)
            else:
                w = act.get("working")
                w = dict(w) if isinstance(w, dict) else ({"default": w} if isinstance(w, str) else {})
                skin_edit._set(w, name, value)
                skin_edit._set(act, "working", w or None)
        self.zmena(do, "animace")

    def _zmena_nalady(self, mood, key):
        if self._plnim:
            return
        row = self.nalady[mood]
        value = row[key].value() if key == "tempo" else row[key].currentData()

        def do():
            m = self.doc.moods.setdefault(mood, {"palette": "base"})
            skin_edit._set(m, key, None if key == "tempo" and abs(value - 1.0) < 1e-9 else value)
        self.zmena(do, "animace")

    def _zmena_meta(self, key):
        if self._plnim or not self.doc:
            return
        value = self.facing.currentData() if key == "facing" else self.meta[key].text().strip()
        if (self.doc.meta.get(key) or None) == (value or None):
            return
        self.zmena(lambda: skin_edit._set(self.doc.meta, key, value or None), "vlastnosti")

    def _zmena_kotvy(self):
        if self._plnim:
            return
        xy = (self.ax.value(), self.ay.value())
        if xy != tuple(self.doc.anchor):
            self.zmena(lambda: setattr(self.doc, "anchor", xy), "platno")

    def zmenit_platno(self):
        w, h = self.sw.value(), self.sh.value()
        if (w, h) == tuple(self.doc.size):
            return
        if self._potvrdit("Změnit plátno", f"Změnit plátno všech vrstev na {w}×{h} px? Kresba zůstane na středu "
                                           "spodní hrany, co se nevejde, se ořízne."):
            self.zmena(lambda: self.doc.resize(w, h))

    # --- soubory ---

    def _potvrdit(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _zeptej_ulozit(self):
        """Save / Discard / Cancel u neuložených změn (testy ho nahrazují)."""
        B = QMessageBox.StandardButton
        return QMessageBox.question(self, "Neuložené změny",
                                    f"Familiar {self.doc.name} má neuložené změny. Uložit je?",
                                    B.Save | B.Discard | B.Cancel, B.Save)

    def muze_zavrit(self):
        """True, když se editor smí zavřít nebo přepnout skin (neuložené se uloží nebo zahodí)."""
        if not self.doc or not self.dirty:
            return True
        r = self._zeptej_ulozit()
        if r == QMessageBox.StandardButton.Save:
            return self.ulozit()
        if r == QMessageBox.StandardButton.Discard:
            self.dirty = False
            return True
        return False

    def ulozit(self, skin_id=None):
        if not self.upravitelny():
            return False
        try:
            dest = skin_edit.save(self.doc, skin_id)
        except (SkinError, OSError) as e:
            self.hlaska(f"Neuloženo: {e}", chyba=True)
            QMessageBox.warning(self, "Skin nejde uložit", str(e))
            return False
        self.dirty = False
        self._obnov_skiny(self.doc.id)
        self._obnov("vlastnosti")
        self.hlaska(f"Uloženo do {_short(dest)}. Běžící familiar ho načte sám.")
        self.ulozeno.emit(self.doc.id)
        return True

    def zahodit(self):
        if self.doc and self.dirty and self._potvrdit("Zahodit změny", "Zahodit neuložené změny skinu?"):
            self.dirty = False
            self.nacti(self.doc.id)

    def _nove_id(self, title, default=""):
        while True:
            sid, ok = QInputDialog.getText(self, title, "Id (jméno adresáře: písmena, číslice, -, _, .):",
                                           text=default)
            sid = sid.strip()
            if not ok or not sid:
                return None
            if not skin_edit.valid_id(sid) or sid == skin.BUILTIN:
                QMessageBox.warning(self, title, f"Id {sid!r} nejde použít.")
            elif skin.find(sid) and not self._potvrdit(title, f"Skin {sid} už existuje. Přepsat (tvou kopií)?"):
                default = sid
            else:
                return sid

    def ulozit_jako(self):
        if not self.upravitelny():
            return
        sid = self._nove_id("Uložit jako", self.doc.id + "-2")
        if sid and self.ulozit(sid):
            self._undo.clear()
            self._redo.clear()
            self._obnov()

    def novy(self):
        if not self.muze_zavrit():
            return
        dlg = NovySkin(self, skin.available(), self.doc.id if self.doc and self.doc.editable() else None)
        while dlg.exec() == QDialog.DialogCode.Accepted:
            sid, name, template, size = dlg.hodnoty()
            if not skin_edit.valid_id(sid) or sid == skin.BUILTIN:
                QMessageBox.warning(self, "Nový familiar", f"Id {sid!r} nejde použít (písmena, číslice, -, _, .).")
                continue
            if skin.find(sid) and not self._potvrdit("Nový familiar", f"Skin {sid} už existuje. Přepsat?"):
                continue
            try:
                if template:
                    doc = skin_edit.load_id(template)
                    if name:
                        doc.meta["name"] = name
                    elif template != sid:
                        doc.meta["name"] = f"{doc.name} (kopie)"
                else:
                    doc = skin_edit.new(sid, name or sid, size)
                skin_edit.save(doc, sid)
            except (SkinError, OSError) as e:
                QMessageBox.warning(self, "Nový familiar", str(e))
                return
            self.nacti(sid)
            self.ulozeno.emit(sid)
            return

    def importovat(self):
        if not self.muze_zavrit():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import postavičky z Aseprite", os.path.expanduser("~"),
                                              "Aseprite a sprite sheety (*.aseprite *.ase *.json *.png);;"
                                              "Všechny soubory (*)")
        if not path:
            return
        from familiar import skin_import
        sid = self._nove_id("Import", skin_import.default_id(path))
        if not sid:
            return
        try:
            dest, report, warn = skin_import.importuj(path, sid, prepsat=True)
        except (SkinError, OSError, ValueError) as e:
            QMessageBox.warning(self, "Import se nepovedl", str(e))
            return
        lines = [f"{st}: {tag}" + (" (odvozeno)" if derived else "") for st, (tag, derived) in report.items()]
        QMessageBox.information(self, "Importováno", f"Skin {sid} je v {_short(dest)}.\n\n" + "\n".join(lines) +
                                ("\n\nVarování:\n" + "\n".join(warn) if warn else ""))
        self.nacti(sid)
        self.ulozeno.emit(sid)

    def smazat(self):
        d = self.doc
        if not d or d.source != skin.USER:
            return
        shadow = os.path.isdir(os.path.join(skin.PACKAGE_DIR, d.id))
        text = (f"Smazat tvou kopii skinu {d.id}? Vrátí se skin z balíčku." if shadow else
                f"Smazat familiar {d.name} ({d.id}) i se všemi soubory v {_short(d.path)}?")
        if not self._potvrdit("Smazat familiar", text):
            return
        try:
            skin_edit.delete(d.id)
        except (SkinError, OSError) as e:
            QMessageBox.warning(self, "Smazat", str(e))
            return
        self.dirty = False
        self.nacti(d.id if shadow else skin.DEFAULT)
        self.ulozeno.emit(d.id)

    def otevrit_slozku(self):
        found = skin.find(self.doc.id) if self.doc else None
        if found:
            QDesktopServices.openUrl(QUrl.fromLocalFile(found[0]))


def nazev_klobouku(h):
    from familiar.nastaveni import HATS
    return f"{HATS[h]} ({h})" if h in HATS else h


def _html(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path and path.startswith(home + os.sep) else path


class OknoEditoru(QWidget):
    """Editor jako samostatné okno (python3 -m familiar.editor)."""

    def __init__(self, skin_id=None):
        super().__init__()
        self.setWindowTitle("Editor familiárů")
        lay = QVBoxLayout(self)
        self.editor = EditorSkinu(self, skin_id)
        lay.addWidget(self.editor)
        self.resize(1200, 800)

    def closeEvent(self, ev):
        if self.editor.muze_zavrit():
            ev.accept()
        else:
            ev.ignore()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = OknoEditoru(argv[0] if argv else None)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()

# Okno „Statistiky a úspěchy“ (M17): záložky Dnes, Týden, Úspěchy a Doplňky.
#
# Styl jako panel nálady (panel.py): malé samostatné okno Qt.Tool s rámečkem. Data dostane
# hotová – nastav(data, skin), data ze stats.prehled() – a sám nic nečte: v daemonu je
# obnovuje zdroj (nabidka.py → sluzby.Sluzby.prehled, tytéž instance, které počítají) každé
# OBNOVA_MS, dokud je okno vidět. Ukazuje jen čísla a názvy nástrojů.
# Grafy kreslí QPainter po „pixelech“ (čtverečky, bez antialiasingu), žádné další knihovny.
# Výběr doplňku (klobouk, emoty v klidu) vyšle signál zmena({klíč configu: hodnota}).
#
#   python3 -m familiar.statistiky_okno       # ukázka se syntetickými daty
import math, time
from datetime import date, datetime, timedelta

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, qRgba
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from familiar import skin as skins
from familiar.stats import DNY, cas
from familiar.panel import BARVA_A, BARVA_V, MRIZKA, PLOCHA, POZADI, TEXT, TLUMENY, _font

OBNOVA_MS = 3000
PX = 4                  # velikost „pixelu“ grafů
NASTROJU = 8            # nejčastějších nástrojů na záložce Dnes
BARVY = ("#5cc8a8", "#ffd166", "#ef476f", "#c77dff", "#5fa8d3", "#f8961e", "#06d6a0", "#a0663c")
CERVENA, ZLATA, ZLATA_TMAVA = "#ef476f", "#ffd166", "#f8961e"
METRIKY = {"aktivni_s": "Aktivní čas", "prompty": "Prompty", "volani": "Nástroje"}


def _datum(ts):
    t = time.localtime(ts)
    return f"{t.tm_mday}. {t.tm_mon}. {t.tm_hour}:{t.tm_min:02d}"


def _michej(a, b, k):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * k), round(a.green() + (b.green() - a.green()) * k),
                  round(a.blue() + (b.blue() - a.blue()) * k))


# --- grafy ---------------------------------------------------------------------

class Nastroje(QWidget):
    """Nejčastější nástroje: vodorovné sloupce z pixelových čtverečků."""
    RADEK = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(self.RADEK * 3)

    def nastav(self, nastroje):
        self.data = sorted(nastroje.items(), key=lambda x: (-x[1], x[0]))[:NASTROJU]
        self.setMinimumHeight(max(3, len(self.data)) * self.RADEK + 4)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(POZADI))
        p.setFont(_font(11))
        if not self.data:
            p.setPen(QColor(TLUMENY))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "dnes zatím žádný nástroj")
            return
        jmeno_w, cislo_w = 120, 44
        sirka = max(PX, self.width() - jmeno_w - cislo_w - 12)
        bunek = sirka // (PX + 1)
        nejvic = self.data[0][1] or 1
        for i, (jmeno, n) in enumerate(self.data):
            y = 2 + i * self.RADEK
            p.setPen(QColor(TEXT))
            text = p.fontMetrics().elidedText(jmeno, Qt.TextElideMode.ElideMiddle, jmeno_w - 6)
            p.drawText(QRect(0, y, jmeno_w - 6, self.RADEK - 4), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            k = max(1, round(n / nejvic * bunek))
            barva = BARVY[i % len(BARVY)]
            for c in range(bunek):
                x = jmeno_w + c * (PX + 1)
                p.fillRect(x, y + 3, PX, self.RADEK - 9, QColor(barva) if c < k else QColor(PLOCHA))
            p.setPen(QColor(TLUMENY))
            p.drawText(QRect(jmeno_w + bunek * (PX + 1) + 6, y, cislo_w, self.RADEK - 4),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(n))


class NaladaDne(QWidget):
    """Průběh nálady za den po hodinách: valence jako sloupce od nuly, aktivace jako pás pod nimi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nalada, self.hodina = {}, None
        self.setMinimumSize(360, 128)

    def nastav(self, nalada, hodina=None):
        self.nalada, self.hodina = {int(h): v for h, v in (nalada or {}).items()}, hodina
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(POZADI))
        p.setFont(_font(10))
        left, right = 22, self.width() - 4
        top, pas = 6, 12
        bottom = self.height() - 16 - pas - 4
        sl = max(PX, (right - left) // 24)
        stred = top + (bottom - top) // 2 // PX * PX
        p.fillRect(left, top, sl * 24, bottom - top, QColor(PLOCHA))
        p.setPen(QColor(TLUMENY))
        for v, text in ((1, "+1"), (0, "0"), (-1, "−1")):
            y = stred - round(v * (stred - top))
            p.drawText(QRect(0, y - 6, left - 3, 12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        p.fillRect(left, stred, sl * 24, 1, QColor(MRIZKA))
        for h in range(24):
            x = left + h * sl
            if h == self.hodina:
                p.fillRect(x, top, sl, bottom - top, QColor(MRIZKA))
            if h % 6 == 0:
                p.drawText(x, self.height() - 3, str(h))
            hod = self.nalada.get(h)
            ya = bottom + 4
            if hod is None:
                p.fillRect(x + 1, ya, sl - 2, pas, QColor(PLOCHA))
                continue
            v, a = hod
            n = round(abs(v) * (stred - top) / PX)
            barva = BARVA_V if v >= 0 else CERVENA
            for k in range(max(1, n)):
                y = stred - (k + 1) * PX if v >= 0 else stred + 1 + k * PX
                p.fillRect(x + 1, y, sl - 2, PX - 1, QColor(barva))
            p.fillRect(x + 1, ya, sl - 2, pas, _michej(PLOCHA, BARVA_A, max(0.15, min(1.0, a))))
        if not self.nalada:
            p.setPen(QColor(TLUMENY))
            p.drawText(QRect(left, top, sl * 24, bottom - top), Qt.AlignmentFlag.AlignCenter, "zatím žádná data")


class Tyden(QWidget):
    """Sloupcový graf po dnech týdne (Po–Ne) ze čtverečků; dnešek zvýrazněný."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dny, self.metrika, self.dnes = [], "aktivni_s", None
        self.setMinimumSize(360, 190)

    def nastav(self, dny, metrika=None, dnes=None):
        self.dny, self.dnes = dny or [], dnes
        self.metrika = metrika or self.metrika
        self.update()

    @staticmethod
    def popis(metrika, v):
        return cas(v) if metrika == "aktivni_s" else str(v)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(POZADI))
        p.setFont(_font(10))
        top, bottom = 18, self.height() - 30
        sl = max(16, (self.width() - 8) // 7)
        hodnoty = [d.get(self.metrika, 0) for d in self.dny]
        nejvic = max(hodnoty, default=0) or 1
        bloku = max(1, (bottom - top) // (PX + 1))
        for i, d in enumerate(self.dny):
            x = 4 + i * sl
            w = sl - 10
            v = hodnoty[i]
            k = round(v / nejvic * bloku) if v else 0
            dnes = d.get("datum") == self.dnes
            barva = BARVA_A if dnes else "#3d7ea6"
            for b in range(bloku):
                y = bottom - (b + 1) * (PX + 1)
                p.fillRect(x + 4, y, w, PX, QColor(barva) if b < k else QColor(PLOCHA))
            p.setPen(QColor(TEXT if dnes else TLUMENY))
            if v:
                p.drawText(QRect(x, bottom - k * (PX + 1) - 15, sl - 2, 13), Qt.AlignmentFlag.AlignCenter,
                           self.popis(self.metrika, v))
            p.setFont(_font(11, dnes))
            p.drawText(QRect(x, bottom + 2, sl - 2, 14), Qt.AlignmentFlag.AlignCenter, DNY[i])
            p.setFont(_font(10))
            try:
                dd = date.fromisoformat(d["datum"])
                p.drawText(QRect(x, bottom + 15, sl - 2, 13), Qt.AlignmentFlag.AlignCenter, f"{dd.day}. {dd.month}.")
            except (KeyError, TypeError, ValueError):
                pass


class PixelBar(QWidget):
    """Ukazatel XP do další úrovně ze čtverečků."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.k = 0.0
        self.setFixedHeight(16)

    def nastav(self, k):
        self.k = max(0.0, min(1.0, k))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(POZADI))
        n = max(1, (self.width() - 4) // (PX + 2))
        plno = round(self.k * n)
        for i in range(n):
            x = 2 + i * (PX + 2)
            p.fillRect(x, 2, PX, 12, QColor(ZLATA if i < plno else PLOCHA))
            if i < plno:
                p.fillRect(x, 11, PX, 3, QColor(ZLATA_TMAVA))


MEDAILE = ["rrr....bbb",
           ".rrr..bbb.",
           "..rrrbbb..",
           "...oooo...",
           "..oyyyyo..",
           ".oyywyyyo.",
           ".oyyyyyyo.",
           ".oyyyyyyd.",
           "..oyyydo..",
           "...oooo..."]


class Medaile(QWidget):
    """Pixelová medaile odznaku: odemčená barevná (stuha podle úspěchu), zamčená šedá."""

    def __init__(self, barva, odemceno, parent=None):
        super().__init__(parent)
        self.barva, self.odemceno = barva, odemceno
        self.setFixedSize(30, 30)

    def paintEvent(self, ev):
        p = QPainter(self)
        if self.odemceno:
            barvy = {"r": self.barva, "b": QColor(self.barva).darker(130).name(), "o": "#1b1b2f",
                     "y": ZLATA, "w": "#f1f1f1", "d": ZLATA_TMAVA}
        else:
            barvy = {"r": "#4a5263", "b": "#3c4352", "o": "#2a2f3c", "y": "#5b6475", "w": "#767f90", "d": "#4f5767"}
        for y, radek in enumerate(MEDAILE):
            for x, ch in enumerate(radek):
                if ch in barvy:
                    p.fillRect(x * 3, y * 3, 3, 3, QColor(barvy[ch]))


# --- náhledy postavičky ------------------------------------------------------------

def umi(skin, druh, sprite):
    """Nakreslí skin tenhle klobouk/emote? (vestavěný všechny, balíček podle tagů vrstvy)."""
    if not isinstance(skin, skins.PackageSkin):
        return True
    sheet = skin.acc if druh == "klobouk" else skin.emote
    return bool(sheet) and sprite in sheet.tags


def nahled(skin, druh, sprite, sedy=False, z=2):
    """QPixmap klidové postavičky s kloboukem nebo emotem (zamčený doplněk šedě)."""
    anim = skin.anim_for("idle")
    look = ("klid", sprite if druh == "klobouk" else None, sprite if druh == "emote" else None, 0, 0, 0)
    try:
        px, colors = skin.render(anim, 0, look)
    except Exception:       # vadný skin: náhled z vestavěného
        skin = skins.builtin()
        px, colors = skin.render(skin.anim_for("idle"), 0, look)
    w, h = skin.size
    tab = []
    for c in colors:
        if c is None:
            tab.append(qRgba(0, 0, 0, 0))
            continue
        q = QColor(c)
        if sedy:
            g = round(60 + 0.45 * (0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()))
            q = QColor(g, g, g + 8)
        tab.append(qRgba(q.red(), q.green(), q.blue(), 255))
    tab += [qRgba(0, 0, 0, 0)] * (256 - len(tab))
    img = QImage(bytes(px), w, h, w, QImage.Format.Format_Indexed8)
    img.setColorTable(tab)
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img.scaled(w * z, h * z, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.FastTransformation))


# --- okno ------------------------------------------------------------------------

def _dlazdice(cislo, popisek):
    f = QFrame(objectName="dlazdice")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(8, 5, 8, 5)
    lay.setSpacing(0)
    c = QLabel(str(cislo), objectName="cislo")
    lay.addWidget(c)
    lay.addWidget(QLabel(popisek, objectName="tlumeny"))
    f.cislo = c
    return f


def _vycisti(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _vycisti(it.layout())


class StatistikyOkno(QWidget):
    zmena = Signal(dict)        # {klíč configu: hodnota} z výběru doplňků

    def __init__(self, zdroj=None, parent=None):
        """zdroj() → (data ze stats.prehled, skin) pro obnovu; bez něj jen nastav()."""
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle("Statistiky a úspěchy")
        self.zdroj = zdroj
        self.data, self.skin = {}, skins.builtin()
        self.metrika = "aktivni_s"
        self._sig_uspechy = self._sig_doplnky = None
        self.setStyleSheet(f"""
            QWidget {{ background: {POZADI}; color: {TEXT}; }}
            QLabel#hlava {{ font-size: 15px; font-weight: bold; }}
            QLabel#tlumeny {{ color: {TLUMENY}; }}
            QLabel#nadpis {{ color: {TLUMENY}; margin-top: 4px; }}
            QLabel#cislo {{ font-size: 18px; font-weight: bold; }}
            QFrame#dlazdice, QFrame#karta {{ background: {PLOCHA}; border: 1px solid {MRIZKA}; }}
            QFrame#dlazdice QLabel, QFrame#karta QLabel, QFrame#karta QRadioButton {{ background: {PLOCHA}; }}
            QTabWidget::pane {{ border: 1px solid {MRIZKA}; top: -1px; }}
            QTabBar::tab {{ background: {PLOCHA}; color: {TLUMENY}; border: 1px solid {MRIZKA};
                            padding: 4px 10px; margin-right: 2px; }}
            QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {POZADI}; background: {POZADI}; }}
            QPushButton {{ background: {PLOCHA}; border: 1px solid {MRIZKA}; padding: 3px 8px; }}
            QPushButton:checked {{ border-color: {TEXT}; color: {TEXT}; background: {MRIZKA}; }}
            QScrollArea {{ border: none; }}
            QScrollBar:vertical {{ background: {POZADI}; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {MRIZKA}; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._stavba_dnes(), "Dnes")
        self.tabs.addTab(self._stavba_tyden(), "Týden")
        self.tabs.addTab(self._stavba_uspechy(), "Úspěchy")
        self.tabs.addTab(self._stavba_doplnky(), "Doplňky")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.tabs)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.obnov)
        self.resize(540, 600)

    # --- stavba záložek ---

    def _stavba_dnes(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        self.dnes_hlava = QLabel(objectName="hlava")
        lay.addWidget(self.dnes_hlava)
        self.dnes_vypnuto = QLabel("Denní statistiky jsou vypnuté ([statistiky] zapnuto v nastavení).",
                                   objectName="tlumeny")
        self.dnes_vypnuto.setWordWrap(True)
        lay.addWidget(self.dnes_vypnuto)
        mriz = QGridLayout()
        mriz.setSpacing(6)
        self.dnes_d = {}
        for i, (k, t) in enumerate((("session", "session"), ("prompty", "promptů"), ("volani", "nástrojů"),
                                    ("chyby", "chyb nástrojů"), ("aktivni_s", "aktivní čas"),
                                    ("subagenti", "subagentů"))):
            self.dnes_d[k] = _dlazdice("0", t)
            mriz.addWidget(self.dnes_d[k], i // 3, i % 3)
        lay.addLayout(mriz)
        lay.addWidget(QLabel("Nejčastější nástroje", objectName="nadpis"))
        self.nastroje = Nastroje()
        lay.addWidget(self.nastroje)
        lay.addWidget(QLabel("Nálada během dne (valence nahoře, aktivace v pásu)", objectName="nadpis"))
        self.nalada = NaladaDne()
        lay.addWidget(self.nalada)
        self.dnes_pata = QLabel(objectName="tlumeny")
        self.dnes_pata.setWordWrap(True)
        lay.addWidget(self.dnes_pata)
        lay.addStretch(1)
        return w

    def _stavba_tyden(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        self.tyden_hlava = QLabel(objectName="hlava")
        lay.addWidget(self.tyden_hlava)
        self.tyden_vypnuto = QLabel("Denní statistiky jsou vypnuté.", objectName="tlumeny")
        lay.addWidget(self.tyden_vypnuto)
        radek = QHBoxLayout()
        self.metriky = QButtonGroup(self)
        for k, t in METRIKY.items():
            b = QPushButton(t)
            b.setCheckable(True)
            b.setChecked(k == self.metrika)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=k: self._metrika(k))
            self.metriky.addButton(b)
            radek.addWidget(b)
        radek.addStretch(1)
        lay.addLayout(radek)
        self.graf_tyden = Tyden()
        lay.addWidget(self.graf_tyden)
        lay.addWidget(QLabel("Součty za týden", objectName="nadpis"))
        mriz = QGridLayout()
        mriz.setSpacing(6)
        self.tyden_d = {}
        for i, (k, t) in enumerate((("session", "session"), ("prompty", "promptů"), ("volani", "nástrojů"),
                                    ("chyby", "chyb nástrojů"), ("aktivni_s", "aktivní čas"),
                                    ("dni", "dní s prací"))):
            self.tyden_d[k] = _dlazdice("0", t)
            mriz.addWidget(self.tyden_d[k], i // 3, i % 3)
        lay.addLayout(mriz)
        self.tyden_pata = QLabel(objectName="tlumeny")
        self.tyden_pata.setWordWrap(True)
        lay.addWidget(self.tyden_pata)
        lay.addStretch(1)
        return w

    def _stavba_uspechy(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        self.uroven = QLabel(objectName="hlava")
        lay.addWidget(self.uroven)
        self.xp = PixelBar()
        lay.addWidget(self.xp)
        self.xp_text = QLabel(objectName="tlumeny")
        lay.addWidget(self.xp_text)
        self.uspechy_pocet = QLabel(objectName="nadpis")
        lay.addWidget(self.uspechy_pocet)
        obsah = QWidget()
        self.mriz_uspechu = QGridLayout(obsah)
        self.mriz_uspechu.setContentsMargins(0, 0, 4, 0)
        self.mriz_uspechu.setSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(obsah)
        lay.addWidget(sc, 1)
        return w

    def _stavba_doplnky(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        self.doplnky_popis = QLabel(objectName="tlumeny")
        self.doplnky_popis.setWordWrap(True)
        lay.addWidget(self.doplnky_popis)
        obsah = QWidget()
        self.lay_doplnku = QVBoxLayout(obsah)
        self.lay_doplnku.setContentsMargins(0, 0, 4, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(obsah)
        lay.addWidget(sc, 1)
        self.volby_klobouku = QButtonGroup(self)
        self.volby_klobouku.setExclusive(True)
        self.klobouk_vzdy = self.emoty_v_klidu = None
        return w

    # --- data ---

    def obnov(self):
        if self.zdroj is not None:
            self.nastav(*self.zdroj())

    def nastav(self, data, skin=None):
        self.data = data or {}
        self.skin = skin or self.skin
        self._nastav_dnes()
        self._nastav_tyden()
        self._nastav_uspechy()
        self._nastav_doplnky()

    def _metrika(self, k):
        self.metrika = k
        self._nastav_tyden()

    def _nastav_dnes(self):
        d = self.data.get("dnes")
        ted = self.data.get("ted") or time.time()
        t = time.localtime(ted)
        self.dnes_hlava.setText(f"Dnes, {t.tm_mday}. {t.tm_mon}. {t.tm_year}")
        self.dnes_vypnuto.setVisible(d is None)
        d = d or {}
        for k, t in self.dnes_d.items():
            t.cislo.setText(cas(d.get(k)) if k == "aktivni_s" else str(d.get(k, 0)))
        self.nastroje.nastav(d.get("nastroje") or {})
        self.nalada.nastav(d.get("nalada") or {}, time.localtime(ted).tm_hour)
        self.dnes_pata.setText(f"přerušení {d.get('preruseni', 0)} · zamítnutí {d.get('zamitnuti', 0)} · "
                               f"selhání agenta {d.get('selhani', 0)} · compacty {d.get('compacty', 0)}" if d else "")

    def _nastav_tyden(self):
        t = self.data.get("tyden")
        self.tyden_vypnuto.setVisible(t is None)
        if t is None:
            self.tyden_hlava.setText("Týden")
            self.graf_tyden.nastav([], self.metrika)
            return
        od, do = date.fromisoformat(t["od"]), date.fromisoformat(t["do"])
        self.tyden_hlava.setText(f"Týden {od.day}. {od.month}. – {do.day}. {do.month}. {do.year}")
        self.graf_tyden.nastav(t["dny"], self.metrika, self.data.get("datum"))
        s = t["soucet"]
        for k, w in self.tyden_d.items():
            if k == "dni":
                w.cislo.setText(str(sum(1 for d in t["dny"] if d["prompty"] or d["volani"] or d["aktivni_s"])))
            else:
                w.cislo.setText(cas(s.get(k)) if k == "aktivni_s" else str(s.get(k, 0)))
        top = sorted(s["nastroje"].items(), key=lambda x: (-x[1], x[0]))[:5]
        text = "Nejčastější nástroje: " + (", ".join(f"{k} {v}" for k, v in top) if top else "—")
        if s.get("nalada"):
            v, a = s["nalada"]
            text += f"\nPrůměrná nálada: valence {v:+.2f}, aktivace {a:.2f}"
        self.tyden_pata.setText(text)

    def _nastav_uspechy(self):
        p = self.data.get("postup")
        if p is None:
            self.uroven.setText("Úrovně a úspěchy jsou vypnuté")
            self.xp.nastav(0)
            self.xp_text.setText("[postup] zapnuto v nastavení")
            self.uspechy_pocet.setText("")
            seznam = []
        else:
            self.uroven.setText(f"Úroveň {p['uroven']}")
            rozsah = p["xp_do"] - p["xp_od"]
            self.xp.nastav((p["xp"] - p["xp_od"]) / rozsah if rozsah > 0 else 1.0)
            self.xp_text.setText(f"{p['xp']} XP · do úrovně {p['uroven'] + 1} zbývá {p['do_dalsi']} XP"
                                 if p["do_dalsi"] else f"{p['xp']} XP · nejvyšší úroveň")
            seznam = p["uspechy"]
            self.uspechy_pocet.setText(f"Odemčeno {sum(u['odemceno'] for u in seznam)} z {len(seznam)}")
        sig = tuple((u["id"], u["cas"]) for u in seznam)
        if sig == self._sig_uspechy:
            return
        self._sig_uspechy = sig
        _vycisti(self.mriz_uspechu)
        # odemčené napřed (podle času), pak zamčené v pevném pořadí
        poradi = sorted(seznam, key=lambda u: (not u["odemceno"], u["cas"] or 0))
        for i, u in enumerate(poradi):
            self.mriz_uspechu.addWidget(self._odznak(u, i), i // 2, i % 2)
        self.mriz_uspechu.setRowStretch(len(poradi) // 2 + 1, 1)

    def _odznak(self, u, i):
        f = QFrame(objectName="karta")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(6, 5, 6, 5)
        barva = BARVY[sum(map(ord, u["id"])) % len(BARVY)]
        lay.addWidget(Medaile(barva, u["odemceno"]), 0, Qt.AlignmentFlag.AlignTop)
        texty = QVBoxLayout()
        texty.setSpacing(1)
        nazev = QLabel(u["nazev"])
        nazev.setStyleSheet(f"font-weight: bold; color: {TEXT if u['odemceno'] else TLUMENY};")
        texty.addWidget(nazev)
        popis = QLabel(f"odemčeno {_datum(u['cas'])}" if u["odemceno"] and u["cas"] else u["popis"],
                       objectName="tlumeny")
        popis.setWordWrap(True)
        popis.setToolTip(u["popis"])
        texty.addWidget(popis)
        lay.addLayout(texty, 1)
        f.setProperty("odemceno", u["odemceno"])
        return f

    def _nastav_doplnky(self):
        p, volba = self.data.get("postup"), self.data.get("volba") or {}
        doplnky = p["doplnky"] if p else []
        sig = (self.skin.id, tuple((d["id"], d["odemceno"]) for d in doplnky), tuple(sorted(volba.items())))
        if sig == self._sig_doplnky:
            return
        self._sig_doplnky = sig
        n = sum(d["odemceno"] for d in doplnky)
        self.doplnky_popis.setText(
            "Úrovně a úspěchy jsou vypnuté." if p is None else
            f"Odemčeno {n} z {len(doplnky)}. Odemčený klobouk postavička nosí, když téma rozhovoru nemá "
            f"vlastní; odemčené emoty občas ukáže, když odpočívá. Náhled: skin {self.skin.name}.")
        for b in self.volby_klobouku.buttons():
            self.volby_klobouku.removeButton(b)
        _vycisti(self.lay_doplnku)
        if p is None:
            return
        vybrany = volba.get("doplnek_klobouk", "")
        klobouky = [d for d in doplnky if d["druh"] == "klobouk"]
        emoty = [d for d in doplnky if d["druh"] == "emote"]

        self.lay_doplnku.addWidget(QLabel("Klobouky", objectName="nadpis"))
        radek = QHBoxLayout()
        for hodnota, text in (("", "žádný"), ("auto", "poslední odemčený")):
            r = QRadioButton(text)
            r.setChecked(vybrany == hodnota)
            r.clicked.connect(lambda _=False, h=hodnota: self._vyber({"postup.doplnek_klobouk": h}))
            self.volby_klobouku.addButton(r)
            radek.addWidget(r)
        radek.addStretch(1)
        self.lay_doplnku.addLayout(radek)
        self.klobouk_vzdy = QCheckBox("nosit i místo klobouku tématu")
        self.klobouk_vzdy.setChecked(bool(volba.get("klobouk_vzdy")))
        self.klobouk_vzdy.clicked.connect(lambda on: self._vyber({"postup.klobouk_vzdy": on}))
        self.lay_doplnku.addWidget(self.klobouk_vzdy)
        if not any(umi(self.skin, "klobouk", d["sprite"]) for d in klobouky):
            pozn = QLabel(f"Skin {self.skin.name} klobouky nekreslí – náhled je na Robo-kunovi.", objectName="tlumeny")
            pozn.setWordWrap(True)
            self.lay_doplnku.addWidget(pozn)
        self.lay_doplnku.addLayout(self._karty(klobouky, vybrany))

        self.lay_doplnku.addWidget(QLabel("Emoty", objectName="nadpis"))
        self.emoty_v_klidu = QCheckBox("ukazovat odemčené emoty, když postavička odpočívá")
        self.emoty_v_klidu.setChecked(bool(volba.get("emoty_v_klidu", True)))
        self.emoty_v_klidu.clicked.connect(lambda on: self._vyber({"postup.emoty_v_klidu": on}))
        self.lay_doplnku.addWidget(self.emoty_v_klidu)
        self.lay_doplnku.addLayout(self._karty(emoty, None))
        self.lay_doplnku.addStretch(1)

    def _karty(self, doplnky, vybrany):
        mriz = QGridLayout()
        mriz.setSpacing(6)
        for i, d in enumerate(doplnky):
            f = QFrame(objectName="karta")
            lay = QHBoxLayout(f)
            lay.setContentsMargins(6, 4, 6, 4)
            s = self.skin if umi(self.skin, d["druh"], d["sprite"]) else skins.builtin()
            obr = QLabel()
            obr.setPixmap(nahled(s, d["druh"], d["sprite"], sedy=not d["odemceno"]))
            obr.setFixedSize(QSize(64, 64))
            lay.addWidget(obr)
            texty = QVBoxLayout()
            texty.setSpacing(1)
            nazev = QLabel(d["nazev"])
            nazev.setStyleSheet(f"font-weight: bold; color: {TEXT if d['odemceno'] else TLUMENY};")
            texty.addWidget(nazev)
            if not d["odemceno"]:
                zamceno = QLabel(f"zamčeno: {d['podminka']}", objectName="tlumeny")
                zamceno.setWordWrap(True)
                texty.addWidget(zamceno)
            elif vybrany is not None:
                r = QRadioButton("nosit")
                r.setChecked(vybrany == d["id"])
                r.clicked.connect(lambda _=False, k=d["id"]: self._vyber({"postup.doplnek_klobouk": k}))
                self.volby_klobouku.addButton(r)
                texty.addWidget(r)
            else:
                texty.addWidget(QLabel("odemčeno", objectName="tlumeny"))
            texty.addStretch(1)
            lay.addLayout(texty, 1)
            mriz.addWidget(f, i // 2, i % 2)
        return mriz

    def _vyber(self, zmeny):
        volba = dict(self.data.get("volba") or {})
        volba.update({k.split(".", 1)[1]: v for k, v in zmeny.items()})
        self.data = dict(self.data, volba=volba)
        self.zmena.emit(zmeny)

    # --- okno ---

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.zdroj is not None and not self.timer.isActive():
            self.timer.start(OBNOVA_MS)

    def hideEvent(self, ev):
        self.timer.stop()
        super().hideEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)


# --- ukázka ------------------------------------------------------------------------

def ukazka(ted=None):
    """Syntetická data ve tvaru stats.prehled (pro náhled a testy)."""
    from familiar import progress, stats
    ted = ted or time.time()
    s = stats.Statistiky(cesta="/nonexistent/familiar-ukazka.json")
    p = progress.Postup(cesta="/nonexistent/familiar-ukazka.json")
    dnes = datetime.fromtimestamp(ted).date()
    po = dnes - timedelta(days=dnes.weekday())
    nastroje = ["Bash", "Read", "Edit", "Grep", "Write", "Glob", "Agent", "mcp__docs__read", "WebFetch"]
    for den in range((dnes - po).days + 1):
        d = po + timedelta(days=den)
        t0 = datetime.combine(d, datetime.min.time()).timestamp() + 9 * 3600
        for k in range(12 + 9 * den):
            ts = t0 + k * 900
            if ts > ted:
                break
            ev = lambda kind, **data: {"kind": kind, "ts": ts, "pid": 1, "session": "s", "data": data}
            for e in [ev("session.start", how="startup")] * (k % 6 == 0) + [ev("user.prompt")] + \
                    [ev("tool.start", tool=nastroje[(k * 3 + i * i) % len(nastroje)]) for i in range(1 + k % 5)] + \
                    [ev("tool.end", tool="Bash", cmd="pytest" if k % 4 == 0 else "ls")] + \
                    [ev("tool.error", tool="Bash")] * (k % 7 == 3) + [ev("subagent.start")] * (k % 9 == 1):
                s.zapocti(e)
                p.zapocti(e)
            s.zapocti({"kind": "agent.done", "ts": ts + 400, "pid": 1, "data": {}})
            p.zapocti({"kind": "agent.done", "ts": ts + 400, "pid": 1, "session": "s", "data": {}})
            s.vzorek_nalady(ts, 0.7 * math.sin(k / 2.5 + den), 0.25 + 0.12 * (k % 6))
    from familiar import config
    cfg = config.defaults()
    cfg["postup"]["doplnek_klobouk"] = "auto"
    return stats.prehled(s, p, cfg, ted)


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    w = StatistikyOkno()
    w.nastav(ukazka())
    w.zmena.connect(print)
    w.show()
    app.exec()

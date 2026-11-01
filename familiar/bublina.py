# Pixelová bublina u postavičky: krátká zpráva („čte hub.py“) nebo žádost o povolení
# s tlačítky Povolit / Zamítnout (a Vždy, když Claude Code nabízí „vždy povolit“).
#
# Kreslí se po „pixelech“ velikosti scale (jako postavička: meritko_perch / meritko_dock),
# bez vyhlazování: rámeček se zkosenými rohy, stín a ocásek k postavičce (dolů, nahoru,
# vlevo nebo vpravo: perch ji staví vedle postavičky, dock pod ni).
# Kam ji posadit a co s rozhodnutím, řeší volající (dock.py, perch.js; rozhodnutí →
# Povoleni.odpovez).
#
# Proti omylu: po novém obsahu (jiný požadavek, jiný text), zobrazení nebo skoku polohy
# jsou tlačítka ZAMEK_S neaktivní (kreslí se šedě); rozhoduje uvolnění tlačítka nad tím
# tlačítkem téhož požadavku, kde začal stisk; dvojklik se nepočítá. Bublina ukáže celý
# příkaz (víc řádků, nejvýš MAX_RADKU_CO) a co znamená „Vždy“; co se nevejde celé nebo
# server označí jen_terminal, nabídne jen Zamítnout. V režimu text je průhledná pro myš.
import time

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
TEXT, POVOLENI = "text", "povoleni"
SLABY = "slaby"         # řádek popisu (slabší barva)
KOD = "kod"             # řádek příkazu (neproporcionální písmo: „--“, l/1/I se nespletou)
DOLU, NAHORU, VLEVO, VPRAVO = "dolu", "nahoru", "vlevo", "vpravo"     # kam míří ocásek
BARVY = {
    "papir": "#f4efe1", "obrys": "#2a2633", "stin": "#00000055", "text": "#2a2633", "slaby": "#6d6577",
    "allow": "#4fa35a", "deny": "#c8503f", "allow_always": "#4a78b8", "svetly": "#ffffff",
}
POPISKY = {"allow": "Povolit", "deny": "Zamítnout", "allow_always": "Vždy"}
SIRKA_TEXT = 46         # nejširší text v režimu text (v „pixelech“ skinu, ×scale)
SIRKA_POVOLENI = 64
SIRKA_POVOLENI_MAX = 110    # dlouhý příkaz: bublina se rozšíří až sem
MAX_RADKU_CO = 10       # víc řádků příkazu = nevejde se celý → jen Zamítnout
MAX_RADKU_VZDY = 4
OCAS = 3                # výška ocásku (pixely)
ZAMEK_S = 0.8           # tlačítka neaktivní po změně obsahu, zobrazení a skoku polohy
SKOK = 8                # posun o tolik pixelů skinu (×scale) a víc = skok polohy
V_TERMINALU = "Celé jen v terminálu – odpověz tam."


class Bublina(QWidget):
    """Bublina nad postavičkou. API:
    text(zprava) – režim text; povoleni(id, shrnuti) – režim povolení (shrnuti jako
    Povoleni.pozadavek: nastroj, co, vzdy, jen_terminal); skryj(); zamkni(); set_scale(s);
    set_ocas(x, smer) – kam míří ocásek: smer DOLU/NAHORU (x = px od levého okraje) nebo VLEVO/VPRAVO (x = px od
    horního okraje). Signál rozhodnuti(id, "allow"|"deny"|"allow_always") po kliku (uvolnění);
    bublina se po kliku sama schová."""

    rozhodnuti = Signal(int, str)

    def __init__(self, scale=3, parent=None, flags=FLAGS, barvy=None):
        super().__init__(parent, flags if parent is None else Qt.Widget)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)     # celý příkaz v tooltipu i bez aktivace okna
        self.setWindowTitle("familiar-bublina")
        self.setMouseTracking(True)
        self.barvy = {**BARVY, **(barvy or {})}
        self.rezim, self.id, self.zprava, self.shrnuti = None, None, "", {}
        self.ocas_x, self.nad, self.smer = None, None, DOLU
        self.tlacitka = []      # [(rozhodnutí, QRect v souřadnicích těla)]
        self.cas = time.monotonic
        self.zamceno_do, self.stisk = float("-inf"), None     # stisk: (id, tlačítko)
        self._odemkni = QTimer(self)
        self._odemkni.setSingleShot(True)
        self._odemkni.timeout.connect(self.update)
        self.scale = None
        self.set_scale(scale)

    # --- API ---

    def set_scale(self, scale):
        scale = max(1, int(scale + 0.5))
        if scale == self.scale:
            return
        self.scale = scale
        self.font = QFont()
        self.font.setPixelSize(max(9, 4 * scale))
        self.font.setStyleStrategy(QFont.NoAntialias)
        self.font_tucne = QFont(self.font)
        self.font_tucne.setBold(True)
        self.font_kod = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.font_kod.setPixelSize(max(9, 4 * scale))
        self.font_kod.setStyleStrategy(QFont.NoAntialias)
        self._rozvrh()

    def set_ocas(self, x, smer=None):
        self.ocas_x = x
        if smer is not None and smer != self.smer:
            self.smer = smer
            self._rozvrh()
        self.update()

    def text(self, zprava):
        self.rezim, self.id, self.zprava, self.shrnuti = TEXT, None, " ".join(str(zprava).split()), {}
        self.stisk = None
        self._vstup()
        self._rozvrh()

    def povoleni(self, id_, shrnuti):
        shrnuti = dict(shrnuti or {})
        if (self.rezim, self.id, self.shrnuti) != (POVOLENI, id_, shrnuti):
            self.zamkni()
        self.rezim, self.id, self.shrnuti = POVOLENI, id_, shrnuti
        self._vstup()
        self._rozvrh()
        tip = shrnuti.get("co") or ""
        if shrnuti.get("vzdy"):
            tip += f"\n\nVždy: {shrnuti['vzdy']}"
        self.setToolTip(tip)

    def skryj(self, id_=None):
        """Schová bublinu; s id jen tehdy, když ukazuje tento požadavek (signál zruseno)."""
        if id_ is not None and (self.rezim != POVOLENI or self.id != id_):
            return
        self.rezim, self.id, self.stisk = None, None, None
        self.setToolTip("")
        self.hide()

    def zamkni(self):
        """Tlačítka na ZAMEK_S neaktivní; rozpracovaný stisk propadne."""
        self.zamceno_do, self.stisk = self.cas() + ZAMEK_S, None
        self._odemkni.start(int(ZAMEK_S * 1000) + 20)
        self.update()

    def zamceno(self):
        return self.cas() < self.zamceno_do

    def _vstup(self):
        """Text nepřijímá myš (klik projde do titulku terminálu / docku), povolení ano.
        Okno (perch): příznak QWindow – na Waylandu prázdná vstupní oblast, na X11 tvar vstupu;
        widget v docku: WA_TransparentForMouseEvents."""
        pruhledna = self.rezim != POVOLENI
        self.setAttribute(Qt.WA_TransparentForMouseEvents, pruhledna)
        okno = self.windowHandle() if self.isWindow() else None
        if okno is not None and bool(okno.flags() & Qt.WindowTransparentForInput) != pruhledna:
            okno.setFlag(Qt.WindowTransparentForInput, pruhledna)

    # --- rozvržení a kreslení ---

    def _rozvrh(self):
        s, fm, fb = self.scale, QFontMetrics(self.font), QFontMetrics(self.font_tucne)
        fk = QFontMetrics(self.font_kod)
        pad = 3 * s
        self.tlacitka, self.radky = [], []     # radky: [(text, True = tučně | False | SLABY | KOD)]
        self.neuplne = False
        if self.rezim == POVOLENI:
            sh = self.shrnuti
            sirka = SIRKA_POVOLENI * s
            co = self._zalom_radky(sh.get("co") or "", fk, sirka)
            if len(co) > 3:     # dlouhý příkaz: širší bublina
                sirka = SIRKA_POVOLENI_MAX * s
                co = self._zalom_radky(sh.get("co") or "", fk, sirka)
            if len(co) > MAX_RADKU_CO:
                self.neuplne = True
                co = co[:MAX_RADKU_CO]
                co[-1] = fk.elidedText(co[-1] + " …", Qt.ElideRight, sirka)
            jen_zamitnout = self.neuplne or bool(sh.get("jen_terminal"))
            nastroj = sh.get("nastroj") or "?"
            self.radky.append((fb.elidedText(f"{nastroj}?", Qt.ElideRight, sirka), True))
            self.radky += [(r, KOD) for r in co]
            vzdy = []
            if sh.get("vzdy") and not jen_zamitnout:
                vzdy = self._zalom_vse(f"Vždy = {sh['vzdy']}", fm, sirka)
                if len(vzdy) > MAX_RADKU_VZDY:
                    vzdy = []       # popis by nebyl celý vidět: „Vždy“ se nenabídne
            self.radky += [(r, SLABY) for r in vzdy]
            if jen_zamitnout:
                self.radky += [(r, SLABY) for r in self._zalom_vse(V_TERMINALU, fm, sirka)]
                volby = ["deny"]
            else:
                volby = ["allow", "deny"] + (["allow_always"] if vzdy else [])
            bw = [fb.horizontalAdvance(POPISKY[v]) + 4 * s for v in volby]
            sirky = {True: fb, KOD: fk}
            obsah = max([sirky.get(b, fm).horizontalAdvance(t) for t, b in self.radky]
                        + [sum(bw) + 2 * s * (len(bw) - 1)])
        else:
            sirka = SIRKA_TEXT * s
            for radek in self._zalom(self.zprava, fm, sirka, 2):
                self.radky.append((radek, False))
            obsah = max([fm.horizontalAdvance(t) for t, _ in self.radky] or [0])
        w = obsah + 2 * pad + 2 * s
        self.h_radku = h_radku = max(fm.height(), fk.height())
        h = 2 * pad + len(self.radky) * h_radku
        if self.rezim == POVOLENI:
            bh = fb.height() + 2 * s
            x, y = pad + s, h + s
            for v, b in zip(volby, bw):
                self.tlacitka.append((v, QRect(x, y, b, bh)))
                x += b + 2 * s
            h += bh + 2 * s
        o = OCAS * s
        x0, y0 = (o if self.smer == VLEVO else 0), (o if self.smer == NAHORU else 0)
        self.telo = QRect(x0, y0, w, h)
        if self.smer in (VLEVO, VPRAVO):
            self.setFixedSize(w + s + o, h + s)     # + stín a ocásek
        else:
            self.setFixedSize(w + s, h + s + o)
        self.update()

    @staticmethod
    def _zalom_vse(text, fm, sirka):
        """Zalomí po slovech (dlouhé slovo po znacích) do řádků široké nejvýš sirka."""
        radky, akt = [], ""
        for slovo in text.split():
            zkus = f"{akt} {slovo}" if akt else slovo
            if fm.horizontalAdvance(zkus) <= sirka:
                akt = zkus
                continue
            if akt:
                radky.append(akt)
            akt = slovo
            while fm.horizontalAdvance(akt) > sirka:
                n = len(akt)
                while n > 1 and fm.horizontalAdvance(akt[:n]) > sirka:
                    n -= 1
                radky.append(akt[:n])
                akt = akt[n:]
        if akt:
            radky.append(akt)
        return radky

    @classmethod
    def _zalom_radky(cls, text, fm, sirka):
        """Víceřádkový text (příkaz): každý řádek zvlášť zalomený."""
        return [r for radek in text.split("\n") for r in cls._zalom_vse(radek, fm, sirka)]

    @classmethod
    def _zalom(cls, text, fm, sirka, max_radku):
        """Zalomí do max_radku řádků; zbytek „…“."""
        radky = cls._zalom_vse(text, fm, sirka)
        if len(radky) > max_radku:      # zbytek do posledního řádku, elidedText ho zakončí „…“
            radky[max_radku - 1] = fm.elidedText(" ".join(radky[max_radku - 1:]), Qt.ElideRight, sirka)
            radky = radky[:max_radku]
        return radky

    def _box(self, p, r, vypln, obrys):
        """Obdélník s pixelovým obrysem a zkosenými rohy (roh = jeden chybějící pixel)."""
        s = self.scale
        p.fillRect(r.adjusted(s, s, -s, -s), QColor(vypln))
        c = QColor(obrys)
        p.fillRect(r.left() + s, r.top(), r.width() - 2 * s, s, c)
        p.fillRect(r.left() + s, r.bottom() + 1 - s, r.width() - 2 * s, s, c)
        p.fillRect(r.left(), r.top() + s, s, r.height() - 2 * s, c)
        p.fillRect(r.right() + 1 - s, r.top() + s, s, r.height() - 2 * s, c)

    def _ocas(self, p):
        """Ocásek: schůdky od obrysu těla k postavičce. Začíná v řádku (sloupci) obrysu,
        kde udělá otvor, a s každým pixelem se zužuje."""
        s, b, t = self.scale, self.barvy, self.telo
        svisly = self.smer in (DOLU, NAHORU)
        delka = t.width() if svisly else t.height()
        o = self.ocas_x - (t.left() if svisly else t.top()) if self.ocas_x is not None else delka // 2
        o = max(2 * s, min(delka - 4 * s, o - o % s))
        for k in range(OCAS + 1):
            w = (OCAS - k) * s
            for a, sirka, barva in ((o - s, w + 2 * s, b["obrys"]), (o, w, b["papir"])):
                if sirka <= 0:
                    continue
                if self.smer == DOLU:
                    r = QRect(t.left() + a, t.bottom() + 1 - s + k * s, sirka, s)
                elif self.smer == NAHORU:
                    r = QRect(t.left() + a, t.top() - k * s, sirka, s)
                elif self.smer == VPRAVO:
                    r = QRect(t.right() + 1 - s + k * s, t.top() + a, s, sirka)
                else:
                    r = QRect(t.left() - k * s, t.top() + a, s, sirka)
                p.fillRect(r, QColor(barva))

    def paintEvent(self, _):
        if self.rezim is None:
            return
        s, b = self.scale, self.barvy
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setRenderHint(QPainter.TextAntialiasing, False)
        telo = self.telo
        # stín o pixel vpravo dole, pak tělo
        p.fillRect(telo.translated(s, s).adjusted(s, s, -s, -s), QColor(b["stin"]))
        self._box(p, telo, b["papir"], b["obrys"])
        self._ocas(p)
        p.translate(telo.topLeft())     # text a tlačítka v souřadnicích těla
        # text
        pad = 3 * s
        fm = QFontMetrics(self.font)
        yy = pad
        for radek, styl in self.radky:
            p.setFont(self.font_tucne if styl is True else self.font_kod if styl == KOD else self.font)
            p.setPen(QColor(b["slaby"] if styl == SLABY else b["text"]))
            p.drawText(pad + s, yy + fm.ascent(), radek)
            yy += self.h_radku
        # tlačítka
        p.setFont(self.font_tucne)
        zamceno = self.zamceno()
        for v, r in self.tlacitka:
            barva = QColor(b["slaby"] if zamceno else b[v])
            if self.nad == v and not zamceno:
                barva = barva.lighter(125)
            self._box(p, r, barva.name(), b["obrys"])
            p.setPen(QColor(b["svetly"]))
            p.drawText(r, Qt.AlignCenter, POPISKY[v])
        p.end()

    # --- myš ---

    def _tlacitko(self, pos):
        pos = pos - self.telo.topLeft()
        for v, r in self.tlacitka:
            if r.contains(pos):
                return v
        return None

    def mouseMoveEvent(self, e):
        nad = self._tlacitko(e.position().toPoint())
        if nad != self.nad:
            self.nad = nad
            self.update()

    def leaveEvent(self, _):
        if self.nad is not None:
            self.nad = None
            self.update()

    def mousePressEvent(self, e):
        self.stisk = None
        if e.button() != Qt.LeftButton or self.rezim != POVOLENI or self.zamceno():
            return
        v = self._tlacitko(e.position().toPoint())
        if v is not None:
            self.stisk = (self.id, v)

    def mouseReleaseEvent(self, e):
        """Rozhoduje uvolnění nad tlačítkem, kde začal stisk, u téhož požadavku."""
        stisk, self.stisk = self.stisk, None
        if e.button() != Qt.LeftButton or stisk is None or self.rezim != POVOLENI or self.zamceno():
            return
        if stisk != (self.id, self._tlacitko(e.position().toPoint())):
            return
        self.skryj()
        self.rozhodnuti.emit(*stisk)

    def mouseDoubleClickEvent(self, e):
        """Druhý stisk dvojkliku nic nerozhoduje (výchozí QWidget by ho poslal jako stisk)."""
        self.stisk = None

    def showEvent(self, e):
        self._vstup()
        if self.rezim == POVOLENI:
            self.zamkni()
        super().showEvent(e)

    def moveEvent(self, e):
        """Skok polohy (v docku posun sousední buňkou) = pod myší může být jiné tlačítko."""
        d = e.pos() - e.oldPos()
        if self.isVisible() and self.rezim == POVOLENI and abs(d.x()) + abs(d.y()) >= SKOK * self.scale:
            self.zamkni()
        super().moveEvent(e)

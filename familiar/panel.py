# Panel nálady jednoho familiara (kapitola 2 konceptu: „kliknutím se otevře malý panel
# s grafem nálady za poslední hodinu a poslední událostí“).
#
# Malé samostatné okno (Qt.Tool, s rámečkem: na Waylandu ho jde přesunout a zavřít
# bez vlastní logiky). Data dostane hotová metodou nastav(stav); sám nic nesleduje.
# Uživatel může štítek nálady potvrdit nebo opravit: signál oprava(predikce, oprava)
# a řádek v opravách přes tune.uloz_opravu() (jen štítky, čísla a čas).
#
#   python3 -m familiar.panel        # ukázka se syntetickou hodinou
import math, time

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from familiar import sprites, tune

OKNO_S = 3600.0         # graf ukazuje poslední hodinu
MEZERA_S = 120.0        # delší díra mezi vzorky = přerušená čára
UDALOSTI_N = 8

POZADI, PLOCHA, MRIZKA, TEXT, TLUMENY = "#1b1f2a", "#232838", "#343c50", "#d5dbe6", "#8d99ae"
BARVA_V, BARVA_A = "#ffd166", "#5cc8a8"     # valence žlutá, aktivace tyrkysová

CINNOST = {"idle": "nečinně", "listening": "poslouchá", "thinking": "přemýšlí", "working": "pracuje",
           "waiting": "čeká na tebe", "error": "chyba", "success": "hotovo", "sleeping": "spí",
           "gone": "odešel"}
TEMA = {"elektronika": "elektronika", "kod": "kód", "web": "web", "studium": "studium",
        "reserse": "rešerše", "system": "systém"}
UDALOST = {"user.prompt": "prompt", "tool.start": "nástroj", "tool.end": "nástroj hotov",
           "tool.error": "chyba nástroje", "tool.denied": "zamítnuto", "agent.done": "kolo hotovo",
           "agent.failed": "agent selhal", "agent.interrupted": "přerušeno", "agent.waiting": "čeká",
           "context.compact": "komprimace", "session.start": "začátek session",
           "session.end": "konec session", "subagent.start": "subagent", "subagent.done": "subagent hotov"}


def _font(px, bold=False):
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _druh(kind):
    """Popisek druhu události; cokoli jiného než identifikátor se neukáže (žádné texty)."""
    if kind in UDALOST:
        return UDALOST[kind]
    ok = isinstance(kind, str) and 0 < len(kind) <= 32 and all(c.isalnum() or c in "._-" for c in kind)
    return kind if ok else "?"


def _barva(nalada):
    return sprites.palette(nalada)[3]


class Graf(QWidget):
    """Valence (−1…1) a aktivace (0…1) za poslední hodinu na společné ose s nulou uprostřed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.historie, self.ted = [], 0.0
        self.setMinimumSize(320, 150)

    def nastav(self, historie, ted):
        self.historie, self.ted = historie, ted
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)    # pixelový vzhled
        p.fillRect(self.rect(), QColor(POZADI))
        p.setFont(_font(10))
        left, top, right, bottom = 26, 16, self.width() - 6, self.height() - 16
        area = QRect(left, top, right - left, bottom - top)
        p.fillRect(area, QColor(PLOCHA))
        x_of = lambda ts: left + (ts - (self.ted - OKNO_S)) / OKNO_S * (right - left)
        y_of = lambda v: top + (1 - v) / 2 * (bottom - top)

        dots = QPen(QColor(MRIZKA), 1, Qt.PenStyle.DotLine)
        for m in (60, 45, 30, 15, 0):
            x = round(x_of(self.ted - m * 60))
            p.setPen(dots)
            p.drawLine(x, top, x, bottom)
            p.setPen(QColor(TLUMENY))
            text = "teď" if m == 0 else f"−{m} min"
            w = p.fontMetrics().horizontalAdvance(text)
            p.drawText(max(left, min(x - w // 2, right - w)), self.height() - 3, text)
        for v, text in ((1, "+1"), (0.5, ""), (0, "0"), (-0.5, ""), (-1, "−1")):
            y = round(y_of(v))
            p.setPen(QPen(QColor(TLUMENY if v == 0 else MRIZKA), 1,
                          Qt.PenStyle.SolidLine if v == 0 else Qt.PenStyle.DotLine))
            p.drawLine(left, y, right, y)
            if text:
                p.setPen(QColor(TLUMENY))
                p.drawText(QRect(0, y - 7, left - 4, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

        body = [h for h in self.historie if self.ted - OKNO_S <= h[0] <= self.ted]
        for i, barva in ((2, BARVA_A), (1, BARVA_V)):       # valence navrch
            p.setPen(QPen(QColor(barva), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
            usek, prev = [], None
            for h in body:
                if prev is not None and h[0] - prev > MEZERA_S:
                    self._cara(p, usek)
                    usek = []
                usek.append(QPoint(round(x_of(h[0])), round(y_of(max(-1.0, min(1.0, h[i]))))))
                prev = h[0]
            self._cara(p, usek)

        x = right - 4
        for text, barva in (("aktivace", BARVA_A), ("valence", BARVA_V)):     # legenda vpravo nahoře
            w = p.fontMetrics().horizontalAdvance(text)
            x -= w
            p.setPen(QColor(TEXT))
            p.drawText(x, 11, text)
            p.fillRect(x - 10, 4, 7, 7, QColor(barva))
            x -= 20
        if not body:
            p.setPen(QColor(TLUMENY))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "zatím žádná data")
        p.end()

    @staticmethod
    def _cara(p, body):
        if len(body) == 1:
            p.drawPoint(body[0])
        elif body:
            p.drawPolyline(body)


class PanelNalady(QWidget):
    oprava = Signal(str, str)       # (predikce, oprava); shodné = potvrzení

    def __init__(self, jmeno="", parent=None, cesta=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle(f"Nálada – {jmeno}" if jmeno else "Nálada familiara")
        self.cesta = cesta              # soubor oprav (None = výchozí z tune.soubor())
        self.stav = {}
        self.setStyleSheet(f"""
            QWidget {{ background: {POZADI}; color: {TEXT}; }}
            QLabel#hlava {{ font-size: 15px; font-weight: bold; }}
            QLabel#tlumeny {{ color: {TLUMENY}; }}
            QPushButton {{ background: {PLOCHA}; border: 1px solid {MRIZKA}; padding: 3px 6px; }}
            QPushButton:hover {{ border-color: {TLUMENY}; }}
            QPushButton[aktualni="true"] {{ border: 2px solid {TEXT}; font-weight: bold; }}
        """)
        self.hlava = QLabel(objectName="hlava")
        self.popis = QLabel(objectName="tlumeny")
        self.graf = Graf()
        self.udalosti = QLabel()
        self.udalosti.setFont(_font(11))
        self.udalosti.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.udalosti.setMinimumHeight(UDALOSTI_N * 15)
        self.zprava = QLabel(objectName="tlumeny")
        self.zprava.setWordWrap(True)

        tlacitka = QGridLayout()
        tlacitka.setSpacing(4)
        self.tlacitka = {}
        for i, s in enumerate(tune.STITKY):
            b = QPushButton(tune.NAZVY[s])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=s: self.opravit(s))
            tlacitka.addWidget(b, i // 3, i % 3)
            self.tlacitka[s] = b

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        lay.addWidget(self.hlava)
        lay.addWidget(self.popis)
        lay.addWidget(self.graf, 1)
        nadpis = QLabel("Poslední události", objectName="tlumeny")
        lay.addWidget(nadpis)
        lay.addWidget(self.udalosti)
        lay.addWidget(QLabel("Sedí nálada? Potvrď ji, nebo vyber správnou:", objectName="tlumeny"))
        lay.addLayout(tlacitka)
        lay.addWidget(self.zprava)
        self.resize(380, 470)
        self.nastav({})

    def nastav(self, stav):
        """stav: historie [(ts, valence, aktivace)], nalada, tema, cinnost, udalosti [(ts, druh)],
        volitelně ted (čas pravého okraje grafu) a signaly (čísla pro opravu, viz tune.SIGNALY)."""
        self.stav = stav = dict(stav)
        hist = sorted(stav.get("historie") or [])
        stav["historie"] = hist
        ted = stav.get("ted") or (hist[-1][0] if hist else time.time())
        nalada = stav.get("nalada") or "klid"
        self.hlava.setText(f'<span style="color:{_barva(nalada)}">■</span> {tune.NAZVY.get(nalada, nalada)}')
        tema = TEMA.get(stav.get("tema"), stav.get("tema") or "—")
        cinnost = CINNOST.get(stav.get("cinnost"), stav.get("cinnost") or "—")
        va = f" · v {hist[-1][1]:+.2f}, a {hist[-1][2]:.2f}" if hist else ""
        self.popis.setText(f"téma: {tema} · činnost: {cinnost}{va}")
        self.graf.nastav(hist, ted)
        ud = sorted(stav.get("udalosti") or [])[-UDALOSTI_N:]
        self.udalosti.setText("\n".join(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {_druh(k)}"
                                        for ts, k in reversed(ud)) or "—")
        for s, b in self.tlacitka.items():
            b.setProperty("aktualni", s == nalada)
            b.style().unpolish(b)
            b.style().polish(b)

    def opravit(self, stitek):
        """Uloží opravu (nebo potvrzení) aktuálního štítku a vyšle signál oprava."""
        pred = self.stav.get("nalada") or "klid"
        hist = self.stav.get("historie") or []
        v, a = (hist[-1][1], hist[-1][2]) if hist else (0.0, 0.0)
        try:
            tune.uloz_opravu(pred, stitek, max(-1.0, min(1.0, v)), max(0.0, min(1.0, a)), time.time(),
                             self.stav.get("signaly"), cesta=self.cesta)
        except (OSError, ValueError) as e:
            self.zprava.setText(f"Neuloženo: {e}")
            return
        self.zprava.setText("Díky, potvrzeno." if stitek == pred
                            else f"Díky, zapsáno: {tune.NAZVY[pred]} → {tune.NAZVY[stitek]}. "
                                 "Postavička náladu převzala.")
        self.oprava.emit(pred, stitek)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)


def ukazka(ted=None):
    """Syntetická hodina dat (pro náhled a testy)."""
    ted = ted or time.time()
    hist = []
    for i in range(0, 3600, 15):
        ts = ted - 3600 + i
        if 1500 <= i < 1900:
            continue                    # pauza
        v = 0.15 * math.sin(i / 400) + (0.5 * math.exp(-(i - 3000) / 200) if i >= 3000 else 0)
        v -= 0.45 * math.exp(-(i - 800) / 250) if i >= 800 else 0
        a = 0.2 + 0.1 * math.sin(i / 170) + (0.5 * math.exp(-(i - 800) / 90) if i >= 800 else 0)
        hist.append((ts, max(-1, min(1, v)), max(0, min(1, a))))
    kinds = ["user.prompt", "tool.start", "tool.end", "tool.error", "tool.start", "tool.end",
             "agent.done", "user.prompt", "tool.start", "tool.end", "agent.done"]
    ud = [(ted - 400 + 30 * i, k) for i, k in enumerate(kinds)]
    return {"historie": hist, "nalada": "radost", "tema": "kod", "cinnost": "working", "udalosti": ud,
            "ted": ted}


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    w = PanelNalady("ukázka", cesta="/dev/null")
    w.nastav(ukazka())
    w.oprava.connect(lambda p, o: print(p, "→", o))
    w.show()
    app.exec()

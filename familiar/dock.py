# familiard + renderer: postavička pro každý běžící claude.
#
#   python -m familiar.dock                      živě z hooků (socket v $XDG_RUNTIME_DIR)
#   python -m familiar.dock --mode dock          všechny postavičky v jednom okně
#   python -m familiar.dock --demo 0ac50887      přehraje nahrávku, bez socketu
#   (nainstalovaný: familiar run / familiar demo, viz familiar/cli.py)
#
# Režim perch (výchozí, kde to backend oken umí, familiar/okna.py): každá postavička má malé
# okno, které na horní hranu jejího terminálu posadí KWin skript perch.js (KDE), rozšíření
# GNOME Shellu (týž perch.js) nebo na X11 sám daemon (rozmisteni.py, Perches.umistovac).
# Klik přepne na terminál.
# Režim dock: jedno okno, přesouvá se tažením, dvojklik otevře panel nálady.
# Pravé tlačítko na postavičce i ikona v liště otevřou nabídku (familiar/nabidka.py).
#
# Config (familiar/config.py) se sleduje časovačem a změny se použijí za běhu:
# hub a familiary dostanou nové hodnoty, okna nové měřítko a umístění, změna
# režimu perch ↔ dock zavře okna a otevře nová (proces i stav postaviček zůstanou).
# Kreslí se přes skin (familiar/skin.py), který drží hub; změna volby `skin`
# ho vymění za běhu. Vadný skin → vestavěný Robo-kun a záznam v logu.
# Notifikace, zvuky, statistiky a úspěchy obstarává familiar/sluzby.py (posluchač hubu, ne v demu).
# Vrstvy u postavičky (data z hubu, familiar/vrstvy.py): měřič kontextu a pomocníci
# subagentů se kreslí do okna/buňky postavičky (rozvrh), bublina (činnost, zpráva
# z oznam(), žádost o povolení) je v perch samostatné okno a v docku widget pod buňkou.
# Povolení z bubliny: Povolovani drží server povoleni.Povoleni podle configu.
# Procházky a myš (logika familiar/pohyb.py v hubu): renderer dá familiaru meze procházky
# (perch: od perch.js přes D-Bus, PerchZpravy; dock: volné místo v buňce) a nakreslí posun,
# poskok a zrcadlení z fam.chuze (poza()). V perch jde posun do titulku okna a okno přesune
# perch.js; bublina, měřič i pomocníci jdou s postavičkou. Události myši → pohyb.Gesta →
# Hub.reaguj. Levý klik v perch podle [mys] klik, prostřední vždy šťouchne; v docku klik
# šťouchne, tažení přesouvá okno (startSystemMove až po pohybu), dvojklik otevře panel.
import argparse, fcntl, glob, json, logging, os, signal, socket, sys, time

from PySide6.QtCore import ClassInfo, QEvent, QObject, QPoint, QRect, QSocketNotifier, Qt, QTimer, Slot
from PySide6.QtDBus import QDBusConnection
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QRegion, qRgba
from PySide6.QtWidgets import QApplication, QMenu, QToolTip, QWidget

import familiar
from familiar import bublina as bubliny, config, log, paths, pohyb
from familiar.hub import FADE_STEPS, Hub

FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
WATCH_MS = 500      # kontrola změny configu
TRANSCRIPT_MS = 750     # čtení přírůstků transcriptů (přerušení Esc)
lg = logging.getLogger("familiar.dock")


def _table(colors):
    out = []
    for c in colors:
        if c is None:
            out.append(qRgba(0, 0, 0, 0))
        else:
            q = QColor(c)
            out.append(qRgba(q.red(), q.green(), q.blue(), 255))
    return out


def _blend(old, new, k, n):
    """Barvy palety v k-tém z n kroků přechodu old → new."""
    out = []
    for a, b in zip(old, new):
        if a is None or b is None or a == b:
            out.append(b)
        else:
            qa, qb = QColor(a), QColor(b)
            mix = [round(x + (y - x) * k / n) for x, y in ((qa.red(), qb.red()), (qa.green(), qb.green()),
                                                            (qa.blue(), qb.blue()))]
            out.append("#%02x%02x%02x" % tuple(mix))
    return out


class Images:
    """QImage snímků podle (animace, snímek, vzhled, přechod palety) jednoho skinu.
    Klíčem je instance skinu (ne id): přenačtený nebo jiný skin se stejným id
    má novou instanci, a ta cache vyprázdní."""

    def __init__(self):
        self.tables, self.images, self.skin = {}, {}, None

    def get(self, skin, anim, i, look, fade=None, mirror=False):
        if skin is not self.skin:
            self.skin = skin
            self.images.clear()
        key = (anim, i, look, fade, mirror)
        if key not in self.images:
            if len(self.images) > 4000:
                self.images.clear()
            px, colors = skin.render(anim, i, look)
            if fade:
                old = skin.render(anim, i, (fade[0],) + tuple(look[1:]))[1]
                colors = _blend(old, colors, fade[1], FADE_STEPS)
            colors = tuple(colors)
            if colors not in self.tables:
                if len(self.tables) > 400:
                    self.tables.clear()
                self.tables[colors] = _table(colors)
            w, h = skin.size
            img = QImage(bytes(px), w, h, w, QImage.Format_Indexed8)
            img.setColorTable(self.tables[colors])
            self.images[key] = img.flipped(Qt.Horizontal) if mirror else img.copy()
        return self.images[key]


def picture(hub_, frame, mirror=False):
    """Obrázek snímku (skin, animace, snímek, vzhled, přechod), případně zrcadlený; když skin
    selže, hub přejde na vestavěný a místo snímku je zatím prázdný obrázek."""
    try:
        return IMAGES.get(*frame, mirror)
    except Exception as e:
        lg.exception("skin %s nevykreslil %s/%s", frame[0].id, frame[1], frame[2])
        hub_.drop_skin(type(e).__name__)
        img = QImage(*frame[0].size, QImage.Format_ARGB32)
        img.fill(0)
        return img


IMAGES = Images()


# --- vrstvy u postavičky: měřič kontextu, pomocníci, bublina ---------------------------

METER_W, METER_H = 4, 12    # baterka měřiče v pixelech skinu (s obrysem a čepičkou)
METER_BARVY = {"ok": "#4fa35a", "pozor": "#e0b040", "plno": "#c8503f", "obrys": "#2a2633",
               "prazdno": "#4a4458"}
BEZ_VRSTEV = (None, (), 0, ())  # (měřič, pomocníci, počet dalších, jejich typy)
_mini = [None, None]            # (skin, rámeček pomocníka) jako Images: klíčem je instance skinu


def mini_ramec(skin):
    """(x, y, š, v) postavičky pracovní animace bez prázdných okrajů plátna: z toho se kreslí
    zmenšený pomocník (celé plátno je kvůli emotům a dronům zbytečně velké)."""
    if _mini[0] is not skin:
        W, H = skin.size
        try:
            anim = skin.anim_for("working")
            xs, ys = [], []
            for i in range(skin.anims[anim].frames):
                px = skin.render(anim, i, None)[0]
                for n in range(W * H):
                    if px[n]:
                        xs.append(n % W)
                        ys.append(n // W)
            ramec = (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) if xs else (0, 0, W, H)
        except Exception:       # vadný skin: celé plátno (picture() při kreslení skin vymění)
            ramec = (0, 0, W, H)
        _mini[:] = [skin, ramec]
    return _mini[1]


def na_px(n, scale):
    """n pixelů skinu v px obrazovky; měřítko může být necelé (2.505 = 250,5 %)."""
    return int(round(n * scale))


def jednotka(scale):
    """Celý pixel pro měřič, pomocníky a bublinu (ty se kreslí po celých px)."""
    return max(1, int(scale + 0.5))


def mini_meritko(scale):
    return max(1, jednotka(scale) // 2)


def rozvrh(size, scale, vnitrni, meric, sloty, mini):
    """Rozmístění postavičky, měřiče a pomocníků v okně (perch) nebo buňce (dock).
    Měřič a sloupce pomocníků (zdola nahoru, nejbližší první) jsou na straně `vnitrni`
    ("vlevo" / "vpravo"), takže postavička na opačném kraji zůstane na místě.
    size = plátno skinu, mini = (š, v) pomocníka v px, sloty = počet pomocníků (s „+N“).
    → (šířka, výška, QRect postavičky, QRect měřiče nebo None, [QRect slotů])."""
    s = jednotka(scale)
    W, H = na_px(size[0], scale), na_px(size[1], scale)
    mw = (METER_W + 1) * s if meric else 0
    sw, sh = mini
    na_sloupec = max(1, (H + s) // (sh + s))
    sloupcu = -(-sloty // na_sloupec)
    blok = sloupcu * (sw + s)
    total = W + mw + blok
    vlevo = vnitrni == "vlevo"
    char = QRect(total - W if vlevo else 0, 0, W, H)
    mr = None
    if meric:
        mr = QRect(total - W - mw if vlevo else W + s, H - METER_H * s, METER_W * s, METER_H * s)
    out = []
    for j in range(sloty):
        c, r = divmod(j, na_sloupec)
        x = blok - (c + 1) * (sw + s) if vlevo else W + mw + s + c * (sw + s)
        out.append(QRect(x, H - (r + 1) * sh - r * s, sw, sh))
    return total, H, char, mr, out


def kresli_meric(p, r, s, meric):
    """Pixelová baterka: čepička, obrys a náplň zdola podle procent (barva podle úrovně)."""
    pct, uroven = meric
    s = jednotka(s)
    obrys = QColor(METER_BARVY["obrys"])
    p.fillRect(r.x() + s, r.y(), r.width() - 2 * s, s, obrys)
    telo = QRect(r.x(), r.y() + s, r.width(), r.height() - s)
    p.fillRect(telo, obrys)
    vnitrek = telo.adjusted(s, s, -s, -s)
    p.fillRect(vnitrek, QColor(METER_BARVY["prazdno"]))
    n = vnitrek.height() // s
    plne = min(n, max(1 if pct > 0 else 0, round(pct / 100 * n)))
    if plne:
        p.fillRect(vnitrek.x(), vnitrek.y() + (n - plne) * s, vnitrek.width(), plne * s,
                   QColor(METER_BARVY[uroven]))


def kresli_pomocniky(p, hub_, sloty, pomocnici, dalsi, scale):
    """Zmenšené postavičky ve slotech; příchod = vynoří se zdola, odchod = stoupá a bliká.
    Poslední slot navíc s „+N“, když se další nevešli."""
    skin, ms = hub_.skin, mini_meritko(scale)
    bx, by, bw, bh = mini_ramec(skin)
    for slot, (_, anim, i, faze, k) in zip(sloty, pomocnici):
        if faze == "odchod" and int(k * 6) % 2:
            continue
        dy = round((1 - k) * slot.height()) if faze == "prichod" else (
            -round(k * slot.height() / 2) if faze == "odchod" else 0)
        p.save()
        if faze == "prichod":
            p.setClipRect(slot)
        p.drawImage(QRect(slot.x(), slot.y() + dy, bw * ms, bh * ms),
                    picture(hub_, (skin, anim, i, None, None)), QRect(bx, by, bw, bh))
        p.restore()
    if dalsi and len(sloty) > len(pomocnici):
        r = sloty[len(pomocnici)]
        s = jednotka(scale)
        f = QFont()
        f.setPixelSize(max(8, 5 * s))
        f.setBold(True)
        f.setStyleStrategy(QFont.NoAntialias)
        p.setFont(f)
        box = QRect(r.x(), r.bottom() + 1 - (5 * s + 2 * s), r.width(), 5 * s + 2 * s)
        p.fillRect(box.adjusted(0, s, 0, -s), QColor(METER_BARVY["obrys"]))
        p.fillRect(box.adjusted(s, 0, -s, 0), QColor(METER_BARVY["obrys"]))
        p.setPen(QColor("#f4efe1"))
        p.drawText(box, Qt.AlignCenter, f"+{dalsi}")


def popis_vrstvy(hub_, key, rv, extra, pos):
    """Text nápovědy podle místa v okně/buňce (pos v jejích souřadnicích): pomocník → typ,
    „+N“ → typy dalších, měřič → obsazení kontextu; None jinde."""
    _, _, _, mr, sloty = rv
    meric, pomocnici, dalsi, typy = extra
    for n, slot in enumerate(sloty):
        if slot.contains(pos):
            if n < len(pomocnici):
                return f"pomocník: {pomocnici[n][0]}"
            return f"další pomocníci: {', '.join(typy)}"
    if mr is not None and mr.adjusted(-2, -2, 2, 2).contains(pos):
        fam = hub_.fams.get(key)
        ctx = fam.kontext if fam else None
        if ctx:
            return f"kontext {meric[0]} % ({ctx['used'] // 1000}k z {ctx['window'] // 1000}k)"
        return f"kontext {meric[0]} %"
    return None


def ukaz_obsah(b, obsah):
    """Obsah z Familiar.bublina() do widgetu bubliny (None = schovat)."""
    if obsah is None:
        b.skryj()
        return
    if obsah[0] == "povoleni":
        b.povoleni(obsah[1], obsah[2])
    else:
        b.text(obsah[1])
    b.show()


def vrstvy_familiara(fam, now):
    """(měřič, pomocníci, počet dalších, jejich typy) pro renderer: hashovatelné, aby šla poznat změna."""
    return (fam.meric(),) + fam.pomocnici_ted(now)


BEZ_POZY = (0, 0, False)    # (posun px dovnitř, poskok px nahoru, zrcadlit)


def poza(fam, skin, scale, dovnitr_vlevo):
    """(posun, poskok, zrcadlit) z fam.chuze: posun po celých pixelech skinu (px obrazovky),
    poskok náhradní chůze, zrcadlení, když na procházce kouká proti tomu, kam kouká skin
    (skin bez facing kouká zepředu a nezrcadlí se). dovnitr_vlevo: strana, kam vede procházka."""
    x, _, smer, poskok = fam.chuze
    posun = na_px(round(x / scale), scale)
    doprava = (smer < 0) if dovnitr_vlevo else (smer > 0)
    zrcadlit = bool(smer) and skin.facing in ("right", "left") and doprava != (skin.facing == "right")
    return posun, na_px(poskok, scale), zrcadlit


def _wayland():
    return QGuiApplication.platformName().startswith("wayland")


def _quit_menu(widget, key, pos):
    """Náhradní nabídka bez ovládání (Ovladani ještě nevzniklo)."""
    menu = QMenu(widget)
    menu.addAction("Ukončit familiara", QApplication.quit)
    menu.exec(pos)


class Dock(QWidget):
    """Režim dock: jedno okno, buňka pro každou postavičku (vpravo od ní měřič kontextu
    a pomocníci). Bubliny (činnost, zprávy, povolení) visí pod buňkami: okno se kvůli nim
    zvětší dolů, postavičky zůstanou na místě."""

    def __init__(self, hub, feed=None, cfg=None, menu=None, panel=None, odpoved=None):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)
        self.setWindowTitle("familiar")
        self.hub, self.feed, self.menu, self.panel = hub, feed, menu or _quit_menu, panel
        self.odpoved = odpoved          # f(id, rozhodnutí) z bubliny povolení
        self.cells = []        # [(klíč, jméno, (skin, animace, snímek, vzhled, přechod), stav, vrstvy, poza)]
        self.bunky = []        # [(x, šířka, rozvrh)] k self.cells
        self.bubliny = {}      # klíč → [Bublina, obsah]
        self.dy = 0            # buňky posunuté dolů o bubliny nad nimi (u spodního kraje obrazovky)
        self.gesta = {}        # klíč → pohyb.Gesta
        self.stisk, self.dvojklik, self.pod_mysi = None, False, None
        self.setMouseTracking(True)
        self.font = QFont()
        self.font.setPointSize(8)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.configure(cfg or config.defaults())

    def configure(self, cfg):
        self.scale = cfg["okno"]["meritko_dock"]
        self.still = cfg["soustredeni"]
        p = cfg["prochazky"]        # místo na procházku v buňce (vpravo od postavičky a vrstev)
        self.dosah = p["dosah"] if p["zapnuto"] and not self.still else 0
        self._cell_size()
        self.mys = cfg["mys"]
        for b, _ in self.bubliny.values():
            b.set_scale(self._bublina_scale())
        self.timer.start(cfg["okno"]["snimek_ms"])
        self._fit()
        self.update()

    def _bublina_scale(self):
        return max(2, jednotka(self.scale) - 1)

    def _cell_size(self):
        """Buňka podle plátna skinu (skiny mají 32×32 až 64×64)."""
        self.size = w, h = self.hub.skin.size
        self.cell_w, self.cell_h = na_px(w, self.scale) + 12, na_px(h, self.scale) + 18
        self.misto = min(self.dosah, na_px(w, self.scale))

    def close(self):
        self.timer.stop()
        return super().close()

    def _fit(self, n=None):
        """Rozvrh buněk a velikost okna (i s bublinami pod buňkami)."""
        x, self.bunky, skin = 0, [], self.hub.skin
        ms = mini_meritko(self.scale)
        mini = tuple(v * ms for v in mini_ramec(skin)[2:])
        for cell in self.cells:
            meric, pomocnici, dalsi, _ = cell[4] if len(cell) > 4 else BEZ_VRSTEV
            rv = rozvrh(cell[2][0].size, self.scale, "vpravo", meric is not None,
                        len(pomocnici) + (1 if dalsi else 0), mini)
            w = max(self.cell_w, rv[0] + 12) + (self.misto if cell[0] is not None else 0)
            self.bunky.append((x, w, rv))
            x += w
        width = max(x, self.cell_w)
        vidne = []
        for key, (b, obsah) in self.bubliny.items():
            n = next((k for k, c in enumerate(self.cells) if c[0] == key), None) if obsah is not None else None
            if n is not None:
                vidne.append((b, n))
        vyska = max((b.height() for b, _ in vidne), default=0)
        dy = vyska + 1 if vyska and not self._misto_dole(vyska) else 0
        if dy != self.dy:
            if not _wayland():      # okno o tolik výš, aby buňky zůstaly na místě (Wayland neumí)
                self.move(self.x(), self.y() - (dy - self.dy))
            self.dy = dy
        height = self.dy + self.cell_h
        prava = 0       # bubliny sousedních buněk se nepřekrývají: další začne až za předchozí
        for b, n in sorted(vidne, key=lambda x: x[1]):
            bx, _, rv = self.bunky[n]
            cx = bx + 6 + self._posun(n) + rv[2].center().x()
            left = max(0, prava, cx - b.width() // 2)
            prava = left + b.width() + 1
            if self.dy:     # u spodního kraje obrazovky nad buňkou, ocásek dolů
                b.move(left, self.dy - 1 - b.height())
                b.set_ocas(cx - left, bubliny.DOLU)
            else:
                b.move(left, self.cell_h + 1)
                b.set_ocas(cx - left, bubliny.NAHORU)
                height = max(height, self.cell_h + 1 + b.height())
            width = max(width, left + b.width())
        if (self.width(), self.height()) != (width, height):
            self.setFixedSize(width, height)

    def _misto_dole(self, vyska):
        """Vejde se bublina pod buňky? Polohu okna zná Qt jen mimo Wayland (tam vždy True)."""
        scr = self.screen()
        if _wayland() or scr is None or not self.isVisible():
            return True
        dole = self.mapToGlobal(QPoint(0, self.dy + self.cell_h + 1 + vyska)).y()
        return dole <= scr.availableGeometry().bottom()

    def _posun(self, n):
        cell = self.cells[n]
        return cell[5][0] if len(cell) > 5 else 0

    def tick(self):
        now = time.time()
        if self.feed:
            self.feed(now)
        cells, skin, obsahy = [], self.hub.skin, {}
        if skin.size != self.size:      # skin přenačtený nebo vyměněný za jiný s jiným plátnem
            self._cell_size()
            self._fit(len(self.cells))
        for fam in self.hub.tick(now):
            fam.meze = self.misto
            anim, i, look = fam.update(now)
            cells.append((fam.key, fam.name, (skin, anim, i, look, fam.fade), fam.fsm.state,
                          vrstvy_familiara(fam, now), poza(fam, skin, self.scale, False)))
            obsahy[fam.key] = fam.bublina(now)
        if not cells:   # nikdo neběží: podřimující postavička
            anim = skin.anim_for("sleeping")
            i = 0 if self.still else skin.frame_at(anim, now)
            cells.append((None, "čekám na Claude", (skin, anim, i, None, None), None, BEZ_VRSTEV))
        changed = self._bubliny(obsahy)
        if cells != self.cells or changed:
            self.cells = cells
            self._fit()
            self.update()

    def _bubliny(self, obsahy):
        """Bubliny podle hub (Familiar.bublina); True, když se nějaká změnila."""
        changed = False
        for key in list(self.bubliny):
            if key not in obsahy:
                self.bubliny.pop(key)[0].deleteLater()
                changed = True
        for key, obsah in obsahy.items():
            item = self.bubliny.get(key)
            if item is None:
                if obsah is None:
                    continue
                b = bubliny.Bublina(self._bublina_scale(), parent=self)
                b.rozhodnuti.connect(self._rozhodnuti)
                item = self.bubliny[key] = [b, None]
            if obsah != item[1]:
                ukaz_obsah(item[0], obsah)
                item[1] = obsah
                changed = True
        return changed

    def _rozhodnuti(self, id_, volba):
        for item in self.bubliny.values():
            if item[1] and item[1][0] == "povoleni" and item[1][1] == id_:
                item[1] = None      # bublina se po kliku schovala sama
        self._fit()
        if self.odpoved:
            self.odpoved(id_, volba)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.setFont(self.font)
        for (key, name, frame, state, *rest), (x, cw, rv) in zip(self.cells, self.bunky):
            extra = rest[0] if rest else BEZ_VRSTEV
            posun, poskok, zrcadlit = rest[1] if len(rest) > 1 else BEZ_POZY
            _, _, char, mr, sloty = rv
            p.drawImage(char.translated(x + 6 + posun, self.dy - poskok), picture(self.hub, frame, zrcadlit))
            p.save()
            p.translate(x + 6 + posun, self.dy)
            if mr is not None:
                kresli_meric(p, mr, self.scale, extra[0])
            kresli_pomocniky(p, self.hub, sloty, extra[1], extra[2], self.scale)
            p.restore()
            p.setFont(self.font)
            label = QRect(x + 2, self.dy + char.height() + 1, cw - 4, 15)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 35, 170))
            p.drawRoundedRect(label, 4, 4)
            p.setPen(QColor("#ffd166") if state == "waiting" else QColor("#e0e0e0"))
            text = p.fontMetrics().elidedText(name, Qt.ElideMiddle, label.width() - 6)
            p.drawText(label, Qt.AlignCenter, text)

    def _cell_at(self, x):
        for n, (bx, w, _) in enumerate(self.bunky):
            if bx <= x < bx + w and n < len(self.cells):
                return n
        return None

    def _key_at(self, x):
        n = self._cell_at(int(x))
        return self.cells[n][0] if n is not None else None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            pos = e.pos()
            n = self._cell_at(pos.x())
            text = None
            if n is not None:
                bx, _, rv = self.bunky[n]
                cell = self.cells[n]
                text = popis_vrstvy(self.hub, cell[0], rv, cell[4] if len(cell) > 4 else BEZ_VRSTEV,
                                    pos - QPoint(bx + 6 + self._posun(n), self.dy))
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def _postavicka_at(self, pos):
        """Klíč postavičky, na jejíž obrázek (s posunem procházky) ukazuje pos, nebo None."""
        n = self._cell_at(int(pos.x()))
        if n is None:
            return None
        bx, _, rv = self.bunky[n]
        return self.cells[n][0] if rv[2].translated(bx + 6 + self._posun(n), self.dy).contains(pos.toPoint()) \
            else None

    def _reaguj(self, key, co):
        """co(gesta, čas) → druh reakce; ten jde do hubu."""
        if key is None or not self.mys["zapnuto"]:
            return
        t = time.time()
        druh = co(self.gesta.setdefault(key, pohyb.Gesta()), t)
        if druh:
            self.hub.reaguj(key, druh, t)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # přesun až po pohybu (startSystemMove v mouseMoveEvent), klik bez pohybu šťouchne
            self.stisk, self.dvojklik = e.position(), False
        elif e.button() == Qt.MiddleButton:
            self._reaguj(self._postavicka_at(e.position()), pohyb.Gesta.klik)
        elif e.button() == Qt.RightButton:
            self.menu(self, self._key_at(e.position().x()), e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.stisk is not None and e.buttons() & Qt.LeftButton:
            if (pos - self.stisk).manhattanLength() >= QApplication.startDragDistance():
                self.stisk = None
                self.windowHandle().startSystemMove()
            return
        key = self._postavicka_at(pos)
        if key != self.pod_mysi:
            self.leaveEvent(None)
            self.pod_mysi = key
            if self.mys["najeti"]:
                self._reaguj(key, pohyb.Gesta.najeti)
        elif key is not None and self.mys["hlazeni"]:
            self._reaguj(key, lambda g, t: g.pohyb(t, pos.x(), pos.y()))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.stisk is not None and not self.dvojklik:
            self._reaguj(self._postavicka_at(e.position()), pohyb.Gesta.klik)
        self.stisk = None

    def leaveEvent(self, e):
        if self.pod_mysi in self.gesta:
            self.gesta[self.pod_mysi].odjeti()
        self.pod_mysi = None

    def mouseDoubleClickEvent(self, e):
        key = self._key_at(e.position().x())
        if e.button() == Qt.LeftButton:
            self.stisk, self.dvojklik = e.position(), True     # tažení po dvojkliku dál přesouvá
            if key is not None and self.panel:
                self.panel(key)


def placement(cfg):
    """Umístění pro perch.js v titulku okna: strana|odsazení|mezera|okraj (px)|zakrytí|roh řady."""
    o = cfg["okno"]
    return f"{o['strana']}|{o['odsazeni']}|{o['mezera']}|{o['okraj']}|{o['zakryti']}|{o['rada_roh']}"


class Perch(QWidget):
    """Okno jedné postavičky; polohu mu určuje KWin skript podle titulku
    "familiar|<pid terminálu>|<stav>|<kliky>|<strana>|<odsazení>|<mezera>|<okraj>|<zakrytí>|<roh řady>|<číslo>|<posun>"
    (posun = procházka, px dovnitř titulku; perch.js ho omezí a mez pošle zpět, PerchZpravy). Měřič kontextu a pomocníci jsou v témže okně na vnitřní straně titulku (okno se rozšíří
    směrem od kraje, postavička zůstane na místě). Bublina je samostatné okno s titulkem
    "familiar-bublina|<číslo okna postavičky>|<strana bubliny>|<rozměr>", perch.js ji posadí
    vedle postavičky; má vlastní vstup, maska okna postavičky se jí netýká."""

    regions, regions_skin = {}, None    # masky pro jednu instanci skinu (jako Images)
    pocet = 0                           # pořadová čísla oken (párování s bublinou v perch.js)

    def __init__(self, hub_, fam, scale, place, menu=None, strana="vpravo", odpoved=None):
        super().__init__(None, FLAGS | Qt.WindowDoesNotAcceptFocus)
        self.hub, self.key, self.menu = hub_, fam.key, menu or _quit_menu
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # X11; na Waylandu fokus vrací perch.js
        self.setAttribute(Qt.WA_AlwaysShowToolTips)
        Perch.pocet += 1
        self.cislo = Perch.pocet
        self.term, self.clicks = fam.term, 0
        self.frame, self.extra, self.rv = None, BEZ_VRSTEV, None
        self.state = None
        self.scale, self.place, self.strana = None, place, strana
        self.odpoved = odpoved
        self.bublina, self.obsah = None, None
        self.strana_bubliny = None      # kde bublina opravdu sedí (perch.js ji u kraje přehodí)
        self.name = fam.name
        self.posun, self.poza = 0, BEZ_POZY[1:]     # posun procházky; (poskok, zrcadlit)
        self.orez = QRegion()       # části okna zakryté okny nad terminálem (perch.js "orez")
        self.mys, self.gesta = dict(pohyb.MYS), pohyb.Gesta()
        self.setMouseTracking(True)
        self.configure(scale, place, strana)

    @property
    def vnitrni(self):
        """Strana, na kterou se přidávají vrstvy a bublina (od kraje titulku dovnitř)."""
        return "vlevo" if self.strana == "vpravo" else "vpravo"

    def configure(self, scale, place, strana=None):
        strana = strana or self.strana
        if scale != self.scale or strana != self.strana:
            self.scale, self.strana = scale, strana
            self._layout(force=True)
            if self.bublina is not None:
                self.bublina.set_scale(scale)
                self._umistit_bublinu()
        if place != self.place:
            self.place = place
            self._title()       # KWin skript změnu titulku pozná a okno přesune

    def _title(self):
        self.setWindowTitle(f"familiar|{self.term or 0}|{self.state}|{self.clicks}|{self.place}|{self.cislo}"
                            f"|{self.posun}")

    def _layout(self, force=False):
        """Rozvrh okna podle snímku a vrstev; při změně velikosti nová velikost a maska."""
        skin = self.frame[0] if self.frame else self.hub.skin
        meric, pomocnici, dalsi, _ = self.extra
        ms = mini_meritko(self.scale)
        mini = tuple(v * ms for v in mini_ramec(skin)[2:])
        rv = rozvrh(skin.size, self.scale, self.vnitrni, meric is not None,
                    len(pomocnici) + (1 if dalsi else 0), mini)
        if force or self.rv is None or rv[:2] != self.rv[:2]:
            self.setFixedSize(rv[0], rv[1])
        self.rv = rv
        if self.frame:
            self._input(self._oblast())

    def nastav_orez(self, rects):
        """Zakryté části okna [(x, y, š, v)] od perch.js: nekreslí se a myš jimi projde do okna nad terminálem."""
        orez = QRegion()
        for r in rects:
            orez = orez.united(QRegion(*r))
        if orez != self.orez:
            self.orez = orez
            if self.frame:
                self._input(self._oblast())
            self.update()

    def set(self, frame, state, extra=None, poza_=None):
        """Snímek, stav pro titulek, vrstvy a poza() procházky (posun jde do titulku)."""
        extra = extra or BEZ_VRSTEV
        posun, *rest = poza_ or BEZ_POZY
        if state != self.state or posun != self.posun:
            self.state, self.posun = state, posun
            self._title()
        if frame != self.frame or extra != self.extra or tuple(rest) != self.poza:
            self.frame, self.extra, self.poza = frame, extra, tuple(rest)
            self._layout()      # kliky mimo postavičku a vrstvy projdou do terminálu
            self.update()

    def _oblast(self):
        """Vstupní oblast: pixely postavičky, měřič a sloty pomocníků."""
        _, _, char, mr, sloty = self.rv
        reg = self._region(self.frame, self.poza[1]).translated(char.x(), char.y() - self.poza[0])
        for r in ([mr] if mr is not None else []) + sloty:
            reg = reg.united(QRegion(r))
        return reg.subtracted(self.orez)

    # --- bublina (samostatné okno, polohu dá perch.js) ---

    def ukaz_bublinu(self, obsah):
        if obsah == self.obsah:
            return
        self.obsah = obsah
        if self.bublina is None:
            if obsah is None:
                return
            self.bublina = bubliny.Bublina(self.scale)
            self.bublina.rozhodnuti.connect(self._rozhodnuti)
        b = self.bublina
        if obsah is None:
            b.skryj()
            return
        if obsah[0] == "povoleni":
            b.povoleni(obsah[1], obsah[2])
        else:
            b.text(obsah[1])
        self._umistit_bublinu()
        b.show()

    def nastav_stranu_bubliny(self, strana):
        """Strana, na kterou bublinu opravdu posadil perch.js (None = jak chtěla, vnitrni)."""
        if strana != self.strana_bubliny:
            self.strana_bubliny = strana
            if self.bublina is not None and self.obsah is not None:
                self._umistit_bublinu()

    def _umistit_bublinu(self):
        """Ocásek míří na postavičku: bublina stojí na vnitřní straně, spodkem v úrovni okna.
        Titulek nese stranu, kterou bublina chce; perch.js ji u kraje obrazovky přehodí na druhou
        a ohlásí to (nastav_stranu_bubliny), ocásek pak míří opačně."""
        b = self.bublina
        smer = bubliny.VPRAVO if (self.strana_bubliny or self.vnitrni) == "vlevo" else bubliny.VLEVO
        b.set_ocas(None, smer)
        b.set_ocas(max(0, b.height() - self.height() * 2 // 3), smer)
        b.setWindowTitle(f"familiar-bublina|{self.cislo}|{self.vnitrni}|{b.width()}x{b.height()}")

    def _rozhodnuti(self, id_, volba):
        self.obsah = None       # bublina se po kliku schovala sama
        if self.odpoved:
            self.odpoved(id_, volba)

    def close(self):
        if self.bublina is not None:
            self.bublina.close()
            self.bublina.deleteLater()
            self.bublina = None
        return super().close()

    def event(self, e):
        if e.type() == QEvent.ToolTip and self.rv is not None:
            text = popis_vrstvy(self.hub, self.key, self.rv, self.extra, e.pos()) or self.name
            QToolTip.showText(e.globalPos(), text, self)
            return True
        return super().event(e)

    def _input(self, region):
        """Vstupní oblast okna. Maska jen na QWindow, ne QWidget.setMask: ta ořízne i kreslení
        (a mazání bufferu) na novou masku, ale na Waylandu je maska jen vstupní oblast, takže
        pixely předchozího snímku mimo novou masku zůstaly vidět jako duch."""
        if self.windowHandle() is None:
            self.create()
        if region.isEmpty():        # prázdná maska = celé okno; vstup jen do pixelu mimo okno
            region = QRegion(-1, -1, 1, 1)
        self.windowHandle().setMask(region)

    def _region(self, frame, mirror=False):
        skin, anim, i, look, _ = frame
        if skin is not Perch.regions_skin:
            Perch.regions_skin = skin
            Perch.regions.clear()
        key = (anim, i, look, self.scale, mirror)
        if key not in self.regions:
            if len(self.regions) > 4000:
                self.regions.clear()
            s, reg, (W, H) = self.scale, QRegion(), skin.size
            try:
                px = skin.render(anim, i, look)[0]
            except Exception:       # picture() při kreslení skin vymění a zaloguje
                return QRegion(0, 0, na_px(W, s), na_px(H, s))
            for y in range(H):
                x = 0
                while x < W:
                    if px[y * W + x]:
                        start = x
                        while x < W and px[y * W + x]:
                            x += 1
                        left = W - x if mirror else start
                        x0, y0 = na_px(left, s), na_px(y, s)
                        reg = reg.united(QRegion(x0, y0, na_px(left + x - start, s) - x0, na_px(y + 1, s) - y0))
                    x += 1
            self.regions[key] = reg
        return self.regions[key]

    def paintEvent(self, _):
        if self.frame:
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.setCompositionMode(QPainter.CompositionMode_Source)    # snímek přepíše celé okno i s průhledností
            _, _, char, mr, sloty = self.rv
            poskok, zrcadlit = self.poza
            if char != self.rect() or poskok:
                p.fillRect(self.rect(), Qt.transparent)
            p.drawImage(char.translated(0, -poskok), picture(self.hub, self.frame, zrcadlit))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            if mr is not None:
                kresli_meric(p, mr, self.scale, self.extra[0])
            kresli_pomocniky(p, self.hub, sloty, self.extra[1], self.extra[2], self.scale)
            if not self.orez.isEmpty():
                p.setCompositionMode(QPainter.CompositionMode_Source)
                p.setClipRegion(self.orez)
                p.fillRect(self.rect(), Qt.transparent)

    # --- myš: přepnutí na terminál a reakce (pohyb.Gesta → Hub.reaguj) ---

    def _reaguj(self, druh):
        if druh and self.mys["zapnuto"]:
            self.hub.reaguj(self.key, druh)

    def _prepni(self):
        self.clicks += 1     # KWin skript změnu titulku pozná a přepne na terminál
        self._title()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            klik = self.mys["klik"] if self.mys["zapnuto"] else "terminal"
            if klik != "stouchnout":
                self._prepni()
            if klik != "terminal":
                self._reaguj(self.gesta.klik(time.time()))
        elif e.button() == Qt.MiddleButton:
            self._reaguj(self.gesta.klik(time.time()))
        elif e.button() == Qt.RightButton:
            self.menu(self, self.key, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.mys["zapnuto"] and self.mys["klik"] == "stouchnout":
            self._prepni()      # klik šťouchá, na terminál přepne dvojklik
        else:
            self.mousePressEvent(e)     # jako dřív: druhý stisk dvojkliku je další klik

    def enterEvent(self, e):
        if self.mys["najeti"]:
            self._reaguj(self.gesta.najeti(time.time()))

    def leaveEvent(self, e):
        self.gesta.odjeti()

    def mouseMoveEvent(self, e):
        # místní souřadnice: polohu okna na Waylandu Qt nezná
        if not e.buttons() and self.mys["hlazeni"]:
            p = e.position()
            self._reaguj(self.gesta.pohyb(time.time(), p.x(), p.y()))


class Perches:
    """Režim perch: drží okno pro každou postavičku z hubu."""

    def __init__(self, hub, feed=None, cfg=None, menu=None, odpoved=None, zpravy=None, umistovac=None):
        self.hub, self.feed, self.menu, self.odpoved = hub, feed, menu, odpoved
        self.zpravy = zpravy        # PerchZpravy (meze procházek, strany bublin), nebo None
        self.umistovac = umistovac  # X11: okna posouvá daemon sám (okna.X11Umistovac), jinak None
        self.windows = {}
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.configure(cfg or config.defaults())

    def configure(self, cfg):
        self.scale, self.place = cfg["okno"]["meritko_perch"], placement(cfg)
        self.strana = cfg["okno"]["strana"]
        p = cfg["prochazky"]
        self.dosah = p["dosah"] if p["zapnuto"] and not cfg["soustredeni"] else 0
        self.mys = cfg["mys"]
        for w in self.windows.values():
            w.configure(self.scale, self.place, self.strana)
            w.mys = self.mys
        self.timer.start(cfg["okno"]["snimek_ms"])

    def close(self):
        self.timer.stop()
        for w in self.windows.values():
            w.close()
        self.windows.clear()

    def tick(self):
        now = time.time()
        if self.feed:
            self.feed(now)
        alive = set()
        for fam in self.hub.tick(now):
            w = self.windows.get(fam.key)
            new = w is None
            if new:
                w = self.windows[fam.key] = Perch(self.hub, fam, self.scale, self.place, self.menu,
                                                  self.strana, self.odpoved)
                w.mys = self.mys
            fam.meze = self._meze(w)
            anim, i, look = fam.update(now)
            w.set((self.hub.skin, anim, i, look, fam.fade), fam.title_state,     # titulek musí být hotový dřív,
                  vrstvy_familiara(fam, now),                                    # než ho uvidí KWin
                  poza(fam, self.hub.skin, self.scale, w.vnitrni == "vlevo"))
            if new and self.umistovac is None:     # umísťovač okno ukáže až na jeho místě
                w.show()
            if self.zpravy is not None:
                w.nastav_stranu_bubliny(self.zpravy.strany.get(str(w.cislo)))
                w.nastav_orez(self.zpravy.orezy.get(str(w.cislo), ()))
            w.ukaz_bublinu(fam.bublina(now))
            alive.add(fam.key)
        for key in set(self.windows) - alive:
            self.windows.pop(key).close()
        if self.umistovac is not None:
            try:
                self.umistovac.umisti(list(self.windows.values()))
            except Exception:
                lg.exception("rozmístění oken postaviček selhalo")

    def _meze(self, w):
        """Kam nejdál smí postavička na procházce: mez od perch.js (titulek, odhad textu); bez
        zpráv z perch.js jen dosah z configu (posun pak omezí perch.js sám)."""
        if not self.dosah:
            return 0
        if self.zpravy is None:
            return self.dosah
        return min(self.dosah, self.zpravy.meze_px.get(str(w.cislo), 0))


@ClassInfo({"D-Bus Interface": "cz.familiar.Perch"})
class PerchZpravy(QObject):
    """Zprávy od perch.js (callDBus, viz kwin.perch_dbus): jak daleko smí postavička na
    procházce (meze), na které straně opravdu sedí bublina (strana) a které části okna
    postavičky zakrývají okna nad terminálem (orez)."""
    CESTA, ROZHRANI = "/familiar/perch", "cz.familiar.Perch"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meze_px, self.strany, self.orezy, self.bus = {}, {}, {}, None
        self.mistni = False     # zprávy volá přímo umísťovač v daemonu (X11), bez D-Bus

    @property
    def funguje(self):
        return self.bus is not None or self.mistni

    def spust(self):
        """Zaregistruje objekt na session sběrnici → {sluzba, cesta, rozhrani} pro perch.js, nebo None."""
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected() or not bus.registerObject(self.CESTA, self, QDBusConnection.ExportAllSlots):
            lg.warning("zprávy z perch.js: objekt na D-Bus nejde zaregistrovat, procházky bez meze titulku")
            return None
        self.bus = bus
        return {"sluzba": bus.baseService(), "cesta": self.CESTA, "rozhrani": self.ROZHRANI}

    @Slot(str, str)
    def meze(self, cislo, px):
        try:
            self.meze_px[cislo] = max(0, int(float(px)))
        except ValueError:
            pass

    @Slot(str, str)
    def strana(self, cislo, strana):
        self.strany[cislo] = strana if strana in ("vlevo", "vpravo") else None

    @Slot(str, str)
    def orez(self, cislo, obdelniky):
        """Zakryté části okna postavičky: "x,y,š,v;…" (prázdné = nic)."""
        try:
            rects = tuple(tuple(int(v) for v in r.split(",")) for r in obdelniky.split(";") if r)
        except ValueError:
            rects = ()
        self.orezy[cislo] = tuple(r for r in rects if len(r) == 4)

    def zastav(self):
        if self.bus is not None:
            self.bus.unregisterObject(self.CESTA)
            self.bus = None


class Povolovani:
    """Povolení z bubliny ([povoleni] v configu, docs/povoleni.md): server povoleni.Povoleni
    běží, jen když je funkce zapnutá (zapnutí i vypnutí za běhu); start až s drženým zámkem
    daemonu (po listen). Požadavek jde do hubu k postavičce podle pid/session, bublina ho
    ukáže, klik → odpovez. Hub hlásí přes on_zrus požadavky, na které uživatel odpověděl
    v terminálu. Shrnutí požadavku se nikam nezapisuje."""

    def __init__(self, hub, parent=None, factory=None):
        self.hub, self.parent, self.srv = hub, parent, None
        self.factory = factory      # testy: náhrada povoleni.Povoleni
        hub.on_zrus = self._zrus

    def configure(self, cfg):
        c = cfg["povoleni"]
        if c["zapnuto"] and self.srv is None:
            self._start(c)
        elif not c["zapnuto"] and self.srv is not None:
            self.close()
            lg.info("povolení z bubliny vypnuto")
        if self.srv is not None:
            self.srv.configure(c["timeout_s"], c["timeout_agent_s"])

    def _start(self, c):
        if self.factory is None:
            from familiar import povoleni
            self.factory = povoleni.Povoleni
        srv = self.factory(self.parent, c["timeout_s"], c["timeout_agent_s"])
        if not srv.start():
            lg.warning("povolení z bubliny: server nejde spustit, dialogy zůstanou jen v terminálu")
            return
        srv.pozadavek.connect(self._pozadavek)
        srv.zruseno.connect(self.hub.vyrizeno)
        self.srv = srv
        lg.info("povolení z bubliny zapnuto")

    def _pozadavek(self, id_, session, pid, shrnuti):
        key = self.hub.pozadavek(id_, session, pid, shrnuti, time.time())
        if key is None:     # nikomu nepatří: hook hned skončí a platí dialog v terminálu
            self.srv.zrus(id_)
        else:
            lg.info("požadavek na povolení %d u familiara %s", id_, key)

    def odpovez(self, id_, volba):
        klic = self.hub.vyrizeno(id_)
        if klic is not None and self.hub.sluzby is not None:
            self.hub.sluzby.odpovezeno(klic)        # notifikace „čeká na povolení“ už neplatí
        if self.srv is not None and not self.srv.odpovez(id_, volba):
            lg.info("požadavek na povolení %d už neplatí", id_)

    def _zrus(self, id_):
        if self.srv is not None:
            self.srv.zrus(id_)

    def close(self):
        srv, self.srv = self.srv, None
        if srv is not None:
            srv.close()     # zruseno → hub.vyrizeno: bubliny zmizí
            srv.deleteLater()


def listen(hub, parent):
    """Naváže socket pro emitter; druhý běžící daemon odmítne. Do zámku zapíše své pid
    (podle něj ho najde `familiar stop`). Bez XDG_RUNTIME_DIR v soukromém /tmp/familiar-<uid>."""
    try:
        paths.secure_runtime_dir()
    except OSError as e:
        sys.exit(f"familiar: {e}")
    sock_path = paths.sock()
    lock = open(os.open(paths.lock(), os.O_RDWR | os.O_CREAT, 0o600), "r+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("familiar už běží")
    lock.truncate(0)
    lock.write(f"{os.getpid()}\n")
    lock.flush()
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(sock_path)
    os.chmod(sock_path, 0o600)
    s.setblocking(False)

    def readable():
        while True:
            try:
                data = s.recv(65536)
            except BlockingIOError:
                return
            except OSError:
                lg.exception("čtení socketu selhalo")
                return
            hub.handle(data)    # chyby zaloguje bez dat hooku a pokračuje

    notifier = QSocketNotifier(s.fileno(), QSocketNotifier.Read, parent)
    notifier.activated.connect(readable)
    return s, lock, notifier


def demo_feed(hub, prefix, speed, gap):
    """Přehrává nahrávku jako živé zprávy; dlouhé pauzy zkrátí na `gap` s."""
    from familiar.replay import REPLAYS
    paths = sorted(glob.glob(os.path.join(REPLAYS, prefix + "*.jsonl")))
    if not paths:
        sys.exit(f"nahrávka {prefix} nenalezena v {REPLAYS}")
    recs = [json.loads(line) for line in open(paths[0])]
    plan, off, prev = [], 1.0, recs[0]["ts"]
    for rec in recs:
        off += min(rec["ts"] - prev, gap) / speed
        prev = rec["ts"]
        procs = rec.get("procs") or [[None, ""]]
        plan.append((off, {"pid": procs[0][0] or 1, "raw": rec["raw"]}))
    state = {"start": time.time(), "i": 0}

    def feed(now):
        while state["i"] < len(plan) and now - state["start"] >= plan[state["i"]][0]:
            msg = dict(plan[state["i"]][1], ts=now)
            hub.handle(json.dumps(msg).encode())    # stejná cesta jako živé zprávy
            state["i"] += 1
        if state["i"] == len(plan) and now - state["start"] > plan[-1][0] + 5:
            state.update(start=now, i=0)    # znovu od začátku
    print(f"demo {os.path.basename(paths[0])}: {len(plan)} hooků, {plan[-1][0]:.0f} s", flush=True)
    return feed


def main(argv=None):
    from familiar.cli import add_daemon_args
    ap = argparse.ArgumentParser(description="familiar: pixelová postavička u Claude Code")
    add_daemon_args(ap, "flag")
    run(ap.parse_args(argv))


class Views:
    """Drží pohled (Dock nebo Perches) podle configu a umí ho za běhu vyměnit."""

    def __init__(self, hub, feed, cfg, forced_mode=None, demo=False, mode_file=None, povolovani=None,
                 okna_=None):
        from familiar import okna
        self.hub, self.feed, self.forced, self.demo = hub, feed, forced_mode, demo
        self.mode_file = mode_file      # sem se zapíše skutečný režim (pro doctor)
        self.povolovani = povolovani    # Povolovani (ne v demu)
        self.okna = okna_ or okna.backend(cfg["okno"]["backend"])     # backend oken (perch)
        self.view, self.mode, self.kwin_failed = None, None, False     # kwin_failed: perch backendu selhal
        self.zpravy = None      # PerchZpravy, když perch hlásí meze a strany bublin
        self.cfg, self.ui = cfg, None     # ui: nabidka.Ovladani, až vznikne
        self.apply(cfg)

    def menu(self, widget, key, pos):
        """Pravé tlačítko na postavičce (key None = podřimující v docku)."""
        if self.ui is not None:
            self.ui.popup(widget, key, pos)
        else:
            _quit_menu(widget, key, pos)

    def panel(self, key):
        if self.ui is not None:
            self.ui.otevri_panel(key)

    def odpoved(self, id_, volba):
        """Klik v bublině povolení."""
        if self.povolovani is not None:
            self.povolovani.odpovez(id_, volba)

    def oznam(self, pid, text, sekund=4):
        """Krátká textová bublina u postavičky procesu pid (viz Hub.oznam)."""
        return self.hub.oznam(pid, text, sekund)

    def _mode(self, cfg):
        # volba --mode má přednost před configem; demo bez ní vždy v docku (perch by
        # odebral KWin skript živého daemonu)
        mode = self.forced or ("dock" if self.demo else cfg["rezim"])
        if mode == "auto":
            mode = "perch" if not self.demo and self.okna.perch_umi() else "dock"
        return "dock" if mode == "perch" and self.kwin_failed else mode

    def apply(self, cfg):
        self.hub.configure(cfg.data)
        if self.povolovani is not None:
            self.povolovani.configure(cfg.data)
        self.cfg = cfg
        mode = self._mode(cfg)
        if mode != self.mode or self.view is None:
            self._switch(mode, cfg)
        else:
            self.view.configure(cfg.data)

    def _switch(self, mode, cfg):
        """Zavře starý pohled a otevře nový. Perch backendu (KWin skript, rozšíření GNOME,
        umísťovač X11) běží, právě když self.mode == "perch": i když vytvoření pohledu selže,
        quit() ho zastaví."""
        if self.view is not None:
            view, self.view = self.view, None
            view.close()
        self.quit()
        if mode == "perch":
            # zprávy z perch.js (meze procházek, přehozené bubliny); bez nich perch.js jen umisťuje
            zpravy = PerchZpravy()
            if self.okna.perch_start(zpravy):
                self.mode = "perch"     # od teď ho quit() zastaví
                self.zpravy = zpravy if zpravy.funguje else None
            else:
                zpravy.zastav()
                print(f"perch ({self.okna.jmeno}) nejde spustit, přepínám na režim dock", file=sys.stderr)
                lg.warning("perch (backend %s) nejde spustit, režim dock", self.okna.jmeno)
                self.kwin_failed, mode = True, "dock"
        try:
            view = (Perches(self.hub, self.feed, cfg.data, self.menu, self.odpoved, self.zpravy,
                            self.okna.umistovac) if mode == "perch"
                    else Dock(self.hub, self.feed, cfg.data, self.menu, self.panel, self.odpoved))
            if mode == "dock":
                view.show()
        except BaseException:
            lg.error("pohled %s se nepodařilo otevřít", mode)
            self.quit()
            raise
        lg.info("režim %s", mode)
        self.view, self.mode = view, mode
        if self.mode_file:
            try:
                with open(self.mode_file, "w") as f:
                    f.write(mode + "\n")
            except OSError:
                lg.warning("režim nejde zapsat do %s", self.mode_file)

    def quit(self):
        """Zastaví perch backendu, u KDE odebere KWin skript (smí se volat opakovaně:
        aboutToQuit i finally v run)."""
        if self.mode == "perch":
            try:
                self.okna.perch_stop()
                lg.info("perch (backend %s) zastaven", self.okna.jmeno)
            except Exception:
                lg.exception("perch (backend %s) se nepodařilo zastavit", self.okna.jmeno)
            self.mode = None
        if self.zpravy is not None:
            self.zpravy.zastav()
            self.zpravy = None


def _exec(app, stop):
    """app.exec(); signál přijatý ještě před vstupem do smyčky (app.quit() tehdy nic
    neudělá) ji ukončí hned po startu."""
    QTimer.singleShot(0, lambda: stop["why"] and app.quit())
    return app.exec()


def run(args):
    """Spustí daemon (args: mode, demo, speed, gap); vrací se až po ukončení.
    Při SIGTERM/SIGINT i při výjimce, která vyletí z hlavní smyčky, odebere KWin skript;
    po SIGKILL ho odebere až příští start (kwin.load nejdřív odnahraje zbytek)."""
    stop = {"why": None}

    def on_signal(sig, _frame):
        stop["why"] = signal.Signals(sig).name
        app = QApplication.instance()
        if app is not None:
            app.quit()

    for sig in (signal.SIGTERM, signal.SIGINT):   # ukončit čistě, i s odebráním KWin skriptu
        signal.signal(sig, on_signal)
    lg = log.setup()
    lg.info("start familiar %s, pid %d%s", familiar.__version__, os.getpid(),
            f", demo {args.demo}" if args.demo else "")

    def excepthook(*exc):
        # výjimka ve slotu Qt: do logu (bez textu výjimky), na stderr jen typ; běží se dál
        lg.error("neošetřená výjimka", exc_info=exc)
        print(f"familiar: neošetřená výjimka {exc[0].__name__}, podrobnosti v {log.log_path()}",
              file=sys.stderr)
    sys.excepthook = excepthook

    watcher = config.Watcher()      # dřív než load: změna mezi nimi se nepřehlédne
    cfg = config.load()
    config.log_problems(cfg, lg)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("familiar")
    app.setDesktopFileName("familiar")   # app_id na Waylandu, podle něj ho najde pravidlo KWinu
    app.setQuitOnLastWindowClosed(False)

    hub = Hub(reap=not args.demo, bind=not args.demo, cfg=cfg.data, transcripts=not args.demo)
    sock = None if args.demo else listen(hub, app)   # zámek dřív než KWin skript: druhý daemon hned skončí
    hub.adopt_live(time.time())     # okna Claude Code otevřená před startem daemonu (po zámku)
    feed = demo_feed(hub, args.demo, args.speed, args.gap) if args.demo else None
    povol = None if args.demo else Povolovani(hub, app)     # server povolení až po zámku (listen)
    views = sluzby = None
    code = 1
    try:
        views = Views(hub, feed, cfg, args.mode, bool(args.demo), None if args.demo else paths.mode_file(),
                      povol)
        app.aboutToQuit.connect(views.quit)

        def written():
            # nabídka nebo dialog právě zapsaly config: použít hned, watcher ho už nehlásí
            try:
                new = watcher.take()
                config.log_problems(new, lg)
                views.apply(new)
            except Exception:
                lg.exception("config se nepodařilo použít, platí dosavadní")

        from familiar import nabidka
        views.ui = nabidka.Ovladani(hub, views, written, tray=not args.demo, demo=bool(args.demo))
        if not args.demo:       # notifikace, statistiky, úspěchy (demo by je plnilo cizími daty)
            from familiar import sluzby as sluzby_
            try:
                sluzby = sluzby_.Sluzby(hub, cfg.data, views, app)
            except Exception:
                lg.exception("služby se nepodařilo spustit, běží bez notifikací a statistik")

        def reload():
            # chyba nesmí zastavit další přenačtení: watcher má nový podpis, časovač běží dál
            try:
                new = watcher.poll()
                if new is not None:
                    config.log_problems(new, lg)
                    lg.info("config přenačten (%d chyb, %d varování)", len(new.errors), len(new.warnings))
                    views.apply(new)
                else:
                    hub.refresh_skin()
            except Exception:
                lg.exception("config se nepodařilo použít, platí dosavadní")

        def poll_transcripts():
            try:
                now = time.time()
                for key in hub.poll_transcripts(now):
                    lg.info("přerušení (transcript) u familiara %s", key)
                hub.poll_kontext(now)       # měřič kontextu
            except Exception:
                lg.exception("chyba při čtení transcriptů")

        timer = QTimer(app)
        timer.timeout.connect(reload)
        timer.start(WATCH_MS)
        ttimer = QTimer(app)
        ttimer.timeout.connect(poll_transcripts)
        ttimer.start(TRANSCRIPT_MS)
        app._familiar = (sock, views, timer, ttimer, views.ui, sluzby)
        code = _exec(app, stop)
    except BaseException:
        stop["why"] = "výjimka"
        lg.exception("daemon spadl")
        raise
    finally:
        if sluzby is not None:
            try:
                sluzby.ukonci()     # uložit statistiky a postup hned, zavřít notifikace
            except Exception:
                lg.exception("služby se nepodařilo ukončit")
        if views is not None:
            views.quit()
        if povol is not None:
            povol.close()
        lg.info("konec familiar (%s), kód %s", stop["why"] or "konec smyčky", code)
    sys.exit(code)


if __name__ == "__main__":
    main()

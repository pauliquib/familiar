# Rozmístění postaviček na titulcích terminálů: výpočet z perch.js přepsaný do Pythonu pro
# backendy, které okna postaviček umisťují samy (X11, familiar/okna.py). perch.js zůstává pro
# KWin (a přes převlek oken i pro rozšíření GNOME Shellu); obě implementace procházejí tytéž
# případy (tests/test_perch.py, každý test perch.js běží i proti tomuto modulu).
#
# Okna jsou slovníky se stejnými klíči jako okna KWinu, se kterými pracuje perch.js:
#   resourceClass, caption, pid, normalWindow, dialog, minimized, hidden, deleted,
#   desktops, onAllDesktops, activities, frameGeometry, clientGeometry, internalId
# (geometrie = {"x", "y", "width", "height"}). Okna postaviček a bublin mají resourceClass
# "familiar" a titulek s polohou (protokol popsaný v perch.js a dock.Perch). Plocha dodá
# seznam oken, pořadí vrstvení (zdola nahoru), pracovní oblast obrazovky a provede přesun,
# „na všech plochách“ a aktivaci terminálu po kliku; výchozí Plocha mění slovníky na místě
# jako KWin. Názvy funkcí odpovídají perch.js, aby šly obě verze porovnat řádek po řádku.
import math, re

RIGHT = 120     # výchozí odsazení: místo pro tlačítka titulku terminálu
GAP = 4
PAD = 8
COVER = "navrchu"
CORNER = "vpravo-dole"
CORNERS = ("vpravo-dole", "vpravo-nahore", "vlevo-dole", "vlevo-nahore")
HIDDEN = -20000     # schování „mimo obrazovku“ (X11 backend okno místo toho skryje)
SLIVER = 4          # zbytek terminálu užší než tolik px = není vidět
TEXT_CHAR = 7       # odhad šířky znaku titulku terminálu, px
TEXT_PAD = 16       # odstup procházky od textu titulku, px

_INT = re.compile(r"\s*([+-]?\d+)")


def _int(s):
    """parseInt z JS: celé číslo na začátku textu, jinak None (NaN)."""
    m = _INT.match(s) if isinstance(s, str) else None
    return int(m.group(1)) if m else None


def parse(w):
    if w.get("resourceClass") != "familiar":
        return None
    p = str(w.get("caption", "")).split("|")
    if p[0] != "familiar" or len(p) < 4:
        return None

    def pole(i):
        return p[i] if i < len(p) else None

    def num(i, d):
        n = _int(pole(i))
        return d if n is None else n
    cover = pole(8) if pole(8) in ("schovat", "rada") else COVER
    return {"term": _int(p[1]) or 0, "state": p[2], "clicks": p[3], "left": pole(4) == "vlevo",
            "offset": num(5, RIGHT), "gap": num(6, GAP), "pad": num(7, PAD), "cover": cover,
            "corner": pole(9) if pole(9) in CORNERS else CORNER, "num": pole(10) or "",
            "walk": max(0, num(11, 0))}


def parse_bubble(w):
    if w.get("resourceClass") != "familiar":
        return None
    p = str(w.get("caption", "")).split("|")
    if p[0] != "familiar-bublina" or len(p) < 3:
        return None
    return {"num": p[1], "left": p[2] == "vlevo"}


def _id(w):
    return str(w.get("internalId"))


def intersects(a, b):
    return a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] \
        and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]


def subtract(r, g, out):
    """r minus g jako nejvýš 4 obdélníky (pruh nad, pod, vlevo, vpravo); úzké zbytky zahodí."""
    if not intersects(r, g):
        out.append(r)
        return
    top, bottom = max(r["y"], g["y"]), min(r["y"] + r["height"], g["y"] + g["height"])
    parts = [{"x": r["x"], "y": r["y"], "width": r["width"], "height": top - r["y"]},
             {"x": r["x"], "y": bottom, "width": r["width"], "height": r["y"] + r["height"] - bottom},
             {"x": r["x"], "y": top, "width": g["x"] - r["x"], "height": bottom - top},
             {"x": g["x"] + g["width"], "y": top, "width": r["x"] + r["width"] - g["x"] - g["width"],
              "height": bottom - top}]
    out.extend(q for q in parts if q["width"] >= SLIVER and q["height"] >= SLIVER)


def walk_limit(term, c, x, width, left):
    """Jak daleko dovnitř titulku smí postavička na procházce (px od klidového místa x)."""
    n = len(str(term.get("caption") or ""))
    tw = min(c["width"], n * TEXT_CHAR + 2 * TEXT_PAD) if n else 0
    mid = c["x"] + c["width"] / 2
    if left:
        lim = ((mid - tw / 2) if n else c["x"] + c["width"]) - (x + width)
    else:
        lim = x - ((mid + tw / 2) if n else c["x"])
    return max(0, math.floor(lim))


class Plocha:
    """Plocha pro jeden průchod (jako workspace v KWinu): okna v pořadí seznamu, pořadí
    vrstvení zdola nahoru, aktuální plocha a aktivita, pracovní oblast (oblast(okno) nebo
    oblast(None) = obrazovka s myší). Výchozí metody mění slovníky na místě jako KWin."""

    def __init__(self, okna, poradi=None, plocha=None, aktivita=None, oblast=None):
        self.okna = okna
        self.poradi = okna if poradi is None else poradi
        self.plocha, self.aktivita = plocha, aktivita
        self._oblast = oblast

    def oblast(self, w):
        return self._oblast(w) if callable(self._oblast) else self._oblast

    def presun(self, w, x, y):
        g = w["frameGeometry"]
        if abs(g["x"] - x) < 0.5 and abs(g["y"] - y) < 0.5:
            return
        w["frameGeometry"] = {"x": x, "y": y, "width": g["width"], "height": g["height"]}

    def vsude(self, w):
        w["onAllDesktops"] = True

    def aktivuj(self, term):
        """Klik na postavičku: odminimalizovat, přepnout plochu, aktivovat (jako perch.js)."""
        if term.get("minimized"):
            term["minimized"] = False
        if not self.na_plose(term) and term.get("desktops"):
            self.plocha = term["desktops"][0]
        self.aktivni = term

    def na_plose(self, w):
        if w.get("onAllDesktops"):
            return True
        return any(d == self.plocha for d in w.get("desktops") or ())

    def na_aktivite(self, w):
        acts = w.get("activities")      # prázdné = na všech aktivitách
        return not acts or any(a == self.aktivita for a in acts)

    def shown(self, w):
        return not w.get("minimized") and self.na_plose(w) and self.na_aktivite(w)


class Rozmisteni:
    """Stav mezi průchody (poslední kliky, ohlášené meze a strany bublin) a průchod layout().
    hlas(co, číslo, hodnota) dostane jen změny, jako callDBus v perch.js."""

    def __init__(self, hlas=None):
        self.hlas = hlas
        self.clicks, self.reported, self.placed = {}, {}, {}

    def report(self, what, num, value):
        key, value = f"{what}|{num}", str(value)
        if self.reported.get(key) == value:
            return
        self.reported[key] = value
        if self.hlas is not None:
            self.hlas(what, str(num), value)

    def _terminal(self, ws, pid):
        if not pid:
            return None
        return next((w for w in ws.okna if w.get("pid") == pid and w.get("normalWindow")), None)

    def _covered(self, ws, term, rect):
        above = False
        for w in ws.poradi:
            if _id(w) == _id(term):
                above = True
                continue
            if not above or w.get("resourceClass") == "familiar" or not w.get("normalWindow") or not ws.shown(w):
                continue
            if intersects(w["frameGeometry"], rect):
                return True
        return False

    def _buried(self, ws, term):
        """Úplně zakrytý terminál: jeho rámeček minus okna nad ním (jako perch.js buried)."""
        left, above = [term["frameGeometry"]], False
        for w in ws.poradi:
            if not left:
                break
            if _id(w) == _id(term):
                above = True
                continue
            if not above or w.get("resourceClass") == "familiar" or not (w.get("normalWindow") or w.get("dialog")) \
                    or w.get("hidden") is True or w.get("deleted") is True or not ws.shown(w):
                continue
            nxt = []
            for r in left:
                subtract(r, w["frameGeometry"], nxt)
            left = nxt
        return not left

    def _occluded(self, ws, term, rect):
        """Části rect zakryté okny nad terminálem pro zprávu „orez“ (jako perch.js occluded)."""
        out, above = [], False
        for w in ws.poradi:
            if _id(w) == _id(term):
                above = True
                continue
            if not above or w.get("resourceClass") == "familiar" or not (w.get("normalWindow") or w.get("dialog")) \
                    or w.get("hidden") is True or w.get("deleted") is True or not ws.shown(w):
                continue
            g = w["frameGeometry"]
            if not intersects(g, rect):
                continue
            x, y = math.floor(max(g["x"], rect["x"]) - rect["x"]), math.floor(max(g["y"], rect["y"]) - rect["y"])
            r = math.ceil(min(g["x"] + g["width"], rect["x"] + rect["width"]) - rect["x"])
            b = math.ceil(min(g["y"] + g["height"], rect["y"] + rect["height"]) - rect["y"])
            out.append(f"{x},{y},{r - x},{b - y}")
        return ";".join(out)

    def _put(self, ws, w, info, x, y):
        ws.presun(w, x, y)
        g = w["frameGeometry"]
        self.placed[info["num"]] = {"x": x, "y": y, "width": g["width"], "height": g["height"], "win": w}

    def layout(self, ws):
        self.placed = {}
        per_term, rows, keys, hid = {}, {}, [], {}
        for f in ws.okna:
            info = parse(f)
            if not info:
                continue
            term = self._terminal(ws, info["term"])
            fid = _id(f)
            if term is not None and fid in self.clicks and self.clicks[fid] != info["clicks"]:
                ws.aktivuj(term)
            self.clicks[fid] = info["clicks"]

            g = f["frameGeometry"]
            hidden = term is None or not ws.shown(term)
            if not hidden and info["cover"] == "navrchu":
                if _id(term) not in hid:
                    hid[_id(term)] = self._buried(ws, term)
                hidden = hid[_id(term)]
            if not hidden:
                k = per_term.get(_id(term), 0)
                per_term[_id(term)] = k + 1
                area = ws.oblast(term)
                c = term["clientGeometry"]
                x = c["x"] + info["offset"] + k * (g["width"] + info["gap"]) if info["left"] \
                    else c["x"] + c["width"] - info["offset"] - (k + 1) * (g["width"] + info["gap"])
                lim = walk_limit(term, c, x, g["width"], info["left"])
                self.report("meze", info["num"], lim)
                x += (1 if info["left"] else -1) * min(info["walk"], lim)
                y = max(area["y"], c["y"] - g["height"] + 2)
                rect = {"x": x, "y": y, "width": g["width"], "height": g["height"]}
                if info["cover"] == "navrchu" or not self._covered(ws, term, rect):
                    self.report("orez", info["num"],
                                self._occluded(ws, term, rect) if info["cover"] == "navrchu" else "")
                    ws.vsude(f)
                    self._put(ws, f, info, x, y)
                    continue
            self.report("orez", info["num"], "")      # v rohu nebo schovaná: nic neořezávat
            # zakrytá (schovat, rada), schovaný či úplně zakrytý terminál (navrchu) nebo žádný terminál
            in_row = info["state"] == "waiting" or term is None or (info["cover"] == "rada" and not hidden)
            if not in_row:
                self._put(ws, f, info, HIDDEN, HIDDEN)
                continue
            corner = info["corner"] if info["cover"] == "rada" else ("vlevo" if info["left"] else "vpravo") + "-dole"
            screen = ws.oblast(term if term is not None and ws.shown(term) else None)
            key = (screen["x"], screen["y"], screen["width"], screen["height"], corner)
            if key not in rows:
                rows[key] = {"area": screen, "corner": corner, "items": []}
                keys.append(key)
            rows[key]["items"].append((f, info))
        for key in keys:
            self._row(ws, rows[key])
        for w in ws.okna:
            bi = parse_bubble(w)
            if bi:
                self._bubble(ws, w, bi)

    def _bubble(self, ws, w, bi):
        at = self.placed.get(bi["num"])
        if not at or at["x"] <= HIDDEN / 2:
            ws.presun(w, HIDDEN, HIDDEN)
            return
        g = w["frameGeometry"]
        a = ws.oblast(at["win"])
        left = bi["left"]
        # u kraje obrazovky na druhou stranu postavičky, když se tam vejde (jinak zarovnat k okraji)
        if left and at["x"] - g["width"] < a["x"] and at["x"] + at["width"] + g["width"] <= a["x"] + a["width"]:
            left = False
        elif not left and at["x"] + at["width"] + g["width"] > a["x"] + a["width"] and at["x"] - g["width"] >= a["x"]:
            left = True
        self.report("strana", bi["num"], "vlevo" if left else "vpravo")
        x = at["x"] - g["width"] if left else at["x"] + at["width"]
        y = at["y"] + at["height"] - g["height"]
        x = max(a["x"], min(x, a["x"] + a["width"] - g["width"]))
        y = max(a["y"], min(y, a["y"] + a["height"] - g["height"]))
        ws.vsude(w)
        ws.presun(w, x, y)

    def _row(self, ws, rw):
        """Řada od rohu podél vodorovného okraje pracovní plochy (bez panelů)."""
        a, corner = rw["area"], rw["corner"]
        left, top = corner.startswith("vlevo"), corner.endswith("nahore")
        n = 0
        for w, ci in rw["items"]:
            g = w["frameGeometry"]
            ws.vsude(w)
            self._put(ws, w, ci, a["x"] + ci["pad"] + n if left else a["x"] + a["width"] - ci["pad"] - n - g["width"],
                      a["y"] + ci["pad"] if top else a["y"] + a["height"] - g["height"] - ci["pad"])
            n += g["width"] + ci["gap"]

# Procházky a reakce na myš: logika bez Qt (hub ji drží u každé postavičky, dock.py kreslí
# a posílá události myši).
#
# Procházka: v klidu (stav idle, ne spánek, soustředění, reakce ani žádost o povolení) se
# postavička občas projde dovnitř titulku (perch) nebo po své buňce (dock): dojde kus cesty,
# zastaví se, otočí se a vrátí se. Posun je v px obrazovky od klidového místa směrem dovnitř
# (≥ 0). Kam nejdál smí (meze), říká renderer: v perch ji hlásí perch.js podle šířky titulku
# a odhadu jeho textu (k tlačítkům okna nejde nikdy), v docku je to volné místo v buňce.
# Událost (práce, čekání …) procházku přeruší: postavička zůstane stát, kde je (bublina, měřič
# i pomocníci jsou u ní), a domů dojde, až bude zase NAVRAT_S v klidu.
#
# Myš: Gesta z časové řady událostí (klik, pohyb, najetí) pozná šťouchnutí, rychlé klikání
# (zamotá se a chvíli se zlobí), hlazení (pomalé pohyby tam a zpátky) a najetí (zbystří).
# Co reakce udělá s postavičkou, je v REAKCE (hub.Familiar.reaguj / update).
import math, random
from collections import deque

PROCHAZKY = {"zapnuto": True, "interval_s": 90.0, "rychlost": 30.0, "dosah": 120}
KLIK = ("oboji", "terminal", "stouchnout")      # levý klik v perch: přepnout + šťouchnout / jen přepnout / jen šťouchnout
MYS = {"zapnuto": True, "klik": "oboji", "hlazeni": True, "najeti": True}

NAVRAT_S = 4.0          # přerušená procházka: domů po tolika s klidu
MIN_DOSAH = 12          # px; kratší procházka se nevyplatí
PAUZA_S = (1.0, 2.5)    # zastavení na procházce (první půlku kouká, kam šla, pak se otočí)

POHLED, STOUCHNUTI, ZAMOTANI, HLAZENI = "pohled", "stouchnuti", "zamotani", "hlazeni"
KLIKY_N, KLIKY_S = 4, 1.5           # tolik kliků během tolika s = rychlé klikání
HLAZENI_S = 1.5                     # hlazení: pohyby za poslední tolik s …
HLAZENI_MIN_S = 0.6                 # … trvající aspoň tolik s,
HLAZENI_DRAHA = 60                  # … dráha aspoň tolik px,
HLAZENI_OBRATY = 2                  # … aspoň tolik obratů směru vodorovně
HLAZENI_RYCHLOST = (15, 450)        # … a průměrná rychlost v px/s (máchnutí přes postavičku není hlazení)
HLAZENI_PAUZA_S = 4.0               # další hlazení nejdřív za tolik s
NAJETI_PAUZA_S = 4.0                # další „zbystření“ nejdřív za tolik s

# druh → stav pro skin.anim_for (None = obvyklá animace), jak dlouho hraje, jak dlouho reakce
# trvá celkem, emote během animace a po ní, nálada obličeje během animace a po ní
REAKCE = {
    POHLED: {"stav": "listening", "anim_s": 0.6, "celkem_s": 0.6},
    STOUCHNUTI: {"stav": "success", "anim_s": 0.75, "celkem_s": 0.75},
    ZAMOTANI: {"stav": "error", "anim_s": 1.5, "celkem_s": 6.0, "emote": "spiral", "emote_po": "grawlix",
               "nalada": "zmatek", "nalada_po": "frustrace"},
    HLAZENI: {"stav": "success", "anim_s": 0.75, "celkem_s": 3.0, "emote": "heart", "emote_po": "heart",
              "nalada": "radost", "nalada_po": "radost"},
}
ZLOST = (STOUCHNUTI, POHLED, ZAMOTANI)  # na co rozzlobená (po zamotání) nereaguje


class Prochazka:
    """Procházka jedné postavičky. krok(now, klid, meze) → (posun px, jde, natočení), natočení
    +1 = kouká dovnitř, −1 = ven, 0 = obvykle (stojí doma nebo procházku přerušila událost)."""

    def __init__(self, cfg=None, rng=None):
        self.rng = rng or random.Random()
        self.x = 0.0
        self.plan = []          # [(t0, t1, x0, x1, natočení)]; zastavení má x0 == x1
        self.dalsi = None       # kdy začne příští procházka
        self.klid_od = None
        self.configure(cfg or PROCHAZKY)

    def configure(self, c):
        self.zapnuto, self.interval = c["zapnuto"], c["interval_s"]
        self.rychlost, self.dosah = max(1.0, c["rychlost"]), c["dosah"]
        self.dalsi = None

    @property
    def probiha(self):
        return bool(self.plan)

    def naplanuj(self, now, meze):
        """Tam (45–100 % meze), zastavit, někdy kus zpátky a zastavit, otočit, domů."""
        r = self.rng
        cile = [r.uniform(0.45, 1.0) * meze]
        if r.random() < 0.4:
            cile.append(r.uniform(0.15, 0.6) * cile[0])
        cile.append(0.0)
        plan, t, x = [], now, self.x
        for cil in cile:
            smer = 1 if cil > x else -1
            if plan:
                p = r.uniform(*PAUZA_S)
                plan += [(t, t + p / 2, x, x, plan[-1][4]), (t + p / 2, t + p, x, x, smer)]
                t += p
            d = abs(cil - x) / self.rychlost
            plan.append((t, t + d, x, cil, smer))
            t, x = t + d, cil
        self.plan = plan

    def _domu(self, now):
        self.plan = [(now, now + self.x / self.rychlost, self.x, 0.0, -1)]

    def _poloha(self, now):
        while self.plan and now >= self.plan[0][1]:
            self.x = self.plan.pop(0)[3]
        if not self.plan or now < self.plan[0][0]:
            return False, (self.plan[0][4] if self.plan else 0)
        t0, t1, x0, x1, smer = self.plan[0]
        self.x = x0 + (x1 - x0) * (now - t0) / (t1 - t0) if t1 > t0 else x1
        return x1 != x0, smer

    def krok(self, now, klid, meze):
        meze = max(0.0, float(meze))
        if not klid:
            self.plan, self.klid_od, self.dalsi = [], None, None
            self.x = min(self.x, meze)
            return self.x, False, 0
        if self.klid_od is None:
            self.klid_od = now
        if self.plan:
            if max(p[3] for p in self.plan) > meze + 0.5:       # titulek se zúžil: rovnou domů
                self.x = min(self.x, meze)
                self._domu(now)
            jde, smer = self._poloha(now)
            if self.plan:
                return self.x, jde, smer
            self.dalsi = None
        self.x = min(self.x, meze)
        if self.x > 0.5:
            if now - self.klid_od >= NAVRAT_S:
                self._domu(now)
                jde, smer = self._poloha(now)
                return self.x, jde, smer
            return self.x, False, 0
        self.x = 0.0
        if not self.zapnuto or min(meze, self.dosah) < MIN_DOSAH:
            self.dalsi = None
            return 0.0, False, 0
        if self.dalsi is None:
            self.dalsi = now + self.interval * self.rng.uniform(0.5, 1.5)
        elif now >= self.dalsi:
            self.naplanuj(now, min(meze, self.dosah))
            jde, smer = self._poloha(now)
            return self.x, jde, smer
        return 0.0, False, 0


class Gesta:
    """Gesta myši nad jednou postavičkou z časové řady událostí (čas v s, poloha v px obrazovky).
    Každá metoda vrací druh reakce (POHLED, STOUCHNUTI, ZAMOTANI, HLAZENI) nebo None."""

    def __init__(self):
        self.kliky, self.pohyby = deque(), deque()
        self.najeti_t = self.hlazeni_t = float("-inf")

    def klik(self, t):
        self.kliky.append(t)
        while self.kliky and t - self.kliky[0] > KLIKY_S:
            self.kliky.popleft()
        if len(self.kliky) >= KLIKY_N:
            self.kliky.clear()
            return ZAMOTANI
        return STOUCHNUTI

    def najeti(self, t):
        self.pohyby.clear()
        if t - self.najeti_t < NAJETI_PAUZA_S:
            return None
        self.najeti_t = t
        return POHLED

    def odjeti(self):
        self.pohyby.clear()

    def pohyb(self, t, x, y):
        self.pohyby.append((t, x, y))
        while self.pohyby and t - self.pohyby[0][0] > HLAZENI_S:
            self.pohyby.popleft()
        if t - self.hlazeni_t < HLAZENI_PAUZA_S or len(self.pohyby) < 3:
            return None
        draha, obraty, smer = 0.0, 0, 0
        body = list(self.pohyby)
        for (_, x0, y0), (_, x1, y1) in zip(body, body[1:]):
            draha += math.hypot(x1 - x0, y1 - y0)
            s = (x1 > x0) - (x1 < x0)
            if s and smer and s != smer:
                obraty += 1
            smer = s or smer
        trvani = t - body[0][0]
        if trvani < HLAZENI_MIN_S:
            return None
        rychlost = draha / trvani
        if draha >= HLAZENI_DRAHA and obraty >= HLAZENI_OBRATY and \
                HLAZENI_RYCHLOST[0] <= rychlost <= HLAZENI_RYCHLOST[1]:
            self.hlazeni_t = t
            self.pohyby.clear()
            return HLAZENI
        return None

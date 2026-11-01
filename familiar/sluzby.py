# Služby daemonu napojené na události hubu: notifikace a zvuky (upozorneni.py),
# denní statistiky (stats.py) a úrovně a úspěchy (progress.py).
#
# Hub volá Sluzby.udalost(familiar, událost) po každé události, kterou familiar přijal
# (Hub.posluchaci). Časovač (1 s) vzorkuje náladu z historie familiarů do statistik
# (nový bod historie = jeden vzorek, jako panel nálady), ukládá (stats a progress samy
# zapisují nejvýš jednou za ukladat_s), pozná nový config (hub.cfg) a nový skin (ikona
# notifikací). Při ukončení ukonci(): uložit hned a zavřít notifikace.
#
# Aktivní okno podle backendu oken (familiar/okna.py): na KDE KWin skript (kwin.js_aktivni),
# na GNOME rozšíření, obojí při každé změně pošle pid aktivního okna přes D-Bus do objektu
# AktivniOkno na session sběrnici daemonu; na X11 ho AktivniOkno čte z _NET_ACTIVE_WINDOW
# (časovač). Okno terminálu té session je aktivní, když se pid shoduje s terminálem familiara
# (fam.term). Funguje v perch i dock režimu. Bez backendu (nebo když se nespustí) je aktivita
# neznámá a bere se jako „neaktivní“: upozornění pak brzdí jen prodleva čekání, délka
# kola a rate limit. Terminál s více okny jednoho procesu (kitty) se nerozliší.
# Klik na notifikaci (signál prepnout) aktivuje okno terminálu přes backend (KDE: dočasný
# KWin skript, X11: _NET_ACTIVE_WINDOW, GNOME: rozšíření).
#
# Úspěchy a nová úroveň: notifikace (Upozorneni.oznam) a oznámení u postavičky přes
# Hub.oznam(klíč, text, sekund) – bublina u postavičky; nová úroveň navíc Hub.oslav (animace success).
# Odemčené doplňky podle [postup] (doplnek_klobouk, emoty_v_klidu) předává časovač hubu
# (Hub.nastav_doplnky). Okno statistik (nabidka.py) bere čísla z prehled(): tytéž instance
# Statistiky a Postup, žádné druhé čtení souborů.
import logging, math, time

from PySide6.QtCore import ClassInfo, QObject, QTimer, Slot
from PySide6.QtDBus import QDBusConnection

from familiar import kwin, okna, sprites, stats
from familiar import upozorneni as upoz
from familiar.fsm import GONE
from familiar.hub import find_terminal

TICK_MS = 1000
CESTA = "/familiar/aktivni"
ROZHRANI = "cz.familiar.Aktivni"
OZNAM_S = 4

lg = logging.getLogger("familiar.sluzby")


@ClassInfo({"D-Bus Interface": ROZHRANI})
class AktivniOkno(QObject):
    """Pid aktivního okna od backendu oken; None = neznámé."""

    def __init__(self, parent=None, jmeno=kwin.AKTIVNI, backend=None):
        super().__init__(parent)
        self.pid, self.jmeno, self.bus = None, jmeno, None
        self.backend, self.bezi = backend, False

    def spust(self):
        """Spustí sledování přes backend oken; True = sleduje se."""
        self.backend = self.backend or okna.backend()
        try:
            self.bezi = bool(self.backend.aktivni_start(self))
        except Exception:
            lg.exception("aktivní okno: backend %s selhal", self.backend.jmeno)
            self.bezi = False
        if self.bezi:
            lg.info("aktivní okno sleduje backend %s", self.backend.jmeno)
        else:
            self.zastav()
        return self.bezi

    def registruj(self):
        """Objekt na session sběrnici pro hlášení z KWin skriptu / rozšíření → jméno služby, nebo None."""
        if self.bus is not None:
            return self.bus.baseService()
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected() or not bus.registerObject(CESTA, self, QDBusConnection.ExportAllSlots):
            lg.warning("aktivní okno: objekt na D-Bus nejde zaregistrovat")
            return None
        self.bus = bus
        return bus.baseService()

    @Slot(int)
    def aktivni(self, pid):
        self.pid = int(pid)

    def zastav(self):
        if self.bezi and self.backend is not None:
            try:
                self.backend.aktivni_stop(self)
            except Exception:
                lg.exception("aktivní okno: backend %s nejde zastavit", self.backend.jmeno)
        self.bezi = False
        if self.bus is not None:
            self.bus.unregisterObject(CESTA)
            self.bus = None
        self.pid = None


def prepnout_na_terminal(term, backend=None):
    """Aktivuje okno terminálu s pid term přes backend oken; True = požadavek odešel."""
    if not term:
        return False
    backend = backend or okna.backend()
    try:
        return bool(backend.prepnout(term))
    except Exception:
        lg.exception("přepnutí do terminálu: backend %s selhal", backend.jmeno)
        return False


class Sluzby(QObject):
    """Notifikace, statistiky a postup nad hubem. Testy mohou podstrčit upozorneni,
    statistiky, postup a okno; statistiky a postup jinak vzniknou až zapnuté."""

    def __init__(self, hub, cfg=None, views=None, parent=None, upozorneni=None, statistiky=None,
                 postup=None, okno=None, ikona=True):
        super().__init__(parent)
        self.hub, self.views = hub, views
        self.cfg = cfg or hub.cfg
        self.okna = getattr(views, "okna", None) or okna.backend(self.cfg["okno"]["backend"])
        self.upoz = upozorneni if upozorneni is not None else upoz.Upozorneni(self.cfg, self)
        self.upoz.prepnout.connect(self.prepni)
        self.stats, self.postup = statistiky, postup
        self._s_zap = self._p_zap = False
        if okno is None:
            okno = AktivniOkno(self, backend=self.okna)
            okno.spust()
        self.okno = okno
        self.vzorky = {}            # klíč familiara → čas posledního vzorku nálady
        self.ceka_na = {}           # klíč familiara → nástroj, na jehož povolení se čeká
        self.ikona, self._ikona_skin = ikona, None
        self._doplnky = None        # naposledy předané hubu
        self.nastav(self.cfg)
        hub.posluchaci.append(self.udalost)
        hub.sluzby = self
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

    # --- config ---

    def nastav(self, cfg):
        """Nový config za běhu (celý efektivní, jako Hub.configure)."""
        self.cfg = cfg
        self.upoz.nastav(cfg)
        s, p = cfg["statistiky"], cfg["postup"]
        if s["zapnuto"] and self.stats is None:
            from familiar.stats import Statistiky
            self.stats = Statistiky()
        if not s["zapnuto"] and self._s_zap and self.stats is not None:
            self.stats.uloz(vynutit=True)       # co se nasbíralo, než se vypnuly
        if self.stats is not None:
            self.stats.retence_dni, self.stats.interval_s = s["retence_dni"], s["ukladat_s"]
        if p["zapnuto"] and self.postup is None:
            from familiar.progress import Postup
            self.postup = Postup()
        if not p["zapnuto"] and self._p_zap and self.postup is not None:
            self.postup.uloz(vynutit=True)
        if self.postup is not None:
            self.postup.interval_s = p["ukladat_s"]
        self._s_zap, self._p_zap = s["zapnuto"], p["zapnuto"]
        self._predej_doplnky()

    # --- události ---

    def aktivni(self, fam):
        """Je okno terminálu familiara aktivní? Neznámé = ne."""
        return self.okno.pid is not None and fam.term is not None and self.okno.pid == fam.term

    def udalost(self, fam, ev):
        """Posluchač hubu: (familiar, událost ve společném schématu)."""
        if self._s_zap:
            self.stats.zapocti(ev)
        if self._p_zap:
            pred = self.postup.uroven
            nove = self.postup.zapocti(ev)
            if self.cfg["postup"]["oznamovat_uspechy"]:
                self._oznam_postup(fam, nove, pred)
        if upoz.rusi(ev, self.ceka_na.get(fam.key)):
            self.odpovezeno(fam.key)
        druh = upoz.druh_udalosti(ev)
        if druh is not None:
            trvani = ev["ts"] - fam.kolo_od
            nastroj = (ev.get("data") or {}).get("tool") or fam.tool
            if druh in upoz.CEKANI:
                self.ceka_na[fam.key] = nastroj
            self.upoz.udalost(fam.key, druh, {
                "jmeno": fam.name, "pid": fam.pid or 0, "aktivni": lambda: self.aktivni(fam),
                "trvani_s": trvani if math.isfinite(trvani) and trvani >= 0 else None, "nastroj": nastroj})

    def odpovezeno(self, klic):
        """Uživatel odpověděl (v terminálu nebo v bublině): pryč s upozorněním té postavičky."""
        self.ceka_na.pop(klic, None)
        self.upoz.zrus(klic)

    def _oznam_postup(self, fam, nove, pred):
        texty = [f"Nový úspěch: {u['nazev']}" for u in nove]
        if self.postup.uroven > pred:
            texty.append(f"Úroveň {self.postup.uroven}!")
        if not texty:
            return
        for t in texty:
            self.oznam(fam.key, t)
        if self.postup.uroven > pred:
            try:
                self.hub.oslav(fam.key)
            except Exception:
                lg.exception("oslava nové úrovně selhala")
        self.upoz.oznam("familiar – " + fam.name, "\n".join(texty))

    def oznam(self, klic, text, sekund=OZNAM_S):
        """Krátká bublina u postavičky (Hub.oznam); False, když postavička není."""
        try:
            return self.hub.oznam(klic, text, sekund)
        except Exception:
            lg.exception("oznámení u postavičky selhalo")
            return False

    @Slot(int)
    def prepni(self, pid):
        """Klik na notifikaci: aktivovat okno terminálu té session."""
        fam = self.hub.fams.get(pid) or next((f for f in self.hub.fams.values() if f.pid == pid), None)
        term = fam.term if fam is not None and fam.term else find_terminal(pid)
        lg.info("přepnutí do terminálu z notifikace")
        prepnout_na_terminal(term, self.okna)

    def odemcene(self):
        """Odemčené doplňky [{"id", "druh", "nazev", "sprite"}] (vypnutý postup = žádné)."""
        return self.postup.odemcene_doplnky() if self._p_zap else []

    def doplnky(self):
        """(klobouk, emoty v klidu) z odemčených doplňků podle [postup]; zamčený klobouk se nenosí."""
        p, odemcene = self.cfg["postup"], self.odemcene()
        klobouky = [d for d in odemcene if d["druh"] == "klobouk" and d["sprite"] in sprites.HATS]
        volba, klobouk = p["doplnek_klobouk"], None
        if volba == "auto" and klobouky:
            klobouk = klobouky[-1]["sprite"]
        elif volba:
            klobouk = next((d["sprite"] for d in klobouky if d["id"] == volba), None)
        emoty = [d["sprite"] for d in odemcene if d["druh"] == "emote" and d["sprite"] in sprites.POPS] \
            if p["emoty_v_klidu"] else []
        return klobouk, tuple(emoty)

    def _predej_doplnky(self):
        d = self.doplnky()
        if d != self._doplnky:
            self._doplnky = d
            self.hub.nastav_doplnky(*d)

    def prehled(self, now=None):
        """Čísla pro okno statistik (stats.prehled) z živých instancí; vypnuté = None."""
        return stats.prehled(self.stats if self._s_zap else None, self.postup if self._p_zap else None,
                             self.cfg, now)

    # --- časovač ---

    def tick(self, now=None):
        try:
            now = time.time() if now is None else now
            if self.hub.cfg is not self.cfg:
                self.nastav(self.hub.cfg)
            if self.ikona and self.hub.skin is not self._ikona_skin:
                self._ikona_skin = self.hub.skin
                self.upoz.ikona = upoz.ulozit_ikonu(self.hub.skin)
            self._vzorkuj()
            self._predej_doplnky()      # nová úroveň nebo úspěch může odemknout doplněk
            self.uloz(now)
        except Exception:
            lg.exception("chyba v časovači služeb")

    def _vzorkuj(self):
        """Nový bod historie nálady (Familiar.update ho přidává po HIST_S) → vzorek do statistik."""
        if not self._s_zap:
            return
        for key, fam in self.hub.fams.items():
            if fam.fsm.state == GONE or not fam.historie:
                continue
            t, v, a = fam.historie[-1]
            if t > self.vzorky.get(key, float("-inf")):
                self.vzorky[key] = t
                self.stats.vzorek_nalady(t, v, a)
        for key in [k for k in self.vzorky if k not in self.hub.fams]:
            del self.vzorky[key]

    def uloz(self, now=None, vynutit=False):
        if self._s_zap:
            self.stats.uloz(now, vynutit)
        if self._p_zap:
            self.postup.uloz(now, vynutit)

    def ukonci(self):
        """Konec daemonu: uložit hned, zavřít notifikace, zastavit sledování aktivního okna."""
        self.timer.stop()
        try:
            self.uloz(vynutit=True)
        finally:
            self.upoz.ukonci()
            self.okno.zastav()

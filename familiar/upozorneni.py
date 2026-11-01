# Upozornění mimo postavičku: notifikace na ploše (org.freedesktop.Notifications přes QtDBus)
# a krátké zvuky (familiar/zvuky/, generuje tools/zvuky.py). Napojuje ho familiar/sluzby.py.
#
# Volající hlásí události: udalost(session, druh, kontext) a zrus(session), když uživatel
# odpověděl. Zda upozornit, rozhoduje čistá funkce pravidla() z configu, kontextu a historie:
# jen když okno terminálu té session není aktivní, čekání až po prodlevě, dokončení jen
# u dlouhého kola, tichý režim / soustředění / noční klid, rate limit.
# Notifikace té session se nahrazuje (replaces_id); akce „Přepnout do terminálu“ (i klik
# na notifikaci) vyšle signál prepnout(pid), samotné přepnutí okna zařídí volající.
# Text notifikace je jen jméno projektu, druh události, délka kola a název nástroje,
# nikdy text promptu. Urgency je normal; critical (obchází systémové Nerušit) jen pro
# čekání a jen s nalehave_kriticke = true. Výchozí hodnoty [upozorneni] jsou v config.py.
#
# QtDBus z Pythonu neumí poslat uint (int jde jako „i“, QDBusArgument << int jako „q“),
# proto se Notify volá přes metaobjekt QDBusInterface z introspekce serveru: Plasma má
# u hints anotaci QVariantMap, takže metoda je typovaná a Q_ARG("uint") projde. Server
# bez anotace (GNOME, dunst) → záloha `gdbus call` (glib2, typy podle introspekce).
import html, logging, os, re, shutil, subprocess, time
from collections import deque

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject, QProcess, Qt, QTimer, SLOT, Signal, Slot
from PySide6.QtDBus import QDBusArgument, QDBusConnection, QDBusInterface

from familiar import config

DRUHY = DOKONCENO, POVOLENI, OTAZKA, CHYBA, COMPACT = config.DRUHY_UPOZORNENI
CEKANI = {POVOLENI, OTAZKA}     # Claude stojí, dokud uživatel neodpoví
SADY = config.SADY_ZVUKU
V_TICHU = config.V_TICHU
VYCHOZI = config.UPOZORNENI     # zvuky (bool), sada, hlasitost 0–100, druhy, nocni_klid "22:00-07:00" …

TEXTY = {DOKONCENO: "Hotovo", POVOLENI: "Čeká na povolení", OTAZKA: "Má otázku",
         CHYBA: "Kolo skončilo chybou", COMPACT: "Zhušťuje kontext"}
NORMAL, KRITICKA = 1, 2         # urgency (0 = low)
AKCE = "terminal"
AKCE_TEXT = "Přepnout do terminálu"
NAZEV = "familiar"
IKONA = "utilities-terminal"    # dokud volající nedodá cestu k PNG postavičky (ulozit_ikonu)
ZVUKY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zvuky")

SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
TIMEOUT_MS = 1500               # Notify je synchronní; zaseklý server nesmí držet GUI déle
_NASTROJ_RE = re.compile(r"[A-Za-z0-9_.:-]{1,48}")

lg = logging.getLogger("familiar.upozorneni")


# --- čistá pravidla ---------------------------------------------------------------------

def nastaveni(cfg):
    """Sekce [upozorneni] z celého configu doplněná výchozími hodnotami; klíč ticho
    = tichý režim nebo soustředění (horní úroveň configu)."""
    cfg = cfg or {}
    sek = cfg.get("upozorneni") or {}
    n = {**VYCHOZI, **sek}
    n["vlastni"] = {**VYCHOZI["vlastni"], **(sek.get("vlastni") or {})}
    n["ticho"] = bool(cfg.get("tichy") or cfg.get("soustredeni"))
    return n


def v_okne(okno, ted):
    """Je místní čas ted (epoch) v okně "HH:MM-HH:MM"? Přes půlnoc funguje; prázdné či vadné = ne."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", okno or "")
    if not m:
        return False
    od, do = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    lt = time.localtime(ted)
    x = lt.tm_hour * 60 + lt.tm_min
    if od == do:
        return False
    return od <= x < do if od < do else x >= od or x < do


def pravidla(druh, kontext, nast, ted, historie=()):
    """(notifikace, zvuk, důvod) bez vedlejších účinků.
    kontext: aktivni (okno terminálu té session je aktivní), ceka_s (jak dlouho čeká
    na odpověď), trvani_s (délka kola), session. historie: [(čas, session, druh)]
    dřívějších upozornění."""
    if druh not in nast["druhy"]:
        return False, False, "druh vypnutý"
    if nast["jen_neaktivni"] and kontext.get("aktivni"):
        return False, False, "terminál je aktivní"
    if druh in CEKANI and kontext.get("ceka_s", 0.0) < nast["cekani_po_s"]:
        return False, False, "čeká krátce"
    trvani = kontext.get("trvani_s")
    if druh == DOKONCENO and trvani is not None and trvani < nast["kolo_nad_s"]:
        return False, False, "krátké kolo"
    notif = bool(nast["notifikace"])
    zvuk = bool(nast["zvuky"] and nast["hlasitost"] > 0)
    if nast["ticho"] or v_okne(nast["nocni_klid"], ted):
        if nast["v_tichu"] == "nic" or (nast["v_tichu"] == "nalehave" and druh not in CEKANI):
            return False, False, "ticho"
        zvuk = False
    if not (notif or zvuk):
        return False, False, "notifikace i zvuky vypnuté"
    session = kontext.get("session")
    if druh not in CEKANI and any(ted - t < nast["rozestup_s"] and s == session and d == druh
                                  for t, s, d in historie):
        return False, False, "rozestup"
    if sum(1 for t, _, _ in historie if ted - t < 60.0) >= nast["za_minutu"]:
        return False, False, "limit za minutu"
    return notif, zvuk, "ok"


def _doba(s):
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s" if s % 60 else f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def text_pro(druh, kontext):
    """Tělo notifikace: druh, délka kola, název nástroje – nic z promptu."""
    text = TEXTY[druh]
    nastroj = kontext.get("nastroj")
    if druh == POVOLENI and isinstance(nastroj, str) and _NASTROJ_RE.fullmatch(nastroj):
        text += f": {nastroj}"
    if druh == DOKONCENO and kontext.get("trvani_s"):
        text += f" za {_doba(kontext['trvani_s'])}"
    return text


def urgence(druh, nast):
    """Urgency notifikace: critical jen pro čekání a jen se zapnutým nalehave_kriticke."""
    return KRITICKA if nast.get("nalehave_kriticke") and druh in CEKANI else NORMAL


def zvuk_pro(druh, nast):
    """Cesta k WAV pro druh: vlastní soubor, jinak ze sady; None = bez zvuku."""
    if not nast["zvuky"]:
        return None
    vlastni = (nast["vlastni"].get(druh) or "").strip()
    if vlastni:
        cesta = os.path.expanduser(vlastni)
        if os.path.isfile(cesta):
            return cesta
        lg.warning("vlastní zvuk pro %s neexistuje, použiji sadu", druh)
    if nast["sada"] not in SADY:
        return None
    cesta = os.path.join(ZVUKY_DIR, nast["sada"], f"{druh}.wav")
    return cesta if os.path.isfile(cesta) else None


def druh_udalosti(ev):
    """Událost hubu → druh upozornění, nebo None."""
    k, d = ev["kind"], ev.get("data") or {}
    if d.get("agent"):
        return None             # subagenti se hlásí přes hlavního agenta
    if k == "agent.done":
        return DOKONCENO
    if k == "agent.waiting":
        return OTAZKA if d.get("why") == "question" else POVOLENI
    if k == "agent.failed":
        return CHYBA
    if k == "context.compact" and d.get("trigger") != "manual":    # ruční /compact uživatel ví
        return COMPACT
    return None


RUSI = {"user.prompt", "tool.start", "tool.denied", "agent.interrupted", "session.end"}
KONEC_NASTROJE = {"tool.end", "tool.error"}


def rusi(ev, ceka_na=None):
    """Znamená událost, že uživatel odpověděl (→ zrus)? Nástroje subagentů ne.
    Konec nástroje hlavního agenta ruší čekání na povolení (uživatel povolil v terminálu,
    PreToolUse přišel už před žádostí); s ceka_na (nástroj, na který se čeká) jen konec
    téhož nástroje, ne paralelního Read."""
    d = ev.get("data") or {}
    if d.get("agent"):
        return False
    if ev["kind"] in KONEC_NASTROJE:
        return ceka_na is None or d.get("tool") == ceka_na
    return ev["kind"] in RUSI


# --- D-Bus ----------------------------------------------------------------------------------

def argumenty_notify(replaces, ikona, titulek, text, urgence, vyprseni_ms, akce=True):
    """Argumenty Notify(susssasa{sv}i) jako hodnoty Pythonu; urgency je bajt (y)."""
    actions = ["default", AKCE_TEXT, AKCE, AKCE_TEXT] if akce else []
    hints = {"urgency": urgence}
    return [NAZEV, int(replaces), ikona or "", titulek, html.escape(text, quote=False), actions, hints,
            int(vyprseni_ms)]


def _gv(v):
    """Hodnota Pythonu → textový zápis GVariant pro gdbus."""
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, list):
        return "[" + ", ".join(_gv(x) for x in v) + "]" if v else "@as []"
    return str(v)


def prikaz_gdbus(args):
    """Záložní volání Notify přes `gdbus call` (bez typové anotace na serveru)."""
    name, rid, icon, summary, body, actions, hints, timeout = args
    hv = ", ".join(f"{_gv(k)}: <byte {v}>" if k == "urgency" else f"{_gv(k)}: <{_gv(v)}>"
                   for k, v in hints.items())
    return ["gdbus", "call", "--session", "--dest", SERVICE, "--object-path", PATH,
            "--method", f"{SERVICE}.Notify", "--timeout", str(TIMEOUT_MS // 1000 or 1), "--",
            _gv(name), str(rid), _gv(icon), _gv(summary), _gv(body), _gv(actions), "{" + hv + "}", str(timeout)]


class Notifikace(QObject):
    """Tenká vrstva nad org.freedesktop.Notifications. Callbacky na_akci(id, klíč)
    a na_zavreni(id) volá pro všechny notifikace na sběrnici; filtruje volající."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.na_akci = self.na_zavreni = None
        self.bus = QDBusConnection.sessionBus()
        self.iface, self.typovane = None, False
        if self.bus.isConnected():
            self.bus.connect(SERVICE, PATH, SERVICE, "ActionInvoked", self, SLOT("_akce(uint,QString)"))
            self.bus.connect(SERVICE, PATH, SERVICE, "NotificationClosed", self, SLOT("_zavreno(uint,uint)"))

    @Slot("uint", str)
    def _akce(self, nid, klic):
        if self.na_akci:
            self.na_akci(int(nid), klic)

    @Slot("uint", "uint")
    def _zavreno(self, nid, duvod):
        if self.na_zavreni:
            self.na_zavreni(int(nid))

    def _rozhrani(self):
        """QDBusInterface z introspekce (synchronní, jen poprvé a po výpadku serveru)."""
        if self.iface is None or not self.iface.isValid():
            if not self.bus.isConnected():
                return None
            iface = QDBusInterface(SERVICE, PATH, SERVICE, self.bus)
            if not iface.isValid():
                return None
            iface.setTimeout(TIMEOUT_MS)
            mo = iface.metaObject()
            self.typovane = any(bytes(mo.method(i).methodSignature()).startswith(b"Notify(")
                                and b"QVariantMap" in bytes(mo.method(i).methodSignature())
                                for i in range(mo.methodOffset(), mo.methodCount()))
            self.iface = iface
        return self.iface

    def zobraz(self, args):
        """Pošle Notify (argumenty z argumenty_notify); vrací id notifikace, 0 = nevyšlo."""
        iface = self._rozhrani()
        if iface is None:
            lg.info("server notifikací není k dispozici")
            return 0
        if not self.typovane:
            return self._zobraz_gdbus(args)
        name, rid, icon, summary, body, actions, hints, timeout = args
        hints = dict(hints)
        urg = QDBusArgument()
        urg << chr(hints.pop("urgency"))        # jednoznakový str = uchar → „y“
        hints["urgency"] = urg
        try:
            nid = QMetaObject.invokeMethod(
                iface, "Notify", Qt.DirectConnection, Q_RETURN_ARG("uint"),
                Q_ARG(str, name), Q_ARG("uint", rid), Q_ARG(str, icon), Q_ARG(str, summary), Q_ARG(str, body),
                Q_ARG("QStringList", actions), Q_ARG("QVariantMap", hints), Q_ARG(int, timeout))
        except RuntimeError:
            lg.warning("Notify selhalo: %s", iface.lastError().name() or "neznámá chyba")
            return 0
        if iface.lastError().isValid():
            lg.warning("Notify selhalo: %s", iface.lastError().name())
            return 0
        return int(nid or 0)

    def _zobraz_gdbus(self, args):
        if not shutil.which("gdbus"):
            lg.warning("server notifikací bez typové anotace a gdbus chybí")
            return 0
        try:
            out = subprocess.run(prikaz_gdbus(args), capture_output=True, text=True, timeout=TIMEOUT_MS / 1000 + 0.5)
        except (OSError, subprocess.TimeoutExpired) as e:
            lg.warning("gdbus Notify selhalo (%s)", type(e).__name__)
            return 0
        m = re.search(r"uint32 (\d+)", out.stdout)
        if not m:
            lg.warning("gdbus Notify selhalo (rc %d)", out.returncode)
            return 0
        return int(m[1])

    def zavri(self, nid):
        iface = self._rozhrani()
        if iface is None or not nid:
            return
        try:
            QMetaObject.invokeMethod(iface, "CloseNotification", Qt.DirectConnection, Q_ARG("uint", nid))
        except RuntimeError:
            lg.warning("CloseNotification selhalo: %s", iface.lastError().name() or "neznámá chyba")


# --- zvuky ----------------------------------------------------------------------------------

def _qt_zvuk():
    """QSoundEffect, je-li v PySide6 QtMultimedia (je v PySide6-Addons, ne v Essentials)."""
    try:
        from PySide6.QtMultimedia import QSoundEffect
        return QSoundEffect
    except ImportError:
        return None


def zpusob_prehravani():
    """'qt', 'pw-play', 'paplay', nebo None."""
    if _qt_zvuk() is not None:
        return "qt"
    for prog in ("pw-play", "paplay"):
        if shutil.which(prog):
            return prog
    return None


def prikaz_prehrani(zpusob, cesta, hlasitost):
    """Příkaz pro externí přehrávač; hlasitost 0–100."""
    h = max(0, min(100, hlasitost))
    if zpusob == "pw-play":
        return ["pw-play", "--media-role=Notification", f"--volume={h / 100:.2f}", cesta]
    if zpusob == "paplay":
        return ["paplay", f"--volume={round(h / 100 * 65536)}", "--property=media.role=event", cesta]
    raise ValueError(zpusob)


class Prehravac(QObject):
    """Přehraje WAV bez blokování GUI: QSoundEffect, jinak pw-play/paplay přes QProcess.
    Hraje nejvýš jeden zvuk; nový přeruší předchozí."""

    def __init__(self, parent=None, zpusob=...):
        super().__init__(parent)
        self.zpusob = zpusob_prehravani() if zpusob is ... else zpusob
        self._efekty = {}
        self._hraje = None
        self._proc = None
        lg.debug("přehrávání zvuků: %s", self.zpusob or "žádné")

    def prehraj(self, cesta, hlasitost):
        if not cesta or not self.zpusob or hlasitost <= 0:
            return False
        if self.zpusob == "qt":
            return self._qt(cesta, hlasitost)
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
        p = self._proc = QProcess(self)
        p.finished.connect(lambda *_, p=p: self._konec(p))
        p.errorOccurred.connect(lambda err, p=p: self._chyba(p, err))
        cmd = prikaz_prehrani(self.zpusob, cesta, hlasitost)
        p.start(cmd[0], cmd[1:])
        return True

    def _konec(self, p):
        if self._proc is p:
            self._proc = None
        p.deleteLater()

    def _chyba(self, p, err):
        if err == QProcess.ProcessError.FailedToStart:     # finished pak nepřijde
            lg.warning("přehrávač %s nejde spustit", self.zpusob)
            self._konec(p)

    def _qt(self, cesta, hlasitost):
        from PySide6.QtCore import QUrl
        eff = self._efekty.get(cesta)
        if eff is None:
            eff = self._efekty[cesta] = _qt_zvuk()(self)
            eff.setSource(QUrl.fromLocalFile(cesta))
        if self._hraje is not None and self._hraje is not eff:
            self._hraje.stop()
        eff.setVolume(max(0, min(100, hlasitost)) / 100)
        eff.play()          # ještě nenačtený zvuk zahraje po načtení
        self._hraje = eff
        return True


# --- upozornění -------------------------------------------------------------------------------

class Upozorneni(QObject):
    """API pro hub/daemon: udalost(), zrus(), nastav(), signál prepnout(pid)."""

    prepnout = Signal(int)

    def __init__(self, cfg=None, parent=None, dbus=None, prehravac=None, cas=time.time):
        super().__init__(parent)
        self.nast = nastaveni(cfg)
        self.dbus = dbus if dbus is not None else Notifikace(self)
        self.dbus.na_akci, self.dbus.na_zavreni = self._akce, self._zavreno
        self.prehravac = prehravac if prehravac is not None else Prehravac(self)
        self.cas = cas
        self.ikona = IKONA
        self.ids = {}               # session → id zobrazené notifikace
        self.notif = {}             # id → (session, pid)
        self.cekajici = {}          # session → QTimer odloženého upozornění na čekání
        self.historie = deque(maxlen=64)    # (čas, session, druh) vydaných upozornění

    def nastav(self, cfg):
        """Nový config za běhu (celý efektivní config, jako Hub.configure)."""
        self.nast = nastaveni(cfg)

    def udalost(self, session, druh, kontext=None):
        """Událost session. kontext: jmeno (titulek), pid (pro prepnout), aktivni (bool nebo
        funkce bez argumentů – u odloženého čekání se zavolá až po prodlevě), trvani_s,
        nastroj. Vrací důvod rozhodnutí ("ok", "odloženo", …)."""
        kontext = dict(kontext or {}, session=session)
        self._zrus_cekani(session)
        if druh not in DRUHY:
            return "neznámý druh"
        prodleva = float(self.nast["cekani_po_s"])
        if druh in CEKANI and prodleva > 0 and druh in self.nast["druhy"]:
            t = self.cekajici[session] = QTimer(self)
            t.setSingleShot(True)
            t.setTimerType(Qt.PreciseTimer)
            t.timeout.connect(lambda: self._po_prodleve(session, druh, kontext, prodleva))
            t.start(int(prodleva * 1000))
            return "odloženo"
        return self._vyhodnot(session, druh, kontext, 0.0)

    def _po_prodleve(self, session, druh, kontext, prodleva):
        t = self.cekajici.pop(session, None)
        if t is not None:
            t.deleteLater()
        self._vyhodnot(session, druh, kontext, prodleva)

    def _vyhodnot(self, session, druh, kontext, ceka_s):
        ted = self.cas()
        k = dict(kontext, ceka_s=ceka_s)
        if callable(k.get("aktivni")):
            k["aktivni"] = bool(k["aktivni"]())
        notif, zvuk, duvod = pravidla(druh, k, self.nast, ted, self.historie)
        lg.debug("upozornění %s: %s", druh, duvod)
        if not (notif or zvuk):
            return duvod
        self.historie.append((ted, session, druh))
        if notif:
            args = argumenty_notify(self.ids.get(session, 0), self.ikona, k.get("jmeno") or NAZEV,
                                    text_pro(druh, k), urgence(druh, self.nast), 0 if druh in CEKANI else -1)
            nid = self.dbus.zobraz(args)
            if nid:
                old = self.ids.get(session)
                if old and old != nid:
                    self.notif.pop(old, None)
                self.ids[session], self.notif[nid] = nid, (session, k.get("pid"))
        if zvuk:
            self.prehravac.prehraj(zvuk_pro(druh, self.nast), self.nast["hlasitost"])
        return duvod

    def oznam(self, titulek, text):
        """Notifikace mimo druhy událostí (nový úspěch, úroveň): bez zvuku a akce, urgency low;
        ne v tichu ani nočním klidu. Vrací True, když vyšla."""
        n = self.nast
        if not n["notifikace"] or n["ticho"] or v_okne(n["nocni_klid"], self.cas()):
            return False
        return bool(self.dbus.zobraz(argumenty_notify(0, self.ikona, titulek, text, 0, -1, akce=False)))

    def _zrus_cekani(self, session):
        t = self.cekajici.pop(session, None)
        if t is not None:
            t.stop()
            t.deleteLater()

    def zrus(self, session):
        """Uživatel odpověděl: zruší odložené upozornění a zavře notifikaci té session."""
        self._zrus_cekani(session)
        nid = self.ids.pop(session, None)
        if nid:
            self.notif.pop(nid, None)
            self.dbus.zavri(nid)

    def ukonci(self):
        """Při ukončení daemonu: nenechat na ploše notifikace, které nevyprší."""
        for session in list(self.ids) + list(self.cekajici):
            self.zrus(session)

    def _akce(self, nid, klic):
        hit = self.notif.get(nid)
        if hit and klic in ("default", AKCE) and hit[1]:
            self.prepnout.emit(int(hit[1]))

    def _zavreno(self, nid):
        hit = self.notif.pop(nid, None)
        if hit and self.ids.get(hit[0]) == nid:
            del self.ids[hit[0]]


def ulozit_ikonu(skin, cesta=None):
    """PNG první klidové pózy postavičky pro app_icon notifikací (potřebuje QGuiApplication);
    vrací cestu. Výchozí místo: $XDG_CACHE_HOME/familiar/ikona.png."""
    from familiar import nabidka, paths
    if cesta is None:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(paths.home(), ".cache")
        cesta = os.path.join(base, "familiar", "ikona.png")
    os.makedirs(os.path.dirname(cesta), exist_ok=True)
    nabidka.ikona(skin).pixmap(nabidka.IKONA_PX, nabidka.IKONA_PX).save(cesta, "PNG")
    return cesta

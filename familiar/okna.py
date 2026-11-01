# Backend oken: kdo zná polohu cizích oken, posadí postavičky na titulek terminálu (perch),
# hlásí aktivní okno a umí přepnout do terminálu (klik na notifikaci).
#
#   kwin   KDE Plasma (Wayland i X11): KWin skripty perch.js, familiar-aktivni, familiar-prepnout
#          (familiar/kwin.py), zprávy zpět přes D-Bus
#   x11    jiná X11 session se správcem oken s EWMH: stav oken čte familiar sám (familiar/x11.py),
#          polohy počítá rozmisteni.py (přepis perch.js) a okna postaviček posouvá Qt
#   gnome  GNOME Shell na Waylandu: s rozšířením familiara (familiar/gnome.py) jako kwin,
#          bez něj dock a aktivní okno neznámé
#   zadny  dock, aktivní okno neznámé (jiný Wayland, nic nezjištěno)
# Volba: [okno] backend v configu, "auto" podle XDG_CURRENT_DESKTOP / XDG_SESSION_TYPE.
# Backend se volí při startu daemonu (změna configu platí po restartu). Modul jde importovat
# bez Qt (doctor); Qt a D-Bus se načítají až v metodách.
import logging, os, shutil, time

from familiar import gnome, rozmisteni

BACKENDY = ("kwin", "x11", "gnome", "zadny")
PREPNOUT_ODEBRAT_MS = 2000      # jednorázový KWin skript aktivace se pak odebere
X11_OBNOVA_S = 0.25             # stav cizích oken X11 nejvýš takhle často (jako časovač perch.js)
X11_AKTIVNI_MS = 500

lg = logging.getLogger("familiar.okna")


def zvol(volba="auto", env=None):
    """(backend, proč) podle configu a prostředí."""
    env = os.environ if env is None else env
    if volba in BACKENDY:
        return volba, "nastaveno v configu"
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    session = env.get("XDG_SESSION_TYPE", "").lower()
    wayland = session == "wayland" or (not session and bool(env.get("WAYLAND_DISPLAY")))
    if "KDE" in desktop:
        return "kwin", "KDE Plasma"
    if "GNOME" in desktop and wayland:
        return "gnome", "GNOME na Waylandu"
    if wayland:
        return "zadny", f"Wayland bez podpory ({env.get('XDG_CURRENT_DESKTOP') or 'neznámé prostředí'})"
    if env.get("DISPLAY"):
        return "x11", "X11 session"
    return "zadny", "neznámé prostředí"


_instance = {}


def backend(volba="auto"):
    """Sdílená instance backendu (daemon: pohledy i služby mají tutéž)."""
    name, _ = zvol(volba)
    if name not in _instance:
        _instance[name] = {"kwin": Kwin, "x11": X11, "gnome": Gnome}.get(name, Zadny)()
    return _instance[name]


class Zadny:
    """Dock, aktivní okno neznámé, přepnout do terminálu nejde."""
    jmeno = "zadny"
    umistovac = None        # objekt s umisti(okna_perch), když okna postaviček posouvá daemon sám

    def perch_umi(self):
        return False

    def perch_start(self, zpravy):
        return False

    def perch_stop(self):
        pass

    def aktivni_start(self, okno):
        return False

    def aktivni_stop(self, okno):
        pass

    def prepnout(self, pid):
        return False


class Kwin(Zadny):
    jmeno = "kwin"

    def __init__(self):
        self._aktivni = None

    def perch_umi(self):
        return True     # jestli se skript opravdu nahraje, ukáže perch_start (jinak dock)

    def perch_start(self, zpravy):
        from familiar import kwin
        kwin.perch_dbus = zpravy.spust() if zpravy is not None else None
        return kwin.load()

    def perch_stop(self):
        from familiar import kwin
        kwin.unload()

    def aktivni_start(self, okno):
        from familiar import kwin, sluzby
        sluzba = okno.registruj()
        if sluzba is None:
            return False
        if not kwin.nahraj_text(kwin.js_aktivni(sluzba, sluzby.CESTA, sluzby.ROZHRANI), okno.jmeno):
            lg.warning("aktivní okno: KWin skript nejde nahrát, aktivita terminálu neznámá")
            return False
        self._aktivni = okno.jmeno
        return True

    def aktivni_stop(self, okno):
        if self._aktivni:
            from familiar import kwin
            try:
                kwin.odeber(self._aktivni)
            except Exception:
                lg.exception("KWin skript %s nejde odebrat", self._aktivni)
            self._aktivni = None

    def prepnout(self, pid):
        from PySide6.QtCore import QTimer
        from familiar import kwin
        if not kwin.nahraj_text(kwin.js_prepnout(pid), kwin.PREPNOUT):
            lg.info("přepnutí do terminálu: KWin není k dispozici")
            return False
        QTimer.singleShot(PREPNOUT_ODEBRAT_MS, lambda: kwin.odeber(kwin.PREPNOUT))
        return True


class Gnome(Zadny):
    """GNOME Shell s rozšířením familiara; bez něj jako zadny."""
    jmeno = "gnome"

    def __init__(self):
        self._umi = None

    def perch_umi(self):
        if self._umi is None:
            self._umi = gnome.verze() is not None
            if not self._umi:
                lg.info("GNOME: rozšíření %s neodpovídá, perch nejde (familiar install --gnome-rozsireni)",
                        gnome.UUID)
        return self._umi

    def _sluzba(self):
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        return bus.baseService() if bus.isConnected() else None

    def perch_start(self, zpravy):
        info = zpravy.spust() if zpravy is not None else None
        sluzba = info["sluzba"] if info else self._sluzba()     # jméno daemonu hlídá rozšíření i bez zpráv
        if not sluzba or not self.perch_umi():
            return False
        return gnome.perch(sluzba, *((info["cesta"], info["rozhrani"]) if info else ("", "")))

    def perch_stop(self):
        gnome.perch_stop()

    def aktivni_start(self, okno):
        from familiar import sluzby
        if not self.perch_umi():
            return False
        sluzba = okno.registruj()
        return bool(sluzba) and gnome.aktivni(sluzba, sluzby.CESTA, sluzby.ROZHRANI)

    def aktivni_stop(self, okno):
        if self._umi:
            gnome.aktivni_stop()

    def prepnout(self, pid):
        return self.perch_umi() and gnome.aktivuj(pid)


class X11(Zadny):
    """Jiná X11 session: stav oken přes libX11 (EWMH), rozmístění v Pythonu."""
    jmeno = "x11"

    def __init__(self, display=None):
        self.display, self._spojeni = display, None
        self.umistovac = None
        self._casovac = None

    def spojeni(self):
        """Spojení se serverem, nebo None (libX11 chybí, server nejde otevřít)."""
        if self._spojeni is None:
            from familiar import x11
            k = 1.0
            try:
                from PySide6.QtGui import QGuiApplication
                scr = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
                k = scr.devicePixelRatio() if scr is not None else 1.0
            except ImportError:
                pass
            s = x11.Spojeni(self.display, k)
            self._spojeni = s if s.ok else False
        return self._spojeni or None

    def perch_umi(self):
        s = self.spojeni()
        return bool(s and s.wm() and (s.podporuje("_NET_CLIENT_LIST_STACKING") or s.podporuje("_NET_CLIENT_LIST")))

    def perch_start(self, zpravy):
        if not self.perch_umi():
            lg.warning("X11: správce oken bez EWMH (_NET_CLIENT_LIST) nebo bez spojení, perch nejde")
            return False
        self.umistovac = X11Umistovac(self.spojeni(), zpravy)
        return True

    def perch_stop(self):
        self.umistovac = None

    def aktivni_start(self, okno):
        from PySide6.QtCore import QTimer
        s = self.spojeni()
        if s is None or not s.podporuje("_NET_ACTIVE_WINDOW"):
            return False

        def tik():
            okno.pid = s.aktivni_pid()
        self._casovac = QTimer(okno)
        self._casovac.timeout.connect(tik)
        self._casovac.start(X11_AKTIVNI_MS)
        tik()
        return True

    def aktivni_stop(self, okno):
        if self._casovac is not None:
            self._casovac.stop()
            self._casovac = None

    def prepnout(self, pid):
        s = self.spojeni()
        win = s.okno_pid(pid) if s is not None else None
        if win is None:
            return False
        plocha = s.vlastnost(win, "_NET_WM_DESKTOP")
        return s.aktivuj(win, plocha[0] if plocha else None)


class X11Plocha(rozmisteni.Plocha):
    """Plocha pro rozmisteni.py: cizí okna z X11, okna postaviček z Qt. Přesun posune okno Qt,
    schování (HIDDEN) ho skryje: správce oken by okno mimo obrazovku vrátil zpátky."""

    def __init__(self, okna, plocha, spojeni, vsude):
        super().__init__(okna, plocha=plocha, aktivita=None)
        self.spojeni, self._vsude = spojeni, vsude

    def oblast(self, w):
        """Pracovní plocha obrazovky okna (Qt ji na xcb bere z _NET_WORKAREA), None = s myší."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QCursor, QGuiApplication
        if w is None:
            pos = QCursor.pos()
        else:
            g = w["frameGeometry"]
            pos = QPoint(int(g["x"] + g["width"] / 2), int(g["y"] + g["height"] / 2))
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        a = scr.availableGeometry()
        return {"x": a.x(), "y": a.y(), "width": a.width(), "height": a.height()}

    def presun(self, w, x, y):
        okno = w.get("_qt")
        if okno is None:
            return
        if x <= rozmisteni.HIDDEN / 2:
            if okno.isVisible():
                okno.hide()
            return
        if (okno.x(), okno.y()) != (round(x), round(y)):
            okno.move(round(x), round(y))
        if not okno.isVisible():
            okno.show()

    def vsude(self, w):
        okno = w.get("_qt")
        if okno is not None and okno.isVisible():
            self._vsude(okno)

    def aktivuj(self, term):
        self.spojeni.aktivuj(int(term["internalId"]), term["desktops"][0] if term.get("desktops") else None)


class X11Umistovac:
    """Volá ho Perches.tick: stav cizích oken obnoví nejvýš po X11_OBNOVA_S, rozmístění spočítá
    každý snímek (je levné) a hlášení mezí a stran bublin předá PerchZpravy přímo, bez D-Bus."""

    def __init__(self, spojeni, zpravy=None):
        self.spojeni, self.zpravy = spojeni, zpravy
        if zpravy is not None:
            zpravy.mistni = True
        self.roz = rozmisteni.Rozmisteni(hlas=self._hlas)
        self.cizi, self.plocha, self.cas = [], 0, float("-inf")
        self.vsude_ids = set()

    def _hlas(self, co, cislo, hodnota):
        if self.zpravy is not None:
            getattr(self.zpravy, co)(cislo, hodnota)

    def _vsude(self, okno):
        wid = int(okno.winId())
        if wid not in self.vsude_ids:
            self.vsude_ids.add(wid)
            self.spojeni.vsude(wid)

    @staticmethod
    def _qt_model(okno, titulek):
        return {"_qt": okno, "internalId": f"qt{id(okno)}", "resourceClass": "familiar", "caption": titulek,
                "frameGeometry": {"x": okno.x(), "y": okno.y(), "width": okno.width(), "height": okno.height()}}

    def umisti(self, perches, now=None):
        if not perches:
            return
        now = time.monotonic() if now is None else now
        terminaly = {p.term for p in perches if p.term}
        if now - self.cas >= X11_OBNOVA_S:
            self.cas = now
            self.cizi, self.plocha = self.spojeni.okna(bez_pid=os.getpid(), titulky_pro=terminaly)
        nase = []
        for p in perches:
            nase.append(self._qt_model(p, p.windowTitle()))
            if p.bublina is not None and p.obsah is not None:     # bublinu chce mít Perch vidět
                nase.append(self._qt_model(p.bublina, p.bublina.windowTitle()))
        okna = self.cizi + nase
        self.roz.layout(X11Plocha(okna, self.plocha, self.spojeni, self._vsude))


# --- doctor ---

def kontroly(volba="auto"):
    """[(ok, název, podrobnost)] backendu oken pro doctor (ok None = jen varování). Bez Qt."""
    name, proc = zvol(volba)
    out = [(True, "backend oken", f"{name} ({proc})")]
    if name == "x11":
        out += _kontroly_x11()
    elif name == "gnome":
        out += _kontroly_gnome()
    elif name == "zadny":
        out.append((True, "perch", "v tomto prostředí nejde, běží dock; aktivní okno neznámé "
                                   "(upozornění se ukazují i při aktivním terminálu)"))
    return out


def _kontroly_x11():
    from familiar import x11
    if x11.knihovna() is None:
        return [(None, "X11", "libX11 nejde načíst: perch nejde, běží dock (doinstaluj libX11)")]
    s = x11.Spojeni()
    if not s.ok:
        return [(None, "X11", f"display {os.environ.get('DISPLAY') or '(chybí DISPLAY)'} nejde otevřít, běží dock")]
    try:
        wm = s.wm()
        stack = s.podporuje("_NET_CLIENT_LIST_STACKING")
        seznam = stack or s.podporuje("_NET_CLIENT_LIST")
        akt = s.podporuje("_NET_ACTIVE_WINDOW")
    finally:
        s.zavri()
    navod = ("ověř `xprop -root _NET_SUPPORTED`" if shutil.which("xprop")
             else "pro ověření doinstaluj xprop (balík xprop / x11-utils) a spusť `xprop -root _NET_SUPPORTED`")
    if not wm or not seznam:
        return [(None, "správce oken (EWMH)", f"{wm or 'nenalezen'} bez seznamu oken (_NET_CLIENT_LIST): "
                                              f"perch nejde, běží dock; {navod}")]
    out = [(True, "správce oken (EWMH)", f"{wm}, vrstvení oken {'ano' if stack else 'ne (zakrytí neurčí přesně)'}")]
    out.append((True if akt else None, "aktivní okno a přepnutí do terminálu",
                "_NET_ACTIVE_WINDOW" if akt else f"správce nepodporuje _NET_ACTIVE_WINDOW, aktivita neznámá; {navod}"))
    return out


def _kontroly_gnome():
    from familiar import install
    reply = install.dbus(gnome.SLUZBA, gnome.CESTA, gnome.ROZHRANI + ".Verze")
    if reply is not None:
        return [(True, "rozšíření GNOME Shellu", f"{gnome.UUID} běží ({reply})")]
    if gnome.nainstalovano():
        how = (f"zapni ho: gnome-extensions enable {gnome.UUID}" if shutil.which("gnome-extensions")
               else "zapni ho v aplikaci Rozšíření")
        return [(None, "rozšíření GNOME Shellu", f"nainstalováno, ale neběží: {how}; nově nainstalované "
                                                 "uvidí GNOME na Waylandu až po odhlášení a přihlášení")]
    return [(None, "rozšíření GNOME Shellu", "není: běží dock, aktivní okno neznámé; perch a přepínání "
                                             "do terminálu přidá `familiar install --gnome-rozsireni`")]

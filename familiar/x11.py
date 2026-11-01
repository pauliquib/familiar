# Okna X11 přes libX11 (ctypes, bez nových závislostí): seznam a vrstvení oken podle EWMH,
# jejich poloha, stav a pid, aktivní okno, aktivace a „na všech plochách“.
#
# Proč ne xprop/wmctrl/xdotool: perch potřebuje stav všech oken několikrát za sekundu a proces
# na každý dotaz by stál víc než celé rozmístění; libX11 je v každé X11 session (Qt na xcb
# ho má taky). Spojení je vlastní (Qt má své přes xcb), id oken jsou na serveru společná.
# Chyby X (okno mezitím zaniklo) zachytí vlastní handler, výchozí by ukončil proces.
#
# Model okna = slovník s klíči oken KWinu (familiar/rozmisteni.py). Souřadnice X jsou fyzické
# pixely; Spojeni(meritko=k) je vydělí poměrem Qt (devicePixelRatio), aby seděly s okny Qt.
import ctypes, ctypes.util, os

from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_uint, c_ulong, c_void_p

VSUDE = 0xFFFFFFFF          # _NET_WM_DESKTOP: okno na všech plochách
CLIENT_MESSAGE = 33
MASKA_WM = (1 << 19) | (1 << 20)    # SubstructureNotifyMask | SubstructureRedirectMask
ZDROJ_PAGER = 2             # zdroj požadavku v EWMH zprávách: pager/nástroj (WM ho nebrzdí focus stealing)
TYPY = ("NORMAL", "DIALOG", "DOCK", "DESKTOP", "TOOLBAR", "MENU", "UTILITY", "SPLASH", "NOTIFICATION",
        "DROPDOWN_MENU", "POPUP_MENU", "TOOLTIP", "COMBO", "DND")


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", c_ulong), ("message_type", c_ulong), ("format", c_int), ("data", c_long * 5)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xclient", XClientMessageEvent), ("pad", c_long * 24)]


_lib = None
_ERROR_HANDLER = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
_handler = None


def knihovna():
    """libX11 s typy funkcí, nebo None (není nainstalovaná)."""
    global _lib, _handler
    if _lib is not None:
        return _lib or None
    lib = None
    for name in ("libX11.so.6", ctypes.util.find_library("X11")):
        if name:
            try:
                lib = ctypes.CDLL(name)
                break
            except OSError:
                pass
    if lib is None:
        _lib = False
        return None
    D, W = c_void_p, c_ulong
    sig = {
        "XOpenDisplay": (D, [c_char_p]), "XCloseDisplay": (c_int, [D]),
        "XDefaultRootWindow": (W, [D]), "XInternAtom": (c_ulong, [D, c_char_p, c_int]),
        "XGetWindowProperty": (c_int, [D, W, c_ulong, c_long, c_long, c_int, c_ulong, POINTER(c_ulong),
                                       POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p)]),
        "XChangeProperty": (c_int, [D, W, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int]),
        "XFree": (c_int, [c_void_p]),
        "XGetGeometry": (c_int, [D, W, POINTER(W), POINTER(c_int), POINTER(c_int), POINTER(c_uint),
                                 POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]),
        "XTranslateCoordinates": (c_int, [D, W, W, c_int, c_int, POINTER(c_int), POINTER(c_int), POINTER(W)]),
        "XSendEvent": (c_int, [D, W, c_int, c_long, POINTER(XEvent)]),
        "XMapRaised": (c_int, [D, W]), "XSetInputFocus": (c_int, [D, W, c_int, c_ulong]),
        "XFlush": (c_int, [D]), "XSync": (c_int, [D, c_int]),
        "XSetErrorHandler": (c_void_p, [_ERROR_HANDLER]),
    }
    for name, (res, args) in sig.items():
        f = getattr(lib, name)
        f.restype, f.argtypes = res, args
    _handler = _ERROR_HANDLER(lambda d, e: 0)      # BadWindow apod.: ignorovat (výchozí handler ukončí proces)
    lib.XSetErrorHandler(_handler)
    _lib = lib
    return lib


class Spojeni:
    """Spojení s X serverem (display None = $DISPLAY). Bez libX11 nebo serveru ok == False."""

    def __init__(self, display=None, meritko=1.0):
        self.x = knihovna()
        self.dpy = None
        self.meritko = meritko or 1.0
        self._atomy, self._staticke = {}, {}
        name = display if display is not None else os.environ.get("DISPLAY")
        if self.x is not None and name:
            self.dpy = self.x.XOpenDisplay(name.encode())
        self.root = self.x.XDefaultRootWindow(self.dpy) if self.dpy else 0

    @property
    def ok(self):
        return bool(self.dpy)

    def zavri(self):
        if self.dpy:
            self.x.XCloseDisplay(self.dpy)
            self.dpy = None

    def atom(self, name):
        a = self._atomy.get(name)
        if a is None:
            a = self._atomy[name] = self.x.XInternAtom(self.dpy, name.encode(), 0)
        return a

    def vlastnost(self, win, name, typ=0):
        """Hodnota vlastnosti okna: formát 32 → [int], 8 → bytes; None, když není."""
        if not self.dpy or not win:
            return None
        t, f, n, zbyva, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
        r = self.x.XGetWindowProperty(self.dpy, win, self.atom(name), 0, 1 << 16, 0, typ, byref(t), byref(f),
                                      byref(n), byref(zbyva), byref(data))
        if r != 0 or not t.value:
            if data.value:
                self.x.XFree(data)
            return None
        try:
            if f.value == 32:      # Xlib vrací 32bitové hodnoty jako pole long
                arr = ctypes.cast(data, POINTER(c_ulong))
                return [arr[i] & 0xFFFFFFFF for i in range(n.value)]
            if f.value == 16:
                arr = ctypes.cast(data, POINTER(ctypes.c_ushort))
                return [arr[i] for i in range(n.value)]
            return ctypes.string_at(data, n.value)
        finally:
            self.x.XFree(data)

    def nastav(self, win, name, typ, hodnoty):
        """Zapíše vlastnost: seznam čísel (formát 32) nebo bytes (formát 8). Pro testy a WM."""
        if isinstance(hodnoty, bytes):
            buf, fmt, n = ctypes.create_string_buffer(hodnoty, len(hodnoty)), 8, len(hodnoty)
        else:
            buf, fmt, n = (c_long * len(hodnoty))(*hodnoty), 32, len(hodnoty)
        self.x.XChangeProperty(self.dpy, win, self.atom(name), self.atom(typ), fmt, 0, buf, n)
        self.x.XFlush(self.dpy)

    def _prvni(self, win, name):
        v = self.vlastnost(win, name)
        return v[0] if v else None

    def text(self, win):
        """Titulek okna (_NET_WM_NAME, jinak WM_NAME)."""
        v = self.vlastnost(win, "_NET_WM_NAME")
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        v = self.vlastnost(win, "WM_NAME")
        return v.decode("latin-1") if isinstance(v, bytes) else ""

    # --- správce oken ---

    def wm(self):
        """Jméno správce oken s EWMH (_NET_SUPPORTING_WM_CHECK), nebo None."""
        check = self._prvni(self.root, "_NET_SUPPORTING_WM_CHECK")
        if not check:
            return None
        return self.text(check) or "neznámý"

    def podporuje(self, name):
        return self.atom(name) in (self.vlastnost(self.root, "_NET_SUPPORTED") or ())

    def plocha(self):
        return self._prvni(self.root, "_NET_CURRENT_DESKTOP") or 0

    def klienti(self):
        """Okna aplikací zdola nahoru (_NET_CLIENT_LIST_STACKING, jinak _NET_CLIENT_LIST)."""
        v = self.vlastnost(self.root, "_NET_CLIENT_LIST_STACKING")
        if v is None:
            v = self.vlastnost(self.root, "_NET_CLIENT_LIST")
        return v or []

    # --- okna ---

    def pid(self, win):
        return self._prvni(win, "_NET_WM_PID")

    def _typ(self, win):
        for a in self.vlastnost(win, "_NET_WM_WINDOW_TYPE") or ():
            for t in TYPY:
                if a == self.atom("_NET_WM_WINDOW_TYPE_" + t):
                    return t
        return "NORMAL"     # bez typu = normální okno (EWMH)

    def geometrie(self, win):
        """(x, y, š, v) okna aplikace v souřadnicích kořene, bez neviditelných okrajů CSD."""
        root, x, y, w, h, b, d = c_ulong(), c_int(), c_int(), c_uint(), c_uint(), c_uint(), c_uint()
        if not self.x.XGetGeometry(self.dpy, win, byref(root), byref(x), byref(y), byref(w), byref(h),
                                   byref(b), byref(d)):
            return None
        ax, ay, child = c_int(), c_int(), c_ulong()
        if not self.x.XTranslateCoordinates(self.dpy, win, self.root, 0, 0, byref(ax), byref(ay), byref(child)):
            return None
        g = [ax.value, ay.value, w.value, h.value]
        gtk = self._staticky(win, "_GTK_FRAME_EXTENTS")       # stíny okna s CSD (GTK)
        if gtk and len(gtk) == 4:
            l, r, t, bt = gtk
            g = [g[0] + l, g[1] + t, g[2] - l - r, g[3] - t - bt]
        return g

    def _staticky(self, win, co):
        """Vlastnosti, které se za života okna nemění (pid, typ, okraje CSD), z cache."""
        key = (win, co)
        if key not in self._staticke:
            self._staticke[key] = self.pid(win) if co == "pid" else self._typ(win) if co == "typ" \
                else self.vlastnost(win, co)
        return self._staticke[key]

    def _rect(self, g):
        k = self.meritko
        return {"x": round(g[0] / k), "y": round(g[1] / k), "width": round(g[2] / k), "height": round(g[3] / k)}

    def model(self, win, s_titulkem=False):
        """Okno jako slovník pro rozmisteni.py (titulek jen na požádání, čte se jen u terminálů)."""
        g = self.geometrie(win)
        if g is None:
            return None
        ext = self.vlastnost(win, "_NET_FRAME_EXTENTS") or [0, 0, 0, 0]
        l, r, t, b = (list(ext) + [0, 0, 0, 0])[:4]
        stav = self.vlastnost(win, "_NET_WM_STATE") or ()
        wm_state = self._prvni(win, "WM_STATE")
        plocha = self._prvni(win, "_NET_WM_DESKTOP")
        typ = self._staticky(win, "typ")
        return {"internalId": str(win), "resourceClass": "", "pid": self._staticky(win, "pid") or 0,
                "caption": self.text(win) if s_titulkem else "",
                "normalWindow": typ == "NORMAL", "dialog": typ == "DIALOG",
                "minimized": self.atom("_NET_WM_STATE_HIDDEN") in stav or wm_state == 3,
                "onAllDesktops": plocha is None or plocha == VSUDE,
                "desktops": [] if plocha is None or plocha == VSUDE else [plocha], "activities": [],
                "clientGeometry": self._rect(g),
                "frameGeometry": self._rect([g[0] - l, g[1] - t, g[2] + l + r, g[3] + t + b])}

    def okna(self, bez_pid=None, titulky_pro=()):
        """(modely oken zdola nahoru, aktuální plocha). bez_pid: vynechat okna tohoto procesu
        (vlastní okna familiara), titulky_pro: pid, u kterých se čte titulek (terminály)."""
        ids = self.klienti()
        zive = set(ids)
        self._staticke = {k: v for k, v in self._staticke.items() if k[0] in zive}
        out = []
        for win in ids:
            pid = self._staticky(win, "pid")
            if bez_pid is not None and pid == bez_pid:
                continue
            m = self.model(win, pid in titulky_pro)
            if m is not None:
                out.append(m)
        return out, self.plocha()

    def okno_pid(self, pid):
        """Nejvyšší normální okno procesu pid, nebo None."""
        for win in reversed(self.klienti()):
            if self.pid(win) == pid and self._typ(win) == "NORMAL":
                return win
        return None

    def aktivni(self):
        return self._prvni(self.root, "_NET_ACTIVE_WINDOW") or None

    def aktivni_pid(self):
        """pid aktivního okna, 0 = žádné nebo bez _NET_WM_PID, None = nejde zjistit."""
        if not self.dpy or not self.podporuje("_NET_ACTIVE_WINDOW"):
            return None
        win = self.aktivni()
        return (self.pid(win) or 0) if win else 0

    # --- požadavky na správce oken ---

    def zprava(self, win, typ, *data):
        """EWMH client message kořenovému oknu (správce oken ji vyřídí)."""
        ev = XEvent()
        ev.xclient.type = CLIENT_MESSAGE
        ev.xclient.send_event = 1
        ev.xclient.window = win
        ev.xclient.message_type = self.atom(typ)
        ev.xclient.format = 32
        for i, v in enumerate(data[:5]):
            ev.xclient.data[i] = v
        self.x.XSendEvent(self.dpy, self.root, 0, MASKA_WM, byref(ev))
        self.x.XFlush(self.dpy)

    def aktivuj(self, win, plocha=None):
        """Přepne na plochu okna (je-li jinde) a aktivuje ho; správce oken ho i odminimalizuje.
        Správce bez _NET_ACTIVE_WINDOW: zvednout a dát fokus přímo."""
        if not self.dpy or not win:
            return False
        if plocha is not None and plocha != VSUDE and plocha != self.plocha():
            self.zprava(self.root, "_NET_CURRENT_DESKTOP", plocha, 0)
        if self.podporuje("_NET_ACTIVE_WINDOW"):
            self.zprava(win, "_NET_ACTIVE_WINDOW", ZDROJ_PAGER, 0, 0)
        else:
            self.x.XMapRaised(self.dpy, win)
            self.x.XSetInputFocus(self.dpy, win, 2, 0)      # RevertToParent, CurrentTime
            self.x.XFlush(self.dpy)
        return True

    def vsude(self, win):
        """Okno na všech plochách (postavička jde s terminálem i při přepnutí plochy)."""
        if self.dpy and win:
            self.zprava(win, "_NET_WM_DESKTOP", VSUDE, ZDROJ_PAGER)

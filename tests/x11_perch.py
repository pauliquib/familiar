# Perch na X11 v izolovaném Xvfb (spouští tests/test_okna.py s DISPLAY na vlastní Xvfb).
# Falešný správce oken: vlastnosti EWMH na kořeni (seznam a vrstvení oken, plochy, aktivní okno)
# a vyřizování zpráv _NET_ACTIVE_WINDOW / _NET_CURRENT_DESKTOP / _NET_WM_DESKTOP. Okna nespravuje
# (bez rámečků), takže okna Qt se posouvají přímo. Výsledek vypíše jako JSON na poslední řádek.
import ctypes, json, os, sys, time

from ctypes import byref, c_int, c_long, c_uint, c_ulong, c_void_p

assert os.environ.get("QT_QPA_PLATFORM") == "xcb" and os.environ["DISPLAY"] != ":0"

from PySide6.QtWidgets import QApplication

from familiar import config, dock, okna, sluzby, x11
from familiar.hub import Hub

lib = x11.knihovna()
lib.XCreateSimpleWindow.restype = c_ulong
lib.XCreateSimpleWindow.argtypes = [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]
lib.XMapWindow.argtypes = [c_void_p, c_ulong]
lib.XSelectInput.argtypes = [c_void_p, c_ulong, c_long]
lib.XPending.argtypes = [c_void_p]
lib.XNextEvent.argtypes = [c_void_p, ctypes.POINTER(x11.XEvent)]


class FalesnyWM:
    def __init__(self):
        self.s = x11.Spojeni()
        s = self.s
        self.check = self.okno(0, 0, 1, 1, mapovat=False)
        for w in (s.root, self.check):
            s.nastav(w, "_NET_SUPPORTING_WM_CHECK", "WINDOW", [self.check])
        s.nastav(self.check, "_NET_WM_NAME", "UTF8_STRING", "falešný-wm".encode())
        s.nastav(s.root, "_NET_SUPPORTED", "ATOM", [s.atom(a) for a in (
            "_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING", "_NET_ACTIVE_WINDOW", "_NET_WM_DESKTOP",
            "_NET_CURRENT_DESKTOP", "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN", "_NET_FRAME_EXTENTS")])
        s.nastav(s.root, "_NET_NUMBER_OF_DESKTOPS", "CARDINAL", [2])
        s.nastav(s.root, "_NET_CURRENT_DESKTOP", "CARDINAL", [0])
        lib.XSelectInput(s.dpy, s.root, 1 << 19)     # SubstructureNotify: dostane i zprávy pro správce
        self.zpravy = []

    def okno(self, x, y, w, h, pid=None, nazev=None, plocha=0, mapovat=True):
        s = self.s
        win = lib.XCreateSimpleWindow(s.dpy, s.root, x, y, w, h, 0, 0, 0)
        if pid is not None:
            s.nastav(win, "_NET_WM_PID", "CARDINAL", [pid])
            s.nastav(win, "_NET_WM_DESKTOP", "CARDINAL", [plocha])
        if nazev:
            s.nastav(win, "_NET_WM_NAME", "UTF8_STRING", nazev.encode())
        if mapovat:
            lib.XMapWindow(s.dpy, win)
        lib.XSync(s.dpy, 0)
        return win

    def vrstveni(self, okna_):
        self.s.nastav(self.s.root, "_NET_CLIENT_LIST_STACKING", "WINDOW", okna_)
        self.s.nastav(self.s.root, "_NET_CLIENT_LIST", "WINDOW", okna_)

    def obsluz(self):
        s, ev = self.s, x11.XEvent()
        lib.XSync(s.dpy, 0)
        while lib.XPending(s.dpy):
            lib.XNextEvent(s.dpy, byref(ev))
            if ev.type != x11.CLIENT_MESSAGE:
                continue
            c = ev.xclient
            data = [c.data[i] & 0xFFFFFFFF for i in range(5)]
            jmeno = next((n for n, a in s._atomy.items() if a == c.message_type), str(c.message_type))
            self.zpravy.append((jmeno, c.window, data))
            if jmeno == "_NET_ACTIVE_WINDOW":
                s.nastav(s.root, "_NET_ACTIVE_WINDOW", "WINDOW", [c.window])
            elif jmeno == "_NET_CURRENT_DESKTOP":
                s.nastav(s.root, "_NET_CURRENT_DESKTOP", "CARDINAL", [data[0]])
            elif jmeno == "_NET_WM_DESKTOP":
                s.nastav(c.window, "_NET_WM_DESKTOP", "CARDINAL", [data[0]])


def main():
    app = QApplication([])
    wm = FalesnyWM()
    s = wm.s
    for name in ("_NET_ACTIVE_WINDOW", "_NET_CURRENT_DESKTOP", "_NET_WM_DESKTOP"):
        s.atom(name)
    pod = [wm.okno(20 * i, 10 * i, 300, 200, pid=1000 + i, nazev=f"okno {i}") for i in range(38)]
    term = wm.okno(100, 200, 800, 600, pid=4242, nazev="kitty")
    wm.vrstveni(pod + [term])
    out = {"terminal": term}

    cfg = config.defaults()
    cfg["rezim"] = "auto"
    hub = Hub(reap=False, bind=False, cfg=cfg, transcripts=False)
    hub.receive({"v": 1, "source": "claude-code", "pid": 7, "ts": time.time(),
                 "raw": {"hook_event_name": "SessionStart", "session_id": "s", "cwd": "/home/x/p"}})
    hub.fams[7].term = 4242
    b = okna.backend()
    out["backend"], out["umi"] = b.jmeno, b.perch_umi()
    views = dock.Views(hub, None, config.Config(cfg, None))
    out["rezim"] = views.mode
    perches = views.view
    perches.timer.stop()

    def kolo(obnovit=True):
        if obnovit:
            b.umistovac.cas = float("-inf")     # stav oken hned znovu (jinak nejvýš po 0,25 s)
        perches.tick()
        for _ in range(3):
            app.processEvents()
            wm.obsluz()
            time.sleep(0.02)
        return perches.windows[7]

    w = kolo()
    kolo()
    out["na_titulku"] = [w.x(), w.y()]
    lib.XSync(s.dpy, 0)
    ax, ay, child = c_int(), c_int(), c_ulong()
    lib.XTranslateCoordinates(s.dpy, int(w.winId()), s.root, 0, 0, byref(ax), byref(ay), byref(child))
    out["x_server"] = [ax.value, ay.value]
    out["meze"] = views.zpravy.meze_px.get(str(w.cislo))
    out["vsude"] = any(z[0] == "_NET_WM_DESKTOP" and z[1] == int(w.winId()) and z[2][0] == x11.VSUDE
                       for z in wm.zpravy)

    s.nastav(term, "_NET_WM_STATE", "ATOM", [s.atom("_NET_WM_STATE_HIDDEN")])
    out["minimalizovany"] = kolo().isVisible()
    s.nastav(term, "_NET_WM_STATE", "ATOM", [])
    s.nastav(term, "_NET_WM_DESKTOP", "CARDINAL", [1])
    out["jina_plocha"] = kolo().isVisible()
    s.nastav(term, "_NET_WM_DESKTOP", "CARDINAL", [0])
    out["zpet"] = kolo().isVisible() and [w.x(), w.y()] == out["na_titulku"]

    views.oznam(7, "ahoj", 0.5)                   # bublina vedle postavičky (vlevo, spodky zarovnané)
    kolo()
    kolo()
    bub = w.bublina
    out["bublina"] = bub.isVisible() and [bub.x(), bub.y()] == [712 - bub.width(), 138 + 64 - bub.height()]
    out["strana"] = views.zpravy.strany.get(str(w.cislo))
    time.sleep(0.6)
    kolo()
    out["bublina_pryc"] = not bub.isVisible()

    s.nastav(term, "_NET_FRAME_EXTENTS", "CARDINAL", [2, 3, 30, 4])     # rámeček správce oken
    m = s.model(term)
    out["ramecek"] = [m["frameGeometry"][k] for k in ("x", "y", "width", "height")]
    s.nastav(term, "_GTK_FRAME_EXTENTS", "CARDINAL", [10, 10, 10, 10])    # stíny CSD
    s._staticke.clear()
    out["csd"] = [s.model(term)["clientGeometry"][k] for k in ("x", "y", "width", "height")]

    kryt = wm.okno(0, 0, 1920, 1080, pid=5000, nazev="přes celou obrazovku")
    wm.vrstveni(pod + [term, kryt])
    out["zakryty"] = kolo().isVisible()
    wm.vrstveni(pod + [term])
    kolo()

    s.nastav(term, "_NET_WM_DESKTOP", "CARDINAL", [1])      # klik na postavičku: terminál na ploše 1
    kolo()
    w._prepni()
    kolo(obnovit=False)
    out["klik"] = [s.aktivni(), s.plocha()]

    o = sluzby.AktivniOkno(backend=b)
    o.spust()
    out["aktivni_pid"] = o.pid
    o.zastav()
    s.nastav(s.root, "_NET_ACTIVE_WINDOW", "WINDOW", [0])
    out["prepnuti"] = bool(b.prepnout(4242))
    wm.obsluz()
    out["prepnuti"] = out["prepnuti"] and s.aktivni() == term

    t = time.perf_counter()
    for _ in range(10):
        b.umistovac.spojeni.okna(bez_pid=os.getpid(), titulky_pro={4242})
    out["obnova_ms"] = (time.perf_counter() - t) * 100
    views.view.close()
    views.quit()
    print(json.dumps(out))


if __name__ == "__main__":
    sys.exit(main())

# Pomocník pro test_upozorneni: běží pod `dbus-run-session` (dočasná session sběrnice).
#
#   python3 tests/upozorneni_dbus.py klient [anotace|bez]   → JSON s voláními serveru a výsledky
#   python3 tests/upozorneni_dbus.py server [anotace|bez] LOG
#   python3 tests/upozorneni_dbus.py sluzby [anotace|bez]  → jako klient, ale přes hub a sluzby.Sluzby
#
# Server je falešný org.freedesktop.Notifications v Gio (PyGObject): každé volání zapíše
# do LOG (typ a hodnoty jako text GVariant), u notifikace s titulkem „akce“ pošle
# ActionInvoked(id, "terminal"), na CloseNotification odpoví NotificationClosed.
# „anotace“ = introspekce jako v Plasmě (QtTypeName QVariantMap u hints), „bez“ = jako GNOME.
import json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def server(anotace, log):
    from gi.repository import Gio, GLib
    ann = '<annotation name="org.qtproject.QtDBus.QtTypeName.In6" value="QVariantMap"/>' if anotace else ""
    xml = f"""<node><interface name="org.freedesktop.Notifications">
<method name="Notify">{ann}<arg type="s" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="as" direction="in"/><arg type="a{{sv}}" direction="in"/><arg type="i" direction="in"/>
<arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>"""
    iface = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
    n = [0]
    out = open(log, "a", buffering=1)

    def emit(conn, name, sig, args):
        conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                         name, GLib.Variant(sig, args))
        return False

    def call(conn, sender, path, ifname, method, params, inv):
        out.write(json.dumps({"metoda": method, "typ": params.get_type_string(), "hodnoty": params.print_(True)}) + "\n")
        if method == "Notify":
            n[0] += 1
            nid = params[1] or 100 + n[0]
            inv.return_value(GLib.Variant("(u)", (nid,)))
            if params[3] == "akce":
                GLib.timeout_add(50, emit, conn, "ActionInvoked", "(us)", (nid, "terminal"))
        else:
            inv.return_value(None)
            GLib.idle_add(emit, conn, "NotificationClosed", "(uu)", (params[0], 3))

    def acquired(conn, name):
        conn.register_object("/org/freedesktop/Notifications", iface, call, None, None)
        out.write(json.dumps({"metoda": "ready"}) + "\n")

    Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications", 0, None, acquired, None)
    GLib.timeout_add(15000, lambda: sys.exit(0))
    GLib.MainLoop().run()


def _cekej(app, s):
    konec = time.monotonic() + s
    while time.monotonic() < konec:
        app.processEvents()
        time.sleep(0.01)


def _spust_server(anotace):
    log = tempfile.mktemp(prefix="notif-", suffix=".log")
    py = os.environ.get("FAMILIAR_FAKE_PY") or sys.executable
    srv = subprocess.Popen([py, os.path.abspath(__file__), "server", "anotace" if anotace else "bez", log],
                           stderr=subprocess.DEVNULL)
    for _ in range(300):
        if os.path.exists(log) and "ready" in open(log).read():
            break
        time.sleep(0.01)
    return srv, log


def sluzby_klient(anotace):
    """Hub → Sluzby → Upozorneni → falešný server: dokončené kolo, úspěch, klik, ukončení."""
    sys.path.insert(0, ROOT)
    os.environ["XDG_CURRENT_DESKTOP"] = "KDE"       # backend oken kwin (přepnutí KWin skriptem)
    from PySide6.QtWidgets import QApplication
    from familiar import config, hub, kwin, sluzby

    srv, log = _spust_server(anotace)
    try:
        app = QApplication.instance() or QApplication([])

        class Ticho:
            def prehraj(self, cesta, hlasitost):
                return False

        class Okno:
            pid = None

            def zastav(self):
                pass

        prepnuto = []
        kwin.nahraj_text = lambda text, name: prepnuto.append(text) or True
        kwin.odeber = lambda name: None
        cfg = config.defaults()
        cfg["upozorneni"].update(zvuky=False, cekani_po_s=0.0)
        h = hub.Hub(reap=False, bind=False, cfg=cfg, transcripts=False)
        from familiar import upozorneni
        u = upozorneni.Upozorneni(cfg, prehravac=Ticho())
        s = sluzby.Sluzby(h, cfg, upozorneni=u, okno=Okno(), ikona=False)
        piny = []
        u.prepnout.connect(piny.append)
        t = time.time()

        def m(ts, hook, **raw):
            return {"v": 1, "source": "claude-code", "pid": 7, "ts": ts,
                    "raw": {"hook_event_name": hook, "session_id": "s", "cwd": "/home/x/akce", **raw}}
        h.receive(m(t, "SessionStart"))
        h.fams[7].term = 4321           # okno terminálu (bez bind)
        h.receive(m(t + 1, "UserPromptSubmit", prompt="TAJNY-PROMPT-5c1e"))
        h.receive(m(t + 70, "Stop"))
        _cekej(app, 0.4)
        h.receive(m(t + 71, "PermissionRequest", tool_name="Bash"))
        _cekej(app, 0.2)
        s.ukonci()
        _cekej(app, 0.3)
        print(json.dumps({"prepnuto": piny, "kwin": sum("=== 4321 &&" in x for x in prepnuto),
                          "volani": [json.loads(x) for x in open(log) if "ready" not in x]}))
    finally:
        srv.terminate()
        srv.wait()
        if os.path.exists(log):
            os.unlink(log)


def klient(anotace):
    sys.path.insert(0, ROOT)
    from PySide6.QtCore import QCoreApplication
    from familiar import upozorneni

    srv, log = _spust_server(anotace)
    try:
        app = QCoreApplication.instance() or QCoreApplication([])

        class Ticho:
            def prehraj(self, cesta, hlasitost):
                return False

        cfg = {"upozorneni": {"cekani_po_s": 0, "kolo_nad_s": 0, "zvuky": False, "nalehave_kriticke": True}}
        u = upozorneni.Upozorneni(cfg, prehravac=Ticho())
        prepnuto = []
        u.prepnout.connect(prepnuto.append)
        r1 = u.udalost("s1", upozorneni.POVOLENI, {"jmeno": "akce", "pid": 4242, "nastroj": "Bash"})
        id1 = u.ids.get("s1")
        _cekej(app, 0.3)
        r2 = u.udalost("s1", upozorneni.DOKONCENO, {"jmeno": "projekt 'x' <b>", "pid": 4242, "trvani_s": 75})
        id2 = u.ids.get("s1")
        u.zrus("s1")
        _cekej(app, 0.3)
        print(json.dumps({"vysledky": [r1, r2], "ids": [id1, id2], "prepnuto": prepnuto,
                          "typovane": u.dbus.typovane, "zbyva": u.notif,
                          "volani": [json.loads(x) for x in open(log) if "ready" not in x]}))
    finally:
        srv.terminate()
        srv.wait()
        if os.path.exists(log):
            os.unlink(log)


if __name__ == "__main__":
    if sys.argv[1] == "server":
        server(sys.argv[2] == "anotace", sys.argv[3])
    elif sys.argv[1] == "sluzby":
        sluzby_klient(sys.argv[2] == "anotace")
    else:
        klient(sys.argv[2] == "anotace")

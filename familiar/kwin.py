# Nahrání a odebrání KWin skriptů přes D-Bus (jen KDE Plasma 6).
#
#   perch.js          posadí okna postaviček na titulky terminálů (load/unload); s perch_dbus
#                     před něj vloží `var DBUS = {…}` a skript pak daemonu hlásí meze procházek
#                     a přehozené bubliny (dock.PerchZpravy)
#   familiar-aktivni  hlásí daemonu pid aktivního okna přes callDBus (sluzby.AktivniOkno)
#   familiar-prepnout jednorázově aktivuje okno terminálu podle pid (klik na notifikaci)
# Skripty s parametry (jméno služby, pid) se generují do $XDG_RUNTIME_DIR.
import json, os

from PySide6.QtDBus import QDBusConnection, QDBusInterface

from familiar import paths

NAME = "familiar-perch"
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perch.js")
AKTIVNI = "familiar-aktivni"
PREPNOUT = "familiar-prepnout"

AKTIVNI_JS = """// familiar: pid aktivního okna → daemon (callDBus), při každé změně a hned po startu
function hlas(w) {
    callDBus(%(sluzba)s, %(cesta)s, %(rozhrani)s, "aktivni", w ? w.pid : 0);
}
workspace.windowActivated.connect(hlas);
hlas(workspace.activeWindow);
"""

PREPNOUT_JS = """// familiar: aktivuje okno terminálu s daným pid (jednorázově, pak se skript odebere)
function naPlose(w) {
    if (w.onAllDesktops) return true;
    for (var i = 0; i < w.desktops.length; i++)
        if (w.desktops[i] === workspace.currentDesktop) return true;
    return false;
}
function aktivuj(w) {       // jako klik na postavičku v perch.js
    if (w.minimized) w.minimized = false;
    if (!naPlose(w) && w.desktops.length) workspace.currentDesktop = w.desktops[0];
    workspace.activeWindow = w;
}
(function () {
    var ws = workspace.windowList();
    for (var i = 0; i < ws.length; i++)
        if (ws[i].pid === %(pid)d && ws[i].normalWindow) { aktivuj(ws[i]); return; }
})();
"""


def _scripting():
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    return iface if iface.isValid() else None


def nahraj(path, name):
    """Nahraje a spustí skript ze souboru pod jménem; vrací True, když KWin skript přijal."""
    s = _scripting()
    if s is None:
        return False
    s.call("unloadScript", name)        # zbytek po předchozím běhu
    reply = s.call("loadScript", path, name)
    args = reply.arguments()
    if not args or not isinstance(args[0], int) or args[0] < 0:
        return False
    script = QDBusInterface("org.kde.KWin", f"/Scripting/Script{args[0]}", "org.kde.kwin.Script",
                            QDBusConnection.sessionBus())
    script.call("run")
    return True


def odeber(name):
    s = _scripting()
    if s is not None:
        s.call("unloadScript", name)


def nahraj_text(text, name):
    """Skript z textu: zapíše ho do $XDG_RUNTIME_DIR/<jméno>.js (0600) a nahraje."""
    if _scripting() is None:
        return False
    path = os.path.join(paths.runtime_dir(), name + ".js")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        return False
    return nahraj(path, name)


perch_dbus = None   # {"sluzba", "cesta", "rozhrani"} pro zprávy z perch.js (nastaví dock.Views)


def load():
    """Nahraje a spustí perch.js; vrací True, když KWin skript přijal."""
    if perch_dbus:
        try:
            with open(SCRIPT, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return False
        return nahraj_text(f"var DBUS = {json.dumps(perch_dbus)};\n" + text, NAME)
    return nahraj(SCRIPT, NAME)


def unload():
    odeber(NAME)


def js_aktivni(sluzba, cesta, rozhrani):
    q = json.dumps
    return AKTIVNI_JS % {"sluzba": q(sluzba), "cesta": q(cesta), "rozhrani": q(rozhrani)}


def js_prepnout(pid):
    return PREPNOUT_JS % {"pid": int(pid)}

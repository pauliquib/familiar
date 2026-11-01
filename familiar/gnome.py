# GNOME Shell (Wayland): rozšíření familiara (extras/gnome-shell/, v balíčku familiar/gnome_shell/)
# a jeho ovládání přes D-Bus. Bez rozšíření cizí okna na GNOME Waylandu číst ani posouvat nejde:
# familiar pak běží v docku a aktivní okno nezná.
#
# Rozšíření exportuje na sběrnici GNOME Shellu objekt /cz/familiar/Gnome (cz.familiar.Gnome):
#   Verze() → s                       běží a jakou má verzi (doctor, volba backendu)
#   Perch(sluzba, cesta, rozhrani)    spustí perch.js nad okny Mutteru; zprávy (meze, strana)
#   PerchStop()                       posílá daemonu jako KWin skript (dock.PerchZpravy)
#   Aktivni(sluzba, cesta, rozhrani)  hlásí pid aktivního okna (sluzby.AktivniOkno.aktivni)
#   AktivniStop()
#   Aktivuj(pid) → b                  aktivuje okno terminálu (klik na notifikaci)
# Když jméno daemonu (sluzba) ze sběrnice zmizí, rozšíření perch i hlášení samo zastaví.
# perch.js je v rozšíření zabalený do modulu (perch_modul) při instalaci, logika je jedna.
import os

from familiar import paths

UUID = "familiar@pixel-familiars"
SLUZBA, CESTA, ROZHRANI = "org.gnome.Shell", "/cz/familiar/Gnome", "cz.familiar.Gnome"
SOUBORY = ("metadata.json", "extension.js", "okna.js")
TIMEOUT_MS = 1000
PERCH_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perch.js")


def zdroj():
    """Adresář se zdrojem rozšíření: v nainstalovaném balíčku, jinak v repozitáři."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "gnome_shell"), os.path.join(os.path.dirname(here), "extras", "gnome-shell")):
        if os.path.exists(os.path.join(d, "metadata.json")):
            return d
    return None


def cil():
    """~/.local/share/gnome-shell/extensions/<uuid>/"""
    return os.path.join(paths.data_home(), "gnome-shell", "extensions", UUID)


def perch_modul(text=None):
    """perch.js jako ES modul pro rozšíření: celý skript v těle funkce spust(workspace, …),
    globální objekty KWinu dostane jako parametry (převlek z okna.js)."""
    if text is None:
        with open(PERCH_JS, encoding="utf-8") as f:
            text = f.read()
    return ("// Vygenerováno z familiar/perch.js (familiar install --gnome-rozsireni), neupravovat.\n"
            "export function spust(workspace, KWin, QTimer, callDBus, DBUS) {\n"
            f"{text}\nreturn {{layout: layout}};\n}}\n")


def soubory():
    """{jméno: text} souborů rozšíření k zápisu; None, když zdroj chybí."""
    d = zdroj()
    if d is None:
        return None
    out = {}
    for name in SOUBORY:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            out[name] = f.read()
    out["perch.js"] = perch_modul()
    return out


def nainstalovano():
    return os.path.exists(os.path.join(cil(), "metadata.json"))


# --- D-Bus (QtDBus, jen v daemonu) ---

def _volej(metoda, *args):
    """Volání metody rozšíření; → seznam návratových hodnot, nebo None (rozšíření neběží)."""
    from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    msg = QDBusMessage.createMethodCall(SLUZBA, CESTA, ROZHRANI, metoda)
    if args:
        msg.setArguments(list(args))
    reply = bus.call(msg, QDBus.Block, TIMEOUT_MS)
    return reply.arguments() if reply.type() == QDBusMessage.ReplyMessage else None


def verze():
    r = _volej("Verze")
    return str(r[0]) if r else None


def perch(sluzba, cesta="", rozhrani=""):
    r = _volej("Perch", sluzba, cesta, rozhrani)
    return bool(r and r[0])


def perch_stop():
    _volej("PerchStop")


def aktivni(sluzba, cesta, rozhrani):
    r = _volej("Aktivni", sluzba, cesta, rozhrani)
    return bool(r and r[0])


def aktivni_stop():
    _volej("AktivniStop")


def aktivuj(pid):
    r = _volej("Aktivuj", int(pid))
    return bool(r and r[0])

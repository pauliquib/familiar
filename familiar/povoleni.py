# Server povolení v daemonu: stream socket pro klienta hooku PermissionRequest
# (familiar/povoleni_klient.py, protokol v docs/povoleni.md).
#
# Každé spojení = jeden požadavek: klient pošle řádek JSON se shrnutím, server vydá
# signál pozadavek a čeká, až UI zavolá odpovez() (klik v bublině). Rozhodnutí vzniká
# jen tam; server sám nikdy nic nepovolí. Odpojení klienta (uživatel odpověděl
# v terminálu, Claude hook zrušil), vlastní timeout nebo zrus()/zrus_pid() požadavek
# zahodí, spojení zavře (klient skončí bez výstupu) a vydá signál zruseno.
# Shrnutí (začátek příkazu, cesta) se nikam nezapisuje, ani do logu.
# Běží v Qt smyčce (QLocalServer), GUI neblokuje. start() volat až s drženým zámkem
# daemonu (dock.listen), jinak by druhý daemon smazal socket prvnímu.
import json, logging, os, socket, struct, unicodedata

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from familiar import paths

SOCK = "familiar-povoleni.sock"     # stejně v povoleni_klient.py
TIMEOUT_S = 300.0       # jak dlouho visí bublina hlavní session
TIMEOUT_AGENT_S = 15.0  # subagent na pozadí / bez terminálu (-p, SDK): Claude čeká, až hook skončí
MAX_POZADAVEK = 16384   # delší řádek = nesmysl, spojení se zavře
CO_MAX = 600            # klient posílá nejvýš 500 znaků (povoleni_klient.CO_ZNAKU)
VZDY_MAX = 320
MAX_CEKAJICICH = 16
ROZHODNUTI = ("allow", "deny", "allow_always")
lg = logging.getLogger("familiar.povoleni")


def sock_path():
    return os.path.join(paths.runtime_dir(), SOCK)


def _peer_uid(fd):
    """uid procesu na druhé straně Unix socketu (SO_PEERCRED), nebo None."""
    try:
        s = socket.socket(fileno=os.dup(fd))
    except OSError:
        return None
    try:
        cred = s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", cred)[1]
    except OSError:
        return None
    finally:
        s.close()


def _skryte(c):
    """Znak, který v bublině není vidět nebo mění pořadí textu (řídicí, formátovací, bidi)."""
    return c != "\n" and unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs", "Cn")


def _co(v):
    """(text, podezřelé): řádky s jednou mezerou, skryté znaky nahrazené „�“."""
    if not isinstance(v, str):
        return "", False
    text = "\n".join(r for r in (" ".join(r.split()) for r in v.split("\n")) if r)
    zkraceno = len(text) > CO_MAX
    text = text[:CO_MAX]
    podezrele = any(_skryte(c) for c in text)
    if podezrele:
        text = "".join("\ufffd" if _skryte(c) else c for c in text)
    return text, podezrele or zkraceno


def shrnuti(data):
    """Očištěné shrnutí z požadavku klienta: jen očekávané klíče, omezené řetězce.
    jen_terminal = bublina smí jen zamítnout (vstup zkrácený, URL s query, skryté znaky)."""
    s = data.get("shrnuti") if isinstance(data.get("shrnuti"), dict) else {}

    def text(v, n):
        return " ".join(v.split())[:n] if isinstance(v, str) else ""
    co, podezrele = _co(s.get("co"))
    vzdy = text(s.get("vzdy"), VZDY_MAX + 1)
    if len(vzdy) > VZDY_MAX or any(_skryte(c) for c in vzdy):
        vzdy = ""       # popis by nebyl celý vidět: „Vždy“ se nenabídne
    return {"nastroj": text(s.get("nastroj"), 60) or "?", "co": co, "vzdy": vzdy or None,
            "jen_terminal": podezrele or s.get("zkraceno") is not False or s.get("dotaz") is not False,
            "agent": data.get("agent") is True, "bez_terminalu": data.get("bez_terminalu") is True}


class Povoleni(QObject):
    """Požadavky na povolení z hooků. Signály:
    pozadavek(id, session, pid, shrnuti) – nový požadavek; shrnuti je dict
        {nastroj, co, vzdy (popis „vždy povolit“ nebo None), jen_terminal (bool: jen Zamítnout),
        agent, bez_terminalu (bool)}
    zruseno(id) – požadavek už neplatí (odpojení, timeout, zrus); bublinu schovat."""

    pozadavek = Signal(int, str, int, object)
    zruseno = Signal(int)

    def __init__(self, parent=None, timeout_s=TIMEOUT_S, timeout_agent_s=TIMEOUT_AGENT_S, path=None):
        super().__init__(parent)
        self.timeout_s, self.timeout_agent_s = timeout_s, timeout_agent_s
        self.path = path or sock_path()
        self.server = None
        self.cekajici = {}      # id → {"sock", "timer", "session", "pid", "shrnuti"}
        self._spojeni = {}      # QLocalSocket → buffer, dokud nepřišel celý požadavek
        self._dalsi = 0

    def start(self):
        """Naslouchá na socketu (0600). False, když to nejde (daemon pak jede bez povolení)."""
        QLocalServer.removeServer(self.path)       # starý socket po pádu
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(self.path):
            lg.error("socket povolení nejde otevřít: %s", self.server.errorString())
            self.server = None
            return False
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.server.newConnection.connect(self._nove)
        return True

    def close(self):
        for i in list(self.cekajici):
            self.zrus(i)
        for sock in list(self._spojeni):
            sock.abort()
        self._spojeni.clear()
        if self.server is not None:
            self.server.close()
            self.server = None

    def configure(self, timeout_s=None, timeout_agent_s=None):
        """Nové timeouty pro další požadavky (config za běhu)."""
        if timeout_s is not None:
            self.timeout_s = timeout_s
        if timeout_agent_s is not None:
            self.timeout_agent_s = timeout_agent_s

    def odpovez(self, id_, rozhodnuti):
        """Odpověď uživatele ("allow" | "deny" | "allow_always") klientovi. False, když požadavek
        už neplatí (pak už ho uživatel odbyl v terminálu) nebo je odpověď neplatná."""
        if rozhodnuti not in ROZHODNUTI:
            return False
        p = self.cekajici.get(id_)
        if p is None or rozhodnuti != "deny" and p["shrnuti"]["jen_terminal"]:
            return False        # povolit jde jen to, co bylo v bublině vidět celé
        del self.cekajici[id_]
        if rozhodnuti == "allow_always" and not p["shrnuti"]["vzdy"]:
            rozhodnuti = "allow"        # klient by stejně neměl co uložit
        p["timer"].stop()
        p["timer"].deleteLater()
        sock = p["sock"]
        sock.disconnected.disconnect()
        ok = sock.state() == QLocalSocket.ConnectedState
        if ok:
            sock.write((json.dumps({"rozhodnuti": rozhodnuti}) + "\n").encode())
            sock.flush()
        sock.disconnectFromServer()     # po odeslání dat
        sock.deleteLater()
        return ok

    def zrus(self, id_):
        """Zahodí požadavek (bez rozhodnutí, klient skončí bez výstupu) a vydá zruseno."""
        p = self.cekajici.pop(id_, None)
        if p is None:
            return False
        p["timer"].stop()
        p["timer"].deleteLater()
        sock = p["sock"]
        sock.disconnected.disconnect()
        sock.abort()
        sock.deleteLater()
        self.zruseno.emit(id_)
        return True

    def zrus_pid(self, pid):
        """Zruší všechny požadavky procesu claude (hub: přišla další událost, uživatel odpověděl
        v terminálu). Vrací počet zrušených."""
        ids = [i for i, p in self.cekajici.items() if p["pid"] == pid]
        for i in ids:
            self.zrus(i)
        return len(ids)

    def zrus_session(self, session):
        ids = [i for i, p in self.cekajici.items() if p["session"] == session]
        for i in ids:
            self.zrus(i)
        return len(ids)

    # --- spojení ---

    def _nove(self):
        while self.server is not None and self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if _peer_uid(sock.socketDescriptor()) != os.getuid() or len(self.cekajici) >= MAX_CEKAJICICH:
                sock.abort()
                sock.deleteLater()
                continue
            self._spojeni[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._cti(s))
            sock.disconnected.connect(lambda s=sock: self._odpojen(s))
            if sock.bytesAvailable():
                self._cti(sock)

    def _odpojen(self, sock):
        """Klient zmizel dřív, než poslal celý požadavek."""
        if self._spojeni.pop(sock, None) is not None:
            sock.deleteLater()

    def _cti(self, sock):
        if sock not in self._spojeni:
            return
        buf = self._spojeni[sock] + bytes(sock.readAll())
        if b"\n" not in buf:
            if len(buf) > MAX_POZADAVEK:
                self._zahod(sock)
            else:
                self._spojeni[sock] = buf
            return
        del self._spojeni[sock]
        sock.readyRead.disconnect()
        sock.disconnected.disconnect()
        try:
            data = json.loads(buf.split(b"\n", 1)[0])
            if not isinstance(data, dict) or data.get("v") != 1:
                raise ValueError("neznámý tvar")
            session = data.get("session") if isinstance(data.get("session"), str) else ""
            pid = data.get("pid") if type(data.get("pid")) is int else 0
        except ValueError as e:
            lg.warning("vadný požadavek na povolení (%s)", type(e).__name__)     # bez obsahu
            sock.abort()
            sock.deleteLater()
            return
        self._dalsi += 1
        id_, info = self._dalsi, shrnuti(data)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.zrus(id_))
        kratce = info["agent"] or info["bez_terminalu"]     # Claude čeká na hook: bublina nesmí zdržovat
        timer.start(int(1000 * (self.timeout_agent_s if kratce else self.timeout_s)))
        self.cekajici[id_] = {"sock": sock, "timer": timer, "session": session, "pid": pid, "shrnuti": info}
        sock.disconnected.connect(lambda: self.zrus(id_))
        self.pozadavek.emit(id_, session, pid, info)

    def _zahod(self, sock):
        self._spojeni.pop(sock, None)
        sock.abort()
        sock.deleteLater()

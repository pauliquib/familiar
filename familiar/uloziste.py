# Malé JSON soubory stavu v $XDG_STATE_HOME/familiar (statistiky, postup).
#
# Zápis je atomický (dočasný soubor 0600 ve stejném adresáři, fsync, rename),
# rozbitý soubor se při čtení odloží stranou jako záloha a začne se znovu.
# Nic odsud nevyhazuje výjimku dál než do volajícího modulu, který ji spolkne.
import json, logging, os, tempfile, time

from familiar import paths

lg = logging.getLogger("familiar.uloziste")


def soubor(jmeno):
    """$XDG_STATE_HOME/familiar/<jmeno> (výchozí ~/.local/state)."""
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(paths.home(), ".local", "state")
    return os.path.join(state, "familiar", jmeno)


def nacti(cesta, zalohovat=True):
    """Slovník ze souboru; chybějící → {}; nečitelný nebo rozbitý → záloha <cesta>.vadny-<čas> a {}.
    zalohovat=False (jen čtení, třeba `familiar statistiky` vedle daemonu): rozbitý soubor nechá být."""
    try:
        with open(cesta, "rb") as f:
            data = json.loads(f.read())
        if not isinstance(data, dict):
            raise ValueError("kořen není objekt")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeDecodeError) as e:
        if not zalohovat:
            return {}
        zaloha = f"{cesta}.vadny-{int(time.time())}"
        try:
            os.replace(cesta, zaloha)
            lg.warning("%s je vadný (%s), záloha %s, začínám znovu",
                       os.path.basename(cesta), type(e).__name__, os.path.basename(zaloha))
        except OSError:
            lg.warning("%s je vadný (%s) a nejde odložit", os.path.basename(cesta), type(e).__name__)
        return {}


def zapis(cesta, data):
    """Atomický zápis JSON s právy 0600; OSError propadne volajícímu."""
    d = os.path.dirname(cesta)
    os.makedirs(d, mode=0o700, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(cesta) + ".", dir=d)   # mkstemp = 0600
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cesta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cele(x, lo=0, hi=10**12):
    """Nezáporné celé číslo z načtených dat, jinak lo."""
    return x if isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi else lo


def cislo(x, lo=0.0, hi=1e12):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or not lo <= x <= hi:
        return lo
    return float(x)

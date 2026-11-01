# Dialog nastavení (Qt): edituje stejný config.toml jako `familiar config`.
#
# Soubor se čte až při uložení a mění se v něm jen hodnoty, které uživatel v dialogu
# změnil (tomlkit: komentáře, pořadí i neznámé klíče zůstanou). Výchozí hodnota, která
# v souboru nebyla, se nepřidává. Neexistující soubor založí stejný generátor jako
# `familiar config --init`. Před zápisem projde výsledek validací config.load();
# nová chyba = neuloží se. Zápis atomicky (tmp + rename), daemon ho přenačte sám.
#
# Dva režimy: jednoduché (výchozí, běžné volby) a pokročilé (všechno). Přepínač je první
# položka dialogu; zvolený režim se hned zapíše do klíče `nastaveni`, takže se pamatuje.
#
# Jak nová funkce přidá svá nastavení:
#   1. config.py: výchozí hodnota v defaults(), rozsah v RANGES nebo volby v ENUMS a komentář
#      v COMMENTS (je zároveň nápovědou v dialogu). Tím je klíč validovaný a v souboru.
#   2. sem do POLOZKY jeden záznam, např.
#        Polozka("bublina.zapnuta", "Bublina s činností", "Bublina", JEDNODUCHE),
#      widget plyne z výchozí hodnoty: bool → zaškrtávátko, číslo → pole s rozsahem z RANGES
#      (jednotka podle přípony _s/_ms), text z ENUMS nebo s volbami → výběr, seznam textů →
#      řádky, [číslo, číslo] → dvě pole. Nová záložka vznikne sama (úvodní text v ZALOZKY).
#   Klíč bez záznamu se přesto ukáže v pokročilém režimu na záložce Ostatní; co se edituje
#   jen v souboru, vyjmenuje NE_V_DIALOGU.
#
# Poslední záložka „Editor familiárů“ je editor skinů a jejich animací (familiar/editor.py).
# Ukládá se vlastním tlačítkem do adresáře skinů, ne do configu; „Použít jako vzhled“
# jen nastaví pole Vzhled (skin) na záložce Obecné, to se zapíše s ostatními přes Uložit.
#
#   python3 -m familiar.nastaveni
import os, sys, tempfile
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QRadioButton, QScrollArea,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from familiar import config, paths, skin, sprites

JEDNODUCHE, POKROCILE = "jednoduche", "pokrocile"
EDITOR = "Editor familiárů"     # záložka s editorem skinů (familiar/editor.py)


@dataclass(frozen=True)
class Polozka:
    """Jedna položka dialogu. Typ, rozsah a nápovědu bere z config.py (výchozí hodnota,
    RANGES/ENUMS, COMMENTS); tady jen to, jak a kde se ukáže."""
    klic: str                   # cesta v configu; „tabulka.*“ = každý její klíč (i vlastní uživatelův)
    popisek: str = ""           # prázdný = klíč
    zalozka: str = "Ostatní"
    rezim: str = POKROCILE      # JEDNODUCHE = ukáže se v obou režimech
    skupina: str = ""           # rámeček na záložce (nápověda z COMMENTS nadřazené tabulky)
    volby: object = None        # [(hodnota, text)] nebo funkce, která je vrátí; jinak config.ENUMS
    jednotka: str = ""          # přípona čísla; jinak podle _s / _ms
    procenta: bool = False      # násobek (2.505) ukázat jako procenta po desetinách (250,5 %)
    napoveda: str = ""          # jinak config.COMMENTS[klic]


def _skiny():
    try:
        return [(sid, f"{name} ({sid})") for sid, name, _ in skin.available()]
    except Exception:
        return []


HATS = {"hardhat": "přilba", "headphones": "sluchátka", "beret": "baret", "mortarboard": "absolventská čepice",
        "explorer": "klobouk badatele", "cap": "kšiltovka", "straw": "slamák", "tophat": "cylindr",
        "crown": "koruna", "nightcap": "noční čepička", "laurel": "vavřínový věnec"}


def _klobouky():
    return [("", "bez klobouku")] + [(h, f"{HATS.get(h, h)} ({h})") for h in sprites.HATS]


ZALOZKY = {     # pořadí a úvodní text záložek; záložka, která tu chybí, se přidá před Ostatní
    "Obecné": "Hlavní přepínače. Změny se projeví do 1 s bez restartu.",
    "Okno": "Velikost a umístění postaviček.",
    "Zobrazit": "Zapnutí jednotlivých vrstev.",
    "Klid": "Pravidlo klidu: výrazné reakce nejdou rychle po sobě.",
    "Nálada": "Model nálady, valence −1…1, aktivace 0…1. Najetím myší na popisek se ukáže vysvětlení.",
    "Témata": "Téma rozhovoru určuje klobouk. Nástroje a příkazy ([temata.nastroje], "
              "[[temata.prikazy]]) se upravují v souboru.",
    "Ostatní": "Nastavení bez vlastního popisku (jména klíčů jako v souboru).",
}
NE_V_DIALOGU = ("verze", "nastaveni", "temata.nastroje", "temata.prikazy")

J = JEDNODUCHE
_NAL, _TEM = "Nálada", "Témata"
POLOZKY = [
    Polozka("rezim", "Kde postavička sedí", "Obecné", J, volby=[
        ("auto", "auto – perch, kde to jde, jinde dock"), ("perch", "perch – na okně terminálu"),
        ("dock", "dock – jedno okno")]),
    Polozka("skin", "Vzhled (skin)", "Obecné", J, volby=_skiny),
    Polozka("tichy", "Tichý režim (bez emotů a dronů)", "Obecné", J),
    Polozka("soustredeni", "Režim soustředění (postavička stojí)", "Obecné", J),

    Polozka("okno.meritko_perch", "Velikost na terminálu", "Okno", J, procenta=True),
    Polozka("okno.meritko_dock", "Velikost v režimu dock", "Okno", J, procenta=True),
    Polozka("okno.strana", "Strana titulku", "Okno", J, volby=[("vpravo", "vpravo"), ("vlevo", "vlevo")]),
    Polozka("okno.zakryti", "Když jiné okno zakryje titulek", "Okno", J, volby=[
        ("navrchu", "navrchu – zůstane na titulku, okno ji zakryje"), ("schovat", "schovat – zmizí"),
        ("rada", "řada – seřadí se v rohu obrazovky")]),
    Polozka("okno.rada_roh", "Roh pro řadu zakrytých", "Okno", J, volby=[
        ("vpravo-dole", "vpravo dole"), ("vpravo-nahore", "vpravo nahoře"),
        ("vlevo-dole", "vlevo dole"), ("vlevo-nahore", "vlevo nahoře")]),
    Polozka("okno.odsazeni", "Odsazení od kraje titulku", "Okno", jednotka=" px"),
    Polozka("okno.mezera", "Mezera mezi postavičkami", "Okno", jednotka=" px"),
    Polozka("okno.okraj", "Okraj obrazovky (v rohu)", "Okno", jednotka=" px"),
    Polozka("okno.snimek_ms", "Perioda překreslení", "Okno"),
    Polozka("okno.terminaly", "Terminály (proces na řádek)", "Okno"),
    Polozka("okno.backend", "Backend oken (prostředí)", "Okno", volby=[
        ("auto", "auto – podle prostředí"), ("kwin", "kwin – KDE Plasma"), ("x11", "x11 – jiná X11 session"),
        ("gnome", "gnome – rozšíření GNOME Shellu"), ("zadny", "žádný – jen dock")]),

    Polozka("zobrazit.nalada", "Nálada (obličej a barvy)", "Zobrazit", J),
    Polozka("zobrazit.temata", "Témata (klobouk)", "Zobrazit", J),
    Polozka("zobrazit.emoty", "Emoty nad hlavou", "Zobrazit", J),
    Polozka("zobrazit.drony", "Drony za subagenty", "Zobrazit", J),

    Polozka("klid.emote_s", "Jak dlouho visí emote", "Klid"),
    Polozka("klid.rozestup_s", "Rozestup emotů", "Klid"),
    Polozka("klid.fronta", "Fronta emotů", "Klid"),
    Polozka("postavicka.ustaleni_s", "Ustálení stavu", "Klid", skupina="Postavička"),
    Polozka("postavicka.odchod_s", "Zmizí po konci za", "Klid", skupina="Postavička"),
    Polozka("postavicka.usnuti_s", "Usne bez událostí za", "Klid", skupina="Postavička"),

    *(Polozka("nalada." + k, t, _NAL) for k, t in (
        ("tau_valence_s", "τ valence"), ("tau_aktivace_s", "τ aktivace"),
        ("zaklad_valence", "Základní valence"), ("zaklad_aktivace", "Základní aktivace"),
        ("hystereze_s", "Hystereze štítku"), ("rucne_s", "Zvolená nálada platí"),
        ("otazky_n", "Okno otázek (promptů)"),
        ("opakovani_s", "Opakování – okno"), ("opakovani_podobnost", "Opakování – podobnost"),
        ("opakovani_min_znaku", "Opakování – min. znaků"), ("zmatek_s", "Zmatek – okno"),
        ("pauza_s", "Pauza (nepočítá se do únavy)"), ("odpocinek_s", "Odpočinek (únava zmizí)"),
        ("vlastni_znaky", "Hodnotit prvních znaků"), ("ostry_min_pismen", "Ostrý tón – min. písmen"),
        ("ostry_podil_verzalek", "Ostrý tón – podíl verzálek"), ("serie_chyb_n", "Série chyb od"))),
    *(Polozka("nalada.prahy." + k, t, _NAL, skupina="Prahy štítků") for k, t in (
        ("zmatek_korekci", "Zmatek – korekcí"), ("frustrace_valence", "Frustrace – valence ≤"),
        ("frustrace_aktivace", "Frustrace – aktivace ≥"), ("unava", "Únava ≥"),
        ("radost_valence", "Radost – valence ≥"), ("zvedavost_aktivace", "Zvědavost – aktivace ≥"),
        ("zvedavost_valence", "Zvědavost – valence ≥"), ("zvedavost_otazek", "Zvědavost – otázek"),
        ("zvedavost_podil", "Zvědavost – podíl otázek"))),
    *(Polozka("nalada.unava." + k, t, _NAL, skupina="Únava") for k, t in (
        ("kol", "Kol do plné únavy"), ("hodin", "Hodin do plné únavy"), ("za_komprimaci", "Za komprimaci"))),
    *(Polozka("nalada.impulsy." + k, t, _NAL, skupina="Impulsy [Δ valence, Δ aktivace]") for k, t in (
        ("dekovani", "Děkování"), ("korekce", "Korekce"), ("ostry_ton", "Ostrý tón"),
        ("opakovani", "Opakování"), ("otazka", "Otázka"), ("chyba_nastroje", "Chyba nástroje"),
        ("serie_chyb", "Série chyb"), ("testy", "Testy prošly"), ("preruseni", "Přerušení"),
        ("zamitnuti", "Zamítnutí"), ("kolo_bez_chyb", "Kolo bez chyb"))),
    *(Polozka("nalada.slova." + k, t, _NAL,
              skupina="Klíčová slova (regex na řádek, malými písmeny bez diakritiky)") for k, t in (
        ("dekovani", "Děkování"), ("korekce", "Korekce"), ("vulgarismy", "Vulgarismy"),
        ("otazky", "Otázky"), ("testy", "Testy"))),

    *(Polozka("temata." + k, t, _TEM) for k, t in (
        ("tau_s", "τ vyprchání"), ("ukazat", "Ukázat od bodů"), ("naskok", "Náskok před druhým"),
        ("za_slovo", "Body za slovo"), ("max_slov", "Max. slov z promptu"),
        ("za_adresar", "Body za slovo v cestě"))),
    Polozka("temata.klobouky.*", zalozka=_TEM, skupina="Klobouky", volby=_klobouky),
    Polozka("temata.slova.*", zalozka=_TEM,
            skupina="Slova témat (začátek slova jako regex, na řádek; prázdné = téma vypnuto)"),
]

# upozornění, statistiky, úrovně a úspěchy, další agenti (vlna 2, M15)
_UPO, _STA, _AGE = "Upozornění", "Statistiky", "Agenti"
ZALOZKY.update({
    _UPO: "Notifikace na ploše a zvuky, když agent skončí, čeká na tebe nebo selže, a ty nejsi "
          "v jeho terminálu. Nikdy neukazují text promptu.",
    _STA: "Denní statistiky, úrovně a úspěchy. Ukládají se jen čísla a názvy nástrojů "
          "(~/.local/state/familiar/).",
    _AGE: "Postavičky pro další agenty. Hooky instaluje `familiar install --agents`.",
})
POLOZKY += [
    Polozka("upozorneni.notifikace", "Notifikace na ploše", _UPO, J),
    Polozka("upozorneni.zvuky", "Zvuky", _UPO, J),
    Polozka("upozorneni.sada", "Sada zvuků", _UPO, J, volby=[("jemne", "jemné"), ("pipani", "pípání")]),
    Polozka("upozorneni.hlasitost", "Hlasitost", _UPO, J, jednotka=" %"),
    Polozka("upozorneni.nocni_klid", "Noční klid (HH:MM-HH:MM)", _UPO, J),
    Polozka("upozorneni.druhy", "Na co upozorňovat (druh na řádek)", _UPO),
    Polozka("upozorneni.jen_neaktivni", "Jen když terminál není aktivní", _UPO),
    Polozka("upozorneni.cekani_po_s", "Čekání upozornit po", _UPO),
    Polozka("upozorneni.kolo_nad_s", "Dokončení jen u kola delšího než", _UPO),
    Polozka("upozorneni.v_tichu", "V tichu a nočním klidu", _UPO, volby=[
        ("nic", "nic"), ("nalehave", "jen čekání na mě, bez zvuku"), ("bez_zvuku", "všechno, bez zvuku")]),
    Polozka("upozorneni.rozestup_s", "Rozestup stejného upozornění", _UPO),
    Polozka("upozorneni.za_minutu", "Nejvýš upozornění za minutu", _UPO),
    Polozka("upozorneni.nalehave_kriticke", "Čekání jako kritické (obchází Nerušit)", _UPO),
    Polozka("upozorneni.vlastni.*", zalozka=_UPO, skupina="Vlastní zvuky (cesta k WAV, prázdné = ze sady)"),
    Polozka("statistiky.zapnuto", "Denní statistiky", _STA, J),
    Polozka("postup.zapnuto", "Úrovně a úspěchy", _STA, J),
    Polozka("postup.oznamovat_uspechy", "Oznamovat nové úspěchy", _STA, J),
    Polozka("statistiky.retence_dni", "Statistiky uchovávat", _STA, jednotka=" dní"),
    Polozka("statistiky.ukladat_s", "Statistiky ukládat nejvýš jednou za", _STA),
    Polozka("postup.ukladat_s", "Postup ukládat nejvýš jednou za", _STA),
    Polozka("agenti.gemini", "Gemini CLI", _AGE),
    Polozka("agenti.codex", "OpenAI Codex", _AGE),
]



def _doplnky_klobouky():
    from familiar import progress
    out = [("", "žádný"), ("auto", "poslední odemčený")]
    for k, (druh, nazev, p) in progress.DOPLNKY.items():
        if druh == "klobouk":
            kdy = f"úroveň {p['uroven']}" if "uroven" in p else f"úspěch {progress.USPECHY[p['uspech']][0]}"
            out.append((k, f"{nazev} (od: {kdy})"))
    return out


# odemčené doplňky na postavičce (M17); vybírat jde i v okně Statistiky a úspěchy
POLOZKY += [
    Polozka("postup.doplnek_klobouk", "Odemčený klobouk", _STA, J, volby=_doplnky_klobouky),
    Polozka("postup.klobouk_vzdy", "Nosit ho i místo klobouku tématu", _STA, J),
    Polozka("postup.emoty_v_klidu", "Odemčené emoty v klidu", _STA, J),
    Polozka("postup.klid_emote_s", "Emote v klidu nejvýš jednou za", _STA),
]

# vrstvy u postavičky (config.vrstvy_defaults): bublina, měřič kontextu, pomocníci, povolení
_BUB, _KON, _POM = "Bublina s činností", "Měřič kontextu", "Pomocníci subagentů"
NAPOVEDA_POVOLENI = ("Na žádost Claude Code o povolení odpovíš kliknutím v bublině u postavičky; dialog "
                     "v terminálu zůstává a platí první odpověď.\nPotřebuje hook PermissionRequest: "
                     "familiar install --povoleni (odebere familiar install --bez-povoleni). "
                     "Zda je nainstalovaný, ukáže familiar doctor.")
ZALOZKY["Povolení"] = ("Povolení z bubliny. Funguje jen s nainstalovaným hookem: "
                       "familiar install --povoleni (kontrola: familiar doctor).")
POLOZKY += [
    Polozka("bublina.cinnost", "Bublina s činností", "Zobrazit", J, skupina=_BUB, volby=[
        ("zmena", "při změně – na chvíli"), ("vzdy", "vždy – celou dobu práce"), ("nikdy", "nikdy")]),
    Polozka("bublina.doba_s", "Doba zobrazení", "Zobrazit", skupina=_BUB),
    Polozka("kontext.zobrazit", "Měřič kontextu", "Zobrazit", J, skupina=_KON, volby=[
        ("vzdy", "vždy"), ("nad_prahem", "jen nad prahem"), ("nikdy", "nikdy")]),
    Polozka("kontext.prah", "Práh varování", "Zobrazit", skupina=_KON, jednotka=" %"),
    Polozka("kontext.varovat", "Bublina při překročení prahu", "Zobrazit", skupina=_KON),
    Polozka("pomocnici.zapnuto", "Pomocníci za subagenty (místo dronů)", "Zobrazit", J, skupina=_POM),
    Polozka("pomocnici.limit", "Nejvýš pomocníků (další jako +N)", "Zobrazit", skupina=_POM),
    Polozka("povoleni.zapnuto", "Povolení z bubliny (potřebuje hook)", "Povolení", J,
            napoveda=NAPOVEDA_POVOLENI),
    Polozka("povoleni.timeout_s", "Žádost hlavní session visí", "Povolení"),
    Polozka("povoleni.timeout_agent_s", "Žádost subagenta visí", "Povolení"),
]

# procházky a reakce na myš (config.pohyb_defaults, M16)
_POH = "Pohyb"
ZALOZKY[_POH] = ("Procházky po titulku okna a reakce na myš. V režimu soustředění postavička stojí "
                 "a na myš nereaguje.")
POLOZKY += [
    Polozka("prochazky.zapnuto", "Občas se projít", _POH, J, skupina="Procházky"),
    Polozka("prochazky.interval_s", "Průměrná pauza mezi procházkami", _POH, skupina="Procházky"),
    Polozka("prochazky.rychlost", "Rychlost chůze", _POH, skupina="Procházky", jednotka=" px/s"),
    Polozka("prochazky.dosah", "Nejdál od svého místa", _POH, skupina="Procházky", jednotka=" px"),
    Polozka("mys.zapnuto", "Reagovat na myš", _POH, J, skupina="Myš"),
    Polozka("mys.klik", "Levý klik (perch)", _POH, skupina="Myš", volby=[
        ("oboji", "přepne na terminál a šťouchne"), ("terminal", "jen přepne (šťouchnutí prostředním)"),
        ("stouchnout", "šťouchne (na terminál dvojklik)")]),
    Polozka("mys.hlazeni", "Hlazení (srdíčko)", _POH, skupina="Myš"),
    Polozka("mys.najeti", "Najetí myší (zbystří)", _POH, skupina="Myš"),
]
SUFFIX = {"_s": " s", "_ms": " ms"}


def _get(data, path):
    for k in path.split("."):
        data = data[k]
    return data


class _NoWheel(QObject):
    """Kolečko myši nemění pole bez fokusu (jinak se při posouvání záložky přepisují hodnoty)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel and not obj.hasFocus():
            ev.ignore()
            return True
        return False


def _listy(data, prefix=""):
    """Cesty ke všem hodnotám configu (vnořené tabulky rozbalí), kromě NE_V_DIALOGU."""
    for key, val in data.items():
        path = prefix + key
        if config._match(path, NE_V_DIALOGU):
            continue
        if isinstance(val, dict):
            yield from _listy(val, path + ".")
        else:
            yield path


def _ma(data, path):
    try:
        _get(data, path)
        return True
    except (KeyError, TypeError):
        return False


class Pole:
    """Jedna hodnota configu: cesta, výchozí hodnota, widget a čtení/zápis."""

    def __init__(self, path, default, widget, get, put):
        self.path, self.default, self.widget = path, default, widget
        self.get, self.put = get, put
        self.initial = None
        self.polozka = self.form = self.box = None      # doplní Nastaveni._row


class Nastaveni(QDialog):
    ulozeno = Signal(str)      # cesta k uloženému souboru

    def __init__(self, parent=None, path=None, zalozka=None, skin_id=None):
        super().__init__(parent)
        self.path = path or paths.config_file()
        self.setWindowTitle("Nastavení familiara")
        self.fields, self.tab_of = {}, {}       # cesta → Pole, cesta → index záložky
        self._nowheel = _NoWheel(self)
        cfg = config.load(self.path)
        self.data, self.defaults = cfg.data, config.defaults()
        self.rezim = self.data.get("nastaveni", JEDNODUCHE)

        self.tabs = QTabWidget()
        self._build()
        self._editor(skin_id)
        for f in self.fields.values():
            f.put(_get(self.data, f.path))
            f.initial = f.get()     # zpětně přečtené z widgetu (zaokrouhlení spinboxu není změna)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setVisible(False)
        if cfg.errors:
            errors = [self._strip(e) for e in cfg.errors]
            for e in errors:        # chybné pole ukazuje výchozí hodnotu; Uložit ji zapíše místo chyby
                if f := self.fields.get(e.split(" – ", 1)[0]):
                    f.initial = object()
            self._show("Soubor obsahuje chyby, platí u nich výchozí hodnoty. Uložení je u polí "
                       "v dialogu nahradí zobrazenou hodnotou, ostatní oprav v editoru:", errors, warn=True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Uložit")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Zrušit")
        reset = self.reset = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        reset.setText("Obnovit výchozí (záložka)")
        reset.setToolTip("vrátí výchozí hodnoty polí viditelných na aktuální záložce "
                         "(uloží se až tlačítkem Uložit)")
        reset.clicked.connect(self.obnovit_zalozku)
        editor = buttons.addButton("Otevřít soubor v editoru", QDialogButtonBox.ButtonRole.ActionRole)
        editor.setToolTip(self.path)
        editor.clicked.connect(self.otevrit_v_editoru)
        buttons.accepted.connect(self.ulozit)
        buttons.rejected.connect(self.reject)

        where = self.where = QLabel()
        self._kde()
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        where.setStyleSheet("color: palette(placeholder-text);")
        lay = QVBoxLayout(self)
        lay.addLayout(self._prepinac())
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.message)
        lay.addWidget(where)
        lay.addWidget(buttons)
        self.prepnout(self.rezim, zapsat=False)
        self.resize(660, 620)
        if zalozka == EDITOR:
            self.tabs.setCurrentIndex(self.editor_tab)

    # --- přepínač režimu ---

    def _prepinac(self):
        h = QHBoxLayout()
        h.addWidget(QLabel("<b>Nastavení:</b>"))
        self.volba_rezimu = QButtonGroup(self)
        self.tlacitka_rezimu = {}
        tips = {JEDNODUCHE: "jen běžné volby", POKROCILE: "všechny volby (nálada, témata, časy, prahy …)"}
        for rezim, text in ((JEDNODUCHE, "Jednoduché"), (POKROCILE, "Pokročilé")):
            b = self.tlacitka_rezimu[rezim] = QRadioButton(text)
            b.setToolTip(tips[rezim])
            self.volba_rezimu.addButton(b)
            h.addWidget(b)
            b.toggled.connect(lambda on, r=rezim: on and r != self.rezim and self.prepnout(r))
        h.addStretch(1)
        return h

    def prepnout(self, rezim, zapsat=True):
        """Ukáže položky režimu (skryje řádky, prázdné rámečky a záložky); zapsat = zapamatovat v souboru."""
        self.rezim = rezim
        b = self.tlacitka_rezimu[rezim]
        if not b.isChecked():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)
        tabs, boxes = {}, {}
        for f in self.fields.values():
            on = self.viditelne(f.path)
            f.form.setRowVisible(f.widget, on)
            if f.box is not None:
                boxes[f.box] = boxes.get(f.box, False) or on
            tabs[self.tab_of[f.path]] = tabs.get(self.tab_of[f.path], False) or on
        for box, on in boxes.items():
            box.setVisible(on)
        tabs[self.editor_tab] = True
        for i, on in tabs.items():
            self.tabs.setTabVisible(i, on)
        if not tabs.get(self.tabs.currentIndex()):
            self.tabs.setCurrentIndex(next((i for i, on in tabs.items() if on), 0))
        if zapsat:
            self._zapamatovat(rezim)

    def viditelne(self, path):
        return self.rezim == POKROCILE or self.fields[path].polozka.rezim == JEDNODUCHE

    def _zapamatovat(self, rezim):
        """Režim dialogu se zapíše hned (volba vzhledu dialogu, ne familiara); chyba nevadí."""
        try:
            text = upravit_text(_read(self.path), {"nastaveni": rezim}, self.defaults)
            if os.path.exists(self.path) or text != config.render(config.defaults()):
                _write(self.path, text)
                self._kde()
        except Exception:       # rozbitý soubor: režim se jen nezapamatuje
            pass

    def _kde(self):
        exists = os.path.exists(self.path)
        self.where.setText(f"Soubor: {config._short(self.path)}" + ("" if exists else " (zatím neexistuje)"))

    # --- stavba záložek ---

    def _polozky(self):
        """[(cesta, Polozka)]: záznamy POLOZKY (vzory „.*“ rozbalené podle dat) a pak hodnoty
        configu bez záznamu (pokročilé, záložka Ostatní)."""
        out, seen = [], set()
        for p in POLOZKY:
            if p.klic.endswith(".*"):
                base = p.klic[:-2]
                found = [f"{base}.{k}" for k in (_get(self.data, base) if _ma(self.data, base) else {})]
            else:
                found = [p.klic] if _ma(self.data, p.klic) else []
            for path in found:
                if path not in seen:
                    seen.add(path)
                    out.append((path, p))
        for path in _listy(self.defaults):
            if path not in seen:
                sec = f"[{path.split('.')[0]}]" if "." in path else ""
                out.append((path, Polozka(path, path.split(".", 1)[-1], "Ostatní", skupina=sec)))
        return out

    def _build(self):
        rows = self._polozky()
        used = list(dict.fromkeys(p.zalozka for _, p in rows))
        order = [t for t in ZALOZKY if t in used and t != "Ostatní"]
        order += [t for t in used if t not in order and t != "Ostatní"]
        order += ["Ostatní"] if "Ostatní" in used else []
        pages = {t: self._page(t, ZALOZKY.get(t, "")) for t in order}
        for path, p in rows:
            lay, form, groups = pages[p.zalozka]
            box = None
            if p.skupina:
                if p.skupina not in groups:
                    groups[p.skupina] = self._group(lay, p.skupina, config.COMMENTS.get(path.rsplit(".", 1)[0]))
                box, form = groups[p.skupina]
            self._row(form, path, p, box, order.index(p.zalozka))
        for lay, _, _ in pages.values():
            lay.addStretch(1)

    def _page(self, title, intro):
        page = QWidget()
        lay = QVBoxLayout(page)
        if intro:
            hint = QLabel(intro)
            hint.setWordWrap(True)
            lay.addWidget(hint)
        form = self._form()
        lay.addLayout(form)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        self.tabs.addTab(area, title)
        return lay, form, {}

    def _form(self):
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return form

    def _group(self, lay, title, tip=None):
        box = QGroupBox(title)
        if tip:
            box.setToolTip(tip)
        form = self._form()
        box.setLayout(form)
        lay.addWidget(box)
        return box, form

    def _row(self, form, path, p, box, tab):
        default = _get(self.defaults, path) if _ma(self.defaults, path) else None
        field = self._field(path, p, default, _get(self.data, path))
        field.polozka, field.form, field.box = p, form, box
        tip = p.napoveda or config.COMMENTS.get(path, "")
        text = p.popisek or path.rsplit(".", 1)[-1]
        field.widget.setToolTip(tip)
        if isinstance(field.widget, QCheckBox):
            field.widget.setText(text)
            form.addRow(field.widget)
        else:
            lab = QLabel(text)
            lab.setToolTip(tip)
            form.addRow(lab, field.widget)
        self.fields[path] = field
        self.tab_of[path] = tab

    def _field(self, path, p, default, current):
        kind = current
        volby = p.volby() if callable(p.volby) else p.volby
        if volby is None and path in config.ENUMS:
            volby = [(v, v) for v in config.ENUMS[path]]
        if volby is not None:
            return self._combo(path, default, current, volby)
        if isinstance(kind, bool):
            w = QCheckBox()
            return Pole(path, default, w, w.isChecked, w.setChecked)
        if p.procenta:
            w = self._spin(path, True, " %", procenta=True)
            return Pole(path, default, w, lambda: round(w.value() / 100, 4), lambda v: w.setValue(v * 100))
        if isinstance(kind, (int, float)):
            w = self._spin(path, isinstance(kind, float), p.jednotka)
            return Pole(path, default, w, w.value, w.setValue)
        if isinstance(kind, str):       # volný text (noční klid, cesta k souboru)
            w = QLineEdit()
            return Pole(path, default, w, lambda: w.text().strip(), w.setText)
        if isinstance(kind, list) and kind and isinstance(kind[0], float):     # impulz [Δv, Δa]
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            spins = [self._spin(path, True, p.jednotka) for _ in kind]
            for s, pre in zip(spins, ("v ", "a ")):
                s.setPrefix(pre)
                h.addWidget(s)

            def put(v, spins=spins):
                for s, x in zip(spins, v):
                    s.setValue(x)
            return Pole(path, default, box, lambda: [s.value() for s in spins], put)
        w = QPlainTextEdit()        # seznam textů, položka na řádek
        w.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lines = max(3, min(8, len(current)))
        w.setFixedHeight(w.fontMetrics().lineSpacing() * lines + 14)
        return Pole(path, default, w,
                    lambda: [x.strip() for x in w.toPlainText().splitlines() if x.strip()],
                    lambda v: w.setPlainText("\n".join(v)))

    def _combo(self, path, default, current, items):
        w = QComboBox()
        items = list(items)
        if current not in [v for v, _ in items]:
            items.append((current, f"{current} (neznámá hodnota)"))
        for value, text in items:
            w.addItem(text, value)
        w.installEventFilter(self._nowheel)
        w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return Pole(path, default, w, w.currentData, lambda v: w.setCurrentIndex(max(0, w.findData(v))))

    def _spin(self, path, real, unit="", procenta=False):
        lo, hi = config._range(path)
        if procenta:
            w = QDoubleSpinBox()
            w.setDecimals(1)
            w.setSingleStep(0.1)
            lo, big = lo * 100, hi * 100
        elif real:
            w = QDoubleSpinBox()
            big = hi if hi is not None else 1e9
            w.setDecimals(3 if big <= 1 or lo < 0 else 2)
            w.setSingleStep(0.05 if big <= 1 else 0.1 if big <= 10 else 1)
        else:
            w = QSpinBox()
            lo, big = int(lo), int(hi) if hi is not None else 2 ** 31 - 1
        w.setRange(lo, big)
        for end, suffix in SUFFIX.items():
            if path.endswith(end):
                w.setSuffix(suffix)
        if unit:
            w.setSuffix(unit)
        w.installEventFilter(self._nowheel)
        w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        w.setMinimumWidth(140)
        return w

    # --- editor familiárů ---

    def _editor(self, skin_id=None):
        from familiar.editor import EditorSkinu
        self.editor = EditorSkinu(self, skin_id or self.data.get("skin"))
        self.editor_tab = self.tabs.addTab(self.editor, EDITOR)
        self.tabs.setTabToolTip(self.editor_tab, "kreslení familiárů a jejich animací, palety, stavy a nálady")
        self.editor.pouzit.connect(self.pouzit_skin)
        self.editor.ulozeno.connect(lambda _: self._volby_skinu())
        self.tabs.currentChanged.connect(self._zalozka)
        self._zvetseno = False

    def _zalozka(self, i):
        on = i == self.editor_tab
        self.reset.setEnabled(not on)
        if on and not self._zvetseno:      # editor potřebuje místo; jednou zvětšit, pak nechat na uživateli
            self._zvetseno = True
            screen = self.screen().availableGeometry() if self.screen() else None
            w, h = 1240, 860
            if screen:
                w, h = min(w, screen.width() - 40), min(h, screen.height() - 60)
            self.resize(max(w, self.width()), max(h, self.height()))

    def _volby_skinu(self):
        """Pole Vzhled (skin) znovu naplní podle skinů na disku (editor přidal nebo smazal skin)."""
        f = self.fields.get("skin")
        if not f:
            return
        cur = f.get()
        w = f.widget
        w.blockSignals(True)
        w.clear()
        items = _skiny()
        if cur not in [v for v, _ in items]:
            items.append((cur, f"{cur} (neznámá hodnota)"))
        for value, text in items:
            w.addItem(text, value)
        w.setCurrentIndex(max(0, w.findData(cur)))
        w.blockSignals(False)

    def pouzit_skin(self, sid):
        """Z editoru: nastaví pole Vzhled; zapíše se s ostatními změnami tlačítkem Uložit."""
        self._volby_skinu()
        f = self.fields.get("skin")
        if f:
            f.put(sid)
            self.editor.hlaska(f"Vzhled nastaven na {sid}; v configu se uloží tlačítkem Uložit dole."
                               if f.get() != f.initial else f"{sid} už je zvolený vzhled.")

    # --- akce ---

    def reject(self):
        if self.editor.muze_zavrit():
            super().reject()

    def zmeny(self):
        """{cesta: nová hodnota} polí, která uživatel změnil."""
        return {p: f.get() for p, f in self.fields.items() if f.get() != f.initial}

    def obnovit_zalozku(self):
        """Výchozí hodnoty polí aktuální záložky viditelných v aktuálním režimu."""
        tab = self.tabs.currentIndex()
        for p, f in self.fields.items():
            if self.tab_of[p] == tab and f.default is not None and self.viditelne(p):
                f.put(f.default)

    def otevrit_v_editoru(self):
        if not os.path.exists(self.path):
            _write(self.path, config.render(config.defaults()))
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def ulozit(self):
        """Uloží změny; při chybě ji ukáže a dialog nezavře. Vrací True po uložení."""
        if not self.editor.muze_zavrit():
            return False
        try:
            text = upravit_text(_read(self.path), self.zmeny(), self.defaults)
        except Exception as e:      # chyby tomlkit dědí z ValueError
            self._show(f"{config._short(self.path)} nejde upravit ({e}). Oprav ho v editoru.", [])
            return False
        before = set(self._strip(e) for e in config.load(self.path).errors)
        errors = [_short_err(e) for e in _check(text) if e not in before]
        if errors:
            self._show("Neuloženo – oprav tyto hodnoty:", errors)
            return False
        _write(self.path, text)
        self.ulozeno.emit(self.path)
        self.accept()
        return True

    def _strip(self, err):
        name = config._short(self.path) + ":"
        return err[len(name):] if err.startswith(name) else err

    def _show(self, head, lines, warn=False):
        for f in self.fields.values():
            f.widget.setStyleSheet("")
        first = None
        for line in lines:
            f = self.fields.get(line.split(" – ", 1)[0])
            if f:
                f.widget.setStyleSheet("border: 2px solid #c0392b;")
                first = first or f
        if first and not warn:
            if not self.viditelne(first.path):      # chyba v poli, které jednoduchý režim skrývá
                self.prepnout(POKROCILE, zapsat=False)
            self.tabs.setCurrentIndex(self.tab_of[first.path])
            if isinstance(area := self.tabs.currentWidget(), QScrollArea):
                area.ensureWidgetVisible(first.widget)
            first.widget.setFocus()
        color = "#9a6700" if warn else "#c0392b"
        body = "".join(f"<li>{_html(x)}</li>" for x in lines)
        self.message.setText(f"<b style='color:{color}'>{_html(head)}</b>" + (f"<ul>{body}</ul>" if body else ""))
        self.message.setVisible(True)


def _short_err(e):
    """Bez dovětku „použije se …“ – při ukládání se nic nepoužije, jen neuloží."""
    head, _, tail = e.rpartition(" – ")
    return head if head and tail.startswith(("použije se", "ignoruje se")) else e


def _html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read(path):
    """Text souboru; neexistující = stejný výchozí soubor jako `familiar config --init`."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return config.render(config.defaults())


def _write(path, text):
    from familiar import install
    install._atomic_write(path, text)       # tmp + os.replace; daemon pozná nový inode


def upravit_text(text, changes, defaults=None):
    """Nový text configu: v dokumentu tomlkit změní jen dané cesty, zbytek nechá beze změny.
    Klíč, který v souboru chybí a má dostat výchozí hodnotu, se nepřidává."""
    import tomlkit
    defaults = defaults or config.defaults()
    doc = tomlkit.parse(text)
    for path, val in changes.items():
        *parents, key = path.split(".")
        tbl, missing = doc, False
        for p in parents:
            if p not in tbl:
                missing = True
                break
            tbl = tbl[p]
        if missing or key not in tbl:
            try:
                if _get(defaults, path) == val:
                    continue
            except KeyError:
                pass
            tbl = doc
            for p in parents:
                if p not in tbl:
                    tbl[p] = tomlkit.table()
                tbl = tbl[p]
        tbl[key] = config._item(path, val)
    return tomlkit.dumps(doc)


def _check(text):
    """Chyby z config.load() pro daný text, bez jména souboru (`cesta – problém – …`)."""
    with tempfile.TemporaryDirectory(prefix="familiar-nastaveni-") as d:
        path = os.path.join(d, "config.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        cfg = config.load(path)
        name = config._short(path) + ":"
        return [e[len(name):] if e.startswith(name) else e for e in cfg.errors]


def otevri(parent=None, path=None, zalozka=None, skin_id=None):
    """Modální dialog nastavení; True = uloženo, False = zrušeno. Bez běžící QApplication ji založí."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    dlg = Nastaveni(parent, path, zalozka, skin_id)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    dlg.deleteLater()
    return ok


def main():
    print("uloženo" if otevri(zalozka=EDITOR if "--editor" in sys.argv[1:] else None) else "zrušeno")


if __name__ == "__main__":
    main()

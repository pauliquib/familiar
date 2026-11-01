# Konfigurace: $XDG_CONFIG_HOME/familiar/config.toml (výchozí ~/.config/familiar/).
#
# Výchozí hodnoty žijí v kódu (konstanty mood, topic, hub, fsm a OKNO níže);
# soubor je jen přepisuje. Chybný klíč dostane výchozí hodnotu, rozbitý TOML
# celé výchozí; familiar běží dál a chyby vrací v Config.errors (daemon je
# zaloguje). Klíče česky bez diakritiky, snake_case. Bez Qt.
#
#   familiar config --init [--force] | --path | --check | --show
import copy, fnmatch, math, os, re, sys, tomllib

from familiar import fsm, hub, mood, paths, pohyb, progress, skin, sprites, topic, vrstvy

VERSION = 1

# okno a renderer (dřív dock.SCALE, PERCH_SCALE, TICK_MS a perch.js RIGHT, GAP, PAD)
OKNO = {"meritko_dock": 3.0, "meritko_perch": 2.0, "strana": "vpravo", "odsazeni": 120, "mezera": 4,
        "okraj": 8, "zakryti": "navrchu", "rada_roh": "vpravo-dole", "snimek_ms": 60}

# upozornění (familiar/upozorneni.py ho bere odsud, config zůstává bez Qt)
DRUHY_UPOZORNENI = ("dokonceno", "povoleni", "otazka", "chyba", "compact")
SADY_ZVUKU = ("jemne", "pipani")
V_TICHU = ("nic", "nalehave", "bez_zvuku")      # co v tichém režimu, soustředění a nočním klidu
UPOZORNENI = {
    "notifikace": True,
    "zvuky": True,
    "sada": "jemne",
    "hlasitost": 60,
    "druhy": ["dokonceno", "povoleni", "otazka", "chyba"],
    "jen_neaktivni": True,
    "cekani_po_s": 10.0,
    "kolo_nad_s": 30.0,
    "v_tichu": "nalehave",
    "nocni_klid": "",
    "rozestup_s": 30.0,
    "za_minutu": 6,
    "nalehave_kriticke": False,
    "vlastni": {d: "" for d in DRUHY_UPOZORNENI},
}
# odemčené doplňky (progress.DOPLNKY) na postavičce: oblíbený klobouk a emoty v klidu (M17)
POSTUP_DOPLNKY = {"doplnek_klobouk": "", "klobouk_vzdy": False, "emoty_v_klidu": True, "klid_emote_s": 120.0}
NOCNI_KLID_RE = re.compile(r"\s*([01]?\d|2[0-3]):[0-5]\d\s*-\s*([01]?\d|2[0-3]):[0-5]\d\s*")


def defaults():
    """Celá výchozí konfigurace jako vnořený slovník (pořadí = pořadí v souboru)."""
    return {
        "verze": VERSION, "rezim": "auto", "skin": skin.DEFAULT, "tichy": False, "soustredeni": False,
        "nastaveni": "jednoduche",
        "okno": {**OKNO, "terminaly": sorted(hub.TERMINALS), "backend": "auto"},
        "zobrazit": {"nalada": True, "temata": True, "emoty": True, "drony": True},
        "klid": {"emote_s": hub.POP_S, "rozestup_s": hub.POP_GAP_S, "fronta": hub.POP_QUEUE},
        "postavicka": {"ustaleni_s": hub.SETTLE_S, "odchod_s": hub.LEAVE_S, "usnuti_s": fsm.SLEEP_S},
        "nalada": mood.defaults(),
        "temata": topic.defaults(),
        "upozorneni": copy.deepcopy(UPOZORNENI),
        "statistiky": {"zapnuto": True, "retence_dni": 365, "ukladat_s": 60.0},
        "postup": {"zapnuto": True, "oznamovat_uspechy": True, "ukladat_s": 60.0, **POSTUP_DOPLNKY},
        "agenti": {"gemini": True, "codex": True},
        **vrstvy_defaults(),
        **pohyb_defaults(),
    }


def vrstvy_defaults():
    """Bublina, měřič kontextu, pomocníci a povolení z bubliny (familiar/vrstvy.py, docs/povoleni.md)."""
    return {
        "bublina": {"cinnost": "zmena", "doba_s": vrstvy.BUBLINA_S},
        "kontext": {"zobrazit": "vzdy", "prah": vrstvy.KONTEXT_PRAH, "varovat": True},
        "pomocnici": {"zapnuto": True, "limit": vrstvy.POMOCNICI_LIMIT},
        # timeouty jako povoleni.TIMEOUT_S / TIMEOUT_AGENT_S (ten modul potřebuje Qt)
        "povoleni": {"zapnuto": False, "timeout_s": 300, "timeout_agent_s": 15},
    }


def pohyb_defaults():
    """Procházky a reakce na myš (familiar/pohyb.py)."""
    return {"prochazky": dict(pohyb.PROCHAZKY), "mys": dict(pohyb.MYS)}


ENUMS = {"rezim": ("auto", "perch", "dock"), "nastaveni": ("jednoduche", "pokrocile"), "okno.strana": ("vlevo", "vpravo"),
         "okno.zakryti": ("navrchu", "schovat", "rada"),
         "okno.rada_roh": ("vpravo-dole", "vpravo-nahore", "vlevo-dole", "vlevo-nahore")}
FREE = ("temata.klobouky", "temata.slova", "temata.nastroje")   # smí mít i vlastní klíče (nová témata, nástroje)
WORD_LISTS = ("nalada.slova.*", "temata.slova.*")               # seznamy regexů
RANGES = [   # (vzor klíče, min, max); první shoda platí, jinak čísla ≥ 0
    ("okno.meritko_*", 1, 8), ("okno.snimek_ms", 16, 1000), ("okno.odsazeni", 0, 4000),
    ("okno.mezera", 0, 500), ("okno.okraj", 0, 4000),
    ("klid.emote_s", 0.1, 60), ("klid.rozestup_s", 0, 600), ("klid.fronta", 0, 10),
    ("postavicka.ustaleni_s", 0, 10), ("postavicka.odchod_s", 0, 3600), ("postavicka.usnuti_s", 1, 86400),
    ("nalada.tau_*", 1, 86400), ("nalada.zaklad_valence", -1, 1), ("nalada.zaklad_aktivace", 0, 1),
    ("nalada.hystereze_s", 0, 600), ("nalada.rucne_s", 0, 86400), ("nalada.otazky_n", 1, 100), ("nalada.serie_chyb_n", 1, 100),
    ("nalada.opakovani_podobnost", 0, 1), ("nalada.ostry_podil_verzalek", 0, 1),
    ("nalada.vlastni_znaky", 1, 100000), ("nalada.ostry_min_pismen", 1, 10000),
    ("nalada.*_s", 0, 7 * 86400), ("nalada.impulsy.*", -1, 1),
    ("nalada.prahy.*_valence", -1, 1), ("nalada.prahy.*_aktivace", 0, 1), ("nalada.prahy.unava", 0, 1),
    ("nalada.prahy.zvedavost_podil", 0, 1), ("nalada.prahy.zvedavost_otazek", 1, 100),
    ("nalada.prahy.*", 0, 100),
    ("nalada.unava.kol", 1, 100000), ("nalada.unava.hodin", 0.01, 1000), ("nalada.unava.za_komprimaci", 0, 1),
    ("temata.tau_s", 1, 7 * 86400), ("temata.naskok", 1, 100), ("temata.max_slov", 1, 100),
    ("temata.nastroje.*", 0, 100), ("temata.prikazy.*", 0, 100), ("temata.*", 0, 1000),
]
# vrstvy u postavičky (vrstvy_defaults); povoleni.timeout_agent_s: klient hooku čeká nejvýš 20 s,
# timeout_s: hook má v settings.json timeout 600 s
ENUMS.update({"bublina.cinnost": ("zmena", "vzdy", "nikdy"), "kontext.zobrazit": ("vzdy", "nad_prahem", "nikdy")})
RANGES += [("bublina.doba_s", 0.5, 60), ("kontext.prah", 1, 100), ("pomocnici.limit", 1, 10),
           ("povoleni.timeout_s", 5, 590), ("povoleni.timeout_agent_s", 1, 20)]

HEADER = """\
Konfigurace familiara. Změny se projeví do 1 s bez restartu.
Smazaný klíč = výchozí hodnota; chyby ukáže `familiar config --check`.
Výchozí soubor vygeneruje `familiar config --init --force` (starý zazálohuje)."""

COMMENTS = {
    "verze": "číslo schématu; neměň, starší verze převede `familiar install`",
    "rezim": ("auto (perch, kde to backend oken umí: KDE, X11, GNOME s rozšířením; jinde dock)\n"
              "/ perch (na okně terminálu) / dock (jedno okno)"),
    "skin": "vzhled postavičky; seznam dostupných: `familiar skins`, vlastní skiny v ~/.local/share/familiar/skins/",
    "tichy": "tichý režim: žádné emoty nad hlavou ani drony subagentů",
    "soustredeni": ("režim soustředění = tichý režim, a navíc postavička stojí bez pohybu (první snímek\n"
                    "klidové animace, i při práci, chybě nebo spánku); hýbe se jen, když čeká na uživatele\n"
                    "(oprávnění nebo otázka). Nálada (obličej, barvy) a klobouk zůstávají, jsou statické."),
    "nastaveni": "dialog nastavení: jednoduche (běžné volby) / pokrocile (všechno); přepínač nahoře v dialogu",
    "okno": "okna postaviček",
    "okno.meritko_dock": "zvětšení v režimu dock (1–8, i desetinné: 2.505 = 250,5 %)",
    "okno.meritko_perch": "zvětšení na okně terminálu (1–8, i desetinné: 2.505 = 250,5 %)",
    "okno.strana": "u kterého kraje titulku terminálu sedí: vlevo / vpravo (i roh obrazovky)",
    "okno.odsazeni": "px od kraje titulku (vpravo místo pro tlačítka okna)",
    "okno.mezera": "px mezi postavičkami u jednoho terminálu",
    "okno.okraj": "px od kraje obrazovky, když sedí v rohu (čeká, nebo řada zakrytých)",
    "okno.zakryti": ("když jiné okno zakryje titulek terminálu: navrchu (zůstane na titulku a to okno\n"
                     "ji zakryje stejně jako terminál; úplně zakrytý terminál ji schová, čekající sedne do rohu)\n"
                     "/ schovat (zmizí; čekající na uživatele si sedne do dolního rohu na své straně)\n"
                     "/ rada (zakryté se seřadí do řady v rohu obrazovky, viz rada_roh).\n"
                     "Minimalizovaný terminál nebo terminál na jiné ploše či aktivitě postavičku schová vždy\n"
                     "(čekající na uživatele sedne do rohu)."),
    "okno.rada_roh": "roh obrazovky pro řadu zakrytých (zakryti = \"rada\"): vpravo-dole / vpravo-nahore / vlevo-dole / vlevo-nahore",
    "okno.snimek_ms": "perioda překreslení, ms (méně = plynulejší, víc CPU)",
    "okno.terminaly": "názvy procesů terminálů (/proc/<pid>/comm), na jejichž okno postavička sedne",
    "zobrazit": "zapnutí jednotlivých vrstev",
    "zobrazit.nalada": "obličej a barvy podle nálady (vypnuto = vždy klid)",
    "zobrazit.temata": "klobouk podle tématu rozhovoru",
    "zobrazit.emoty": "jednorázové reakce nad hlavou (srdce, fajfka, květinka, …)",
    "zobrazit.drony": "drony za běžící subagenty",
    "klid": "pravidlo klidu: výrazné reakce nejdou rychle po sobě",
    "klid.emote_s": "jak dlouho visí emote nad hlavou, s",
    "klid.rozestup_s": "pauza mezi dvěma emoty, s (emote_s + rozestup_s = nejvýš jedna reakce za tu dobu)",
    "klid.fronta": "kolik emotů smí čekat ve frontě (další se zahodí)",
    "postavicka": "chování postavičky",
    "postavicka.ustaleni_s": "trvalý stav se ukáže, až vydrží tolik s (proti blikání)",
    "postavicka.odchod_s": "po konci session zmizí za tolik s",
    "postavicka.usnuti_s": "bez událostí usne za tolik s",
    "nalada": "model nálady (koncept, kapitola 3): valence −1…1, aktivace 0…1",
    "nalada.tau_valence_s": "časová konstanta návratu valence k základu, s",
    "nalada.tau_aktivace_s": "časová konstanta návratu aktivace k základu, s",
    "nalada.zaklad_valence": "klidová valence",
    "nalada.zaklad_aktivace": "klidová aktivace",
    "nalada.hystereze_s": "nový štítek nálady se ukáže, až vyhrává tolik s",
    "nalada.rucne_s": "nálada zvolená v panelu nálady platí tolik s (0 = jen zapsat opravu)",
    "nalada.otazky_n": "z kolika posledních promptů se počítá podíl otázek",
    "nalada.opakovani_s": "opakovaná prosba: porovnává se s prompty za tolik s",
    "nalada.opakovani_podobnost": "od jaké podobnosti (0–1) jde o opakování",
    "nalada.opakovani_min_znaku": "kratší prompty se na opakování nehodnotí",
    "nalada.zmatek_s": "korekce za posledních tolik s se počítají do zmatku",
    "nalada.pauza_s": "delší pauza se do aktivního času (únavy) nepočítá, s",
    "nalada.odpocinek_s": "po tolika s klidu únava zmizí",
    "nalada.vlastni_znaky": "hodnotí se jen tolik prvních znaků promptu (dál bývá vložený text)",
    "nalada.ostry_min_pismen": "ostrý tón verzálkami: aspoň tolik písmen…",
    "nalada.ostry_podil_verzalek": "…a takový podíl velkých (0–1)",
    "nalada.serie_chyb_n": "od kolikáté chyby nástroje za sebou platí impulz serie_chyb",
    "nalada.impulsy": "signál = [Δ valence, Δ aktivace], tabulka 3.3",
    "nalada.prahy": "štítky (vyhodnocuje se shora): zmatek, frustrace, únava, radost, zvědavost, jinak klid",
    "nalada.unava": "únava = kola/kol + aktivní hodiny/hodin + za_komprimaci × komprimace (nejvýš 1)",
    "nalada.slova": ("klíčová slova = regexy na textu malými písmeny bez diakritiky, celá slova (\\b na obou\n"
                     "stranách; u `testy` jen na začátku, hledá se v příkazu Bash)"),
    "nalada.slova.otazky": "začátky otázek (otazník kdekoli se počítá vždy)",
    "temata": "témata rozhovoru → klobouk (kapitola 3.6); body vyprchávají",
    "temata.tau_s": "časová konstanta vyprchání bodů, s",
    "temata.ukazat": "od kolika bodů se téma ukáže",
    "temata.naskok": "kolikrát víc bodů musí mít před druhým tématem",
    "temata.za_slovo": "body za každé různé klíčové slovo v promptu",
    "temata.max_slov": "nejvýš tolik slov z jednoho promptu",
    "temata.za_adresar": "body za klíčové slovo v cestě k projektu",
    "temata.klobouky": ("téma → klobouk: " + ", ".join(sprites.HATS) + " (\"\" = bez klobouku)"),
    "temata.slova": ("téma → začátky slov (regexy, \\b jen na začátku, takže chytí i tvary);\n"
                     "nové téma = nový klíč, [] téma vypne"),
    "temata.nastroje": "nástroj Claude Code → body pro téma",
    "temata.prikazy": "regex hledaný v příkazu Bash → body pro téma",
}
COMMENTS.update({
    "bublina": "bublina s činností u postavičky („čte hub.py“, „spouští pytest“); ne v tichém režimu a soustředění",
    "bublina.cinnost": "zmena (na chvíli při změně činnosti) / vzdy (celou dobu práce) / nikdy",
    "bublina.doba_s": "jak dlouho visí bublina po změně činnosti, s (0,5–60)",
    "kontext": "měřič obsazení kontextu (baterka u postavičky, údaj z transcriptu)",
    "kontext.zobrazit": "vzdy / nad_prahem (jen když je kontext skoro plný) / nikdy",
    "kontext.prah": "od kolika % je měřič červený a ukáže se varování (1–100)",
    "kontext.varovat": "při překročení prahu krátká bublina „kontext 85 %, brzy compact“",
    "pomocnici": "malí pomocníci vedle postavičky za běžící subagenty (nahrazují drony)",
    "pomocnici.zapnuto": "ukazovat pomocníky (vypnuto = drony podle zobrazit.drony); ne v tichém režimu",
    "pomocnici.limit": "nejvýš tolik pomocníků, další jako „+N“ (1–10)",
    "povoleni": ("povolení z bubliny: na žádost o povolení odpovíš kliknutím v bublině u postavičky\n"
                 "(dialog v terminálu zůstává, platí první odpověď). Potřebuje hook: familiar install --povoleni"),
    "povoleni.zapnuto": "zapnout povolení z bubliny (bez hooku nemá vliv, viz familiar doctor)",
    "povoleni.timeout_s": "jak dlouho visí žádost hlavní session, s (5–590)",
    "povoleni.timeout_agent_s": "žádost subagenta na pozadí (Claude čeká na hook, dialog zdrží), s (1–20)",
})

# procházky a reakce na myš (pohyb_defaults, M16)
ENUMS["mys.klik"] = pohyb.KLIK
RANGES += [("prochazky.interval_s", 5, 3600), ("prochazky.rychlost", 5, 300), ("prochazky.dosah", 0, 2000)]
COMMENTS.update({
    "prochazky": ("procházky: v klidu se postavička občas projde po titulku okna (perch) nebo po své buňce\n"
                  "(dock) a vrátí se; k tlačítkům okna ani do textu titulku nezajde. Ne při soustředění."),
    "prochazky.zapnuto": "občas se projít",
    "prochazky.interval_s": "průměrná pauza mezi procházkami, s (5–3600; skutečná je náhodně 0,5–1,5×)",
    "prochazky.rychlost": "rychlost chůze, px/s (5–300)",
    "prochazky.dosah": "nejdál od svého místa, px (0–2000; v perch ještě omezí šířka titulku)",
    "mys": ("reakce na myš: klik = šťouchnutí (poskočí), rychlé klikání = zamotá se a chvíli se zlobí,\n"
            "pomalé hlazení = srdíčko, najetí = zbystří. V soustředění žádné, v tichém režimu bez emotů."),
    "mys.zapnuto": "postavička reaguje na myš (vypnuto = klik jen přepne na terminál, v docku jen přesun)",
    "mys.klik": ("levý klik na postavičku v perch: oboji (přepne na terminál a šťouchne) / terminal (jen přepne,\n"
                 "šťouchnutí prostředním tlačítkem) / stouchnout (šťouchne, na terminál přepne dvojklik).\n"
                 "V docku klik vždy šťouchne, tažení přesouvá okno, dvojklik otevře panel nálady."),
    "mys.hlazeni": "pomalé pohyby myší tam a zpátky nad postavičkou = hlazení (srdíčko)",
    "mys.najeti": "najetí myší: postavička zbystří",
})

# upozornění, statistiky, úrovně a úspěchy, další agenti (vlna 2, M15)
ENUMS.update({"upozorneni.sada": SADY_ZVUKU, "upozorneni.v_tichu": V_TICHU})
LIST_ENUMS = {"upozorneni.druhy": DRUHY_UPOZORNENI}     # seznamy, jejichž položky jsou z výčtu
RANGES += [
    ("upozorneni.hlasitost", 0, 100), ("upozorneni.cekani_po_s", 0, 3600), ("upozorneni.kolo_nad_s", 0, 86400),
    ("upozorneni.rozestup_s", 0, 3600), ("upozorneni.za_minutu", 1, 60),
    ("statistiky.retence_dni", 1, 3650), ("statistiky.ukladat_s", 10, 3600), ("postup.ukladat_s", 10, 3600),
]
COMMENTS.update({
    "upozorneni": ("notifikace na ploše a zvuky, když agent skončí, čeká na povolení nebo odpověď či selže;\n"
                   "nikdy s textem promptu (jen projekt, druh, délka kola, název nástroje)"),
    "upozorneni.notifikace": "notifikace na ploše (klik na ni přepne do terminálu)",
    "upozorneni.zvuky": "krátký zvuk k upozornění",
    "upozorneni.sada": "sada zvuků: jemne / pipani",
    "upozorneni.hlasitost": "hlasitost zvuků, 0–100",
    "upozorneni.druhy": "na co upozorňovat: " + ", ".join(DRUHY_UPOZORNENI) + " (compact = zhušťování kontextu)",
    "upozorneni.jen_neaktivni": "neupozorňovat, když je okno terminálu té session aktivní (zjišťuje KWin)",
    "upozorneni.cekani_po_s": "povolení a otázka: upozornit, až agent čeká déle než tolik s",
    "upozorneni.kolo_nad_s": "dokončení: jen u kola delšího než tolik s",
    "upozorneni.v_tichu": ("v tichém režimu, soustředění a nočním klidu: nic / nalehave (jen čekání na tebe,\n"
                           "bez zvuku) / bez_zvuku (všechno, jen potichu)"),
    "upozorneni.nocni_klid": "noční klid \"HH:MM-HH:MM\" (třeba \"22:00-07:00\"), platí jako tichý režim; \"\" = vypnuto",
    "upozorneni.rozestup_s": "stejný druh téže session nejvýš jednou za tolik s (kromě čekání)",
    "upozorneni.za_minutu": "nejvýš tolik upozornění za minutu celkem",
    "upozorneni.nalehave_kriticke": ("čekání na povolení a otázky jako kritické notifikace (urgency critical):\n"
                                     "obchází systémový režim Nerušit a nezmizí samy"),
    "upozorneni.vlastni": "vlastní zvuk (cesta k WAV) pro druh upozornění; přebíjí sadu, \"\" = ze sady",
    "statistiky": "denní statistiky (jen čísla a názvy nástrojů) v ~/.local/state/familiar/statistiky.json",
    "statistiky.zapnuto": "sbírat denní statistiky",
    "statistiky.retence_dni": "starší dny se mažou, dní",
    "statistiky.ukladat_s": "ukládat nejvýš jednou za tolik s (a vždy při ukončení)",
    "postup": "úrovně, XP a úspěchy v ~/.local/state/familiar/postup.json",
    "postup.zapnuto": "počítat XP, úrovně a úspěchy",
    "postup.oznamovat_uspechy": "nový úspěch a úroveň oznámit u postavičky a notifikací",
    "postup.ukladat_s": "ukládat nejvýš jednou za tolik s (a vždy při ukončení)",
    "agenti": "další agenti (hooky instaluje `familiar install --agents`); false = jejich události se ignorují",
    "agenti.gemini": "postavičky pro Gemini CLI",
    "agenti.codex": "postavičky pro OpenAI Codex",
})

# backend oken (familiar/okna.py, M18): kdo zná polohu cizích oken, posadí postavičky na titulek,
# hlásí aktivní okno a přepne do terminálu; "auto" podle XDG_CURRENT_DESKTOP a XDG_SESSION_TYPE
OKNA_BACKENDY = ("auto", "kwin", "x11", "gnome", "zadny")
ENUMS["okno.backend"] = OKNA_BACKENDY
COMMENTS["okno.backend"] = ("backend oken: auto (KDE → kwin, GNOME na Waylandu → gnome, jiná X11 session → x11,\n"
                            "jinak zadny) / kwin (KWin skripty) / x11 (správce oken s EWMH) / gnome (rozšíření\n"
                            "GNOME Shellu, familiar install --gnome-rozsireni) / zadny (jen dock, aktivní okno\n"
                            "neznámé). Změna platí po restartu daemonu; co je k dispozici, ukáže familiar doctor.")

# odemčené doplňky: klobouk = "" (žádný), "auto" (poslední odemčený) nebo id doplňku druhu klobouk;
# zamčený doplněk se nenosí, dokud se neodemkne (to config neví, rozhoduje sluzby.py)
ENUMS["postup.doplnek_klobouk"] = ("", "auto") + tuple(k for k, v in progress.DOPLNKY.items() if v[0] == "klobouk")
RANGES += [("postup.klid_emote_s", 10, 3600)]
COMMENTS.update({
    "postup.doplnek_klobouk": ("odemčený klobouk, který postavička nosí, když téma nemá vlastní: \"\" = žádný,\n"
                               "\"auto\" = poslední odemčený, nebo " + ", ".join(ENUMS["postup.doplnek_klobouk"][2:])),
    "postup.klobouk_vzdy": "nosit odemčený klobouk vždy, i místo klobouku tématu",
    "postup.emoty_v_klidu": "odemčené emoty (srdíčko, hvězdička …) občas ukázat, když postavička odpočívá",
    "postup.klid_emote_s": "emote v klidu nejvýš jednou za tolik s (10–3600)",
})


# --- validace ---------------------------------------------------------------

def _match(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def _range(path):
    for pat, lo, hi in RANGES:
        if fnmatch.fnmatchcase(path, pat):
            return lo, hi
    return 0, None


def _fmt(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, dict)):
        return "výchozí hodnota"
    text = str(value)
    return text if len(text) <= 30 else text[:27] + "…"


def _skins():
    """Id dostupných skinů, nebo None, když je zjistit nejde (vadný skin nesmí shodit načtení)."""
    try:
        return [sid for sid, _, _ in skin.available()]
    except Exception:
        return None


class _Checker:
    def __init__(self, name):
        self.name, self.errors, self.warnings = name, [], []

    def bad(self, path, problem, default):
        what = "ignoruje se" if default is None else f"použije se {_fmt(default)}"   # None: nový klíč volné tabulky
        self.errors.append(f"{self.name}:{path} – {problem} – {what}")

    def warn(self, path, problem):
        self.warnings.append(f"{self.name}:{path} – {problem}")

    def table(self, user, default, prefix=""):
        """Efektivní slovník: výchozí hodnoty přepsané platnými hodnotami ze souboru."""
        out = copy.deepcopy(default)
        free = prefix.rstrip(".") in FREE
        for key, val in user.items():
            path = prefix + key
            if key in default:
                ok, v = self.value(path, val, default[key])
            elif free and default:
                ok, v = self.value(path, val, None, template=next(iter(default.values())))
            else:
                self.warn(path, "neznámý klíč – ignoruje se")
                continue
            if ok:
                out[key] = v
        return out

    def value(self, path, val, default, template=None):
        """(platná?, hodnota); u chyby zapíše hlášku s výchozí hodnotou."""
        kind = default if default is not None else template
        problem = None
        if isinstance(kind, dict) and not _match(path, ("temata.nastroje.*",)):
            if not isinstance(val, dict):
                problem = "musí být tabulka"
            else:
                return True, self.table(val, kind, path + ".")
        elif _match(path, ("temata.nastroje.*",)):
            problem = self._record(path, val)
            if not problem:
                return True, {"tema": val["tema"], "body": float(val["body"])}
        elif path == "temata.prikazy":
            problem = self._commands(val)
            if not problem:
                return True, [{"regex": c["regex"], "tema": c["tema"], "body": float(c["body"])} for c in val]
        elif isinstance(kind, bool):
            if not isinstance(val, bool):
                problem = "musí být true nebo false"
        elif isinstance(kind, (int, float)):
            problem = self._number(path, val, isinstance(kind, int))
            if not problem:
                val = float(val) if isinstance(kind, float) else val
        elif isinstance(kind, str):
            problem = self._string(path, val)
        elif isinstance(kind, list):
            problem = self._list(path, val, kind)
            if not problem and kind and isinstance(kind[0], float):
                val = [float(x) for x in val]
        if problem:
            self.bad(path, problem, default)
            return False, None
        return True, val

    def _number(self, path, val, integer):
        lo, hi = _range(path)
        span = f"{lo}–{hi}" if hi is not None else f"≥ {lo}"
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return f"musí být {'celé ' if integer else ''}číslo {span}, je {_fmt(val)}"
        if integer and not isinstance(val, int):
            return f"musí být celé číslo {span}, je {_fmt(val)}"
        # porovnání bez převodu na float: obří celé číslo by v math.isfinite přeteklo
        if (isinstance(val, float) and not math.isfinite(val)) or val < lo or (hi is not None and val > hi):
            return f"musí být v rozsahu {span}, je {_fmt(val)}"
        return None

    def _string(self, path, val):
        if not isinstance(val, str):
            return f"musí být text, je {_fmt(val)}"
        if path in ENUMS and val not in ENUMS[path]:
            return f"neznámá hodnota {_fmt(val)}, možnosti: {', '.join(ENUMS[path])}"
        if path == "skin":
            skins = _skins()
            if skins is None:
                self.warn(path, "seznam skinů nejde zjistit, skin se nekontroluje")
            elif val not in skins:
                return f"skin {_fmt(val)} neexistuje, k dispozici: {', '.join(skins)}"
        if path == "upozorneni.nocni_klid" and val and not NOCNI_KLID_RE.fullmatch(val):
            return f"musí být HH:MM-HH:MM (např. \"22:00-07:00\") nebo \"\", je {_fmt(val)}"
        if path.startswith("temata.klobouky.") and val and val not in sprites.HATS:
            return f"neznámý klobouk {_fmt(val)}, možnosti: {', '.join(sprites.HATS)} nebo \"\""
        return None

    def _list(self, path, val, kind):
        if not isinstance(val, list):
            return "musí být seznam"
        if kind and isinstance(kind[0], float):        # impulz [Δv, Δa]
            if len(val) != len(kind):
                return f"musí mít {len(kind)} čísla"
            for x in val:
                if p := self._number(path, x, False):
                    return p
            return None
        for i, w in enumerate(val):
            if not isinstance(w, str) or not w:
                return f"položka {i + 1} musí být neprázdný text"
            if path in LIST_ENUMS and w not in LIST_ENUMS[path]:
                return f"neznámá položka {_fmt(w)}, možnosti: {', '.join(LIST_ENUMS[path])}"
            if _match(path, WORD_LISTS):
                if p := _regex_problem(w):
                    return f"položka {_fmt(w)}: {p}"
        if _match(path, WORD_LISTS) and val:
            try:        # engine slova spojí do jednoho vzoru: inline příznaky nebo stejně
                _joined(path, val)     # pojmenované skupiny projdou samostatně, spojené ne
            except re.error as e:
                return f"slova nejdou spojit do jednoho regexu ({e})"
        return None

    def _record(self, path, val):
        if not isinstance(val, dict) or set(val) != {"tema", "body"}:
            return "musí být {tema = \"…\", body = číslo}"
        if not isinstance(val["tema"], str) or not val["tema"]:
            return "tema musí být neprázdný text"
        return self._number(path + ".body", val["body"], False)

    def _commands(self, val):
        if not isinstance(val, list):
            return "musí být seznam tabulek [[temata.prikazy]]"
        for i, c in enumerate(val, 1):
            if not isinstance(c, dict) or set(c) != {"regex", "tema", "body"}:
                return f"položka {i} musí mít právě regex, tema a body"
            if not isinstance(c["regex"], str) or (p := _regex_problem(c["regex"])):
                return f"položka {i}: regex {p or 'musí být text'}"
            if not isinstance(c["tema"], str) or not c["tema"]:
                return f"položka {i}: tema musí být neprázdný text"
            if p := self._number("temata.prikazy.body", c["body"], False):
                return f"položka {i}: body {p}"
        return None

    def topics(self, data):
        """Odkazy na témata, která nemají slova ani klobouk (fungují, jen bez klobouku)."""
        t = data["temata"]
        known = set(t["slova"]) | set(t["klobouky"])
        used = [(f"temata.nastroje.{k}", v["tema"]) for k, v in t["nastroje"].items()]
        used += [(f"temata.prikazy[{i}]", c["tema"]) for i, c in enumerate(t["prikazy"], 1)]
        for path, name in used:
            if name not in known:
                self.warn(path, f"téma {_fmt(name)} nemá slova ani klobouk")


def _joined(path, words):
    """Stejný spojený vzor, jaký sestaví engine (mood.compile_words, topic)."""
    if path.startswith("temata."):
        return topic._rx(words)
    if path == "nalada.slova.otazky":
        return mood._question_rx(words)
    return mood._rx(words, end="" if path == "nalada.slova.testy" else r"\b")


def _regex_problem(rx):
    try:
        compiled = re.compile(rx)
    except re.error as e:
        return f"neplatný regex ({e})"
    if compiled.match(""):
        return "odpovídá i prázdnému textu"
    return None


# --- migrace ----------------------------------------------------------------

def _from_v0(doc):
    """Verze 0 = soubor bez klíče verze (psaný ručně); obsah je stejný jako ve verzi 1."""


MIGRATIONS = {0: _from_v0}     # verze → krok, který dokument (dict nebo tomlkit) na místě převede na verzi + 1


def migrate(doc):
    """Převede dokument na VERSION; vrací (původní verze, chyba nebo None)."""
    v = doc.get("verze", 0)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None, f"verze musí být celé číslo ≥ 0, je {_fmt(v)}"
    old = v
    while v < VERSION:
        MIGRATIONS[v](doc)
        v += 1
    if old < VERSION:
        doc["verze"] = VERSION
    return old, None


def migrate_file(run, path=None):
    """Pro `familiar install`: starší soubor převede, původní zazálohuje přes run (install.Run)."""
    import tomlkit
    path = path or paths.config_file()
    try:
        with open(path, encoding="utf-8") as f:
            doc = tomlkit.parse(f.read())
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as e:      # chyby tomlkit dědí z ValueError
        print(f"POZOR: {path} nejde přečíst ({e}), konfiguraci nemigruji")
        return False
    old, err = migrate(doc)
    if err or old >= VERSION:
        return False
    return run.write(path, tomlkit.dumps(doc), f"konfigurace převedena z verze {old} na {VERSION}")


# --- načtení ----------------------------------------------------------------

class Config:
    """Efektivní konfigurace (data) a co se při načtení našlo."""

    def __init__(self, data, path, exists=False, errors=(), warnings=()):
        self.data, self.path, self.exists = data, path, exists
        self.errors, self.warnings = list(errors), list(warnings)

    def __getitem__(self, key):
        return self.data[key]


def _short(path):
    home = paths.home().rstrip("/")
    return "~" + path[len(home):] if home and path.startswith(home + "/") else path


def load(path=None):
    """Načte config; nikdy nevyhodí výjimku – chybné části nahradí výchozími."""
    path = path or paths.config_file()
    try:
        return _load(path)
    except Exception as e:      # pojistka: chyba ve validaci nesmí shodit daemon, --check ani doctor
        return Config(defaults(), path, os.path.exists(path),
                      [f"{_short(path)} – nečekaná chyba při načítání ({type(e).__name__}) – "
                       "použije se celá výchozí konfigurace"])


def _load(path):
    name = _short(path)
    try:
        with open(path, "rb") as f:
            user = tomllib.load(f)
    except FileNotFoundError:
        return Config(defaults(), path)
    except (OSError, ValueError) as e:      # TOMLDecodeError, UnicodeDecodeError
        return Config(defaults(), path, True,
                      [f"{name} – neplatný soubor ({e}) – použije se celá výchozí konfigurace"])
    chk = _Checker(name)
    old, err = migrate(user)
    if err:
        chk.bad("verze", err, VERSION)
    elif old > VERSION:
        chk.warn("verze", f"soubor je z novější verze familiara ({old} > {VERSION}), neznámé klíče se ignorují")
    elif old < VERSION and "verze" in user and old != 0:
        chk.warn("verze", f"stará verze {old}, převedeno v paměti; soubor převede `familiar install`")
    user.pop("verze", None)
    data = chk.table(user, defaults())
    data["verze"] = VERSION
    chk.topics(data)
    return Config(data, path, True, chk.errors, chk.warnings)


class Watcher:
    """Sleduje config podle mtime, velikosti a inode (editor ho často atomicky nahradí).
    poll() volat časovačem: vrátí nový Config, až se soubor změní a do dalšího volání
    zůstane stejný (rozepsaný zápis se nenačte), jinak None. Smazaný soubor = výchozí."""

    def __init__(self, path=None):
        self.path = path or paths.config_file()
        self.sig, self.pending = self._sig(), False    # False = nic nečeká (None = soubor chybí)

    def _sig(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size, st.st_ino

    def poll(self):
        sig = self._sig()
        if sig == self.sig:
            self.pending = False
            return None
        if sig != self.pending:
            self.pending = sig
            return None
        self.sig, self.pending = sig, False
        return load(self.path)

    def take(self):
        """Načte config hned (po vlastním zápisu daemonu); tuto verzi už poll() nevrátí."""
        self.sig, self.pending = self._sig(), False
        return load(self.path)


def log_problems(cfg, log):
    for e in cfg.errors:
        log.error("config: %s", e)
    for w in cfg.warnings:
        log.warning("config: %s", w)


# --- zápis (tomlkit) --------------------------------------------------------

def _str(s):
    import tomlkit
    return tomlkit.string(s, literal=True) if "\\" in s and "'" not in s and "\n" not in s else s


def _item(path, val):
    import tomlkit
    if isinstance(val, str):
        return _str(val)
    if isinstance(val, list):
        arr = tomlkit.array()
        arr.extend(_str(x) if isinstance(x, str) else x for x in val)
        if any(isinstance(x, str) for x in val) and len(val) > 3:
            arr.multiline(True)
        return arr
    if isinstance(val, dict):
        it = tomlkit.inline_table()
        it.update({k: _item(f"{path}.{k}", v) for k, v in val.items()})
        return it
    return val


def _comment(tbl, text):
    import tomlkit
    for line in text.split("\n"):
        tbl.add(tomlkit.comment(line))


def _fill(tbl, data, prefix, notes):
    import tomlkit
    for key, val in data.items():
        path = prefix + key
        note = notes.get(path)
        if path == "temata.prikazy":
            aot = tomlkit.aot()
            for c in val:
                t = tomlkit.table()
                for k, v in c.items():
                    t.add(k, _item(path, v))
                aot.append(t)
            if note:
                _comment(tbl, note)
            tbl.add(key, aot)
        elif isinstance(val, dict) and not path.startswith("temata.nastroje."):
            sub = tomlkit.table()
            if note:
                _comment(sub, note)
            _fill(sub, val, path + ".", notes)
            tbl.add(tomlkit.nl())
            tbl.add(key, sub)
        elif note and (isinstance(val, list) and len(val) > 3 or "\n" in note):
            _comment(tbl, note)
            tbl.add(key, _item(path, val))
        else:
            it = tomlkit.item(_item(path, val))
            if note:
                it.comment(note)
            tbl.add(key, it)


def render(data, comments=True):
    """Text config.toml z dat (s komentáři pro --init, bez nich pro --show)."""
    import tomlkit
    doc = tomlkit.document()
    if comments:
        _comment(doc, HEADER)
        doc.add(tomlkit.nl())
    _fill(doc, data, "", COMMENTS if comments else {})
    return tomlkit.dumps(doc)


# --- familiar config ----------------------------------------------------------

def add_args(ap):
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--path", action="store_true", help="vypsat cestu ke konfiguraci")
    g.add_argument("--init", action="store_true", help="vytvořit komentovaný soubor s výchozími hodnotami")
    g.add_argument("--check", action="store_true", help="zkontrolovat soubor (exit 1 při chybě)")
    g.add_argument("--show", action="store_true", help="vypsat efektivní hodnoty")
    ap.add_argument("--force", action="store_true", help="s --init přepsat existující soubor (zazálohuje ho)")


def _print_problems(cfg, out=None):
    out = out or sys.stdout
    for e in cfg.errors:
        print(f"CHYBA  {e}", file=out)
    for w in cfg.warnings:
        print(f"POZOR  {w}", file=out)


def cli(args):
    path = paths.config_file()
    if args.path:
        print(path)
        return 0
    if args.init:
        exists = os.path.lexists(path)
        if exists and not args.force:
            print(f"{path} už existuje; přepíšeš ho s --force (starý se zazálohuje)", file=sys.stderr)
            return 1
        from familiar import install
        run = install.Run(False)
        run.write(path, render(defaults()), "výchozí konfigurace")
        if run.backup_dir:
            print(f"záloha: {run.backup_dir}")
        return 0
    if args.check:
        cfg = load(path)
        _print_problems(cfg)
        if not cfg.exists:
            print(f"OK  {path} neexistuje, platí výchozí hodnoty")
        elif not cfg.errors:
            print(f"OK  {path}" + (f" ({len(cfg.warnings)} varování)" if cfg.warnings else ""))
        return 1 if cfg.errors else 0
    if args.show:
        cfg = load(path)
        _print_problems(cfg, sys.stderr)
        print(render(cfg.data, comments=False), end="")
        return 1 if cfg.errors else 0
    print("použití: familiar config --init [--force] | --path | --check | --show", file=sys.stderr)
    return 2

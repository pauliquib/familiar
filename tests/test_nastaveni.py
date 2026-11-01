import difflib, os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from familiar import config, nastaveni, paths


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch, app):
    """Dočasný HOME i XDG_CONFIG_HOME; skutečný ~/.config se nedotkne."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path


def write(text):
    path = paths.config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def read():
    with open(paths.config_file(), encoding="utf-8") as f:
        return f.read()


def diff(a, b):
    return [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]


def test_bez_souboru_otevre_a_ulozi_init(home):
    d = nastaveni.Nastaveni()
    assert not os.path.exists(d.path)          # otevření nic nezakládá
    assert d.fields["okno.mezera"].get() == 4 and d.zmeny() == {}
    assert d.ulozit()
    assert read() == config.render(config.defaults())
    assert d.path.startswith(str(home))


def test_zmena_jen_te_hodnoty_komentare_zustanou(home):
    before = config.render(config.defaults())
    path = write(before)
    ino = os.stat(path).st_ino
    d = nastaveni.Nastaveni()
    d.fields["okno.mezera"].put(10)
    d.fields["nalada.prahy.unava"].put(0.55)
    assert d.zmeny() == {"okno.mezera": 10, "nalada.prahy.unava": 0.55}
    assert d.ulozit()
    changed = diff(before, read())
    assert sorted(changed) == ["+mezera = 10 # px mezi postavičkami u jednoho terminálu", "+unava = 0.55",
                               "-mezera = 4 # px mezi postavičkami u jednoho terminálu", "-unava = 0.7"]
    assert os.stat(path).st_ino != ino         # atomicky: tmp + rename
    cfg = config.load()
    assert not cfg.errors and not cfg.warnings
    assert cfg["okno"]["mezera"] == 10 and cfg["nalada"]["prahy"]["unava"] == 0.55


def test_velikost_v_procentech_po_desetinach(home):
    write("[okno]\nmeritko_perch = 2\n")
    d = nastaveni.Nastaveni()
    w = d.fields["okno.meritko_perch"].widget
    assert w.suffix() == " %" and w.value() == 200 and w.singleStep() == 0.1 and d.zmeny() == {}
    w.setValue(250.5)
    assert d.zmeny() == {"okno.meritko_perch": 2.505}
    assert d.ulozit()
    assert config.load()["okno"]["meritko_perch"] == 2.505


def test_seznam_slov_a_impulz(home):
    before = config.render(config.defaults())
    write(before)
    d = nastaveni.Nastaveni()
    d.fields["temata.slova.web"].widget.setPlainText("web\n  strank  \n\ncss\n")
    d.fields["nalada.impulsy.otazka"].put([0.1, 0.2])
    assert d.ulozit()
    cfg = config.load()
    assert not cfg.errors
    assert cfg["temata"]["slova"]["web"] == ["web", "strank", "css"]
    assert cfg["nalada"]["impulsy"]["otazka"] == [0.1, 0.2]
    assert all(l.lstrip("+-").split("#")[0].strip() for l in diff(before, read()))
    assert "# téma → začátky slov" in read()


def test_nezname_klice_a_vychozi_se_nepridava(home):
    text = ('# můj komentář\nneznamy = 1\n\n[okno]\nvlastni = "x" # můj\nmezera = 4\n\n'
            '[cizi]\nklic = [1, 2]\n')
    write(text)
    d = nastaveni.Nastaveni()
    d.fields["rezim"].put("dock")
    d.fields["rezim"].put("auto")          # tam a zpět = beze změny
    d.fields["okno.okraj"].put(8)          # výchozí, v souboru není
    d.fields["klid.fronta"].put(5)         # chybějící sekce se založí
    d.fields["okno.strana"].put("vlevo")   # chybějící klíč existující sekce
    assert set(d.zmeny()) == {"klid.fronta", "okno.strana"}
    assert d.ulozit()
    out = read()
    assert out.startswith(text.split("\n\n[cizi]")[0])
    assert "[cizi]\nklic = [1, 2]" in out and 'vlastni = "x" # můj' in out
    assert "okraj" not in out and "rezim" not in out
    cfg = config.load()
    assert not cfg.errors
    assert cfg["klid"]["fronta"] == 5 and cfg["okno"]["strana"] == "vlevo"


def test_neplatna_hodnota_neulozi(home):
    before = config.render(config.defaults())
    path = write(before)
    mtime = os.stat(path).st_mtime_ns
    d = nastaveni.Nastaveni()
    d.fields["okno.mezera"].put(7)
    d.fields["nalada.slova.korekce"].widget.setPlainText("(\nzase")
    assert not d.ulozit()
    assert read() == before and os.stat(path).st_mtime_ns == mtime
    assert not d.message.isHidden() and "nalada.slova.korekce" in d.message.text()
    assert d.tabs.tabText(d.tabs.currentIndex()) == "Nálada"
    assert d.rezim == nastaveni.POKROCILE      # chybné pole jednoduchý režim skrývá → přepne se
    assert d.result() != d.DialogCode.Accepted


def test_neplatny_soubor_neulozi(home):
    write("[okno\nmezera = 4\n")
    d = nastaveni.Nastaveni()
    d.fields["okno.mezera"].put(7)
    assert not d.ulozit()
    assert read() == "[okno\nmezera = 4\n"
    assert "nejde upravit" in d.message.text()


def test_chybna_hodnota_v_souboru_opravi_ulozeni(home):
    write("[okno]\nmezera = -5 # moje\n")
    d = nastaveni.Nastaveni()
    assert "okno.mezera" in d.message.text()
    assert d.fields["okno.mezera"].get() == 4
    assert d.ulozit()
    assert read() == "[okno]\nmezera = 4 # moje\n"
    assert not config.load().errors


def test_obnovit_vychozi_jen_zalozka(home):
    write("[okno]\nmezera = 9\nstrana = \"vlevo\"\n\n[klid]\nfronta = 5\n")
    d = nastaveni.Nastaveni()
    d.tabs.setCurrentIndex(1)
    assert d.tabs.tabText(1) == "Okno"
    d.obnovit_zalozku()             # jednoduchý režim: jen viditelná pole
    assert d.fields["okno.strana"].get() == "vpravo" and d.fields["okno.mezera"].get() == 9
    d.prepnout(nastaveni.POKROCILE, zapsat=False)
    d.obnovit_zalozku()
    assert d.fields["okno.mezera"].get() == 4 and d.fields["klid.fronta"].get() == 5
    assert d.ulozit()
    assert read() == "[okno]\nmezera = 4\nstrana = \"vpravo\"\n\n[klid]\nfronta = 5\n"


def test_vlastni_tema_v_dialogu(home):
    write('[temata.slova]\nhudba = ["kytar", "pisn"]\n')
    d = nastaveni.Nastaveni()
    f = d.fields["temata.slova.hudba"]
    assert f.get() == ["kytar", "pisn"] and f.default is None
    f.widget.setPlainText("kytar\npisn\nakord")
    assert d.ulozit()
    assert config.load()["temata"]["slova"]["hudba"] == ["kytar", "pisn", "akord"]


def test_zakryti_titulku_na_zalozce_okno(home):
    write(config.render(config.defaults()))
    d = nastaveni.Nastaveni()
    okno = [i for i in range(d.tabs.count()) if d.tabs.tabText(i) == "Okno"][0]
    for path, values in (("okno.zakryti", ["navrchu", "schovat", "rada"]),
                         ("okno.rada_roh", ["vpravo-dole", "vpravo-nahore", "vlevo-dole", "vlevo-nahore"])):
        w = d.fields[path].widget
        assert d.tab_of[path] == okno and isinstance(w, QComboBox)
        assert [w.itemData(i) for i in range(w.count())] == values and w.currentData() == values[0]
    d.fields["okno.zakryti"].put("rada")
    d.fields["okno.rada_roh"].put("vlevo-dole")
    assert d.ulozit()
    cfg = config.load()
    assert not cfg.errors and cfg["okno"]["zakryti"] == "rada" and cfg["okno"]["rada_roh"] == "vlevo-dole"


# --- režimy jednoduché / pokročilé ---

def viditelne_zalozky(d):
    return [d.tabs.tabText(i) for i in range(d.tabs.count()) if d.tabs.isTabVisible(i)]


def radek(d, path):
    f = d.fields[path]
    return f.form.isRowVisible(f.widget) and (f.box is None or not f.box.isHidden())


def test_vychozi_je_jednoduchy_rezim(home):
    d = nastaveni.Nastaveni()
    assert config.defaults()["nastaveni"] == "jednoduche" and d.rezim == nastaveni.JEDNODUCHE
    assert d.tlacitka_rezimu[nastaveni.JEDNODUCHE].isChecked()
    assert viditelne_zalozky(d) == ["Obecné", "Okno", "Zobrazit", "Upozornění", "Statistiky", "Povolení", "Pohyb",
                                    nastaveni.EDITOR]
    for path in ("rezim", "skin", "tichy", "soustredeni", "okno.meritko_perch", "okno.zakryti", "zobrazit.emoty"):
        assert radek(d, path), path
    for path in ("okno.mezera", "okno.terminaly", "klid.fronta", "nalada.prahy.unava", "temata.slova.web"):
        assert not radek(d, path), path
    d.prepnout(nastaveni.POKROCILE, zapsat=False)
    assert viditelne_zalozky(d) == ["Obecné", "Okno", "Zobrazit", "Klid", "Nálada", "Témata", "Upozornění",
                                    "Statistiky", "Agenti", "Povolení", "Pohyb", nastaveni.EDITOR]
    assert all(radek(d, p) for p in d.fields)
    assert "nastaveni" not in d.fields and "verze" not in d.fields and "temata.prikazy" not in d.fields


def test_prepinac_rezimu_se_pamatuje(home):
    before = config.render(config.defaults())
    write(before)
    d = nastaveni.Nastaveni()
    d.tlacitka_rezimu[nastaveni.POKROCILE].click()
    assert d.rezim == nastaveni.POKROCILE and "Nálada" in viditelne_zalozky(d)
    changed = sorted(diff(before, read()))
    assert len(changed) == 2 and changed[0].startswith('+nastaveni = "pokrocile" # dialog nastavení')
    assert changed[1].startswith('-nastaveni = "jednoduche" # dialog nastavení')
    assert d.zmeny() == {}                      # režim není neuložená změna
    d.reject()                                  # zapamatovaný zůstane i po Zrušit
    d2 = nastaveni.Nastaveni()
    assert d2.rezim == nastaveni.POKROCILE and d2.tlacitka_rezimu[nastaveni.POKROCILE].isChecked()
    d2.tlacitka_rezimu[nastaveni.JEDNODUCHE].click()
    assert read() == before and config.load()["nastaveni"] == "jednoduche"


def test_prepinac_bez_souboru(home):
    d = nastaveni.Nastaveni()
    d.prepnout(nastaveni.JEDNODUCHE)            # výchozí: soubor nevznikne
    assert not os.path.exists(d.path)
    d.prepnout(nastaveni.POKROCILE)
    cfg = config.load()
    assert cfg.exists and not cfg.errors and cfg["nastaveni"] == "pokrocile"
    assert "(zatím neexistuje)" not in d.where.text()


def test_rozbity_soubor_rezim_nezapise(home):
    write("[okno\n")
    d = nastaveni.Nastaveni()
    d.prepnout(nastaveni.POKROCILE)
    assert read() == "[okno\n" and d.rezim == nastaveni.POKROCILE


def test_nova_funkce_jednim_zaznamem(home, monkeypatch):
    """Budoucí funkce: výchozí hodnoty v config.py + záznam v POLOZKY; klíč bez záznamu je v Ostatní."""
    orig = config.defaults
    monkeypatch.setattr(config, "defaults", lambda: {**orig(), "bublina": {"zapnuta": True, "sirka": 30,
                                                                          "pismo": "malé"}})
    monkeypatch.setitem(config.ENUMS, "bublina.pismo", ("malé", "velké"))
    monkeypatch.setattr(nastaveni, "POLOZKY", nastaveni.POLOZKY + [
        nastaveni.Polozka("bublina.zapnuta", "Bublina s činností", "Bublina", nastaveni.JEDNODUCHE),
        nastaveni.Polozka("bublina.pismo", "Písmo", "Bublina")])
    write('[bublina]\nsirka = 40 # moje\n')
    d = nastaveni.Nastaveni()
    zal = viditelne_zalozky(d)
    assert zal[:3] == ["Obecné", "Okno", "Zobrazit"] and zal[-2:] == ["Bublina", nastaveni.EDITOR]
    assert zal.count("Bublina") == 1
    assert radek(d, "bublina.zapnuta") and not radek(d, "bublina.pismo")
    w = d.fields["bublina.pismo"].widget
    assert isinstance(w, QComboBox) and [w.itemData(i) for i in range(w.count())] == ["malé", "velké"]
    d.prepnout(nastaveni.POKROCILE, zapsat=False)
    assert viditelne_zalozky(d)[-3:] == ["Bublina", "Ostatní", nastaveni.EDITOR]
    assert d.tabs.tabText(d.tab_of["bublina.sirka"]) == "Ostatní" and d.fields["bublina.sirka"].get() == 40
    d.fields["bublina.zapnuta"].put(False)
    d.fields["bublina.sirka"].put(50)
    assert d.ulozit()
    assert read() == '[bublina]\nsirka = 50 # moje\nzapnuta = false\n'


def test_vsechny_klice_maji_zaznam(home):
    d = nastaveni.Nastaveni()
    assert "Ostatní" not in [d.tabs.tabText(i) for i in range(d.tabs.count())]
    for p in nastaveni.POLOZKY:
        assert p.rezim in (nastaveni.JEDNODUCHE, nastaveni.POKROCILE) and p.zalozka in nastaveni.ZALOZKY

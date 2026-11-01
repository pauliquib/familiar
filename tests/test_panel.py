import json, os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from familiar import panel, tune

TED = 1792648800.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def state(tmp_path, monkeypatch, app):
    """Dočasný XDG_STATE_HOME; skutečný ~/.local/state se nedotkne."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state" / "familiar" / "opravy.jsonl"


def test_vykresli_syntetickou_hodinu(state):
    w = panel.PanelNalady("robokun")
    w.nastav(panel.ukazka(TED))
    img = w.grab().toImage()
    assert img.width() >= 320 and img.height() >= 300
    assert len({img.pixel(x, y) for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)}) > 5
    assert "Radost" in w.hlava.text()
    assert "kód" in w.popis.text() and "pracuje" in w.popis.text()
    assert len(w.udalosti.text().splitlines()) == panel.UDALOSTI_N
    assert w.tlacitka["radost"].property("aktualni") is True


def test_prazdny_stav_a_cizi_druh_udalosti(state):
    w = panel.PanelNalady()
    w.nastav({"udalosti": [(TED, "user.prompt"), (TED + 1, "tohle je text promptu!")]})
    w.grab()
    text = w.udalosti.text()
    assert "prompt" in text and "text promptu" not in text and "?" in text


def test_oprava_vysle_signal_a_zapise_radek(state):
    w = panel.PanelNalady()
    w.nastav({**panel.ukazka(TED), "nalada": "klid", "signaly": {"korekce": 2, "zmatek": 1}})
    got = []
    w.oprava.connect(lambda p, o: got.append((p, o)))
    w.tlacitka["frustrace"].click()
    w.tlacitka["klid"].click()
    assert got == [("klid", "frustrace"), ("klid", "klid")]
    rows = [json.loads(line) for line in state.read_text().splitlines()]
    assert [(r["predikce"], r["oprava"]) for r in rows] == got
    v, a = w.stav["historie"][-1][1:]
    assert rows[0]["valence"] == round(v, 4) and rows[0]["aktivace"] == round(a, 4)
    assert rows[0]["signaly"] == {"korekce": 2, "zmatek": 1}
    assert "potvrzeno" in w.zprava.text()


def test_oprava_bez_zapisu_ukaze_chybu(state, tmp_path):
    (tmp_path / "soubor").write_text("")
    w = panel.PanelNalady(cesta=str(tmp_path / "soubor" / "opravy.jsonl"))     # rodič není adresář
    got = []
    w.oprava.connect(lambda p, o: got.append(o))
    w.tlacitka["radost"].click()
    assert got == [] and "Neuloženo" in w.zprava.text()

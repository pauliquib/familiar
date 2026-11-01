import io, json, os, random

import pytest

from familiar import mood, tune

PRAHY = mood.defaults()["prahy"]


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Dočasný XDG_STATE_HOME i HOME; skutečný ~/.local/state se nedotkne."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path / "state" / "familiar" / "opravy.jsonl"


def test_soubor_z_xdg_state_home(state, monkeypatch, tmp_path):
    assert tune.soubor() == str(state)
    monkeypatch.delenv("XDG_STATE_HOME")
    assert tune.soubor() == str(tmp_path / ".local" / "state" / "familiar" / "opravy.jsonl")


def test_radek_obsahuje_jen_stitky_cisla_a_cas(state):
    tune.uloz_opravu("klid", "radost", 0.123456, 0.3, 1792648800.5, {"dekovani": 1, "unava": 0.25})
    tune.uloz_opravu("frustrace", "frustrace", -0.5, 0.7, 1792648900.0)
    lines = state.read_text().splitlines()
    assert len(lines) == 2
    r = json.loads(lines[0])
    assert r == {"ts": 1792648800.5, "predikce": "klid", "oprava": "radost", "valence": 0.1235,
                 "aktivace": 0.3, "signaly": {"dekovani": 1, "unava": 0.25}}
    assert set(json.loads(lines[1])) == {"ts", "predikce", "oprava", "valence", "aktivace"}
    for line in lines:
        for k, v in json.loads(line).items():
            if k in ("predikce", "oprava"):
                assert v in tune.STITKY
            elif k == "signaly":
                assert set(v) <= tune.SIGNALY and all(isinstance(x, (int, float)) for x in v.values())
            else:
                assert isinstance(v, (int, float))
    assert oct(os.stat(state).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("args", [
    ("klid", "naštvaný", 0, 0, 1.0),                    # štítek mimo mood
    ("klid", "radost", "0.1", 0, 1.0),                  # text místo čísla
    ("klid", "radost", 0, 2, 1.0),                      # mimo rozsah
    ("klid", "radost", float("nan"), 0, 1.0),
    ("klid", "radost", 0, 0, 1.0, {"prompt": 1}),       # neznámý signál
    ("klid", "radost", 0, 0, 1.0, {"korekce": "ne, to jsem nemyslel"}),
])
def test_nic_jineho_se_nezapise(state, args):
    with pytest.raises(ValueError):
        tune.uloz_opravu(*args)
    assert not state.exists()


def test_odhad_odpovida_prahum_enginu():
    e = mood.MoodEngine(0.0)
    for v, a in [(-0.5, 0.7), (0.4, 0.2), (0.0, 0.2), (-0.2, 0.9), (0.29, 0.5)]:
        e.v, e.a = v, a
        assert tune.odhad(v, a, PRAHY) == e._classify()
    e.v, e.a, e.questions = 0.1, 0.5, [True, True, False]
    assert tune.odhad(0.1, 0.5, PRAHY, {"otazek": 3, "podil_otazek": 2 / 3}) == e._classify() == mood.ZVEDAVOST
    assert tune.odhad(0.1, 0.5, PRAHY) == mood.KLID      # bez údaje o otázkách
    assert tune.odhad(0.5, 0.1, PRAHY, {"zmatek": 2}) == mood.ZMATEK
    assert tune.odhad(0.5, 0.1, PRAHY, {"unava": 0.8}) == mood.UNAVA


def _zapis(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _radek(i, pred, opr, v=0.0, a=0.2, **signaly):
    return {"ts": 1792648800.0 + i, "predikce": pred, "oprava": opr, "valence": v, "aktivace": a,
            "signaly": signaly}


def test_presnost_matice_a_nesplnena_brana(state):
    rows = [_radek(i, "klid", "klid") for i in range(7)] + [_radek(7 + i, "klid", "radost") for i in range(3)]
    _zapis(state, rows)
    with open(state, "a") as f:
        f.write("nejde o json\n")
    rep = tune.spocitej(str(state))
    assert (rep["zaznamu"], rep["trefa"], rep["vadnych"]) == (10, 7, 1)
    assert rep["presnost"] == 0.7
    assert rep["matice"]["klid"]["radost"] == 3 and rep["matice"]["klid"]["klid"] == 7
    assert rep["brana"] == {"splneno": False, "chybi_zaznamu": 40, "chybi_trefa": 40}
    assert rep["navrh"] is None             # málo dat


def test_brana_splnena_a_chybejici_trefy(state):
    _zapis(state, [_radek(i, "klid", "klid") for i in range(35)] + [_radek(35 + i, "klid", "zmatek") for i in range(15)])
    rep = tune.spocitej(str(state))
    assert rep["brana"]["splneno"] and rep["presnost"] == 0.7
    _zapis(state, [_radek(i, "klid", "klid") for i in range(30)] + [_radek(30 + i, "klid", "zmatek") for i in range(30)])
    b = tune.spocitej(str(state))["brana"]
    # 30/60: potřeba k dalších trefených, aby (30 + k) / (60 + k) ≥ 0,7 → k = 40
    assert b == {"splneno": False, "chybi_zaznamu": 0, "chybi_trefa": 40}


def test_navrh_posune_prah_radosti(state):
    rnd = random.Random(1)
    rows = []
    for i in range(30):         # familiar čte klid, ale ty máš radost už od valence ~0,2
        v = rnd.uniform(0.18, 0.28)
        rows.append(_radek(i, "klid", "radost", v=v))
    for i in range(30):
        rows.append(_radek(100 + i, "klid", "klid", v=rnd.uniform(-0.2, 0.1)))
    for i in range(10):
        rows.append(_radek(200 + i, "radost", "radost", v=rnd.uniform(0.35, 0.8)))
    _zapis(state, rows)
    rep = tune.spocitej(str(state))
    nav = rep["navrh"]
    assert set(nav["prahy"]) == {"radost_valence"}
    assert 0.1 < nav["prahy"]["radost_valence"] <= 0.18
    assert nav["po"] > nav["nyni"]
    out = io.StringIO()
    tune.vypis(rep, out)
    text = out.getvalue()
    assert "[nalada.prahy]" in text and "radost_valence = 0.1" in text and "# bylo 0.30" in text
    assert "nesplněno" in text


def test_bez_zlepseni_zadny_navrh(state):
    rnd = random.Random(2)
    rows = [_radek(i, "klid", rnd.choice(["radost", "klid"]), v=0.0) for i in range(40)]
    _zapis(state, rows)
    assert tune.spocitej(str(state))["navrh"]["prahy"] == {}


def test_main_vypis_a_chybejici_soubor(state, capsys):
    assert tune.main([]) == 0
    assert "Zatím žádné opravy" in capsys.readouterr().out
    assert not state.exists()
    _zapis(state, [_radek(i, "klid", "klid") for i in range(3)])
    assert tune.main(["--soubor", str(state)]) == 0
    out = capsys.readouterr().out
    assert "Přesnost: 100,0 % (3/3)" in out and "Brána fáze 1" in out and "chybí 47 záznamů" in out

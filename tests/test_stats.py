import json, os, stat
from datetime import date, datetime, timedelta, timezone

import pytest

from familiar import stats
from familiar.stats import Statistiky

UTC = timezone.utc
T0 = datetime(2026, 10, 21, 10, 0, tzinfo=UTC).timestamp()   # středa 10:00 UTC


def ev(kind, ts, pid=7, session="s1", **data):
    return {"v": 1, "source": "claude-code", "session": session, "pid": pid, "ts": ts, "kind": kind, "data": data}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state" / "familiar" / "statistiky.json"


def test_soubor_v_xdg_state(state):
    assert stats.soubor() == str(state)
    assert Statistiky().cesta == str(state)


def test_citace_a_nastroje(state):
    s = Statistiky(tz=UTC)
    for e in [ev("session.start", T0, how="startup", cwd="/tajne/cesta"),
              ev("user.prompt", T0 + 1, text="tajný prompt"),
              ev("tool.start", T0 + 2, tool="Bash", cmd="rm -rf /tajne"),
              ev("tool.error", T0 + 3, tool="Bash", code=1, error="tajná chyba"),
              ev("tool.start", T0 + 4, tool="Read"),
              ev("tool.start", T0 + 5, tool="Bash"),
              ev("tool.start", T0 + 5, tool="divný název\n s mezerou"),
              ev("tool.denied", T0 + 6, tool="Bash"),
              ev("subagent.start", T0 + 7, type="Explore"),
              ev("context.compact", T0 + 8, trigger="auto"),
              ev("session.start", T0 + 9, how="compact"),     # po compactu není nová session
              ev("agent.failed", T0 + 10, error="x"),
              ev("agent.done", T0 + 11)]:
        s.zapocti(e)
    d = s.den("2026-10-21")
    assert (d["session"], d["prompty"], d["chyby"], d["zamitnuti"], d["subagenti"], d["compacty"],
            d["selhani"]) == (1, 1, 1, 1, 1, 1, 1)
    assert d["nastroje"] == {"Bash": 2, "Read": 1, "jiny": 1} and d["volani"] == 4


def test_aktivni_cas_a_preruseni(state):
    s = Statistiky(tz=UTC)
    s.zapocti(ev("user.prompt", T0))
    s.zapocti(ev("agent.done", T0 + 60))
    s.zapocti(ev("user.prompt", T0 + 100))
    s.zapocti(ev("agent.interrupted", T0 + 130))
    s.zapocti(ev("agent.interrupted", T0 + 131, tool_use=True))   # dvojí hlášení téhož přerušení
    s.zapocti(ev("user.prompt", T0 + 120, pid=8, session="s2"))   # jiné okno souběžně: nezdvojí se
    s.zapocti(ev("session.end", T0 + 140, pid=8, session="s2"))
    d = s.den(date(2026, 10, 21))
    assert d["aktivni_s"] == 140 and d["session"] == 2
    assert d["preruseni"] == 1
    s.zapocti(ev("user.prompt", T0 + 1000))             # přestávka delší než MEZERA_S se nepočítá
    s.zapocti(ev("agent.interrupted", T0 + 1010))
    d = s.den("2026-10-21")
    assert d["preruseni"] == 2 and d["aktivni_s"] == 150


def test_aktivni_cas_bez_promptu_subagenti_a_dlouhy_nastroj(state):
    s = Statistiky(tz=UTC)
    s.zapocti(ev("agent.done", T0))
    # úloha na pozadí probudí agenta bez UserPromptSubmit, pracují subagenti
    s.zapocti(ev("subagent.start", T0 + 200, agent="a1", type="Explore"))
    s.zapocti(ev("tool.start", T0 + 400, agent="a1", tool="Read", id="r1"))
    s.zapocti(ev("tool.end", T0 + 401, agent="a1", tool="Read", id="r1"))
    s.zapocti(ev("agent.done", T0 + 500))
    assert s.den("2026-10-21")["aktivni_s"] == 500
    s.zapocti(ev("tool.start", T0 + 600, tool="Bash", id="b1"))     # dlouhý build
    s.zapocti(ev("tool.end", T0 + 600 + 1200, tool="Bash", id="b1"))
    assert s.den("2026-10-21")["aktivni_s"] == 500 + 100 + 1200
    s.zapocti(ev("tool.start", T0 + 5000, tool="Bash", id="b2"))     # zapomenutý nástroj: strop
    s.zapocti(ev("agent.done", T0 + 5000 + 3 * 3600))
    assert s.den("2026-10-21")["aktivni_s"] == 1800


def test_aktivni_cas_a_session_preziji_restart(state):
    s = Statistiky(tz=UTC)
    s.zapocti(ev("user.prompt", T0, session="s1"))
    s.zapocti(ev("tool.start", T0 + 50, session="s2", pid=8, tool="Bash"))
    s.uloz(T0 + 50, vynutit=True)
    raw = state.read_text()
    assert "s1" not in json.loads(raw)["stav"]["session"] and stats.otisk("s1") in raw
    s2 = Statistiky(tz=UTC)                         # restart daemonu, session běží dál
    s2.zapocti(ev("agent.done", T0 + 100, session="s1"))
    s2.zapocti(ev("user.prompt", T0 + 110, session="s3", pid=9))
    d = s2.den("2026-10-21")
    assert d["aktivni_s"] == 110 and d["session"] == 3


def test_session_ze_starsiho_souboru(state):
    os.makedirs(state.parent)
    state.write_text(json.dumps({"v": 1, "dny": {"2026-10-21": {"session": 4, "aktivni_s": 60.0}}}))
    s = Statistiky(tz=UTC)
    assert s.den("2026-10-21")["session"] == 4
    for i, sid in enumerate(["a", "b", "a", "c"]):
        s.zapocti(ev("tool.start", T0 + i, session=sid, tool="Bash"))
    assert s.den("2026-10-21")["session"] == 4      # dřívější počet se nezdvojí
    for sid in ["d", "e"]:
        s.zapocti(ev("tool.start", T0 + 10, session=sid, tool="Bash"))
    assert s.den("2026-10-21")["session"] == 5 and s.den("2026-10-21")["aktivni_s"] == 70


def test_kolo_pres_pulnoc(state):
    s = Statistiky(tz=UTC)
    pulnoc = datetime(2026, 10, 22, tzinfo=UTC).timestamp()
    for t in (-600, -300, 0, 300):
        s.zapocti(ev("tool.start", pulnoc + t, tool="Bash"))
    assert s.den("2026-10-21")["aktivni_s"] == 600
    assert s.den("2026-10-22")["aktivni_s"] == 300
    assert s.den("2026-10-21")["session"] == s.den("2026-10-22")["session"] == 1


def test_nalada_hodinove_prumery(state):
    s = Statistiky(tz=UTC)
    s.vzorek_nalady(T0, 0.5, 0.2)
    s.vzorek_nalady(T0 + 60, -0.1, 0.4)
    s.vzorek_nalady(T0 + 3600, 3.0, -1)          # oříznutí
    s.vzorek_nalady(T0, float("nan"), 0.1)       # zahozeno
    s.vzorek_nalady(T0, "x", 0.1)
    d = s.den("2026-10-21")
    assert d["nalada"] == {10: (0.2, 0.3), 11: (1.0, 0.0)}
    t = s.tyden("2026-10-23")
    assert t["soucet"]["nalada"] == (round(1.4 / 3, 4), 0.2)


def test_tyden(state):
    s = Statistiky(tz=UTC)
    s.zapocti(ev("user.prompt", T0))                                   # středa
    s.zapocti(ev("tool.start", T0 + 1, tool="Bash"))
    s.zapocti(ev("tool.start", T0 + 2 * 86400, tool="Bash"))          # pátek
    s.zapocti(ev("tool.start", T0 + 5 * 86400, tool="Read"))          # další pondělí
    t = s.tyden(date(2026, 10, 25))
    assert (t["od"], t["do"]) == ("2026-10-19", "2026-10-25")
    assert len(t["dny"]) == 7 and t["dny"][2]["prompty"] == 1
    assert t["soucet"]["nastroje"] == {"Bash": 2} and t["soucet"]["volani"] == 2
    assert t["soucet"]["nalada"] is None
    assert s.den("1999-01-01")["volani"] == 0 and s.den("nesmysl")["datum"] is None


def test_ulozeni_atomicke_0600_throttled(state):
    s = Statistiky(tz=UTC, interval_s=60)
    assert s.uloz(T0) is False                      # nic se nezměnilo
    s.zapocti(ev("user.prompt", T0, text="TAJNY_PROMPT"))
    s.zapocti(ev("tool.start", T0, tool="Bash", cmd="echo TAJNY_PRIKAZ"))
    s.zapocti(ev("session.start", T0, cwd="/home/TAJNA_CESTA"))
    assert s.uloz(T0) is True
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o600
    s.zapocti(ev("tool.start", T0 + 1, tool="Read"))
    assert s.uloz(T0 + 30) is False                 # throttling
    assert s.uloz(T0 + 30, vynutit=True) is True
    raw = state.read_text()
    assert "TAJN" not in raw
    assert [p.name for p in state.parent.iterdir()] == ["statistiky.json"]   # žádné dočasné soubory
    s2 = Statistiky(tz=UTC)
    assert s2.den("2026-10-21")["nastroje"] == {"Bash": 1, "Read": 1}


def test_retence(state):
    s = Statistiky(tz=UTC, retence_dni=30)
    s.zapocti(ev("user.prompt", T0 - 40 * 86400))
    s.zapocti(ev("user.prompt", T0 - 10 * 86400))
    s.uloz(T0, vynutit=True)
    dny = json.loads(state.read_text())["dny"]
    assert sorted(dny) == [(date(2026, 10, 21) - timedelta(days=10)).isoformat()]


def test_rozbity_soubor_zaloha(state):
    state.parent.mkdir(parents=True)
    state.write_text("{nejde to")
    s = Statistiky(tz=UTC)
    assert s.dny == {}
    assert any(p.name.startswith("statistiky.json.vadny-") for p in state.parent.iterdir())
    s.zapocti(ev("user.prompt", T0))
    assert s.uloz(T0) is True


def test_vadna_data_se_vycisti(state):
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"v": 1, "dny": {
        "2026-10-21": {"prompty": 3, "chyby": -5, "nastroje": {"Bash": 2, "zlé jméno": 1, "X": "a"},
                       "aktivni_s": 1e9, "nalada": {"10": [1.0, 0.5, 2], "99": [1, 1, 1], "11": "x"},
                       "text": "nemá tu co dělat"},
        "není datum": {}, "2026-10-20": "x"}}))
    s = Statistiky(tz=UTC)
    d = s.den("2026-10-21")
    assert d["prompty"] == 3 and d["chyby"] == 0 and d["nastroje"] == {"Bash": 2, "X": 0}
    assert d["aktivni_s"] == 0 and d["nalada"] == {10: (0.5, 0.25)}
    assert sorted(s.dny) == ["2026-10-20", "2026-10-21"]


def test_nikdy_nevyhodi(state, monkeypatch):
    s = Statistiky(tz=UTC)
    for bad in [{}, {"kind": "user.prompt"}, {"kind": "user.prompt", "ts": "x"}, {"kind": 1, "ts": T0},
                {"kind": "tool.start", "ts": T0, "data": None}, {"kind": "user.prompt", "ts": float("inf")}]:
        s.zapocti(bad)
    s.vzorek_nalady(None, None, None)

    def boom(*a):
        raise OSError("disk plný")
    monkeypatch.setattr(stats.uloziste, "zapis", boom)
    s.zapocti(ev("user.prompt", T0))
    assert s.uloz(T0, vynutit=True) is False and s.zmeneno


def test_neprectitelny_adresar(tmp_path):
    s = Statistiky(cesta=str(tmp_path / "soubor" / "x.json"), tz=UTC)
    (tmp_path / "soubor").write_text("tohle je soubor, ne adresář")
    s.zapocti(ev("user.prompt", T0))
    assert s.uloz(T0) is False

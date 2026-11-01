import json, os, stat
from datetime import datetime, timezone

import pytest

from familiar import progress
from familiar.progress import Postup, je_test, uroven_z_xp, xp_na_uroven

UTC = timezone.utc
T0 = datetime(2026, 10, 21, 10, 0, tzinfo=UTC).timestamp()   # středa 10:00 UTC
DEN = 86400


def ev(kind, ts, pid=7, session="s1", **data):
    return {"v": 1, "source": "claude-code", "session": session, "pid": pid, "ts": ts, "kind": kind, "data": data}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state" / "familiar" / "postup.json"


def ids(nove):
    return [u["id"] for u in nove]


def test_je_test():
    for cmd in ["pytest -q", "python3 -m pytest -q tests", "python -m unittest", "uv run pytest",
                "npm test", "npm run test -- --watch=false", "pnpm test", "cargo test --all", "go test ./...",
                "cd /repo && pytest", "CI=1 npx vitest run", "timeout 60 cargo test", "make test",
                "./gradlew test", "mvn -q test"]:
        assert je_test(cmd), cmd
    for cmd in ["git status", "echo pytest", "npm install", "pytestish", "cat tests/test_x.py", "", None, 42]:
        assert not je_test(cmd), cmd


def test_krivka_urovni():
    assert [xp_na_uroven(n) for n in (1, 2, 3, 4)] == [0, 100, 250, 450]
    assert uroven_z_xp(0) == 1 and uroven_z_xp(99) == 1 and uroven_z_xp(100) == 2 and uroven_z_xp(449) == 3
    assert all(xp_na_uroven(n + 1) - xp_na_uroven(n) == 100 + 50 * (n - 1) for n in range(1, 50))
    assert uroven_z_xp(10**9) == progress.MAX_UROVEN


def test_uspechy_a_doplnky_jsou_platna_data():
    assert 20 <= len(progress.USPECHY) <= 30
    for k, (nazev, popis, podm) in progress.USPECHY.items():
        assert nazev and popis and callable(podm)
    for k, (druh, nazev, p) in progress.DOPLNKY.items():
        assert druh in ("klobouk", "emote") and nazev
        assert ("uroven" in p) != ("uspech" in p)
        assert p.get("uspech", "prvni_session") in progress.USPECHY


def test_prvni_session_a_ciste_kolo(state):
    p = Postup(tz=UTC)
    assert p.uroven == 1 and p.xp == 0 and p.do_dalsi == 100
    assert ids(p.zapocti(ev("session.start", T0, how="startup"))) == ["prvni_session"]
    assert p.xp == progress.XP_DEN + progress.XP_SESSION
    p.zapocti(ev("user.prompt", T0 + 1, text="cokoli"))
    p.zapocti(ev("tool.start", T0 + 2, tool="Read"))
    p.zapocti(ev("tool.end", T0 + 3, tool="Read"))
    nove = p.zapocti(ev("agent.done", T0 + 4))
    assert ids(nove) == ["prvni_kolo"] and nove[0]["nazev"] == "Hotovo!" and nove[0]["cas"] == T0 + 4
    assert p.xp == progress.XP_DEN + progress.XP_SESSION + progress.XP_NASTROJ + progress.XP_KOLO
    assert p.do_dalsi == 100 - p.xp
    u = {x["id"]: x for x in p.uspechy()}
    assert u["prvni_kolo"]["odemceno"] and u["prvni_kolo"]["cas"] == T0 + 4
    assert not u["nocni_sova"]["odemceno"] and u["nocni_sova"]["cas"] is None
    assert p.zapocti(ev("agent.done", T0 + 5)) == []     # kolo bez promptu se nepočítá


def test_kolo_s_chybou_a_oprava(state):
    p = Postup(tz=UTC)
    p.zapocti(ev("user.prompt", T0))
    p.zapocti(ev("tool.error", T0 + 1, tool="Edit", code=None))
    xp = p.xp
    assert "prvni_oprava" in ids(p.zapocti(ev("tool.end", T0 + 2, tool="Edit")))
    assert p.xp == xp + progress.XP_OPRAVA
    p.zapocti(ev("tool.error", T0 + 3, tool="Edit"))
    p.zapocti(ev("tool.end", T0 + 4, tool="Edit"))         # druhá oprava v kole už XP nedá
    assert p.xp == xp + progress.XP_OPRAVA
    assert "prvni_kolo" not in ids(p.zapocti(ev("agent.done", T0 + 5)))
    assert p.c["kola_cista"] == 0


def test_testy_serie_a_oprava(state):
    p = Postup(tz=UTC)
    p.zapocti(ev("user.prompt", T0))
    nove = p.zapocti(ev("tool.end", T0 + 1, tool="Bash", cmd="python3 -m pytest -q tests"))
    assert ids(nove) == ["zelene_testy"]
    p.zapocti(ev("tool.error", T0 + 2, tool="Bash", cmd="pytest -q", code=1))
    assert p.c["serie_testu"] == 0
    nove = p.zapocti(ev("tool.end", T0 + 3, tool="Bash", cmd="pytest -q"))
    assert "oprava_testu" in ids(nove)
    p.zapocti(ev("tool.end", T0 + 4, tool="Bash", cmd="pytest", killed=True))   # zabitý se nepočítá
    p.zapocti(ev("tool.end", T0 + 4, tool="Bash", cmd="ls"))                    # jiný příkaz sérii nepřeruší
    got = []
    for i in range(9):
        got += ids(p.zapocti(ev("tool.end", T0 + 5 + i, tool="Bash", cmd="cargo test")))
    assert got == ["testy_10"] and p.c["max_serie_testu"] == 10
    assert "emote_zelena" in [d["id"] for d in p.odemcene_doplnky()]


def test_den_serie_vikend_noc(state):
    p = Postup(tz=UTC)
    noc = datetime(2026, 10, 19, 2, 30, tzinfo=UTC).timestamp()     # pondělí 2:30
    assert "nocni_sova" in ids(p.zapocti(ev("user.prompt", noc)))
    assert "ranni_ptace" in ids(p.zapocti(ev("user.prompt", noc + 3 * 3600)))
    assert "klobouk_cepicka" in [d["id"] for d in p.odemcene_doplnky()]
    p.zapocti(ev("tool.start", noc + DEN))
    assert "serie_3" in ids(p.zapocti(ev("tool.start", noc + 2 * DEN)))
    p.zapocti(ev("tool.start", noc + 2 * DEN + 60))                  # stejný den: bez bonusu
    assert p.c["serie"] == 3 and p.c["aktivnich_dni"] == 3
    p.zapocti(ev("tool.start", noc + 4 * DEN))                       # mezera → série znovu
    assert p.c["serie"] == 1 and p.c["max_serie"] == 3
    assert "vikend" in ids(p.zapocti(ev("tool.start", noc + 5 * DEN)))   # sobota


def test_compact_preziti_a_dlouha_session(state):
    p = Postup(tz=UTC)
    p.zapocti(ev("session.start", T0, how="startup"))
    p.zapocti(ev("user.prompt", T0 + 1))
    p.zapocti(ev("context.compact", T0 + 2, trigger="auto"))
    p.zapocti(ev("session.start", T0 + 3, how="compact"))
    assert p.c["session"] == 1
    assert "compact" in ids(p.zapocti(ev("agent.done", T0 + 4)))
    t = T0 + 4
    while t < T0 + progress.DLOUHA_S - 600:             # práce s pauzami kratšími než přestávka
        t += 600
        assert "maraton" not in ids(p.zapocti(ev("tool.start", t, tool="Read")))
    assert "maraton" in ids(p.zapocti(ev("tool.start", T0 + progress.DLOUHA_S, tool="Read")))
    p.zapocti(ev("tool.start", T0 + progress.DLOUHA_S + 2, tool="Read"))
    assert p.c["dlouhe_session"] == 1
    q = Postup(cesta=str(state) + ".q", tz=UTC)          # s přestávkou se maraton nepočítá
    q.zapocti(ev("tool.start", T0, tool="Read"))
    q.zapocti(ev("tool.start", T0 + 3600, tool="Read"))
    q.zapocti(ev("tool.start", T0 + progress.DLOUHA_S, tool="Read"))
    assert q.c["dlouhe_session"] == 0


def test_preruseni_jednou_za_kolo(state):
    p = Postup(tz=UTC)
    p.zapocti(ev("user.prompt", T0))
    assert "zarazit" in ids(p.zapocti(ev("agent.interrupted", T0 + 1)))
    p.zapocti(ev("agent.interrupted", T0 + 2, tool_use=True))
    assert p.c["preruseni"] == 1
    p.zapocti(ev("agent.done", T0 + 3))
    assert p.c["kola_cista"] == 0


def test_strop_xp_za_nastroje(state):
    p = Postup(tz=UTC)
    for i in range(progress.XP_NASTROJE_DEN + 50):
        p.zapocti(ev("tool.start", T0 + i, tool="Read"))
    assert p.xp == progress.XP_DEN + progress.XP_NASTROJE_DEN
    assert p.c["nastroje"] == progress.XP_NASTROJE_DEN + 50
    p.zapocti(ev("tool.start", T0 + DEN, tool="Read"))
    assert p.xp == 2 * progress.XP_DEN + progress.XP_NASTROJE_DEN + 1


def test_deterministicke(state, tmp_path):
    evs = [ev("session.start", T0, how="startup"), ev("user.prompt", T0 + 1)]
    evs += [ev("tool.start", T0 + 2 + i, tool=f"T{i % 12}") for i in range(120)]
    evs += [ev("subagent.start", T0 + 200, type="Explore"), ev("agent.done", T0 + 300)]
    a, b = Postup(cesta=str(tmp_path / "a.json"), tz=UTC), Postup(cesta=str(tmp_path / "b.json"), tz=UTC)
    na = [ids(a.zapocti(e)) for e in evs]
    nb = [ids(b.zapocti(e)) for e in evs]
    assert na == nb and a.xp == b.xp and a.uspechy() == b.uspechy()
    vse = sum(na, [])
    assert {"sberatel", "nastroje_100", "prvni_subagent"} <= set(vse)
    assert a.uroven == uroven_z_xp(a.xp) >= 2


def test_ulozeni_a_nacteni(state):
    p = Postup(tz=UTC)
    p.zapocti(ev("session.start", T0, how="startup", cwd="/home/TAJNA_CESTA"))
    p.zapocti(ev("user.prompt", T0 + 1, text="TAJNY_PROMPT"))
    p.zapocti(ev("tool.end", T0 + 2, tool="Bash", cmd="pytest TAJNY_PRIKAZ"))
    p.zapocti(ev("tool.error", T0 + 3, tool="Bash", cmd="pytest", error="TAJNA_CHYBA"))
    assert p.uloz(T0) is True
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o600
    assert "TAJN" not in state.read_text()
    assert p.uloz(T0 + 1) is False                   # nic nového
    p.zapocti(ev("tool.start", T0 + 4, tool="Grep"))
    assert p.uloz(T0 + 10) is False                  # throttling
    assert p.uloz(T0 + 61) is True
    q = Postup(tz=UTC)
    assert (q.xp, q.c, q.odemceno, q.nazvy, q.posledni_den) == (p.xp, p.c, p.odemceno, p.nazvy, p.posledni_den)
    assert q.xp_den == p.xp_den
    assert "oprava_testu" in ids(q.zapocti(ev("tool.end", T0 + 70, tool="Bash", cmd="pytest")))   # červené přežily


def test_rozbity_a_vadny_soubor(state):
    state.parent.mkdir(parents=True)
    state.write_text("[1, 2")
    p = Postup(tz=UTC)
    assert p.xp == 0 and p.odemceno == {}
    assert any(x.name.startswith("postup.json.vadny-") for x in state.parent.iterdir())
    state.write_text(json.dumps({"xp": -3, "citace": {"session": "x", "prompty": 4}, "uspechy": {
        "neexistuje": 1, "prvni_session": 5}, "nastroje": ["Bash", "zlé jméno", 3], "posledni_den": "včera"}))
    p = Postup(tz=UTC)
    assert p.xp == 0 and p.c["session"] == 0 and p.c["prompty"] == 4
    assert p.odemceno == {"prvni_session": 5.0} and p.nazvy == {"Bash"} and p.posledni_den is None


def test_nikdy_nevyhodi(state, monkeypatch):
    p = Postup(tz=UTC)
    for bad in [{}, {"kind": "x"}, {"kind": "user.prompt", "ts": None}, {"kind": "tool.end", "ts": T0, "data": 5}]:
        assert p.zapocti(bad) == []

    def boom(*a):
        raise OSError("disk plný")
    monkeypatch.setattr(progress.uloziste, "zapis", boom)
    p.zapocti(ev("user.prompt", T0))
    assert p.uloz(T0, vynutit=True) is False

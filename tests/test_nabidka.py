# M3B: nabídka postavičky a lišty, uspání, panel nálady napojený na hub, CLI tune, doctor tray.
import json, os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from familiar import cli, config, doctor, dock, kwin, nabidka, paths
from familiar.hub import HIST_N, HIST_S, Hub

SECRET = "UNIKATNI-PROMPT-91bd"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch, app):
    """Dočasný HOME, XDG_CONFIG_HOME a XDG_STATE_HOME; KWin jen naoko."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")       # backend oken kwin, KWin naoko
    monkeypatch.setattr(kwin, "load", lambda: True)
    monkeypatch.setattr(kwin, "unload", lambda: None)
    return tmp_path


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": "s", "cwd": f"/home/x/projekt{pid}", **raw}}


@pytest.fixture
def ui(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    hub.receive(msg(0, "SessionStart"))
    views = dock.Views(hub, None, config.load(), "dock")

    def written():
        views.apply(config.load())
    u = nabidka.Ovladani(hub, views, written, tray=False)
    views.ui = u
    yield u
    for p in list(u.panely.values()):
        p.close()
    views.view.close()


KEEP = []      # nabídky musí žít, dokud test kliká na jejich akce


def nab(ui, key):
    """{text: akce} nabídky postavičky (key) nebo lišty (None)."""
    m = QMenu()
    KEEP.append(m)
    return actions(ui.naplnit(m, key))


def actions(menu):
    """{text: akce} včetně podnabídek (klíč „Podnabídka/položka“)."""
    out = {}
    for a in menu.actions():
        if a.menu():
            out[a.text()] = a
            for b in a.menu().actions():
                out[f"{a.text()}/{b.text()}"] = b
        elif a.text():
            out[a.text()] = a
    return out


def click(action):
    action.trigger()
    QApplication.processEvents()        # akce běží po zavření nabídky (QTimer 0)


def test_nabidka_postavicky_a_listy(ui):
    m = nab(ui, 7)
    for text in ("Panel nálady…", "Ztlumit emoty", "Uspat", "Režim soustředění", "Přepnout na perch",
                 "Skin", "Nastavení…", "Ukončit familiara"):
        assert text in m, text
    skins = {k: a for k, a in m.items() if k.startswith("Skin/")}
    assert "Skin/Robo-kun" in skins and skins["Skin/Robo-kun"].isChecked()
    assert sum(a.isChecked() for a in skins.values()) == 1
    t = nab(ui, None)
    assert "Uspat všechny" in t and "Panel nálady/projekt7" in t and "Uspat" not in t


def test_prepinace_zapisou_config_az_pri_zmene(ui, home):
    path = paths.config_file()
    m = nab(ui, 7)
    click(m["Skin/Robo-kun"])           # už zvolený: nic se nezapíše
    assert not os.path.exists(path)
    click(m["Ztlumit emoty"])
    assert config.load()["zobrazit"]["emoty"] is False and ui.hub.fams[7].emotes is False
    m = nab(ui, 7)
    assert m["Ztlumit emoty"].isChecked()
    click(m["Režim soustředění"])
    assert config.load()["soustredeni"] is True and ui.hub.fams[7].focus
    click(m["Skin/Robo-kun Rubín"])
    assert config.load()["skin"] == "rubin" and ui.hub.skin.id == "rubin"
    text = open(path, encoding="utf-8").read()
    assert "# " in text         # komentáře výchozího souboru zůstaly (upravit_text)


def test_prepnuti_rezimu(ui):
    assert ui.views.mode == "dock"
    click(nab(ui, 7)["Přepnout na perch"])
    assert ui.views.mode == "perch" and config.load()["rezim"] == "perch" and ui.views.forced is None
    click(nab(ui, 7)["Přepnout na dock"])
    assert ui.views.mode == "dock" and config.load()["rezim"] == "dock"


def test_rozbity_config_se_neprepise(ui):
    path = paths.config_file()
    os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        f.write("rezim = [\n")
    click(nab(ui, 7)["Režim soustředění"])
    assert open(path).read() == "rezim = [\n"
    assert ui._hlaska is not None and ui._hlaska.isVisible()      # bez lišty nemodální upozornění
    assert not nab(ui, None)["Režim soustředění"].isChecked() and not ui.cfg["soustredeni"]
    ui._hlaska.close()


def test_demo_nezapisuje(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    hub.receive(msg(0, "SessionStart"))
    views = dock.Views(hub, None, config.load(), "dock", demo=True)
    u = nabidka.Ovladani(hub, views, lambda: 1 / 0, tray=False, demo=True)
    m = nab(u, 7)
    assert not m["Nastavení… (ne v demu)"].isEnabled() and not m["Přepnout na perch"].isEnabled()
    click(m["Režim soustředění"])
    click(m["Skin/Robo-kun Rubín"])
    assert views.cfg["soustredeni"] and hub.fams[7].focus and hub.skin.id == "rubin"
    assert not os.path.exists(paths.config_file())
    p = u.otevri_panel(7)
    assert p.cesta == os.devnull
    p.opravit("radost")
    assert not (home / "state").exists()
    p.close()
    views.view.close()


def test_uspani(ui):
    hub, fam = ui.hub, ui.hub.fams[7]
    click(nab(ui, 7)["Uspat"])
    assert fam.spi and not hub.spi and fam.title_state == "sleeping"
    fam._queue("srdce")
    assert fam.update(10)[0] == fam.skin.anim_for("sleeping") and fam.pops == []
    click(nab(ui, 7)["Uspat"])
    assert not fam.spi and fam.title_state != "sleeping"
    click(nab(ui, None)["Uspat všechny"])
    hub.receive(msg(20, "SessionStart", pid=8))
    assert hub.spi and fam.spi and hub.fams[8].spi
    assert nab(ui, None)["Uspat všechny"].isChecked()
    hub.uspat(False, 7)         # probuzení jedné ruší „spí všichni“
    assert not hub.spi and not fam.spi and hub.fams[8].spi
    assert not nab(ui, None)["Uspat všechny"].isChecked()
    hub.uspat(False)
    assert not any(f.spi for f in hub.fams.values())


def test_dvoji_preruseni_jen_jednou(home, tmp_path):
    hub = Hub(reap=False, bind=False)
    tr = tmp_path / "t.jsonl"
    tr.write_text("")
    hub.receive(msg(0, "UserPromptSubmit", prompt="x", transcript_path=str(tr)))
    assert hub.poll_transcripts(0.5) == []     # od teď projde i přerušení bez času záznamu
    hub.receive(msg(1, "PreToolUse", tool_name="Bash", tool_use_id="a"))
    fam = hub.fams[7]
    v0 = fam.mood.v
    hub.receive(msg(2, "PostToolUseFailure", tool_name="Bash", tool_use_id="a", error="x", is_interrupt=True))
    v1 = fam.mood.v
    with open(tr, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user for tool use]"}]}}) + "\n")
    assert hub.poll_transcripts(3) == []        # hook už přerušení nahlásil
    assert fam.mood.v == v1 and [k for _, k in fam.udalosti].count("agent.interrupted") == 1
    hub.receive(msg(5, "UserPromptSubmit", prompt="y"))
    assert fam.feed({"ts": 6, "kind": "agent.interrupted", "data": {}}) is True    # nové kolo = nové přerušení
    assert v0 != v1


def test_panel_napojeny_na_hub(ui, home):
    hub, fam = ui.hub, ui.hub.fams[7]
    hub.receive(msg(1, "UserPromptSubmit", prompt=f"{SECRET} díky, skvělé"))
    hub.receive(msg(2, "PreToolUse", tool_name="Bash", tool_use_id="a", tool_input={"command": SECRET}))
    hub.receive(msg(3, "PostToolUse", tool_name="Bash", tool_use_id="a"))
    for k in range(HIST_N + 20):
        fam.update(4 + k * HIST_S)
    stav = hub.stav_panelu(7, 4 + HIST_N * HIST_S)
    assert len(stav["historie"]) == HIST_N and stav["historie"][-1][0] == 4 + (HIST_N + 19) * HIST_S
    assert [k for _, k in stav["udalosti"]][-3:] == ["user.prompt", "tool.start", "tool.end"]
    assert set(stav["signaly"]) == {"zmatek", "unava", "otazek", "podil_otazek"}
    assert SECRET not in repr(stav) and SECRET not in repr(vars(fam).get("udalosti"))

    p = ui.otevri_panel(7)
    assert ui.otevri_panel(7) is p and ui.panely == {7: p}
    assert "prompt" in p.udalosti.text() and SECRET not in p.udalosti.text()
    fam.update(4 + (HIST_N + 30) * HIST_S)
    ui.obnov_panely()
    assert p.graf.historie[-1][0] == 4 + (HIST_N + 30) * HIST_S
    p.opravit("frustrace")
    rows = [json.loads(x) for x in open(home / "state" / "familiar" / "opravy.jsonl")]
    assert rows[-1]["oprava"] == "frustrace" and set(rows[-1]["signaly"]) <= {"zmatek", "unava", "otazek",
                                                                              "podil_otazek"}
    assert SECRET not in (home / "state" / "familiar" / "opravy.jsonl").read_text()
    p.close()
    QApplication.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert ui.panely == {}


def test_nastaveni_jedna_instance(ui):
    click(nab(ui, None)["Nastavení…"])
    d = ui.dialog
    assert d is not None and d.isVisible() and not d.isModal()
    ui.otevri_nastaveni()
    assert ui.dialog is d
    d.reject()
    assert ui.dialog is None


def test_ukoncit(ui, monkeypatch):
    called = []
    monkeypatch.setattr(nabidka.QApplication, "quit", lambda: called.append(1))
    click(nab(ui, 7)["Ukončit familiara"])
    assert called == [1]


def test_ikona_a_klice_v_docku(ui):
    assert not nabidka.ikona(ui.hub.skin).isNull() and not nabidka.ikona(ui.hub.skin, True).isNull()
    view = ui.views.view
    view.tick()
    assert view._key_at(1) == 7 and view._key_at(10 ** 6) is None


def test_cli_tune(tmp_path, capsys):
    f = tmp_path / "opravy.jsonl"
    f.write_text(json.dumps({"ts": 1.0, "predikce": "klid", "oprava": "radost", "valence": 0.4,
                             "aktivace": 0.3}) + "\n")
    assert cli.main(["tune", "--soubor", str(f), "--config", str(tmp_path / "nic.toml")]) == 0
    out = capsys.readouterr().out
    assert "1" in out and out.strip()
    with pytest.raises(SystemExit) as e:
        cli.main(["tune", "--help"])
    assert e.value.code == 0 and "--soubor" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["doctor", "--nic"])


def test_doctor_kwin_podle_rezimu_a_log(home, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(home))
    monkeypatch.setattr(doctor.paths, "daemon_pid", lambda: 4242)
    monkeypatch.setattr(doctor, "measure_emit", lambda exe: ([1.0], None))
    monkeypatch.setattr(doctor.install, "dbus", lambda *a: "(false,)")
    (home / "familiar.rezim").write_text("dock\n")
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert rows["KWin skript familiar-perch"][0] is True
    (home / "familiar.rezim").write_text("perch\n")
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert rows["KWin skript familiar-perch"][0] is False
    logdir = home / "state" / "familiar"
    logdir.mkdir(parents=True)
    (logdir / "familiar.log.1").write_bytes(b"x" * 2048)
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert "zatím neexistuje + 1 starší (2 kB)" in rows["log"][1]


def test_dock_zapise_rezim(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    views = dock.Views(hub, None, config.load(), "dock", mode_file=str(home / "rezim"))
    assert (home / "rezim").read_text() == "dock\n"
    views.view.close()


def test_doctor_tray(monkeypatch):
    replies = {"IsStatusNotifierHostRegistered": "(<true>,)",
               "RegisteredStatusNotifierItems": "(<[':1.5/StatusNotifierItem', ':1.9/StatusNotifierItem']>,)"}

    def dbus(dest, path, method, *args):
        if method.endswith("GetConnectionUnixProcessID"):
            return {":1.5": "(uint32 111,)", ":1.9": "(uint32 4242,)"}[args[0]]
        return replies.get(args[-1])
    monkeypatch.setattr(doctor.install, "dbus", dbus)
    assert doctor.tray(4242) == (True, "tray dostupný, ikona daemonu registrovaná (:1.9)")
    assert doctor.tray(999)[0] is False
    assert doctor.tray(0)[0] is False and doctor.tray(None)[0] is True
    replies["IsStatusNotifierHostRegistered"] = None
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert doctor.tray(4242)[0] is False
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert doctor.tray(4242)[0] is True


def test_perch_levy_klik_prepina_terminal_pravy_otevre_nabidku(home, app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    hub = Hub(reap=False, bind=False, transcripts=False)
    hub.receive(msg(0, "SessionStart"))
    seen = []
    views = dock.Views(hub, None, config.load(), "perch")
    views.ui = type("UI", (), {"popup": lambda self, w, key, pos: seen.append(key)})()
    views.view.tick()
    w = views.view.windows[7]
    before = w.windowTitle().split("|")[3]
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(32, 40))
    assert int(w.windowTitle().split("|")[3]) == int(before) + 1      # perch.js podle toho přepne na terminál
    QTest.mouseClick(w, Qt.RightButton, Qt.NoModifier, QPoint(32, 40))
    assert seen == [7]
    hub.uspat(True, 7)
    views.view.tick()
    assert w.windowTitle().split("|")[2] == "sleeping"
    views.view.close()


def test_oprava_v_panelu_zmeni_naladu_postavicky(ui):
    key = next(iter(ui.hub.fams))
    p = ui.otevri_panel(key)
    p.tlacitka["zmatek"].click()
    fam = ui.hub.fams[key]
    assert fam.mood.label == "zmatek"
    assert p.stav["nalada"] == "zmatek" and p.tlacitka["zmatek"].property("aktualni")
    assert "převzala" in p.zprava.text()

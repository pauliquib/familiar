import os, time, tomllib

import pytest

from familiar import cli, config, install, paths
from familiar.hub import Hub
from familiar.mood import MoodEngine
from familiar.topic import TopicTracker


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Dočasný HOME; config v tmp/.config/familiar/config.toml."""
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def write(text):
    path = paths.config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": "s", **raw}}


def ev(ts, kind, **data):
    return {"ts": ts, "kind": kind, "data": data}


def cfg_with(text):
    write(text)
    cfg = config.load()
    assert not cfg.errors, cfg.errors
    return cfg


# --- výchozí hodnoty, --init, --show ---

def test_missing_file_gives_defaults(home):
    cfg = config.load()
    assert not cfg.exists and not cfg.errors and cfg.data == config.defaults()
    assert cfg.path == str(home / ".config" / "familiar" / "config.toml")


def test_defaults_mirror_module_constants():
    d = config.defaults()
    assert d["nalada"]["tau_valence_s"] == 300.0 and d["nalada"]["impulsy"]["dekovani"] == [0.35, 0.05]
    assert d["temata"]["klobouky"]["kod"] == "headphones" and d["klid"]["rozestup_s"] == 2.5
    assert d["okno"]["odsazeni"] == 120 and d["rezim"] == "auto" and d["skin"] == "robokun"


def test_init_file_loads_back_as_defaults(home, capsys):
    assert cli.main(["config", "--init"]) == 0
    text = open(paths.config_file(), encoding="utf-8").read()
    assert "# režim soustředění" in text and "[nalada.impulsy]" in text
    cfg = config.load()
    assert cfg.exists and not cfg.errors and not cfg.warnings
    assert cfg.data == config.defaults()


def test_init_does_not_overwrite_without_force(home, capsys):
    write('rezim = "dock"\n')
    assert cli.main(["config", "--init"]) == 1
    assert config.load()["rezim"] == "dock"
    assert cli.main(["config", "--init", "--force"]) == 0
    assert config.load()["rezim"] == "auto"
    backups = list((home / ".local" / "share" / "familiar" / "backup").rglob("config.toml"))
    assert len(backups) == 1 and 'rezim = "dock"' in backups[0].read_text()


def test_show_prints_effective_values(home, capsys):
    write('[okno]\nmeritko_dock = 5\n')
    assert cli.main(["config", "--show"]) == 0
    shown = tomllib.loads(capsys.readouterr().out)
    assert shown["okno"]["meritko_dock"] == 5 and shown == config.load().data


def test_check_exit_codes(home, capsys):
    assert cli.main(["config", "--check"]) == 0          # bez souboru platí výchozí
    write('[okno]\nmeritko_dock = 5\n')
    assert cli.main(["config", "--check"]) == 0
    write('[okno]\nmeritko_dock = "velke"\n')
    assert cli.main(["config", "--check"]) == 1
    assert "okno.meritko_dock" in capsys.readouterr().out
    assert cli.main(["config", "--path"]) == 0


# --- validace ---

def test_bad_key_falls_back_to_its_default_only(home):
    write('rezim = "plocha"\nskin = "neni"\ntichy = "ano"\n'
          '[okno]\nmeritko_dock = 20\nmeritko_perch = 3\nstrana = "vlevo"\nsnimek_ms = 2.5\n'
          '[nalada.impulsy]\ndekovani = [0.5]\nkorekce = [-0.5, 0.0]\n')
    cfg = config.load()
    d = config.defaults()
    assert cfg["rezim"] == "auto" and cfg["skin"] == d["skin"] and cfg["tichy"] is False
    assert cfg["okno"]["meritko_dock"] == 3 and cfg["okno"]["snimek_ms"] == 60
    assert cfg["okno"]["meritko_perch"] == 3 and cfg["okno"]["strana"] == "vlevo"
    assert cfg["nalada"]["impulsy"]["dekovani"] == d["nalada"]["impulsy"]["dekovani"]
    assert cfg["nalada"]["impulsy"]["korekce"] == [-0.5, 0.0]
    bad = " ".join(cfg.errors)
    for key in ("rezim", "skin", "tichy", "okno.meritko_dock", "okno.snimek_ms", "nalada.impulsy.dekovani"):
        assert f"config.toml:{key} –" in bad
    assert "použije se 3" in bad and "1–8" in bad
    assert len(cfg.errors) == 6


def test_word_lists_must_be_valid_regexes(home):
    write('[nalada.slova]\ndekovani = ["dik("]\notazky = ["a*"]\nkorekce = ["", "ne"]\n'
          '[temata.slova]\nkod = ["py"]\n')
    cfg = config.load()
    d = config.defaults()["nalada"]["slova"]
    for key in ("dekovani", "otazky", "korekce"):
        assert cfg["nalada"]["slova"][key] == d[key]
    assert cfg["temata"]["slova"]["kod"] == ["py"]
    assert len(cfg.errors) == 3 and "prázdnému textu" in " ".join(cfg.errors)


def test_unknown_keys_warn(home):
    cfg = cfg_with('neco = 1\n[okno]\nsirka = 3\n[nova_sekce]\na = 1\n')
    assert len(cfg.warnings) == 3 and all("neznámý klíč" in w for w in cfg.warnings)
    assert cfg.data == config.defaults()


def test_broken_toml_uses_all_defaults(home):
    write('rezim = "dock\n')
    cfg = config.load()
    assert cfg.data == config.defaults() and len(cfg.errors) == 1 and "celá výchozí" in cfg.errors[0]


def test_new_topic_with_hat_tool_and_command(home):
    cfg = cfg_with('[temata.slova]\nhudba = ["kytar", "pisn"]\nweb = []\n'
                   '[temata.klobouky]\nhudba = "cap"\nkod = ""\n'
                   '[temata.nastroje]\nBash = {tema = "hudba", body = 2}\n'
                   '[[temata.prikazy]]\nregex = "\\\\bmpv\\\\b"\ntema = "hudba"\nbody = 1\n')
    t = cfg["temata"]
    assert t["slova"]["hudba"] == ["kytar", "pisn"] and "elektronika" in t["slova"]
    assert t["nastroje"]["Bash"] == {"tema": "hudba", "body": 2.0} and "WebSearch" in t["nastroje"]
    assert t["prikazy"] == [{"regex": r"\bmpv\b", "tema": "hudba", "body": 1.0}]
    tr = TopicTracker(0, t)
    tr.feed(ev(1, "user.prompt", text="ladím kytaru na písničku"))
    assert tr.topic == "hudba"
    tr.feed(ev(2, "user.prompt", text="udělej web stránku"))      # web vypnuté prázdným seznamem
    assert "web" not in tr.score


def test_bad_hat_and_record_are_errors(home):
    write('[temata.klobouky]\nkod = "cylindr"\nhudba = "cylindr"\n'
          '[temata.nastroje]\nEdit = {tema = "kod"}\n[[temata.prikazy]]\nregex = "("\ntema = "kod"\nbody = 1\n')
    cfg = config.load()
    d = config.defaults()["temata"]
    assert cfg["temata"]["klobouky"] == d["klobouky"]
    assert cfg["temata"]["nastroje"] == d["nastroje"] and cfg["temata"]["prikazy"] == d["prikazy"]
    assert len(cfg.errors) == 4


# --- migrace ---

def test_file_without_version_is_v0_and_install_migrates(home, capsys):
    write('# můj config\nrezim = "dock"\n')
    cfg = config.load()
    assert cfg["rezim"] == "dock" and not cfg.errors
    run = install.Run(False)
    assert config.migrate_file(run)
    text = open(paths.config_file(), encoding="utf-8").read()
    assert "verze = 1" in text and "# můj config" in text
    assert os.path.exists(os.path.join(run.backup_dir, ".config", "familiar", "config.toml"))
    assert not config.migrate_file(install.Run(False))     # podruhé už nic


def test_migration_steps(home, monkeypatch):
    def v1_to_v2(doc):      # např. přejmenování klíče
        if "okno" in doc and "zvetseni" in doc["okno"]:
            doc["okno"]["meritko_dock"] = doc["okno"].pop("zvetseni")
    monkeypatch.setattr(config, "VERSION", 2)
    monkeypatch.setitem(config.MIGRATIONS, 1, v1_to_v2)
    write('verze = 1\n[okno]\nzvetseni = 5\n')
    cfg = config.load()
    assert cfg["okno"]["meritko_dock"] == 5 and cfg["verze"] == 2 and not cfg.errors
    assert "stará verze 1" in cfg.warnings[0]
    assert config.migrate_file(install.Run(False))
    data = tomllib.loads(open(paths.config_file()).read())
    assert data == {"verze": 2, "okno": {"meritko_dock": 5}}


def test_newer_version_warns(home):
    cfg = config.load(write(f'verze = {config.VERSION + 1}\nrezim = "dock"\n'))
    assert cfg["rezim"] == "dock" and "novější" in cfg.warnings[0]


def test_install_runs_migration(home, monkeypatch):
    monkeypatch.setattr(install, "dbus", lambda *a: "()")
    monkeypatch.setattr(install, "installed", lambda name: None)
    write('rezim = "dock"\n')
    install.install()
    assert tomllib.loads(open(paths.config_file()).read())["verze"] == config.VERSION


# --- přenačtení ---

def test_watcher_reloads_after_stable_change(home):
    w = config.Watcher()
    assert w.poll() is None                        # soubor neexistuje, nic se nezměnilo
    write('[okno]\nmeritko_dock = 4\n')
    assert w.poll() is None                        # změna, ale ještě se může zapisovat
    cfg = w.poll()
    assert cfg is not None and cfg["okno"]["meritko_dock"] == 4
    assert w.poll() is None


def test_watcher_sees_atomic_replace_and_delete(home):
    path = write('[okno]\nmeritko_dock = 4\n')
    w = config.Watcher()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:      # editor: nový soubor + rename (stejná velikost i mtime možné)
        f.write('[okno]\nmeritko_dock = 5\n')
    st = os.stat(path)
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(tmp, path)
    w.poll()
    assert w.poll()["okno"]["meritko_dock"] == 5
    os.unlink(path)
    w.poll()
    cfg = w.poll()
    assert cfg.data == config.defaults() and not cfg.exists


# --- vliv na náladu, témata a hub ---

def test_mood_weights_and_words(home):
    d = config.defaults()["nalada"]
    m = MoodEngine(0)
    assert m.feed(ev(1, "user.prompt", text="díky")) == ["heart"] and m.v > 0.3
    cfg = cfg_with('[nalada.impulsy]\ndekovani = [0.0, 0.0]\n[nalada.slova]\ndekovani = ["hura"]\n')
    m = MoodEngine(0, cfg["nalada"])
    assert m.feed(ev(1, "user.prompt", text="díky")) == []
    assert m.feed(ev(2, "user.prompt", text="hurá")) == ["heart"] and m.v == 0.0
    assert m.c["tau_valence_s"] == d["tau_valence_s"]


def test_mood_thresholds_and_fatigue(home):
    cfg = cfg_with('[nalada.prahy]\nradost_valence = 0.5\n[nalada.unava]\nkol = 2\n')
    m = MoodEngine(0, cfg["nalada"])
    m.feed(ev(1, "user.prompt", text="díky"))       # +0,35 už nestačí
    assert m._classify() == "klid"
    m.feed(ev(2, "agent.done"))
    m.feed(ev(3, "agent.done"))
    assert m.fatigue == 1.0 and m._classify() == "unava"


def test_topic_thresholds(home):
    t = TopicTracker(0, cfg_with('[temata]\nukazat = 5.0\n')["temata"])
    t.feed(ev(1, "user.prompt", text="přerouti desku v KiCadu, footprint U11 nesedí"))
    assert t.topic is None and t.score["elektronika"] == pytest.approx(2.4)


def thanks_hub(cfg=None):
    hub = Hub(reap=False, bind=False, cfg=cfg)
    hub.receive(msg(0, "UserPromptSubmit", prompt="díky, funguje to"))
    hub.receive(msg(0.1, "SubagentStart", agent_id="a1", agent_type="Explore"))
    (fam,) = hub.tick(0.1)
    return hub, fam


def test_hub_defaults_show_emote_and_drone():
    _, fam = thanks_hub()
    anim, i, look = fam.update(0.2)
    assert look[2] == "heart" and look[4] == 0      # drony nahrazují pomocníci
    assert [p[0] for p in fam.pomocnici_ted(0.2)[0]] == ["Explore"]
    _, fam = thanks_hub(dict(config.defaults(), pomocnici={"zapnuto": False, "limit": 3}))
    assert fam.update(0.2)[2][4] == 1 and fam.pomocnici_ted(0.2) == ((), 0, ())


def test_hub_quiet_and_switches(home):
    _, fam = thanks_hub(cfg_with("tichy = true\n").data)
    look = fam.update(0.2)[2]
    assert look[2] is None and look[4] == 0
    _, fam = thanks_hub(cfg_with("[zobrazit]\nemoty = false\nnalada = false\n[pomocnici]\nzapnuto = false\n").data)
    for t in (0.2, 5, 10):
        look = fam.update(t)[2]
        assert look[2] is None and look[0] == "klid" and look[4] == 1


def test_hub_focus_freezes_until_waiting(home):
    hub = Hub(reap=False, bind=False, cfg=cfg_with("soustredeni = true\n").data)
    hub.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="t"))
    (fam,) = hub.tick(0)
    frames = {fam.update(1 + k * 0.1)[:2] for k in range(30)}
    assert frames == {("idle", 0)}
    hub.receive(msg(5, "PermissionRequest", tool_name="Bash"))
    fam.update(5)
    frames = {fam.update(5.5 + k * 0.1)[:2] for k in range(30)}
    assert {a for a, _ in frames} == {"wave"} and len(frames) > 1


def test_hub_configure_applies_to_running_familiar(home):
    hub, fam = thanks_hub()
    hub.configure(cfg_with("[zobrazit]\nemoty = false\ndrony = false\n"
                           "[temata.klobouky]\nkod = \"cap\"\n[postavicka]\nodchod_s = 0.5\n").data)
    look = fam.update(0.2)[2]
    assert look[2] is None and look[4] == 0 and fam.hats["kod"] == "cap"
    hub.receive(msg(1, "SessionEnd", reason="exit"))
    hub.tick(1)
    assert hub.tick(1.6) == []
    hub.configure(config.defaults())        # nový familiar dostane hubův config
    hub.receive(msg(2, "UserPromptSubmit", pid=8, prompt="díky"))
    (fam2,) = hub.tick(2)
    assert fam2.update(2.1)[2][2] == "heart"


def test_hub_rule_of_calm_spacing(home):
    cfg = cfg_with("[klid]\nemote_s = 1.0\nrozestup_s = 10.0\nfronta = 1\n")
    hub, fam = thanks_hub(cfg.data)
    assert fam.update(0.2)[2][2] == "heart"
    fam._queue("check")
    fam._queue("camera")             # fronta 1: zahodí se (i emote při změně nálady)
    assert fam.update(1.5)[2][2] is None
    assert fam.update(10)[2][2] is None
    assert fam.update(11.3)[2][2] == "check"


def test_flower_emote_obeys_toggle_and_rule_of_calm(home):
    cfg = cfg_with("[klid]\nemote_s = 1.0\nrozestup_s = 10.0\n")
    hub, fam = thanks_hub(cfg.data)
    assert fam.update(0.2)[2][2] == "heart"
    fam.update(5)                                       # radost se ustálí (hystereze)
    hub.receive(msg(6, "Stop"))
    hub.tick(6)
    assert fam.update(6.1)[2][2] is None                # rozestup po srdíčku
    assert fam.update(11.3)[2][2] == "heart"            # změna nálady na radost
    assert fam.update(17)[2][2] is None
    assert fam.update(22.6)[2][2] == "flower"
    hub.configure(cfg_with("[zobrazit]\nemoty = false\n").data)
    hub.receive(msg(20, "UserPromptSubmit", prompt="díky"))
    hub.receive(msg(30, "Stop"))
    hub.tick(30)
    assert fam.update(30.1)[2][2] is None and fam.pops == []


# --- opravy po kontrole ---

def test_huge_integer_is_an_error_not_a_crash(home):
    write("[okno]\nmeritko_dock = 1" + "0" * 400 + "\n[nalada]\ntau_valence_s = 1" + "0" * 400 + "\n")
    cfg = config.load()
    assert cfg["okno"]["meritko_dock"] == 3 and cfg["nalada"]["tau_valence_s"] == 300.0
    assert len(cfg.errors) == 2 and all(len(e) < 200 for e in cfg.errors)


def test_load_never_raises(home, monkeypatch):
    write('rezim = "dock"\n')
    monkeypatch.setattr(config, "_load", lambda path: 1 / 0)
    cfg = config.load()
    assert cfg.data == config.defaults() and "ZeroDivisionError" in cfg.errors[0]
    w = config.Watcher()
    write('rezim = "perch"\n')
    w.poll()
    assert w.poll().errors           # i přenačtení dá výchozí config s chybou, nevyhodí


def test_words_are_validated_as_joined_pattern(home):
    write('[nalada.slova]\ndekovani = ["(?i)dik", "super"]\n'
          '[temata.slova]\nkod = ["(?P<a>py)", "(?P<a>rust)"]\n')
    cfg = config.load()
    d = config.defaults()
    assert cfg["nalada"]["slova"]["dekovani"] == d["nalada"]["slova"]["dekovani"]
    assert cfg["temata"]["slova"]["kod"] == d["temata"]["slova"]["kod"]
    assert len(cfg.errors) == 2 and all("spojit" in e for e in cfg.errors)
    hub = Hub(reap=False, bind=False, cfg=cfg.data)       # postavička vznikne
    hub.receive(msg(0, "UserPromptSubmit", prompt="díky"))
    assert len(hub.tick(0)) == 1


def test_hub_configure_is_atomic():
    hub = Hub(reap=False, bind=False)
    for pid in (7, 8):
        hub.receive(msg(0, "UserPromptSubmit", pid=pid, prompt="ahoj"))
    bad = config.defaults()
    bad["zobrazit"]["emoty"] = False
    bad["temata"]["slova"]["kod"] = ["(?P<a>py)", "(?P<a>rust)"]   # obejde validaci
    with pytest.raises(Exception):
        hub.configure(bad)
    assert hub.cfg["zobrazit"]["emoty"] and all(f.emotes for f in hub.fams.values())


def test_zero_question_threshold(home):
    write("[nalada.prahy]\nzvedavost_otazek = 0\n")
    cfg = config.load()
    assert cfg["nalada"]["prahy"]["zvedavost_otazek"] == 2 and len(cfg.errors) == 1
    sec = config.defaults()["nalada"]
    sec["prahy"]["zvedavost_otazek"] = 0      # i bez validace engine nedělí nulou
    m = MoodEngine(0, sec)
    m.a = 0.9
    assert m.advance(1) == ("klid", False)


def test_non_utf8_user_skin(home):
    from familiar import skin
    d = home / ".local" / "share" / "familiar" / "skins" / "rozbity"
    d.mkdir(parents=True)
    (d / "skin.toml").write_bytes(b"[skin]\nname = \"\xff\xfe\"\n")
    ids = [sid for sid, name, _ in skin.available()]
    assert "rozbity" in ids
    with pytest.raises(skin.SkinError):
        skin.read_toml(str(d / "skin.toml"))
    assert not cfg_with('skin = "robokun"\n').errors


def test_skin_list_failure_is_only_a_warning(home, monkeypatch):
    from familiar import skin
    monkeypatch.setattr(skin, "available", lambda: 1 / 0)
    write('skin = "cokoli"\n')
    cfg = config.load()
    assert cfg["skin"] == "cokoli" and not cfg.errors and "skinů" in cfg.warnings[0]


def test_demo_is_dock_unless_mode_given():
    pytest.importorskip("PySide6")
    from familiar import dock
    v = dock.Views.__new__(dock.Views)
    v.kwin_failed, v.demo, v.forced = False, True, None
    assert v._mode({"rezim": "perch"}) == "dock"
    v.forced = "perch"
    assert v._mode({"rezim": "dock"}) == "perch"
    v.demo, v.forced = False, None
    assert v._mode({"rezim": "perch"}) == "perch"


def test_zakryti_titulku_vychozi_a_validace(home):
    d = config.defaults()["okno"]
    assert d["zakryti"] == "navrchu" and d["rada_roh"] == "vpravo-dole"
    assert cfg_with('[okno]\nzakryti = "rada"\nrada_roh = "vlevo-nahore"\n')["okno"]["rada_roh"] == "vlevo-nahore"
    write('[okno]\nzakryti = "skryt"\nrada_roh = "dole"\n')
    cfg = config.load()
    assert cfg["okno"]["zakryti"] == "navrchu" and cfg["okno"]["rada_roh"] == "vpravo-dole"
    bad = " ".join(cfg.errors)
    assert "okno.zakryti" in bad and "navrchu, schovat, rada" in bad and "okno.rada_roh" in bad
    text = config.render(config.defaults())
    assert '# když jiné okno zakryje titulek' in text and '\nzakryti = "navrchu"\n' in text and 'rada_roh = "vpravo-dole"' in text


def test_rezim_dialogu_nastaveni(home):
    assert config.defaults()["nastaveni"] == "jednoduche"
    assert cfg_with('nastaveni = "pokrocile"\n')["nastaveni"] == "pokrocile"
    write('nastaveni = "expert"\n')
    cfg = config.load()
    assert cfg["nastaveni"] == "jednoduche"
    assert len(cfg.errors) == 1 and "nastaveni" in cfg.errors[0] and "jednoduche, pokrocile" in cfg.errors[0]
    assert '\nnastaveni = "jednoduche" # dialog nastavení' in config.render(config.defaults())

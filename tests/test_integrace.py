# M4B + M6: skin v hubu a rendereru, přerušení z transcriptu, log bez promptů.
import json, logging, os
from datetime import datetime, timezone

import pytest

from familiar import config, hub as hub_mod, log as flog, skin
from familiar.hub import FADE_STEP_S, Hub

SECRET = "UNIKATNI-PROMPT-7f3a9c"


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": "s", **raw}}


def cfg(**top):
    d = config.defaults()
    d.update(top)
    return d


INTERRUPT = json.dumps({"type": "user", "message": {"role": "user", "content": [
    {"type": "text", "text": "[Request interrupted by user for tool use]"}]}}) + "\n"


def interrupt_at(ts):
    """Řádek přerušení s časem záznamu ts (s epochy, UTC)."""
    iso = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return json.dumps({"type": "user", "timestamp": iso, "message": {"role": "user", "content": [
        {"type": "text", "text": "[Request interrupted by user]"}]}}) + "\n"


@pytest.fixture
def tr(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"type": "user", "message": {"role": "user", "content": "ahoj"}}\n')
    return p


@pytest.fixture
def logfile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    lg = logging.getLogger(flog.NAME)
    old = lg.handlers[:]
    lg.handlers = []
    flog.setup(logging.DEBUG)

    def read():
        for h in lg.handlers:
            h.flush()
        return (tmp_path / "state" / "familiar" / "familiar.log").read_text(encoding="utf-8")
    yield read
    for h in lg.handlers:
        h.close()
    lg.handlers = old


# --- přerušení z transcriptu ---

def test_interrupt_from_transcript_ends_round(tr):
    hub = Hub(reap=False)
    hub.receive(msg(0, "UserPromptSubmit", prompt="x", transcript_path=str(tr)))
    hub.receive(msg(1, "PreToolUse", tool_name="Bash", tool_use_id="a", transcript_path=str(tr)))
    assert hub.poll_transcripts(1.5) == []
    (fam,) = hub.tick(2)
    assert fam.fsm.state == "working" and fam.fsm.tools
    v = fam.mood.v
    with open(tr, "a") as f:
        f.write(INTERRUPT)
    assert hub.poll_transcripts(3) == [7]
    assert fam.fsm.state == "idle" and not fam.fsm.tools and not fam.fsm.in_round
    assert fam.fsm.log[-1][3] == "agent.interrupted"
    assert fam.mood.v < v       # impuls přerušení
    assert hub.poll_transcripts(4) == []     # stejný řádek podruhé ne


def test_prompt_after_interrupt_wins(tr):
    hub = Hub(reap=False)
    hub.receive(msg(100, "PreToolUse", tool_name="Bash", tool_use_id="a", transcript_path=str(tr)))
    hub.poll_transcripts(100.5)
    with open(tr, "a") as f:
        f.write(interrupt_at(100.6))        # Esc, hned potom nový prompt (stejné okno čtení)
    hub.receive(msg(100.8, "UserPromptSubmit", prompt="dál", transcript_path=str(tr)))
    assert hub.poll_transcripts(101.0) == []
    assert hub.tick(101.0)[0].fsm.in_round


def test_interrupt_after_prompt_in_same_window_counts(tr):
    hub = Hub(reap=False)
    hub.receive(msg(100, "PreToolUse", tool_name="Bash", tool_use_id="a", transcript_path=str(tr)))
    hub.poll_transcripts(100.5)
    hub.receive(msg(100.6, "UserPromptSubmit", prompt="dál", transcript_path=str(tr)))
    with open(tr, "a") as f:
        f.write(interrupt_at(100.8))        # prompt, hned potom Esc
    assert hub.poll_transcripts(101.0) == [7]
    (fam,) = hub.tick(101.0)
    assert fam.fsm.state == "idle" and not fam.fsm.in_round


def test_interrupt_without_time_uses_poll_window(tr):
    hub = Hub(reap=False)
    hub.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="a", transcript_path=str(tr)))
    hub.poll_transcripts(0.5)
    with open(tr, "a") as f:
        f.write(INTERRUPT)
    hub.receive(msg(0.8, "UserPromptSubmit", prompt="dál", transcript_path=str(tr)))
    assert hub.poll_transcripts(1.0) == []


def test_unwatch_on_session_end_and_removal(tr):
    hub = Hub(reap=False)
    hub.receive(msg(0, "SessionStart", transcript_path=str(tr)))
    assert 7 in hub.watchers
    hub.receive(msg(1, "SessionEnd", reason="clear"))
    assert 7 not in hub.watchers
    hub.receive(msg(1.1, "SessionStart", source="clear", transcript_path=str(tr)))
    assert 7 in hub.watchers
    hub.receive(msg(2, "SessionEnd", reason="other", transcript_path=str(tr)))
    assert 7 not in hub.watchers
    assert hub.tick(10) == [] and len(hub.watchers) == 0


def test_demo_hub_does_not_watch(tr):
    hub = Hub(reap=False, transcripts=False)
    hub.receive(msg(0, "SessionStart", transcript_path=str(tr)))
    assert hub.watchers is None and hub.poll_transcripts(1) == []


# --- skin ---

def test_hub_uses_configured_skin_and_switches_live():
    hub = Hub(reap=False, cfg=cfg(skin="robokun"))
    hub.receive(msg(0, "SessionStart"))
    (fam,) = hub.tick(0)
    assert hub.skin.id == "robokun" and fam.skin is hub.skin
    anim, i, look = fam.update(1)
    before = hub.skin.render(anim, i, look)
    hub.configure(cfg(skin="rubin"))
    assert hub.skin.id == "rubin" and fam.skin is hub.skin
    anim, i, look = fam.update(1.1)
    assert hub.skin.render(anim, i, look) != before


def test_broken_skin_falls_back_and_logs(tmp_path, monkeypatch, logfile):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    d = tmp_path / "data" / "familiar" / "skins" / "rozbity"
    d.mkdir(parents=True)
    (d / "skin.toml").write_text('[skin]\nname = "Rozbitý"\n[layers]\nbody = "chybi.png"\n')
    hub = Hub(reap=False, cfg=cfg(skin="rozbity"))
    assert hub.skin.id == skin.BUILTIN and "rozbity" in hub.skin.error
    assert "rozbity/skin.toml" in logfile() and "vestavěného" in logfile()
    hub.receive(msg(0, "SessionStart"))
    hub.tick(0)[0].update(1)        # vestavěný kreslí dál


def test_drop_skin_switches_to_builtin(logfile):
    hub = Hub(reap=False)
    hub.receive(msg(0, "SessionStart"))
    hub.drop_skin("KeyError")
    assert hub.skin.id == skin.BUILTIN and hub.tick(0)[0].skin is hub.skin
    assert "selhal při kreslení" in logfile()


def test_mood_change_fades_palette_in_three_steps():
    hub = Hub(reap=False)
    hub.receive(msg(0, "SessionStart"))
    (fam,) = hub.tick(0)
    fam.update(0)
    fam.mood.label = "radost"
    fam.mood.advance = lambda now: ("radost", True)
    fam.update(10)
    assert fam.fade == ("klid", 1)
    fam.update(10 + FADE_STEP_S)
    assert fam.fade == ("klid", 2)
    fam.update(10 + 2 * FADE_STEP_S)
    assert fam.fade is None


# --- log ---

def test_prompt_text_never_reaches_log(logfile, monkeypatch, tr):
    hub = Hub(reap=False)
    m = msg(0, "UserPromptSubmit", prompt=SECRET, transcript_path=str(tr))
    hub.handle(json.dumps(m).encode())              # běžná zpráva
    hub.handle(b"{neni json " + SECRET.encode())     # vadná zpráva

    def boom(*_):
        raise ValueError(f"špatný prompt {SECRET}")
    monkeypatch.setattr(hub_mod.adapters, "translate", boom)
    hub.handle(json.dumps(msg(1, "UserPromptSubmit", prompt=SECRET)).encode())
    text = logfile()
    assert "chyba při zpracování zprávy hooku" in text and "prompt_len" in text
    assert SECRET not in text and "UNIKATNI" not in text


# --- renderer (jen QImage, bez okna) ---

def test_images_keyed_by_skin_and_fade_blends():
    from familiar import dock
    imgs = dock.Images()
    a, b = skin.load("robokun"), skin.load("rubin")
    look = ("radost", None, None, 0, 0, 0)
    ia, ib = imgs.get(a, "idle", 0, look), imgs.get(b, "idle", 0, look)
    assert ia != ib and len(imgs.images) == 1       # výměna skinu cache vyprázdní
    b.id = "robokun"        # jiný (třeba uživatelský nebo přenačtený) skin se stejným id
    assert imgs.get(b, "idle", 0, look) == ib != imgs.get(a, "idle", 0, look)
    full_old = imgs.get(a, "idle", 0, ("klid",) + look[1:]).colorTable()
    full_new = ia.colorTable()
    mid = imgs.get(a, "idle", 0, look, ("klid", 1)).colorTable()
    assert mid != full_new and mid != full_old


def test_picture_survives_broken_skin(logfile):
    from familiar import dock

    class Rozbity(skin.BuiltinSkin):
        def render(self, *a):
            raise KeyError("x")
    bad = Rozbity()
    bad.id = "rozbity"
    hub = Hub(reap=False)
    img = dock.picture(hub, (bad, "idle", 0, None, None))
    assert img.width() == 32 and hub.skin.id == skin.BUILTIN
    assert "rozbity nevykreslil" in logfile()


def test_cli_skins_lists_and_marks_chosen(tmp_path, monkeypatch, capsys):
    from familiar import cli
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / ".config" / "familiar" / "config.toml"
    p.parent.mkdir(parents=True)
    p.write_text('skin = "rubin"\n')
    assert cli.main(["skins"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(l.startswith("* rubin") for l in lines) and any("vestaveny" in l for l in lines)
    d = tmp_path / ".local" / "share" / "familiar" / "skins" / "zly"
    d.mkdir(parents=True)
    (d / "skin.toml").write_text("[skin]\n")
    assert cli.main(["skins"]) == 1 and "CHYBA" in capsys.readouterr().out

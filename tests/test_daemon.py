# Daemon (dock.py) offscreen: KWin skript se odebere ve všech cestách, signál před smyčkou,
# přenačtení skinu po změně souborů.
import os, shutil, signal, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from familiar import config, dock, kwin, log as flog, skin
from familiar.hub import Hub


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_kwin(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")       # backend oken kwin
    calls = []
    monkeypatch.setattr(kwin, "load", lambda: calls.append("load") or True)
    monkeypatch.setattr(kwin, "unload", lambda: calls.append("unload"))
    return calls


def cfg(rezim="dock"):
    d = config.defaults()
    d["rezim"] = rezim
    return config.Config(d, None)


def broken_perches(*a, **k):
    raise RuntimeError("okno nejde vytvořit")


def test_failed_perch_view_at_start_unloads_script(app, fake_kwin, monkeypatch):
    monkeypatch.setattr(dock, "Perches", broken_perches)
    with pytest.raises(RuntimeError):
        dock.Views(Hub(reap=False), None, cfg(), forced_mode="perch")
    assert fake_kwin == ["load", "unload"]


def test_failed_perch_view_at_runtime_unloads_script(app, fake_kwin, monkeypatch):
    views = dock.Views(Hub(reap=False), None, cfg("dock"))
    monkeypatch.setattr(dock, "Perches", broken_perches)
    with pytest.raises(RuntimeError):
        views.apply(cfg("perch"))
    assert fake_kwin == ["load", "unload"] and views.mode is None and views.view is None
    views.quit()
    assert fake_kwin == ["load", "unload"]      # podruhé už se nic neodebírá
    views.apply(cfg("dock"))                    # příští změna configu pohled zase otevře
    assert views.mode == "dock" and views.view is not None
    views.view.close()


def test_perch_to_dock_unloads_once(app, fake_kwin):
    views = dock.Views(Hub(reap=False), None, cfg("perch"))
    views.apply(cfg("dock"))
    views.quit()
    assert fake_kwin == ["load", "unload"]
    views.view.close()


def test_signal_before_loop_ends_it(app):
    hung = []
    QTimer.singleShot(3000, lambda: (hung.append(1), app.quit()))
    assert dock._exec(app, {"why": "SIGTERM"}) == 0 and not hung


def test_sigterm_during_startup_exits_cleanly(app, tmp_path, monkeypatch, capsys):
    for var, sub in (("XDG_CONFIG_HOME", "c"), ("XDG_DATA_HOME", "d"), ("XDG_STATE_HOME", "s"),
                     ("XDG_RUNTIME_DIR", "r")):
        (tmp_path / sub).mkdir(mode=0o700)
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    real, hung = dock.Views, []

    class Views(real):      # signál přijde dřív, než daemon vstoupí do smyčky
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            QTimer.singleShot(3000, lambda: (hung.append(1), app.quit()))
            os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(dock, "Views", Views)
    lg = flog.logging.getLogger(flog.NAME)
    handlers = lg.handlers[:]

    class A:
        mode, demo, speed, gap = "dock", None, 1.0, 4.0
    try:
        with pytest.raises(SystemExit) as e:
            dock.run(A())
        try:
            raise ValueError("TAJ" + "NY-TEXT")     # v traceback je jen zdrojový řádek
        except ValueError:
            sys.excepthook(*sys.exc_info())     # hook z run(): na stderr jen typ
    finally:
        for s, h in old.items():
            signal.signal(s, h)
        for h in lg.handlers[len(handlers):]:
            h.close()
        lg.handlers = handlers
        app._familiar[0][0].close()
        app._familiar[1].view.close()
    assert e.value.code == 0 and not hung
    text = (tmp_path / "s" / "familiar" / "familiar.log").read_text()
    assert "konec familiar (SIGTERM)" in text and "neošetřená výjimka" in text and "TAJNY" not in text
    err = capsys.readouterr().err
    assert "ValueError" in err and "TAJNY" not in err


def test_skin_reloads_after_files_change(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    user = tmp_path / "familiar" / "skins"
    user.mkdir(parents=True)
    hub = Hub(reap=False, cfg=dict(config.defaults(), skin="rubin"))
    first = hub.skin
    assert first.source == skin.PACKAGE
    hub.refresh_skin()
    assert hub.skin is first                    # nic se nezměnilo
    shutil.copytree(os.path.join(skin.PACKAGE_DIR, "robokun"), user / "rubin")
    hub.refresh_skin()
    assert hub.skin is first                    # čeká, až se soubory ustálí
    hub.refresh_skin()
    assert hub.skin is not first and hub.skin.source == skin.USER
    second = hub.skin
    toml = user / "rubin" / "skin.toml"
    toml.write_text(toml.read_text().replace('name = "Robo-kun"', 'name = "Upravený"'))
    hub.refresh_skin()
    hub.refresh_skin()
    assert hub.skin is not second and hub.skin.name == "Upravený"

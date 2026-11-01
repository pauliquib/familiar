import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from familiar import config, editor, nastaveni, paths, skin, skin_edit

B = QMessageBox.StandardButton


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch, app):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: B.Ok)
    return tmp_path


def user_skins():
    return os.path.join(paths.data_dir(), "skins")


def mouse(e, x, y, button=Qt.MouseButton.LeftButton, to=None):
    z = e.platno.zoom
    pts = [(x, y)] + ([to] if to else [])
    for k, (px, py) in enumerate(pts):
        p = QPointF(px * z + z / 2, py * z + z / 2)
        kind = QEvent.Type.MouseButtonPress if k == 0 else QEvent.Type.MouseMove
        QApplication.sendEvent(e.platno, QMouseEvent(kind, p, p, button, button, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(e.platno, QMouseEvent(QEvent.Type.MouseButtonRelease, p, p, button,
                                                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def otevrit(skin_id="robokun"):
    w = editor.OknoEditoru(skin_id)
    w.show()
    QApplication.processEvents()
    return w, w.editor


def test_zalozka_v_nastaveni(home):
    d = nastaveni.Nastaveni()
    assert d.tabs.tabText(d.editor_tab) == nastaveni.EDITOR
    assert d.editor.doc is None             # skin se načte až při zobrazení záložky
    d.prepnout(nastaveni.POKROCILE, zapsat=False)
    d.prepnout(nastaveni.JEDNODUCHE, zapsat=False)
    assert d.tabs.isTabVisible(d.editor_tab)
    d = nastaveni.Nastaveni(zalozka=nastaveni.EDITOR)
    d.show()
    QApplication.processEvents()
    assert d.tabs.currentIndex() == d.editor_tab and d.editor.doc.id == "robokun"
    assert not d.reset.isEnabled()
    d.reject()


def test_kresleni_zpet_znovu_a_ulozeni(home):
    w, e = otevrit()
    assert e.doc.source == skin.PACKAGE and e.vrstva == "body" and e.anim_name == "idle"
    e.vyber_barvu(3)
    mouse(e, 0, 0)
    mouse(e, 0, 2, to=(3, 2))                       # tužka táhne čáru bez mezer
    px = e.doc.body.get("idle").frames[0].px
    assert px[0] == 3 and [px[2 * 32 + x] for x in range(4)] == [3] * 4 and e.dirty
    mouse(e, 0, 0, Qt.MouseButton.RightButton)      # pravé tlačítko maže
    assert e.doc.body.get("idle").frames[0].px[0] == 0
    e.zpet()
    assert e.doc.body.get("idle").frames[0].px[0] == 3
    e.zpet()
    e.znovu()
    assert e.doc.body.get("idle").frames[0].px[0] == 3 and len(e._redo) == 1
    assert e.ulozit()
    s = skin.load("robokun")
    assert s.source == skin.USER and s.render("idle", 0)[0][0] == 3 and not e.dirty
    assert e.b_smazat.text() == "Vrátit balíčkový"
    w.close()


def test_nastroje_vypln_kapatko_kotva_fx(home):
    w, e = otevrit()
    e.vyber_barvu(4)
    e.vyber_nastroj("fill")
    mouse(e, 0, 0)                                   # pozadí (průhledná) se vyplní
    fr = e.frame()
    assert fr.px[0] == 4 and fr.px[31 * 32 + 31] == 4
    e.vyber_nastroj("picker")
    mouse(e, 16, 20)
    assert e.barva == fr.px[20 * 32 + 16] and e.nastroj == "pencil"      # po kapátku zpět tužka
    e.vyber_nastroj("rect")
    e.vyber_barvu(2)
    mouse(e, 1, 1, to=(4, 3))
    assert fr.px[1 * 32 + 1] == fr.px[3 * 32 + 4] == 2 and fr.px[2 * 32 + 2] == 4
    e.vyber_nastroj("anchor")
    e.kotva.setCurrentIndex(e.kotva.findData("eyes"))
    mouse(e, 5, 6)
    assert fr.anchors["eyes"] == (5, 6) and e.doc.body.get("idle").frames[1].anchors["eyes"] != (5, 6)
    e.do_fx.setChecked(True)
    e.vyber_nastroj("pencil")
    e.vyber_barvu(1)
    mouse(e, 9, 9)
    assert fr.fx is not None and fr.fx[9 * 32 + 9] == 1 and fr.px[9 * 32 + 9] != 1
    e.dirty = False
    w.close()


def test_animace_snimky_a_stavy(home, monkeypatch):
    w, e = otevrit()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("walk2", True))
    e.pridat_animaci()
    assert e.anim_name == "walk2" and e.doc.body.get("walk2").frames
    e.pridat_snimek(True)
    e.pridat_snimek(False)
    assert len(e.anim().frames) == 3 and e.snimek == 2 and e.snimky.count() == 3
    e.smazat_snimek()
    assert len(e.anim().frames) == 2
    e.fps.setValue(12)
    e.jednorazova.setChecked(True)
    assert e.anim().fps == 12 and e.anim().oneshot
    c = e.stavy[("state", "walking")]
    c.setCurrentIndex(c.findData("walk2"))
    assert e.doc.activity["walking"] == "walk2"
    c = e.stavy[("tool", "Bash")]
    c.setCurrentIndex(c.findData("think"))
    assert e.doc.activity["working"]["Bash"] == "think"
    row = e.nalady["unava"]
    row["tempo"].setValue(0.5)
    row["emote"].setCurrentIndex(row["emote"].findData("coffee"))
    assert e.doc.moods["unava"]["tempo"] == 0.5 and e.doc.moods["unava"]["emote"] == "coffee"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("chuze", True))
    e.prejmenovat_animaci()
    assert e.doc.activity["walking"] == "chuze" and e.anim_name == "chuze"
    e.vrstvy.setCurrentIndex(e.vrstvy.findData("acc"))
    assert e.vrstva == "acc" and e.anim_name == "hardhat" and e.kotva.findData("head") >= 0
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("cap@chuze", True))
    e.pridat_animaci()                  # varianta klobouku: kopie klobouku na každý snímek animace
    assert len(e.anim().frames) == 2 and e.anim().frames[0].px == e.doc.layers["acc"].get("cap").frames[0].px
    e._sestav_nahled()
    assert e.chyby == [] and e.nahled.snimek() is not None
    assert e.ulozit()
    s = skin.load("robokun")
    assert s.walk_anim() == "chuze" and s.anims["chuze"].oneshot and s.anims["chuze"].fps == 12
    assert s.mood_tempo("unava") == 0.5 and s.anim_for("working", "Bash") == "think"
    w.close()


def test_novy_skin_a_smazani(home, monkeypatch):
    w, e = otevrit()

    class Dlg:
        def __init__(self, *a):
            pass

        def exec(self):
            return editor.QDialog.DialogCode.Accepted

        def hodnoty(self):
            return "muj", "Můj familiar", None, (48, 48)
    monkeypatch.setattr(editor, "NovySkin", Dlg)
    hlaseno = []
    e.ulozeno.connect(lambda sid: hlaseno.append(sid))
    e.novy()
    assert e.doc.id == "muj" and e.doc.size == (48, 48) and hlaseno == ["muj"]
    assert skin.load("muj").name == "Můj familiar" and e.skiny.currentData() == "muj"
    e.smazat()
    assert skin.find("muj") is None and e.doc.id == skin.DEFAULT
    w.close()


def test_vestaveny_nejde_upravit(home):
    w, e = otevrit(skin.BUILTIN)
    assert e.doc.source == skin.CODE and not e.upravitelny()
    assert not e.b_ulozit.isEnabled() and not e.tabs.widget(0).isEnabled()
    e._sestav_nahled()
    assert e.nahled.snimek() is not None and "kreslený kódem" in e.info.text()
    w.close()


def test_neulozene_zmeny_pri_zavreni(home):
    d = nastaveni.Nastaveni(zalozka=nastaveni.EDITOR)
    d.show()
    QApplication.processEvents()
    e = d.editor
    e.vyber_barvu(2)
    mouse(e, 0, 0)
    asked = []
    e._zeptej_ulozit = lambda: asked.append(1) or B.Cancel
    d.reject()
    assert d.isVisible() and asked == [1]
    assert not d.ulozit() and d.isVisible()
    e._zeptej_ulozit = lambda: B.Discard
    d.reject()
    assert not d.isVisible() and skin.find("robokun")[1] == skin.PACKAGE


def test_pouzit_jako_vzhled(home):
    skin_edit.save(skin_edit.new("nova"))
    d = nastaveni.Nastaveni(zalozka=nastaveni.EDITOR)
    d.show()
    QApplication.processEvents()
    d.editor.nacti("nova")
    d.editor.b_pouzit.click()
    assert d.fields["skin"].get() == "nova" and d.zmeny() == {"skin": "nova"}
    assert d.ulozit()
    assert config.load()["skin"] == "nova"


def test_vyber_ze_seznamu_animaci_a_skinu(home):
    w, e = otevrit()
    names = e.layer().names()
    e.animace.setCurrentRow(3)                  # skutečný signál seznamu
    assert e.anim_name == names[3] and e.animace.count() == len(names) and e.snimek == 0
    assert e.snimky.count() == len(e.anim().frames) and e.n_anim.currentData() in (None, names[3])
    e.vyber_barvu(2)
    mouse(e, 0, 0)
    i = e.skiny.findData("kvetina")
    e._zeptej_ulozit = lambda: B.Discard
    e.skiny.setCurrentIndex(i)
    e.skiny.activated.emit(i)
    QApplication.processEvents()
    assert e.doc.id == "kvetina" and not e.dirty and not e._undo
    w.close()

# Ovládání familiara v GUI: nabídka na postavičce (pravé tlačítko), ikona v liště,
# dialog nastavení, panely nálady a okno statistik a úspěchů (čísla z hub.sluzby, výběr
# doplňků se zapíše do configu jako změna z nabídky).
#
# Trvalé volby (emoty, soustředění, notifikace, zvuky, režim, skin) jdou do config.toml stejnou cestou
# jako dialog nastavení (nastaveni.upravit_text + atomický zápis): změní se jen daný
# klíč, soubor vznikne až první skutečnou změnou a daemon ho použije hned (callback
# zapsano). Uspání platí jen za běhu (hub.uspat): z postavičky jen ta, z lišty všechny.
# V demu (`familiar demo`) se nic nezapisuje: volby platí jen za běhu dema a opravy
# z panelu nálady se zahodí (data jsou z nahrávky, ne z tvé práce).
# Akce nabídky běží až po jejím zavření (QTimer 0), protože přepnutí režimu zavře
# okno, ze kterého nabídka vyskočila.
import copy, logging, os, time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QActionGroup, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from familiar import config, nastaveni, paths, skin as skins
from familiar.fsm import GONE, SLEEPING

PANEL_MS = 5000         # obnova otevřených panelů nálady
OBNOVA_MS = 1000        # kontrola, zda se změnil obsah nabídky v liště a ikona
SKINY_S = 10.0          # seznam skinů se čte z disku nejvýš jednou za tolik s
IKONA_PX = 64
lg = logging.getLogger("familiar.nabidka")


def ikona(skin, spi=False):
    """QIcon z prvního snímku postavičky (spící, když spí všichni)."""
    from familiar.dock import _table
    try:
        px, colors = skin.render(skin.anim_for(SLEEPING if spi else "idle"), 0, None)
    except Exception:       # vadný skin: ikona z vestavěného
        skin = skins.builtin()
        px, colors = skin.render(skin.anim_for(SLEEPING if spi else "idle"), 0, None)
    w, h = skin.size
    img = QImage(bytes(px), w, h, w, QImage.Format_Indexed8)
    img.setColorTable(_table(colors))
    img = img.convertToFormat(QImage.Format_ARGB32).scaled(IKONA_PX, IKONA_PX, Qt.KeepAspectRatio,
                                                            Qt.FastTransformation)
    return QIcon(QPixmap.fromImage(img))


class Ovladani(QObject):
    """Nabídky, lišta, nastavení a panely nálady nad hubem a pohledem (dock.Views)."""

    def __init__(self, hub, views, zapsano=None, path=None, tray=True, demo=False):
        super().__init__()
        self.hub, self.views, self.zapsano, self.demo = hub, views, zapsano, demo
        self.path = path or paths.config_file()
        self.panely = {}            # klíč familiara → PanelNalady
        self.dialog = None
        self.statistiky = None      # statistiky_okno.StatistikyOkno, nejvýš jedno
        self.chce_tray, self.tray, self.tray_menu = tray, None, None
        self._menu_sig = self._ikona_sig = self._tip = None
        self._hlaska = None
        self._skiny, self._skiny_cas = [], float("-inf")
        self.ptimer = QTimer(self)
        self.ptimer.timeout.connect(self.obnov_panely)
        self.otimer = QTimer(self)
        self.otimer.timeout.connect(self.obnov)
        self.otimer.start(OBNOVA_MS)
        self.obnov()

    @property
    def cfg(self):
        return self.views.cfg.data

    def postavicky(self):
        return sorted((f for f in self.hub.fams.values() if f.fsm.state != GONE), key=lambda f: f.name)

    def skiny(self):
        if time.monotonic() - self._skiny_cas > SKINY_S:
            self._skiny, self._skiny_cas = skins.available(), time.monotonic()
        return self._skiny

    # --- stavba nabídky ---

    @staticmethod
    def _akce(menu, text, f):
        a = menu.addAction(text)
        a.triggered.connect(lambda _=False: QTimer.singleShot(0, f))
        return a

    @staticmethod
    def _prepinac(menu, text, on, f):
        a = menu.addAction(text)
        a.setCheckable(True)
        a.setChecked(bool(on))
        a.triggered.connect(lambda checked: QTimer.singleShot(0, lambda: f(checked)))
        return a

    def naplnit(self, menu, key=None):
        """Akce nabídky postavičky (key) nebo lišty/podřimující postavičky (None)."""
        cfg, fam = self.cfg, self.hub.fams.get(key) if key is not None else None
        if fam is not None:
            menu.addSection(fam.name)
            self._akce(menu, "Panel nálady…", lambda: self.otevri_panel(key))
        else:
            sub = menu.addMenu("Panel nálady")
            fams = self.postavicky()
            for f in fams:
                self._akce(sub, f.name, lambda k=f.key: self.otevri_panel(k))
            sub.setEnabled(bool(fams))
        a = self._akce(menu, "Statistiky a úspěchy…", self.otevri_statistiky)
        if self.demo:
            a.setText("Statistiky a úspěchy… (ne v demu)")
            a.setEnabled(False)
        menu.addSeparator()
        a = self._prepinac(menu, "Ztlumit emoty", not cfg["zobrazit"]["emoty"] or cfg["tichy"],
                           lambda on: self.uloz({"zobrazit.emoty": not on}))
        if cfg["tichy"]:
            a.setText("Ztlumit emoty (tichý režim v nastavení)")
            a.setEnabled(False)
        if fam is not None:
            self._prepinac(menu, "Uspat", fam.spi, lambda on: self.hub.uspat(on, key))
        else:
            self._prepinac(menu, "Uspat všechny", self.hub.spi, lambda on: self.hub.uspat(on))
        self._prepinac(menu, "Režim soustředění", cfg["soustredeni"], lambda on: self.uloz({"soustredeni": on}))
        if fam is None:     # lišta (a podřimující postavička v docku): upozornění pro všechny
            u = cfg["upozorneni"]
            self._prepinac(menu, "Notifikace", u["notifikace"], lambda on: self.uloz({"upozorneni.notifikace": on}))
            self._prepinac(menu, "Zvuky", u["zvuky"], lambda on: self.uloz({"upozorneni.zvuky": on}))
        menu.addSeparator()
        cil = "dock" if self.views.mode == "perch" else "perch"
        a = self._akce(menu, f"Přepnout na {cil}", lambda: self.prepni_rezim(cil))
        if self.views.demo or (cil == "perch" and self.views.kwin_failed):
            a.setEnabled(False)
        sub = menu.addMenu("Skin")
        grp = QActionGroup(sub)
        for sid, name, _ in self.skiny():
            grp.addAction(self._prepinac(sub, name, sid == cfg["skin"],
                                         lambda on, sid=sid: on and self.uloz({"skin": sid})))
        sub.addSeparator()
        a = self._akce(sub, "Editor familiárů…", lambda: self.otevri_nastaveni(nastaveni.EDITOR))
        a.setEnabled(not self.demo)
        a = self._akce(menu, "Nastavení…", self.otevri_nastaveni)
        if self.demo:
            a.setText("Nastavení… (ne v demu)")
            a.setEnabled(False)
        menu.addSeparator()
        self._akce(menu, "Ukončit familiara", self.ukoncit)
        return menu

    def popup(self, widget, key, pos):
        """Nabídka u postavičky; widget drží odkaz, i kdyby ho mezitím pohled zavřel."""
        menu = QMenu(widget)
        self.naplnit(menu, key)
        menu.exec(pos)
        menu.deleteLater()

    # --- akce ---

    def uloz(self, changes):
        """Zapíše do configu jen hodnoty, které se liší od platných; True = zapsáno."""
        changes = {k: v for k, v in changes.items() if nastaveni._get(self.cfg, k) != v}
        if not changes:
            return False
        if self.demo:       # jen za běhu dema, config živého daemonu se nemění
            data = copy.deepcopy(self.cfg)
            for k, v in changes.items():
                *parents, key = k.split(".")
                tbl = data
                for part in parents:
                    tbl = tbl[part]
                tbl[key] = v
            self.views.apply(config.Config(data, self.path))
            self.obnov()
            return True
        try:
            nastaveni._write(self.path, nastaveni.upravit_text(nastaveni._read(self.path), changes))
        except Exception as e:      # rozbitý TOML, disk
            lg.error("změnu z nabídky nejde uložit do configu (%s)", type(e).__name__)
            self._menu_sig = None       # přepínače v liště zpět podle platného configu
            self.obnov()
            self.upozornit(f"Nastavení se nepodařilo uložit ({type(e).__name__}). "
                           f"Oprav {config._short(self.path)} v editoru nebo přes Nastavení….")
            return False
        lg.info("nabídka: %s", ", ".join(f"{k} = {v}" for k, v in changes.items()))
        if self.zapsano:
            self.zapsano()
        self.obnov()
        return True

    def upozornit(self, text):
        """Krátké upozornění: bublina z lišty, bez lišty nemodální okno."""
        if self.tray is not None:
            self.tray.showMessage("familiar", text, QSystemTrayIcon.Warning)
            return
        if self._hlaska is not None:
            self._hlaska.close()
        box = self._hlaska = QMessageBox(QMessageBox.Warning, "familiar", text)
        box.setModal(False)
        box.finished.connect(lambda _: box is self._hlaska and setattr(self, "_hlaska", None))
        box.show()

    def prepni_rezim(self, cil):
        self.views.forced = None        # volba z nabídky přebíjí i --mode
        if not self.uloz({"rezim": cil}):
            self.views.apply(self.views.cfg)

    def otevri_nastaveni(self, zalozka=None):
        """Nemodální dialog, nejvýš jeden; zalozka = nastaveni.EDITOR otevře editor familiárů."""
        if self.dialog is None:
            d = self.dialog = nastaveni.Nastaveni(None, self.path, zalozka)
            d.ulozeno.connect(lambda _: self.zapsano and self.zapsano())
            d.finished.connect(lambda _: self._zavri_dialog(d))
        elif zalozka == nastaveni.EDITOR:
            self.dialog.tabs.setCurrentIndex(self.dialog.editor_tab)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _zavri_dialog(self, d):
        if self.dialog is d:
            self.dialog = None
        d.deleteLater()

    def data_statistik(self):
        """(čísla ze služeb daemonu, skin); bez služeb (vypnuté, demo) prázdný přehled."""
        from familiar import stats
        sl = self.hub.sluzby
        return (sl.prehled() if sl is not None else stats.prehled(cfg=self.cfg)), self.hub.skin

    def otevri_statistiky(self):
        """Okno Statistiky a úspěchy; druhé otevření jen vytáhne existující."""
        from familiar import statistiky_okno
        w = self.statistiky
        if w is None:
            w = self.statistiky = statistiky_okno.StatistikyOkno(self.data_statistik)
            w.setAttribute(Qt.WA_DeleteOnClose)
            w.zmena.connect(self.uloz)
            w.destroyed.connect(lambda _=None, w=w: self.statistiky is w and setattr(self, "statistiky", None))
        w.obnov()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def otevri_panel(self, key):
        """Panel nálady familiara; druhé otevření jen vytáhne existující okno."""
        from familiar import panel
        p = self.panely.get(key)
        if p is None:
            fam = self.hub.fams.get(key)
            if fam is None:
                return None
            p = self.panely[key] = panel.PanelNalady(fam.name + (" (demo)" if self.demo else ""),
                                                     cesta=os.devnull if self.demo else None)
            p.setAttribute(Qt.WA_DeleteOnClose)
            p.oprava.connect(lambda pred, opr, k=key, p=p: self._prevezmi(k, p, pred, opr))
            p.destroyed.connect(lambda _=None, k=key, p=p: self.panely.get(k) is p and self.panely.pop(k))
            self._nastav_panel(key, p)
        p.show()
        p.raise_()
        p.activateWindow()
        if not self.ptimer.isActive():
            self.ptimer.start(PANEL_MS)
        return p

    def _prevezmi(self, key, p, pred, opr):
        """Oprava z panelu: zapsaná pro `familiar tune` a postavička náladu hned převezme."""
        lg.info("oprava nálady %s → %s", pred, opr)
        fam = self.hub.fams.get(key)
        if fam is not None:
            fam.mood.take(opr, time.time())
            self._nastav_panel(key, p)

    def _nastav_panel(self, key, p):
        stav = self.hub.stav_panelu(key, time.time())
        if stav is None:
            p.setWindowTitle(p.windowTitle().removesuffix(" (odešel)") + " (odešel)")
        else:
            p.nastav(stav)

    def obnov_panely(self):
        for key, p in list(self.panely.items()):
            self._nastav_panel(key, p)
        if not self.panely:
            self.ptimer.stop()

    def ukoncit(self):
        """Stejně čistý konec jako SIGTERM: smyčka skončí, run() odebere KWin skript."""
        lg.info("ukončení z nabídky")
        QApplication.quit()

    # --- lišta ---

    def obnov(self):
        """Lištu založí, jakmile je k dispozici (po přihlášení může chvíli chybět);
        nabídku a ikonu přestaví, jen když se změnilo, co ukazují."""
        if self.chce_tray and self.tray is None and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_menu = QMenu()
            self.tray = QSystemTrayIcon(self)
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self._klik)
            lg.info("ikona v liště")
        if self.tray is None:
            return
        cfg, fams = self.cfg, self.postavicky()
        sig = (cfg["zobrazit"]["emoty"], cfg["tichy"], cfg["soustredeni"], cfg["skin"], self.views.mode,
               cfg["upozorneni"]["notifikace"], cfg["upozorneni"]["zvuky"],
               self.views.kwin_failed, self.hub.spi, tuple((f.key, f.name) for f in fams), tuple(self.skiny()))
        if sig != self._menu_sig:
            self._menu_sig = sig
            for sub in self.tray_menu.findChildren(QMenu):
                sub.deleteLater()
            self.tray_menu.clear()
            self.naplnit(self.tray_menu, None)
        spi = self.hub.spi or bool(fams) and all(f.spi for f in fams)
        if (self.hub.skin, spi) != self._ikona_sig:
            self._ikona_sig = (self.hub.skin, spi)
            self.tray.setIcon(ikona(self.hub.skin, spi))
        n = len(fams)
        tip = "familiar – " + ("spí" if spi else "nikdo neběží" if not n
                               else f"{n} {'postavička' if n == 1 else 'postavičky' if n < 5 else 'postaviček'}")
        if tip != self._tip:        # každá změna je zpráva přes D-Bus do lišty
            self._tip = tip
            self.tray.setToolTip(tip)
        if not self.tray.isVisible():
            self.tray.show()

    def _klik(self, reason):
        """Levý klik na ikonu: panel nálady první postavičky."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            fams = self.postavicky()
            if fams:
                self.otevri_panel(fams[0].key)

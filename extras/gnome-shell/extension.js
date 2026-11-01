// familiar: rozšíření GNOME Shellu (45+) pro pixelové postavičky familiara.
//
// Na GNOME Waylandu aplikace nevidí cizí okna ani nemůže posunout svoje. Rozšíření proto dělá
// totéž co KWin skripty na KDE: spustí perch.js nad okny Mutteru (převlek v okna.js), hlásí
// daemonu pid aktivního okna a aktivuje okno terminálu. Daemon ho ovládá přes D-Bus objekt
// /cz/familiar/Gnome na sběrnici GNOME Shellu (popis rozhraní ve familiar/gnome.py); když jméno
// daemonu ze sběrnice zmizí, rozšíření se zastaví samo.
// perch.js do adresáře rozšíření zapíše `familiar install --gnome-rozsireni` (modul vygenerovaný
// z familiar/perch.js), v repozitáři (extras/gnome-shell/) proto chybí.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {aktivujPid, spustAktivni, spustPerch} from './okna.js';
import {spust as perchJs} from './perch.js';

const CESTA = '/cz/familiar/Gnome';
const VERZE = '1';
const XML = `<node>
  <interface name="cz.familiar.Gnome">
    <method name="Verze"><arg type="s" direction="out"/></method>
    <method name="Perch">
      <arg type="s" name="sluzba" direction="in"/><arg type="s" name="cesta" direction="in"/>
      <arg type="s" name="rozhrani" direction="in"/><arg type="b" direction="out"/>
    </method>
    <method name="PerchStop"/>
    <method name="Aktivni">
      <arg type="s" name="sluzba" direction="in"/><arg type="s" name="cesta" direction="in"/>
      <arg type="s" name="rozhrani" direction="in"/><arg type="b" direction="out"/>
    </method>
    <method name="AktivniStop"/>
    <method name="Aktivuj"><arg type="i" name="pid" direction="in"/><arg type="b" direction="out"/></method>
  </interface>
</node>`;

function prostredi() {
    return {
        display: global.display,
        workspaceManager: global.workspace_manager,
        WindowType: Meta.WindowType,
        aktivuj: mw => Main.activateWindow(mw),
        cas: () => global.get_current_time(),
        casovac: (ms, fn) => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            fn();
            return GLib.SOURCE_CONTINUE;
        }),
        zrusCasovac: id => GLib.source_remove(id),
        volej: (sluzba, cesta, rozhrani, metoda, args) => {
            const sig = `(${args.map(a => (typeof a === 'number' ? 'i' : 's')).join('')})`;
            const hodnoty = args.map(a => (typeof a === 'number' ? Math.trunc(a) : String(a)));
            Gio.DBus.session.call(sluzba, cesta, rozhrani, metoda, new GLib.Variant(sig, hodnoty), null,
                Gio.DBusCallFlags.NO_AUTO_START, 1000, null, (conn, res) => {
                    try {
                        conn.call_finish(res);
                    } catch (e) {
                        // daemon zrovna končí: nevadí, hlídání jména rozšíření zastaví
                    }
                });
        },
    };
}

export default class FamiliarExtension extends Extension {
    enable() {
        this._perch = null;
        this._aktivni = null;
        this._hlidani = {};
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, CESTA);
    }

    disable() {
        this.PerchStop();
        this.AktivniStop();
        this._dbus.unexport();
        this._dbus = null;
    }

    Verze() {
        return VERZE;
    }

    Perch(sluzba, cesta, rozhrani) {
        this.PerchStop();
        try {
            this._perch = spustPerch(prostredi(), perchJs, {sluzba, cesta, rozhrani});
        } catch (e) {
            logError(e, 'familiar: perch.js nejde spustit');
            return false;
        }
        this._hlidej('perch', sluzba, () => this.PerchStop());
        return true;
    }

    PerchStop() {
        this._nehlidej('perch');
        if (this._perch) {
            this._perch();
            this._perch = null;
        }
    }

    Aktivni(sluzba, cesta, rozhrani) {
        this.AktivniStop();
        this._aktivni = spustAktivni(prostredi(), {sluzba, cesta, rozhrani});
        this._hlidej('aktivni', sluzba, () => this.AktivniStop());
        return true;
    }

    AktivniStop() {
        this._nehlidej('aktivni');
        if (this._aktivni) {
            this._aktivni();
            this._aktivni = null;
        }
    }

    Aktivuj(pid) {
        return aktivujPid(prostredi(), pid);
    }

    _hlidej(co, sluzba, stop) {
        this._nehlidej(co);
        if (sluzba) {
            this._hlidani[co] = Gio.bus_watch_name_on_connection(Gio.DBus.session, sluzba,
                Gio.BusNameWatcherFlags.NONE, null, () => stop());
        }
    }

    _nehlidej(co) {
        if (this._hlidani[co]) {
            Gio.bus_unwatch_name(this._hlidani[co]);
            delete this._hlidani[co];
        }
    }
}

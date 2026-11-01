// familiar: okna GNOME Shellu (Mutter) převlečená za okna KWinu, aby nad nimi beze změny
// běžel perch.js (v rozšíření jako modul perch.js, vygenerovaný familiar/gnome.py), a aktivní
// okno a aktivace podle pid. Čistá logika bez importů gi://: Mutter a Main dodá extension.js
// v `env`, testy (tests/test_okna.py, QJSEngine) falešné objekty.
//
// env = {display, workspaceManager, WindowType,    global.display, global.workspace_manager, Meta.WindowType
//        aktivuj(metaOkno),                        Main.activateWindow (odminimalizuje, přepne plochu)
//        cas(),                                    global.get_current_time()
//        casovac(ms, fn) → id, zrusCasovac(id),    GLib.timeout_add / source_remove
//        volej(sluzba, cesta, rozhrani, metoda, [argumenty])}    D-Bus volání daemonu (bez odpovědi)
//
// Rozdíly proti KWinu: aktivity GNOME nemá (prázdné = všude); schovat okno posunem mimo obrazovku
// Mutter nedovolí (drží okna na obrazovce), proto se schovaná postavička skryje (aktor okna)
// a znovu ukáže při dalším přesunu; „na všech plochách“ u postavičky = stick() + make_above()
// (vždy navrchu, Qt to na Waylandu samo neumí).

const HIDDEN = -20000;

function obdelnik(r) {
    return {x: r.x, y: r.y, width: r.width, height: r.height};
}

// Převlek oken pro perch.js: {workspace, KWin, QTimer, callDBus, zastav()}.
export function vytvorPlochu(env) {
    var spojeni = [];       // [objekt, id signálu] k odpojení
    var casovace = [];
    var obaly = {};         // id okna → převlek (stejný objekt pro totéž okno)
    var skryte = {};        // id okna → metaOkno: postavička schovaná skrytím aktoru

    function pripoj(obj, signal, fn) {
        spojeni.push([obj, obj.connect(signal, fn)]);
    }

    function aktor(mw) {
        return mw.get_compositor_private ? mw.get_compositor_private() : null;
    }

    function obal(mw) {
        if (!mw) return null;
        var id = String(mw.get_id());
        if (obaly[id] && obaly[id].mw === mw) return obaly[id];
        var o = {
            mw: mw, internalId: id, activities: [], hidden: false, deleted: false,
            get resourceClass() { return String(mw.get_wm_class() || "").toLowerCase(); },
            get caption() { return String(mw.get_title() || ""); },
            get pid() { return mw.get_pid(); },
            get normalWindow() { return mw.get_window_type() === env.WindowType.NORMAL; },
            get dialog() {
                var t = mw.get_window_type();
                return t === env.WindowType.DIALOG || t === env.WindowType.MODAL_DIALOG;
            },
            get minimized() { return mw.minimized; },
            set minimized(v) { if (v) mw.minimize(); else mw.unminimize(); },
            get onAllDesktops() { return mw.is_on_all_workspaces(); },
            set onAllDesktops(v) {
                if (!v) return;
                if (!mw.is_on_all_workspaces()) mw.stick();
                if (!mw.is_above()) mw.make_above();
            },
            get desktops() {
                var w = mw.get_workspace();
                return mw.is_on_all_workspaces() || !w ? [] : [w];
            },
            get frameGeometry() {
                var r = obdelnik(mw.get_frame_rect()), a = aktor(mw);
                if (skryte[id] && a && !a.visible) { r.x = HIDDEN; r.y = HIDDEN; }
                return r;
            },
            set frameGeometry(g) {
                var a = aktor(mw);
                if (g.x <= HIDDEN / 2) {
                    skryte[id] = mw;
                    if (a) a.hide();
                    return;
                }
                mw.move_frame(true, Math.round(g.x), Math.round(g.y));
                if (skryte[id]) {
                    delete skryte[id];
                    if (a) a.show();
                }
            },
            get clientGeometry() { return obdelnik(mw.frame_rect_to_client_rect(mw.get_frame_rect())); },
            captionChanged: {connect: function (fn) { pripoj(mw, "notify::title", function () { fn(); }); }},
            frameGeometryChanged: {connect: function (fn) {
                pripoj(mw, "position-changed", function () { fn(); });
                pripoj(mw, "size-changed", function () { fn(); });
            }}
        };
        obaly[id] = o;
        return o;
    }

    var workspace = {
        windowList: function () {
            var ws = env.display.list_all_windows(), out = [], nove = {};
            for (var i = 0; i < ws.length; i++) {
                var o = obal(ws[i]);
                nove[o.internalId] = o;
                out.push(o);
            }
            obaly = nove;
            return out;
        },
        get stackingOrder() {
            return env.display.sort_windows_by_stacking(env.display.list_all_windows()).map(obal);
        },
        get currentDesktop() { return env.workspaceManager.get_active_workspace(); },
        set currentDesktop(ws) { ws.activate(env.cas()); },
        currentActivity: "",
        get activeScreen() { return env.display.get_current_monitor(); },
        get activeWindow() { return obal(env.display.focus_window); },
        set activeWindow(w) { if (w) env.aktivuj(w.mw); },
        clientArea: function (_, kde) {
            if (kde && kde.mw) return obdelnik(kde.mw.get_work_area_current_monitor());
            return obdelnik(env.workspaceManager.get_active_workspace().get_work_area_for_monitor(kde));
        },
        windowAdded: {connect: function (fn) {
            pripoj(env.display, "window-created", function (_, mw) { fn(obal(mw)); });
        }},
        windowRemoved: {connect: function () {}},      // pojistkou je časovač perch.js
        windowActivated: {connect: function (fn) {
            pripoj(env.display, "notify::focus-window", function () { fn(workspace.activeWindow); });
        }},
        currentDesktopChanged: {connect: function (fn) {
            pripoj(env.workspaceManager, "active-workspace-changed", function () { fn(); });
        }}
    };

    function QTimer() {
        var self = this, fns = [];
        this.interval = 1000;
        this.id = 0;
        this.timeout = {connect: function (fn) { fns.push(fn); }};
        this.start = function () {
            self.stop();
            self.id = env.casovac(self.interval, function () {
                for (var i = 0; i < fns.length; i++) fns[i]();
            });
            casovace.push(self);
        };
        this.stop = function () {
            if (self.id) env.zrusCasovac(self.id);
            self.id = 0;
        };
    }

    function callDBus(sluzba, cesta, rozhrani, metoda) {
        env.volej(sluzba, cesta, rozhrani, metoda, Array.prototype.slice.call(arguments, 4));
    }

    function zastav() {
        for (var i = 0; i < spojeni.length; i++) {
            try { spojeni[i][0].disconnect(spojeni[i][1]); } catch (e) { /* okno už zaniklo */ }
        }
        spojeni = [];
        for (var j = 0; j < casovace.length; j++) casovace[j].stop();
        casovace = [];
        for (var id in skryte) {
            var a = aktor(skryte[id]);
            if (a) a.show();
        }
        skryte = {};
    }

    return {workspace: workspace, KWin: {MaximizeArea: 2}, QTimer: QTimer, callDBus: callDBus, zastav: zastav};
}

// Spustí perch.js (funkce spust z vygenerovaného modulu) nad okny Mutteru; → funkce, která ho zastaví.
// dbus = {sluzba, cesta, rozhrani} pro zprávy daemonu (meze, strana), null = jen umisťovat.
export function spustPerch(env, spust, dbus) {
    var p = vytvorPlochu(env);
    spust(p.workspace, p.KWin, p.QTimer, p.callDBus, dbus && dbus.cesta ? dbus : null);
    return p.zastav;
}

// Hlásí daemonu pid aktivního okna (jako KWin skript familiar-aktivni); → funkce, která to zastaví.
export function spustAktivni(env, dbus) {
    function hlas() {
        var w = env.display.focus_window;
        env.volej(dbus.sluzba, dbus.cesta, dbus.rozhrani, "aktivni", [w ? w.get_pid() : 0]);
    }
    var id = env.display.connect("notify::focus-window", hlas);
    hlas();
    return function () { env.display.disconnect(id); };
}

// Aktivuje nejvyšší normální okno procesu pid (klik na notifikaci); true = našlo se.
export function aktivujPid(env, pid) {
    var ws = env.display.sort_windows_by_stacking(env.display.list_all_windows());
    for (var i = ws.length - 1; i >= 0; i--) {
        if (ws[i].get_pid() === pid && ws[i].get_window_type() === env.WindowType.NORMAL) {
            env.aktivuj(ws[i]);
            return true;
        }
    }
    return false;
}

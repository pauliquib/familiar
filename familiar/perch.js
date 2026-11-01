// familiar: posadí okna postaviček na horní hranu jejich terminálu (KWin, Plasma 6).
//
// Titulek okna postavičky:
//   "familiar|<pid terminálu>|<stav>|<počet kliků>|<strana>|<odsazení>|<mezera>|<okraj>|<zakrytí>|<roh řady>|<číslo>|<posun>"
// posun = procházka (familiar/pohyb.py): px od klidového místa směrem dovnitř titulku. Skript ho
// omezí tak, aby postavička nezajela do textu titulku (odhad podle délky titulku terminálu,
// TEXT_CHAR px na znak) ani za kraj okna; ven k tlačítkům okna nejde nikdy. Mez pošle daemonu.
// Titulek okna bubliny (činnost, zpráva, žádost o povolení):
//   "familiar-bublina|<číslo postavičky>|<strana>|<rozměr>"
// Bublina sedí vedle své postavičky na dané straně (vlevo/vpravo), spodkem v úrovni jejího
// okna; když by na té straně vyjela z obrazovky, přehodí se na druhou stranu postavičky
// (a skript to daemonu ohlásí, ocásek pak míří opačně). Schovanou postavičku následuje mimo obrazovku.
// Zprávy daemonu: když daemon před skript vloží `var DBUS = {sluzba, cesta, rozhrani}`
// (familiar/kwin.py), volá callDBus(…, "meze", číslo, px), callDBus(…, "strana", číslo, strana)
// a callDBus(…, "orez", číslo, obdélníky) při každé změně; bez DBUS jen umisťuje.
// strana vlevo/vpravo a px z configu ([okno] v familiar/config.py); daemon je
// posílá v titulku, takže změna configu se projeví hned (captionChanged).
// Chybějící pole (starší titulek) = výchozí hodnoty.
// Skript nahrává a odebírá daemon sám přes D-Bus (familiar/kwin.py).
//
// Zakrytý titulek terminálu (jiné okno nad ním) podle volby zakrytí:
//   navrchu  postavička zůstane na titulku. Její okno je keepAbove, ale části zakryté okny nad
//            terminálem skript ohlásí ("orez": "x,y,š,v;…" v souřadnicích okna postavičky,
//            prázdné = nic) a daemon je nekreslí, takže je postavička za oknem jako terminál.
//            Úplně zakrytý terminál (není z něj vidět nic) ji schová jako minimalizovaný.
//   schovat  postavička zmizí; čekající na uživatele (waiting) sedne do dolního rohu na své straně
//   rada     postavička sedne do řady v rohu obrazovky (roh řady), po odkrytí se vrátí;
//            v řadě zůstane i u úplně zakrytého terminálu (řada je právě pro zakryté)
// Minimalizovaný terminál nebo terminál na jiné ploše či aktivitě postavičku schová
// vždy; čekající si sedne do řady v rohu (v režimu rada do rohu řady, jinak dolů na
// svou stranu). Postavička bez nalezeného terminálu sedí v rohu stejně.

const RIGHT = 120;      // výchozí odsazení: místo pro tlačítka titulku terminálu
const GAP = 4;
const PAD = 8;
const COVER = "navrchu";
const CORNER = "vpravo-dole";
const CORNERS = ["vpravo-dole", "vpravo-nahore", "vlevo-dole", "vlevo-nahore"];
const HIDDEN = -20000;  // schování posunem mimo obrazovku, bez animace minimalizace
const SLIVER = 4;       // zbytek terminálu užší než tolik px = není vidět (stíny, zaokrouhlení škálování)
const TEXT_CHAR = 7;    // odhad šířky znaku titulku terminálu (Breeze, 10 pt), px
const TEXT_PAD = 16;    // odstup procházky od textu titulku, px
const FRESH = 1000;     // ms po přidání okna postavičky, kdy jeho aktivace není od uživatele

var clicks = {};        // id postavičky → poslední počet kliků
var reported = {};      // "meze|číslo" / "strana|číslo" → naposledy ohlášená hodnota

function report(what, num, value) {
    var key = what + "|" + num;
    value = String(value);
    if (reported[key] === value) return;
    reported[key] = value;
    if (typeof DBUS !== "undefined" && DBUS && typeof callDBus === "function")
        callDBus(DBUS.sluzba, DBUS.cesta, DBUS.rozhrani, what, String(num), value);
}

function parse(w) {
    if (w.resourceClass !== "familiar") return null;
    var p = String(w.caption).split("|");
    if (p[0] !== "familiar" || p.length < 4) return null;
    function num(s, d) { var n = parseInt(s); return isNaN(n) ? d : n; }
    return {term: parseInt(p[1]) || 0, state: p[2], clicks: p[3], left: p[4] === "vlevo",
            offset: num(p[5], RIGHT), gap: num(p[6], GAP), pad: num(p[7], PAD),
            cover: p[8] === "schovat" || p[8] === "rada" ? p[8] : COVER,
            corner: CORNERS.indexOf(p[9]) >= 0 ? p[9] : CORNER, num: p[10] || "",
            walk: Math.max(0, num(p[11], 0))};
}

function parseBubble(w) {
    if (w.resourceClass !== "familiar") return null;
    var p = String(w.caption).split("|");
    if (p[0] !== "familiar-bublina" || p.length < 3) return null;
    return {num: p[1], left: p[2] === "vlevo"};
}

function id(w) {
    return String(w.internalId);
}

function terminalOf(pid) {
    if (!pid) return null;
    var ws = workspace.windowList();
    for (var i = 0; i < ws.length; i++)
        if (ws[i].pid === pid && ws[i].normalWindow) return ws[i];
    return null;
}

function onCurrentDesktop(w) {
    if (w.onAllDesktops) return true;
    var ds = w.desktops;
    for (var i = 0; i < ds.length; i++)
        if (ds[i] === workspace.currentDesktop) return true;
    return false;
}

function onCurrentActivity(w) {
    var as = w.activities;      // prázdné = na všech aktivitách
    if (!as || !as.length) return true;
    for (var i = 0; i < as.length; i++)
        if (as[i] === workspace.currentActivity) return true;
    return false;
}

function shown(w) {
    return !w.minimized && onCurrentDesktop(w) && onCurrentActivity(w);
}

function intersects(a, b) {
    return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function covered(term, rect) {
    var order = workspace.stackingOrder;
    var above = false;
    for (var i = 0; i < order.length; i++) {
        var w = order[i];
        if (id(w) === id(term)) { above = true; continue; }
        if (!above || w.resourceClass === "familiar" || !w.normalWindow || !shown(w)) continue;
        if (intersects(w.frameGeometry, rect)) return true;
    }
    return false;
}

// Úplně zakrytý terminál: jeho rámeček minus okna nad ním ve stackingOrder.
// Odečítají se jen normální okna a dialogy na téže ploše a aktivitě, neminimalizovaná
// a neskrytá; ne postavičky, plocha ani panely (panely jsou úzké a vždy nahoře,
// terminál pod nimi bývá vidět, a raději necháme postavičku navrchu než ji ztratit).
function buried(term, order) {
    var left = [term.frameGeometry];
    var above = false;
    for (var i = 0; i < order.length && left.length; i++) {
        var w = order[i];
        if (id(w) === id(term)) { above = true; continue; }
        if (!above || w.resourceClass === "familiar" || !(w.normalWindow || w.dialog)
            || w.hidden === true || w.deleted === true || !shown(w)) continue;
        var g = w.frameGeometry, next = [];
        for (var j = 0; j < left.length; j++)
            subtract(left[j], g, next);
        left = next;
    }
    return !left.length;
}

// Části rect zakryté okny nad terminálem (stejná okna jako v buried) pro zprávu "orez":
// "x,y,š,v;…" relativně k rect, zaokrouhlené ven (radši o pixel víc zakrytého než prosvítání).
function occluded(term, rect, order) {
    var out = [];
    var above = false;
    for (var i = 0; i < order.length; i++) {
        var w = order[i];
        if (id(w) === id(term)) { above = true; continue; }
        if (!above || w.resourceClass === "familiar" || !(w.normalWindow || w.dialog)
            || w.hidden === true || w.deleted === true || !shown(w)) continue;
        var g = w.frameGeometry;
        if (!intersects(g, rect)) continue;
        var x = Math.floor(Math.max(g.x, rect.x) - rect.x), y = Math.floor(Math.max(g.y, rect.y) - rect.y);
        var r = Math.ceil(Math.min(g.x + g.width, rect.x + rect.width) - rect.x);
        var b = Math.ceil(Math.min(g.y + g.height, rect.y + rect.height) - rect.y);
        out.push([x, y, r - x, b - y].join(","));
    }
    return out.join(";");
}

// r minus g jako nejvýš 4 obdélníky (pruh nad, pod, vlevo, vpravo); úzké zbytky zahodí
function subtract(r, g, out) {
    if (!intersects(r, g)) { out.push(r); return; }
    var top = Math.max(r.y, g.y), bottom = Math.min(r.y + r.height, g.y + g.height);
    var parts = [{x: r.x, y: r.y, width: r.width, height: top - r.y},
                 {x: r.x, y: bottom, width: r.width, height: r.y + r.height - bottom},
                 {x: r.x, y: top, width: g.x - r.x, height: bottom - top},
                 {x: g.x + g.width, y: top, width: r.x + r.width - g.x - g.width, height: bottom - top}];
    for (var i = 0; i < parts.length; i++)
        if (parts[i].width >= SLIVER && parts[i].height >= SLIVER) out.push(parts[i]);
}

function move(w, x, y) {
    var g = w.frameGeometry;
    if (Math.abs(g.x - x) < 0.5 && Math.abs(g.y - y) < 0.5) return;
    w.frameGeometry = {x: x, y: y, width: g.width, height: g.height};
}

var placed = {};        // číslo postavičky → {x, y, width, height, win} z posledního průchodu

function put(w, info, x, y) {
    move(w, x, y);
    var g = w.frameGeometry;
    placed[info.num] = {x: x, y: y, width: g.width, height: g.height, win: w};
}

function layout() {
    placed = {};
    var perTerm = {};
    var rows = {};      // obrazovka + roh → postavičky v řadě
    var keys = [];
    var hid = {};       // id terminálu → úplně zakrytý (počítá se jednou za průchod)
    var order = null;
    var ws = workspace.windowList();
    for (var i = 0; i < ws.length; i++) {
        var f = ws[i];
        var info = parse(f);
        if (!info) continue;
        var term = terminalOf(info.term);
        if (term && clicks[id(f)] !== undefined && clicks[id(f)] !== info.clicks) {
            if (term.minimized) term.minimized = false;
            if (!onCurrentDesktop(term) && term.desktops.length) workspace.currentDesktop = term.desktops[0];
            workspace.activeWindow = term;
        }
        clicks[id(f)] = info.clicks;

        var g = f.frameGeometry;
        var hidden = !term || !shown(term);
        if (!hidden && info.cover === "navrchu") {
            if (hid[id(term)] === undefined) hid[id(term)] = buried(term, order || (order = workspace.stackingOrder));
            hidden = hid[id(term)];
        }
        if (!hidden) {
            var k = perTerm[id(term)] || 0;
            perTerm[id(term)] = k + 1;
            var area = workspace.clientArea(KWin.MaximizeArea, term);
            var c = term.clientGeometry;
            var x = info.left ? c.x + info.offset + k * (g.width + info.gap)
                              : c.x + c.width - info.offset - (k + 1) * (g.width + info.gap);
            var lim = walkLimit(term, c, x, g.width, info.left);
            report("meze", info.num, lim);
            x += (info.left ? 1 : -1) * Math.min(info.walk, lim);
            var y = Math.max(area.y, c.y - g.height + 2);
            var rect = {x: x, y: y, width: g.width, height: g.height};
            if (info.cover === "navrchu" || !covered(term, rect)) {
                report("orez", info.num, info.cover === "navrchu"
                       ? occluded(term, rect, order || (order = workspace.stackingOrder)) : "");
                f.onAllDesktops = true;
                put(f, info, x, y);
                continue;
            }
        }
        report("orez", info.num, "");      // v rohu nebo schovaná: nic neořezávat
        // sem dojde zakrytá (schovat, rada), schovaný či úplně zakrytý terminál (navrchu)
        // nebo žádný terminál
        var inRow = info.state === "waiting" || !term || (info.cover === "rada" && !hidden);
        if (!inRow) {
            put(f, info, HIDDEN, HIDDEN);
            continue;
        }
        var corner = info.cover === "rada" ? info.corner : (info.left ? "vlevo" : "vpravo") + "-dole";
        var screen = term && shown(term) ? workspace.clientArea(KWin.MaximizeArea, term)
                                     : workspace.clientArea(KWin.MaximizeArea, workspace.activeScreen,
                                                            workspace.currentDesktop);
        var key = [screen.x, screen.y, screen.width, screen.height, corner].join(",");
        if (!rows[key]) { rows[key] = {area: screen, corner: corner, items: []}; keys.push(key); }
        rows[key].items.push([f, info]);
    }
    for (var r = 0; r < keys.length; r++)
        row(rows[keys[r]]);
    for (var b = 0; b < ws.length; b++) {
        var bi = parseBubble(ws[b]);
        if (bi) bubble(ws[b], bi);
    }
}

// Jak daleko dovnitř titulku smí postavička na procházce (px od klidového místa x):
// k odhadnutému textu titulku (vycentrovaný, TEXT_CHAR px na znak) nejblíž na TEXT_PAD,
// bez textu ke druhému kraji okna.
function walkLimit(term, c, x, width, left) {
    var n = String(term.caption || "").length;
    var tw = n ? Math.min(c.width, n * TEXT_CHAR + 2 * TEXT_PAD) : 0;
    var mid = c.x + c.width / 2;
    var lim = left ? (n ? mid - tw / 2 : c.x + c.width) - (x + width)
                   : x - (n ? mid + tw / 2 : c.x);
    return Math.max(0, Math.floor(lim));
}

function bubble(w, bi) {
    var at = placed[bi.num];
    if (!at || at.x <= HIDDEN / 2) { move(w, HIDDEN, HIDDEN); return; }
    var g = w.frameGeometry;
    var a = workspace.clientArea(KWin.MaximizeArea, at.win);
    var left = bi.left;
    // u kraje obrazovky na druhou stranu postavičky, když se tam vejde (jinak zarovnat k okraji)
    if (left && at.x - g.width < a.x && at.x + at.width + g.width <= a.x + a.width) left = false;
    else if (!left && at.x + at.width + g.width > a.x + a.width && at.x - g.width >= a.x) left = true;
    report("strana", bi.num, left ? "vlevo" : "vpravo");
    var x = left ? at.x - g.width : at.x + at.width;
    var y = at.y + at.height - g.height;
    x = Math.max(a.x, Math.min(x, a.x + a.width - g.width));
    y = Math.max(a.y, Math.min(y, a.y + a.height - g.height));
    w.onAllDesktops = true;
    move(w, x, y);
}

function row(rw) {
    // řada od rohu podél vodorovného okraje pracovní plochy (bez panelů)
    var a = rw.area, left = rw.corner.indexOf("vlevo") === 0, top = rw.corner.indexOf("nahore") > 0;
    var n = 0;
    for (var j = 0; j < rw.items.length; j++) {
        var w = rw.items[j][0], ci = rw.items[j][1], g = w.frameGeometry;
        w.onAllDesktops = true;
        put(w, ci, left ? a.x + ci.pad + n : a.x + a.width - ci.pad - n - g.width,
            top ? a.y + ci.pad : a.y + a.height - g.height - ci.pad);
        n += g.width + ci.gap;
    }
}

var known = {};         // id → okna, o kterých skript ví (watch)
var born = {};          // id → kdy přibylo (windowAdded), ms
var lastActive = null;  // poslední aktivní okno, které není postavička ani bublina

function watch(w) {
    known[id(w)] = true;
    if (w.resourceClass === "familiar") w.captionChanged.connect(layout);
    else w.frameGeometryChanged.connect(layout);
}

function ours(w) {
    return !!w && !!(parse(w) || parseBubble(w));
}

// Nové okno postavičky či bubliny KWin aktivuje (Qt na Waylandu WindowDoesNotAcceptFocus
// kompozitoru nepředá), terminál by ztratil fokus: vrátí se oknu aktivnímu předtím. Až po
// návratu do smyčky událostí (ne uvnitř aktivace) a jen pokud je aktivní pořád naše okno.
// Klik na existující postavičku nechá být (terminál aktivuje layout podle počtu kliků).
var refocus = new QTimer();
refocus.singleShot = true;
refocus.interval = 0;
refocus.timeout.connect(function () {
    if (lastActive && ours(workspace.activeWindow)) workspace.activeWindow = lastActive;
});

function activated(w) {
    if (w && !ours(w)) lastActive = w;
    else if (w && (!known[id(w)] || Date.now() - born[id(w)] < FRESH))
        refocus.start();        // KWin ho aktivuje před windowAdded, nebo hned po něm
    layout();
}

workspace.windowList().forEach(watch);
workspace.windowAdded.connect(function (w) {
    watch(w);
    born[id(w)] = Date.now();
    var a = workspace.activeWindow;
    if (ours(w) && a && id(a) === id(w)) refocus.start();
    layout();
});
workspace.windowRemoved.connect(function (w) {
    delete known[id(w)];
    delete born[id(w)];
    if (lastActive && id(lastActive) === id(w)) lastActive = null;
    layout();
});
workspace.windowActivated.connect(activated);
workspace.currentDesktopChanged.connect(layout);
if (workspace.currentActivityChanged) workspace.currentActivityChanged.connect(layout);

var timer = new QTimer();   // pojistka pro změny bez signálu (minimalizace, plochy)
timer.interval = 250;
timer.timeout.connect(layout);
timer.start();
lastActive = ours(workspace.activeWindow) ? null : workspace.activeWindow;
layout();

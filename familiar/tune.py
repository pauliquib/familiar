# Opravy nálady a jejich vyhodnocení (`familiar tune`, brána fáze 1 v kapitole 8 konceptu).
#
# Panel nálady zapisuje každou opravu (i potvrzení) jako řádek JSONL do
# $XDG_STATE_HOME/familiar/opravy.jsonl. Řádek nese jen štítky, čísla a čas:
#   {"ts": 1792648800.0, "predikce": "klid", "oprava": "radost", "valence": 0.12,
#    "aktivace": 0.31, "signaly": {"dekovani": 1, "unava": 0.2}}
# Žádný text promptu ani událostí; uloz_opravu() jiné hodnoty odmítne.
#
# spocitej() z oprav určí přesnost, matici záměn, stav brány (≥ 50 oprav, ≥ 70 %)
# a navrhne posun prahů [nalada.prahy]. Nic nezapisuje, návrh vypíše jako TOML.
import argparse, json, math, os, sys

from familiar import mood, paths

STITKY = (mood.KLID, mood.RADOST, mood.ZVEDAVOST, mood.FRUSTRACE, mood.ZMATEK, mood.UNAVA)
NAZVY = {mood.KLID: "Klid", mood.RADOST: "Radost", mood.ZVEDAVOST: "Zvědavost",
         mood.FRUSTRACE: "Frustrace", mood.ZMATEK: "Zmatek", mood.UNAVA: "Únava"}
# číselné signály, které smí řádek nést: počty impulzů (tabulka 3.3) a stav čítačů enginu
SIGNALY = set(mood.IMPULSES) | {"zmatek", "unava", "otazek", "podil_otazek"}

BRANA_N, BRANA_PROCENT = 50, 70     # fáze 1: ve vzorku 50 okamžiků aspoň 35 trefa
NAVRH_N, NAVRH_CHYB = 20, 5         # návrh až od tolika záznamů a tolika neshod
NAVRH_ZLEPSENI = 2                  # návrh jen, když přidá aspoň tolik trefených záznamů
KROK, MAX_POSUN = 0.05, 0.2         # mřížka prahů a největší posun za jedno ladění
# laditelné prahy: klíč → (min, max, celé číslo)
ROZSAHY = {"frustrace_valence": (-1.0, 1.0, False), "frustrace_aktivace": (0.0, 1.0, False),
           "radost_valence": (-1.0, 1.0, False), "zvedavost_aktivace": (0.0, 1.0, False),
           "zvedavost_valence": (-1.0, 1.0, False), "unava": (0.05, 1.0, False),
           "zmatek_korekci": (1, 10, True)}


def soubor():
    """$XDG_STATE_HOME/familiar/opravy.jsonl (výchozí ~/.local/state)."""
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(paths.home(), ".local", "state")
    return os.path.join(state, "familiar", "opravy.jsonl")


def _cislo(x, lo, hi, co):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f"{co}: čekám číslo {lo}…{hi}, ne {x!r}")
    return x


def _stitek(x, co):
    if x not in STITKY:
        raise ValueError(f"{co}: neznámý štítek nálady {x!r}")
    return x


def uloz_opravu(predikce, oprava, valence, aktivace, ts, signaly=None, cesta=None):
    """Připojí řádek opravy (oprava == predikce je potvrzení); vrací cestu k souboru.
    Neznámý štítek, nečíselná hodnota nebo neznámý signál = ValueError, nic se nezapíše."""
    row = {"ts": round(_cislo(ts, 0, 1e11, "ts"), 3),
           "predikce": _stitek(predikce, "predikce"), "oprava": _stitek(oprava, "oprava"),
           "valence": round(_cislo(valence, -1, 1, "valence"), 4),
           "aktivace": round(_cislo(aktivace, 0, 1, "aktivace"), 4)}
    if signaly:
        bad = [k for k in signaly if k not in SIGNALY]
        if bad:
            raise ValueError(f"neznámé signály {bad!r}")
        row["signaly"] = {k: round(_cislo(v, 0, 1e6, k), 4) for k, v in sorted(signaly.items())}
    cesta = cesta or soubor()
    os.makedirs(os.path.dirname(cesta), mode=0o700, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(cesta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)      # jeden zápis s O_APPEND: řádky se nepromíchají
    finally:
        os.close(fd)
    return cesta


def nacti(cesta):
    """(záznamy, počet vadných řádků); chybějící soubor vyhodí FileNotFoundError."""
    rows, vadne = [], 0
    with open(cesta, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                rows.append({"ts": float(r["ts"]), "predikce": _stitek(r["predikce"], ""),
                             "oprava": _stitek(r["oprava"], ""), "valence": float(r["valence"]),
                             "aktivace": float(r["aktivace"]), "signaly": dict(r.get("signaly") or {})})
            except (ValueError, KeyError, TypeError):
                vadne += 1
    return rows, vadne


def odhad(v, a, prahy, signaly=None):
    """Štítek z bodu (v, a) a čítačů v signálech podle stejných prahů jako MoodEngine._classify.

    MoodEngine štítek z čísel nedává (_classify čte stav enginu: korekce, únavu, otázky),
    proto tahle čistá funkce pro simulaci prahů nad uloženými body. Chybějící čítač
    znamená, že jeho podmínka neplatí (zmatek, únava, zvědavost bez údaje o otázkách)."""
    s, p = signaly or {}, prahy
    if s.get("zmatek", 0) >= p["zmatek_korekci"]:
        return mood.ZMATEK
    if v <= p["frustrace_valence"] and a >= p["frustrace_aktivace"]:
        return mood.FRUSTRACE
    if "unava" in s and s["unava"] >= p["unava"]:
        return mood.UNAVA
    if v >= p["radost_valence"]:
        return mood.RADOST
    if ("otazek" in s and "podil_otazek" in s and a >= p["zvedavost_aktivace"] and v >= p["zvedavost_valence"]
            and s["otazek"] >= p["zvedavost_otazek"] and s["podil_otazek"] >= p["zvedavost_podil"]):
        return mood.ZVEDAVOST
    return mood.KLID


def _trefy(rows, prahy):
    return sum(odhad(r["valence"], r["aktivace"], prahy, r["signaly"]) == r["oprava"] for r in rows)


def _kandidati(klic, cur):
    lo, hi, cele = ROZSAHY[klic]
    if cele:
        return [x for x in range(int(cur) - 2, int(cur) + 3) if lo <= x <= hi or x == cur]
    n = round(MAX_POSUN / KROK)
    vals = {round(cur + i * KROK, 2) for i in range(-n, n + 1)} | {cur}
    return sorted(x for x in vals if lo <= x <= hi or x == cur)


def navrhni(rows, prahy):
    """Souřadnicový sestup po mřížce prahů; při shodě vyhraje hodnota nejblíž současné.
    Vrací (nové prahy jen se změnami, trefy nyní, trefy s návrhem)."""
    nyni = _trefy(rows, prahy)
    best = dict(prahy)
    for _ in range(3):
        for klic in ROZSAHY:
            cur = prahy[klic]
            score = lambda x: (_trefy(rows, {**best, klic: x}), -abs(x - cur))
            best[klic] = max(_kandidati(klic, cur), key=score)
    po = _trefy(rows, best)
    zmeny = {k: best[k] for k in ROZSAHY if best[k] != prahy[k]}
    if po - nyni < NAVRH_ZLEPSENI:
        zmeny = {}
    return zmeny, nyni, po


def spocitej(cesta=None, prahy=None):
    """Report jako slovník: přesnost, matice záměn, brána fáze 1 a návrh prahů."""
    cesta = cesta or soubor()
    prahy = prahy or mood.defaults()["prahy"]
    rows, vadne = nacti(cesta)
    n = len(rows)
    trefa = sum(r["predikce"] == r["oprava"] for r in rows)
    matice = {p: {o: 0 for o in STITKY} for p in STITKY}
    for r in rows:
        matice[r["predikce"]][r["oprava"]] += 1
    # kolik dalších trefených záznamů chybí: n + k ≥ 50 a 10 (trefa + k) ≥ 7 (n + k)
    chybi_zaznamu = max(0, BRANA_N - n)
    chybi_trefa = max(chybi_zaznamu, -(-(BRANA_PROCENT * n - 100 * trefa) // (100 - BRANA_PROCENT)))
    report = {
        "soubor": cesta, "zaznamu": n, "vadnych": vadne, "trefa": trefa,
        "presnost": trefa / n if n else None, "matice": matice,
        "brana": {"splneno": n >= BRANA_N and 100 * trefa >= BRANA_PROCENT * n,
                  "chybi_zaznamu": chybi_zaznamu, "chybi_trefa": chybi_trefa},
        "navrh": None, "prahy": dict(prahy),
    }
    if n >= NAVRH_N and n - trefa >= NAVRH_CHYB:
        zmeny, nyni, po = navrhni(rows, prahy)
        report["navrh"] = {"prahy": zmeny, "nyni": nyni / n, "po": po / n}
    return report


# --- výstup ---------------------------------------------------------------------

def _pct(x):
    return f"{100 * x:.1f} %".replace(".", ",")


def _toml(x):
    return str(x) if isinstance(x, int) else f"{x:.2f}"


def vypis(rep, out=None):
    w = lambda s="": print(s, file=out or sys.stdout)
    n, t = rep["zaznamu"], rep["trefa"]
    w(f"Opravy nálady: {_kratce(rep['soubor'])}")
    w(f"Záznamů: {n} (potvrzení {t}, oprav {n - t})" + (f", vadných řádků: {rep['vadnych']}" if rep["vadnych"] else ""))
    if not n:
        w("Zatím žádný záznam. Náladu oprav nebo potvrď v panelu familiara.")
        return
    w(f"Přesnost: {_pct(rep['presnost'])} ({t}/{n})")
    w()
    used = [s for s in STITKY if any(rep["matice"][s].values()) or any(rep["matice"][p][s] for p in STITKY)]
    w("Matice záměn (řádek = familiar, sloupec = ty):")
    w(" " * 11 + "".join(f"{NAZVY[s]:>10}" for s in used))
    for p in used:
        w(f"{NAZVY[p]:<11}" + "".join(f"{rep['matice'][p][o] or '·':>10}" for o in used))
    w()
    b = rep["brana"]
    head = f"Brána fáze 1 (≥ {BRANA_N} záznamů a ≥ {BRANA_PROCENT} % přesnost): "
    if b["splneno"]:
        w(head + "splněno")
    else:
        why = []
        if b["chybi_zaznamu"]:
            why.append(f"chybí {b['chybi_zaznamu']} záznamů")
        if b["chybi_trefa"] > b["chybi_zaznamu"]:
            why.append(f"přesnost dorovná až aspoň {b['chybi_trefa']} dalších trefených záznamů v řadě")
        w(head + "nesplněno – " + ", ".join(why))
    w()
    nav = rep["navrh"]
    if nav is None:
        w(f"Návrh prahů: málo dat (potřeba ≥ {NAVRH_N} záznamů a ≥ {NAVRH_CHYB} oprav).")
    elif not nav["prahy"]:
        w(f"Návrh prahů: posun prahů by odhad z (valence, aktivace) nezlepšil (nyní {_pct(nav['nyni'])}).")
    else:
        w(f"Návrh prahů – odhad z uložených (valence, aktivace): nyní {_pct(nav['nyni'])}, "
          f"s návrhem {_pct(nav['po'])}.")
        w("Vlož do ~/.config/familiar/config.toml (tabulka [nalada.prahy] smí v souboru být jen jednou,")
        w("pokud tam už je, uprav jen uvedené klíče):")
        w()
        w("[nalada.prahy]")
        for k, x in nav["prahy"].items():
            w(f"{k} = {_toml(x)}    # bylo {_toml(rep['prahy'][k])}")
    w()
    w("Váhy impulzů [nalada.impulsy] se z oprav nenavrhují: bod (valence, aktivace) je součet celé")
    w("historie impulzů s útlumem, váha se z něj zpětně určit nedá. Lad je přehráváním nahrávek.")


def _kratce(path):
    home = paths.home().rstrip("/")
    return "~" + path[len(home):] if home and path.startswith(home + "/") else path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="familiar tune", description="přesnost nálady podle tvých oprav a návrh prahů")
    ap.add_argument("--soubor", help="soubor s opravami (výchozí $XDG_STATE_HOME/familiar/opravy.jsonl)")
    ap.add_argument("--config", help="config, jehož prahy se ladí (výchozí ~/.config/familiar/config.toml)")
    args = ap.parse_args(argv)
    from familiar import config
    prahy = config.load(args.config)["nalada"]["prahy"]
    cesta = args.soubor or soubor()
    try:
        rep = spocitej(cesta, prahy)
    except FileNotFoundError:
        print(f"Zatím žádné opravy ({_kratce(cesta)} neexistuje).")
        print("Pravé tlačítko na familiarovi → Panel nálady, tam štítek potvrď nebo oprav.")
        return 0
    except OSError as e:
        print(f"Soubor s opravami nejde přečíst: {e}", file=sys.stderr)
        return 1
    vypis(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())

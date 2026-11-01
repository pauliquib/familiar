# familiar: příkazová řádka (run, demo, replay, doctor, install, uninstall, config, nastaveni, editor, skins,
# skin-import, tune, statistiky, upgrade, stop).
# Qt se importuje až v podpříkazech, které ho potřebují.
import argparse, os, signal, subprocess, sys, time

from familiar import __version__, paths


def add_daemon_args(ap, demo):
    """Volby daemonu; sdílí je `familiar run/demo` i `python -m familiar.dock`.
    demo: None = bez dema, "flag" = volba --demo ID, "positional" = povinné ID."""
    ap.add_argument("--mode", choices=("auto", "perch", "dock"), default=None,
                    help="perch = na okně terminálu (KDE), dock = jedno okno; bez volby podle configu (rezim)")
    if demo is None:
        return
    if demo == "flag":
        ap.add_argument("--demo", metavar="SESSION", help="přehrát nahrávku (začátek id)")
    else:
        ap.add_argument("demo", metavar="ID", help="začátek id nahrávky")
    ap.add_argument("--speed", type=float, default=1.0, help="zrychlení dema")
    ap.add_argument("--gap", type=float, default=4.0, help="nejdelší pauza v demu, s")


def cmd_run(args):
    from familiar import dock
    os.chdir(paths.home())      # nedržet pracovní adresář (třeba výměnný disk s repem)
    args.demo = None
    dock.run(args)


def cmd_demo(args):
    from familiar import dock
    dock.run(args)


def cmd_replay(args):
    from familiar import replay
    replay.report(args)


def cmd_doctor(args):
    from familiar import doctor
    return doctor.main()


def cmd_install(args):
    from familiar import install
    install.install(dry=args.dry_run, autostart=args.autostart, source=args.source, via=args.via,
                    povoleni=args.povoleni, agents=args.agents, gnome_rozsireni=args.gnome_rozsireni)


def cmd_uninstall(args):
    from familiar import install
    install.uninstall(dry=args.dry_run, agents=args.agents)


def cmd_config(args):
    from familiar import config
    return config.cli(args)


def cmd_nastaveni(args):
    """Dialog nastavení samostatně (běžící daemon změnu přenačte sám)."""
    from familiar import nastaveni
    print("uloženo" if nastaveni.otevri() else "zrušeno")


def cmd_editor(args):
    """Dialog nastavení otevřený na záložce Editor familiárů (s volbou id rovnou ten skin)."""
    from familiar import nastaveni
    print("uloženo" if nastaveni.otevri(zalozka=nastaveni.EDITOR, skin_id=args.id) else "zavřeno")


def cmd_tune(args):
    from familiar import tune
    return tune.main(args.args)


def cmd_skins(args):
    """Dostupné skiny; * = zvolený v configu. Každý se zkusí načíst, vadný ukáže chybu."""
    from familiar import config, skin
    chosen, bad = config.load()["skin"], 0
    for sid, name, source in skin.available():
        s = skin.load(sid)
        print(f"{'*' if sid == chosen else ' '} {sid:16} {name:30} {source}")
        if s.error:
            bad += 1
            print(f"    CHYBA: {s.error}")
    print(f"\nzměna: skin = \"<id>\" v {paths.config_file()} (projeví se za běhu)")
    return 1 if bad else 0


def cmd_skin_import(args):
    """Skin z exportu Aseprite (PNG + JSON) nebo souboru .aseprite do uživatelských skinů."""
    from familiar import skin, skin_import
    try:
        dest, report, warn = skin_import.importuj(args.soubor, args.id, args.mapa, args.prepsat)
    except skin.SkinError as e:
        print(f"CHYBA: {e}", file=sys.stderr)
        return 1
    for w in warn:
        print(f"pozor: {w}")
    for state, (tag, derived) in report.items():
        print(f"  {state:10} {tag}{'  (odvozeno z idle)' if derived else ''}")
    sid = os.path.basename(dest)
    print(f"skin {sid!r} vytvořen v {dest}")
    if args.nahled:
        skin.save_preview(skin.load(sid), args.nahled)
        print(f"náhled: {args.nahled}")
    print(f'použití: skin = "{sid}" v {paths.config_file()}')
    return 0


def cmd_statistiky(args):
    """Dnešek a týden z uložených souborů (bez daemonu; daemon ukládá jednou za [statistiky] ukladat_s).
    Jen čte: nic nezapíše ani vadný soubor neodloží."""
    import json
    from familiar import config, progress, stats
    data = stats.prehled(stats.Statistiky(zalohovat=False), progress.Postup(zalohovat=False), config.load().data)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    from familiar.stats import DNY, cas

    def radek(d):
        return (f"session {d['session']} · prompty {d['prompty']} · nástroje {d['volani']} · chyby {d['chyby']} · "
                f"aktivní {cas(d['aktivni_s'])}")
    d, t, p = data["dnes"], data["tyden"], data["postup"]
    print(f"Dnes {data['datum']}: {radek(d)}")
    top = sorted(d["nastroje"].items(), key=lambda x: (-x[1], x[0]))[:5]
    if top:
        print("  nejčastější nástroje: " + ", ".join(f"{k} {v}" for k, v in top))
    print(f"\nTýden {t['od']} – {t['do']}: {radek(t['soucet'])}")
    for jm, den in zip(DNY, t["dny"]):
        print(f"  {jm} {den['datum'][5:]}  prompty {den['prompty']:4}  nástroje {den['volani']:5}  "
              f"aktivní {cas(den['aktivni_s']):>12}")
    odem = sum(u["odemceno"] for u in p["uspechy"])
    print(f"\nÚroveň {p['uroven']} ({p['xp']} XP, do další {p['do_dalsi']}) · úspěchy {odem}/{len(p['uspechy'])} · "
          f"doplňky {sum(x['odemceno'] for x in p['doplnky'])}/{len(p['doplnky'])}")
    print(f"(z {config._short(stats.soubor())}; běžící daemon ukládá nejvýš jednou za minutu)")
    return 0


def cmd_upgrade(args):
    """Přeinstaluje z uloženého zdroje přes install.sh (ten spustí i `familiar install`)."""
    from familiar import install
    rec = install.read_record()
    src = rec.get("source")
    if not src:
        sys.exit("CHYBA: neznám zdroj instalace, spusť install.sh z repozitáře")
    script = os.path.join(src, "install.sh")
    if not os.path.exists(script):
        sys.exit(f"CHYBA: {script} neexistuje (je připojený disk s repozitářem?)")
    cmd = ["sh", script] + (["--autostart"] if rec.get("autostart") else [])
    print(" ".join(cmd), flush=True)
    code = subprocess.call(cmd)
    if code == 0 and paths.daemon_pid() is not None:
        print("daemon běží se starou verzí: familiar stop && familiar run")
    return code


def cmd_stop(args):
    pid = paths.daemon_pid()
    if pid is None:
        print("familiar neběží")
        return 0
    if pid == 0:
        sys.exit("CHYBA: daemon běží, ale nezapsal pid (starší verze), ukonči ho ručně")
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):     # nejvýš 5 s
        time.sleep(0.1)
        if paths.daemon_pid() is None:
            print(f"familiar (pid {pid}) ukončen")
            return 0
    sys.exit(f"CHYBA: familiar (pid {pid}) neskončil do 5 s")


def parser():
    from familiar import replay
    ap = argparse.ArgumentParser(prog="familiar", description="familiar: pixelová postavička u Claude Code")
    ap.add_argument("--version", action="version", version=f"familiar {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="PŘÍKAZ")

    p = sub.add_parser("run", help="spustit daemon (živě z hooků)")
    add_daemon_args(p, None)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("demo", help="přehrát nahrávku v okně")
    add_daemon_args(p, "positional")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("replay", help="souhrn nahrávek bez okna")
    replay.add_args(p)
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("doctor", help="zkontrolovat instalaci")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("install", help="hooky, pravidlo KWinu (KDE), spouštěč (idempotentní)")
    p.add_argument("--autostart", action="store_true", help="spouštět po přihlášení")
    p.add_argument("--dry-run", action="store_true", help="jen vypsat, co by se udělalo")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--povoleni", action="store_true", default=None,
                   help="zapnout povolení (Povolit/Zamítnout) z bubliny u postavičky")
    g.add_argument("--bez-povoleni", dest="povoleni", action="store_false", default=None, help="vypnout povolení z bubliny")
    p.add_argument("--source", help=argparse.SUPPRESS)     # předává install.sh: cesta k repu
    p.add_argument("--via", choices=("uv", "pipx", "venv"), help=argparse.SUPPRESS)
    p.add_argument("--agents", metavar="SEZNAM", help="hooky dalších agentů: auto (výchozí, jen "
                   "používaní: ~/.gemini, ~/.codex), none, all, nebo gemini,codex")
    p.add_argument("--gnome-rozsireni", action="store_true",
                   help="nainstalovat rozšíření GNOME Shellu (postavičky na okně terminálu na GNOME Waylandu)")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="vrátit, co udělal install")
    p.add_argument("--dry-run", action="store_true", help="jen vypsat, co by se udělalo")
    p.add_argument("--agents", metavar="SEZNAM", help="odebrat jen hooky těchto agentů (gemini,codex "
                   "nebo all), zbytek instalace nechat; auto je pak nebude znovu přidávat")
    p.set_defaults(func=cmd_uninstall)

    from familiar import config
    p = sub.add_parser("config", help="konfigurace (~/.config/familiar/config.toml)")
    config.add_args(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("nastaveni", help="otevřít dialog nastavení")
    p.set_defaults(func=cmd_nastaveni)

    p = sub.add_parser("editor", help="editor familiárů a jejich animací (záložka v nastavení)")
    p.add_argument("id", nargs="?", help="skin, který se otevře (výchozí zvolený v configu)")
    p.set_defaults(func=cmd_editor)

    p = sub.add_parser("tune", help="přesnost nálady podle oprav z panelu a návrh prahů", add_help=False)
    p.add_argument("args", nargs=argparse.REMAINDER, help="volby `familiar tune --help`")
    p.set_defaults(func=cmd_tune)

    p = sub.add_parser("skins", help="dostupné skiny (vlastní v ~/.local/share/familiar/skins/)")
    p.set_defaults(func=cmd_skins)

    p = sub.add_parser("skin-import", help="vytvořit skin z Aseprite (.aseprite nebo PNG + JSON)")
    p.add_argument("soubor", help="soubor .aseprite/.ase nebo export Export Sprite Sheet (.json/.png)")
    p.add_argument("--id", help="id skinu (výchozí podle jména souboru)")
    p.add_argument("--mapa", metavar="TOML", help="mapování tagů na stavy, viz docs/skiny.md")
    p.add_argument("--nahled", metavar="PNG", help="uložit náhled všech stavů a nálad")
    p.add_argument("--prepsat", action="store_true", help="přepsat existující skin se stejným id")
    p.set_defaults(func=cmd_skin_import)

    p = sub.add_parser("statistiky", help="dnešní a týdenní statistiky, úroveň a úspěchy (z uložených souborů)")
    p.add_argument("--json", action="store_true", help="vypsat jako JSON")
    p.set_defaults(func=cmd_statistiky)

    p = sub.add_parser("upgrade", help="přeinstalovat z repozitáře, odkud byl nainstalován")
    p.set_defaults(func=cmd_upgrade)

    p = sub.add_parser("stop", help="ukončit běžící daemon")
    p.set_defaults(func=cmd_stop)
    return ap


def main(argv=None):
    ap = parser()
    args, rest = ap.parse_known_args(argv)
    if getattr(args, "func", None) is cmd_tune:
        args.args = rest + args.args        # volby tune (--soubor …) předá celé tune.main
    elif rest:
        ap.error("neznámé argumenty: " + " ".join(rest))
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())

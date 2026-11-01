# Logika vizuálních vrstev u postavičky, bez Qt (hub ji drží, dock.py jen kreslí):
#   bublina s činností  cinnost_text(událost) → „čte hub.py“, „spouští pytest“ …
#   měřič kontextu      kontext_procento / kontext_uroven / ukazat_meric
#   pomocníci           Pomocnici: malé postavičky za běžící subagenty (příchod a odchod)
#   povolení z bubliny  Zadosti: čekající požadavky jedné postavičky a kdy je zrušit
# Do textů jde jen jméno nástroje, jméno souboru (bez cesty), vzor hledání a program
# z příkazu Bash; nikdy text promptu ani obsah souboru.
import os, re

BUBLINA_S = 3.0     # [bublina] doba_s: jak dlouho visí bublina s činností po změně
ZPRAVA_S = 4.0      # oznam(): výchozí doba krátké zprávy
KONTEXT_PRAH = 80   # [kontext] prah, %: varování a červený měřič
KONTEXT_POZOR = 20  # žlutý měřič od prahu − tolik %
KONTEXT_HYST = 5    # varování znovu až po poklesu pod práh − tolik % (po compactu)
POMOCNICI_LIMIT = 3     # [pomocnici] limit, další jako „+N“
PRICHOD_S = 0.3     # animace pomocníka: vynoření …
ODCHOD_S = 0.6      # … a odchod (stoupá a bliká)
NASLEDUJICI_S = 1.0     # povolení: nový stejný nástroj až tolik s po požadavku = uživatel odpověděl

# --- bublina s činností ---------------------------------------------------------

CTENI = {"Read", "NotebookRead", "read_file", "read_many_files"}
UPRAVY = {"Edit", "MultiEdit", "NotebookEdit", "replace", "apply_patch", "edit"}
ZAPIS = {"Write", "write_file"}
SHELL = {"Bash", "run_shell_command", "shell", "exec_command", "local_shell"}
HLEDANI = {"Grep", "search_file_content", "grep", "grep_search"}
SOUBORY = {"Glob", "glob", "LS", "list_directory"}
PEVNE = {"WebFetch": "čte web", "web_fetch": "čte web", "WebSearch": "hledá na webu",
         "google_web_search": "hledá na webu", "web_search": "hledá na webu",
         "TodoWrite": "plánuje", "write_todos": "plánuje", "Agent": "deleguje…", "Task": "deleguje…",
         "AskUserQuestion": "ptá se"}
PREDPONY = {"sudo", "env", "time", "nice", "nohup", "exec", "command", "timeout", "xargs", "npx",
            "pnpx", "bunx", "uvx"}
SPUSTENI = {("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("pdm", "run"), ("hatch", "run")}
PODPRIKAZY = {"git", "npm", "pnpm", "yarn", "bun", "cargo", "go", "uv", "docker", "podman", "kubectl",
              "make", "gh", "pip", "pip3", "dnf", "systemctl", "just"}
PRESKOCIT = {"cd", "pushd", "popd", "export", "source", ".", "set", "true", ":", "echo"}
MAX_JMENO = 24      # delší jméno souboru, vzor nebo program se zkrátí uprostřed


def zkrat(text, n=MAX_JMENO):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - n // 2 - 1] + "…" + text[-(n // 2):]


def program(cmd):
    """Co příkaz Bash spouští: „pytest“, „git status“, „python3 -m pytest …“ → „pytest“.
    Přeskočí cd, echo a přiřazení proměnných, předpony (sudo, env, uv run …); None, když nic."""
    for cast in re.split(r"&&|\|\||[;|\n]", cmd if isinstance(cmd, str) else ""):
        slova = cast.split()
        while slova and (re.match(r"[A-Za-z_]\w*=", slova[0]) or slova[0] in PREDPONY
                         or slova[0].startswith("-") or slova[0].isdigit()):
            slova.pop(0)
        if len(slova) >= 2 and (os.path.basename(slova[0]), slova[1]) in SPUSTENI:
            slova = slova[2:]
        if not slova or slova[0] in PRESKOCIT:
            continue
        prog = os.path.basename(slova[0].strip("\"'()")) or slova[0]
        if re.fullmatch(r"python[\d.]*", prog) and len(slova) >= 3 and slova[1] == "-m":
            return zkrat(slova[2])
        if prog in PODPRIKAZY and len(slova) >= 2 and re.fullmatch(r"[a-z][\w:-]*", slova[1]):
            return zkrat(f"{prog} {slova[1]}")
        return zkrat(prog)
    return None


def cinnost_text(ev):
    """Krátký text do bubliny podle události, nebo None (činnost se nemění)."""
    kind, d = ev["kind"], ev["data"]
    tool = d.get("tool") or ""
    if kind == "user.prompt":
        return "přemýšlí…"
    if kind == "subagent.start":
        return f"deleguje: {zkrat(d.get('type') or 'agent')}"
    if kind == "context.compact":
        return "zhušťuje kontext"
    if d.get("agent"):
        return None     # nástroje subagentů hlavní postavičku nepřepisují (jsou to pomocníci)
    if kind == "agent.waiting":
        if d.get("why") == "question":
            return "čeká na odpověď"
        return f"čeká na povolení: {zkrat(tool or '?')}"
    if kind != "tool.start":
        return None
    soubor = d.get("file")
    soubor = zkrat(soubor) if isinstance(soubor, str) and soubor.strip() else None
    vzor = d.get("pattern")
    vzor = zkrat(vzor, 20) if isinstance(vzor, str) and vzor.strip() else None
    if tool in CTENI:
        return f"čte {soubor}" if soubor else "čte soubor"
    if tool in UPRAVY:
        return f"upravuje {soubor}" if soubor else "upravuje kód"
    if tool in ZAPIS:
        return f"píše {soubor}" if soubor else "píše soubor"
    if tool in SHELL:
        prog = program(d.get("cmd"))
        return f"spouští {prog}" if prog else "spouští příkaz"
    if tool in HLEDANI:
        return f"hledá {vzor}" if vzor else "hledá v kódu"
    if tool in SOUBORY:
        return f"hledá {vzor}" if vzor else "hledá soubory"
    if tool in PEVNE:
        return PEVNE[tool]
    if tool.startswith("mcp__"):
        tool = tool.rsplit("__", 1)[-1]
    return f"používá {zkrat(tool)}" if tool else None


# --- měřič kontextu --------------------------------------------------------------

def kontext_procento(ctx):
    """Obsazení kontextu v celých procentech (0–100), nebo None."""
    if not ctx or not ctx.get("window"):
        return None
    return max(0, min(100, round(100 * ctx["used"] / ctx["window"])))


def kontext_uroven(pct, prah):
    """Barva měřiče: "ok" / "pozor" (od prahu − KONTEXT_POZOR) / "plno" (od prahu)."""
    if pct >= prah:
        return "plno"
    return "pozor" if pct >= prah - KONTEXT_POZOR else "ok"


def ukazat_meric(rezim, pct, prah):
    """[kontext] zobrazit: vzdy / nad_prahem / nikdy."""
    if pct is None or rezim == "nikdy":
        return False
    return rezim == "vzdy" or pct >= prah


# --- pomocníci subagentů -----------------------------------------------------------

class Pomocnici:
    """Malé postavičky za běžící subagenty: přijdou při subagent.start, při subagent.done
    krátce odcházejí (ODCHOD_S) a pak zmizí."""

    def __init__(self):
        self.seznam = []    # [{"agent", "typ", "od", "konec"}] v pořadí příchodu

    def feed(self, ev):
        kind, d = ev["kind"], ev["data"]
        if kind == "subagent.start":
            for p in self.seznam:
                if p["agent"] == d.get("agent") and p["konec"] is None:
                    p["typ"] = d.get("type") or p["typ"]
                    return
            self.seznam.append({"agent": d.get("agent"), "typ": d.get("type") or "agent",
                                "od": ev["ts"], "konec": None})
        elif kind == "subagent.done":
            for p in self.seznam:
                if p["agent"] == d.get("agent") and p["konec"] is None:
                    p["konec"] = ev["ts"]
                    return
        elif kind == "session.end":
            self.seznam.clear()

    def ted(self, now, limit):
        """→ ([(pomocník, fáze "prichod" | "bezi" | "odchod", postup 0–1)], kolik dalších se
        nevešlo, jejich typy). Odešlé zahodí; odcházející drží místo, dokud nezmizí."""
        self.seznam = [p for p in self.seznam if p["konec"] is None or now - p["konec"] < ODCHOD_S]
        out = []
        for p in self.seznam[:limit]:
            if p["konec"] is not None:
                out.append((p, "odchod", min(1.0, (now - p["konec"]) / ODCHOD_S)))
            elif now - p["od"] < PRICHOD_S:
                out.append((p, "prichod", max(0.0, (now - p["od"]) / PRICHOD_S)))
            else:
                out.append((p, "bezi", 1.0))
        dalsi = tuple(p["typ"] for p in self.seznam[limit:] if p["konec"] is None)
        return out, len(dalsi), dalsi


# --- povolení z bubliny ---------------------------------------------------------------

KONEC_KOLA = ("user.prompt", "agent.done", "agent.interrupted", "agent.failed")


class Zadosti:
    """Čekající požadavky na povolení u jedné postavičky. Hook PermissionRequest běží
    souběžně s dialogem v terminálu; když uživatel odpoví tam, hook o tom neví a bublinu
    je třeba zrušit podle dalších událostí (udalost() vrátí, které požadavky zrušit).
    PermissionRequest nemá tool_use_id: požadavek si zapamatuje otevřené nástroje stejného
    jména a stejného druhu (hlavní agent / subagent) jako kandidáty a zruší se, až všechny
    skončí. Konec jiného nástroje (paralelní Read při čekajícím Bash) ho neruší; nový
    stejný nástroj déle než NASLEDUJICI_S po požadavku nebo tool.start se `schvaleno` ano."""

    def __init__(self):
        self.cekajici = {}      # id → {"shrnuti", "nastroj", "agent", "kandidati", "cas"}
        self.otevrene = {}      # (agent_id nebo None, tool_use_id) → jméno nástroje

    def __bool__(self):
        return bool(self.cekajici)

    def pridej(self, id_, shrnuti, now):
        agent, nastroj = bool(shrnuti.get("agent")), shrnuti.get("nastroj")
        kand = {k for k, t in self.otevrene.items() if t == nastroj and (k[0] is not None) == agent}
        self.cekajici[id_] = {"shrnuti": dict(shrnuti), "nastroj": nastroj, "agent": agent,
                              "kandidati": kand, "cas": now}

    def odeber(self, id_):
        return self.cekajici.pop(id_, None) is not None

    def prvni(self):
        """(id, shrnuti) nejstaršího čekajícího požadavku, nebo None."""
        if not self.cekajici:
            return None
        i = min(self.cekajici)
        return i, self.cekajici[i]["shrnuti"]

    def udalost(self, ev):
        """Další událost postavičky → [id požadavků, které už neplatí] (a odebere je)."""
        kind, d = ev["kind"], ev["data"]
        agent = d.get("agent")
        klic, tool = (agent, d.get("id")), d.get("tool")
        zrusit = []
        if kind == "session.end":
            zrusit = list(self.cekajici)
            self.otevrene.clear()
        elif kind in KONEC_KOLA and not agent:
            zrusit = [i for i, z in self.cekajici.items() if not z["agent"]]
            self.otevrene = {k: t for k, t in self.otevrene.items() if k[0] is not None}
        elif kind == "subagent.done":
            self.otevrene = {k: t for k, t in self.otevrene.items() if k[0] != agent}
        elif kind == "tool.start":
            novy = klic not in self.otevrene
            self.otevrene[klic] = tool
            for i, z in self.cekajici.items():
                if z["agent"] == bool(agent) and z["nastroj"] == tool and (
                        d.get("schvaleno") or (novy and ev["ts"] - z["cas"] >= NASLEDUJICI_S)):
                    zrusit.append(i)
        elif kind in ("tool.end", "tool.error", "tool.denied"):
            self.otevrene.pop(klic, None)
            for i, z in self.cekajici.items():
                if z["agent"] != bool(agent) or z["nastroj"] != tool:
                    continue
                if not z["kandidati"]:
                    zrusit.append(i)        # PreToolUse nedorazil: stačí stejné jméno
                elif klic in z["kandidati"]:
                    z["kandidati"].discard(klic)
                    if not z["kandidati"]:
                        zrusit.append(i)
        for i in zrusit:
            del self.cekajici[i]
        return zrusit

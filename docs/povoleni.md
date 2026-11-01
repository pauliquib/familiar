# Povolení z bubliny (hook `PermissionRequest`)

Zjištěno 23. 10. 2026 pro Claude Code 2.1.309 z dokumentace
([hooks](https://code.claude.com/docs/en/hooks#permissionrequest),
[hooks-guide](https://code.claude.com/docs/en/hooks-guide),
[changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md))
a tam, kde dokumentace mlčí, z kódu nainstalované verze (řetězce v binárce, ne spuštěním).

## Vstup
- Hook běží, když se Claude Code chystá zeptat na povolení (ne u každého nástroje jako
  `PreToolUse`). Matcher je jméno nástroje.
- Pole: společná (`session_id`, `transcript_path`, `cwd`, `permission_mode`,
  `hook_event_name`, u subagenta `agent_id`, `agent_type`) + `tool_name`, `tool_input`,
  volitelně `permission_suggestions`, u MCP `mcp_server`. **Bez `tool_use_id`.**
- `permission_suggestions`: pole „permission update“ záznamů (`addRules` s `rules`
  `[{toolName, ruleContent?}]`, `behavior`, `destination`; `setMode`, `addDirectories` …).
  Není to přesný seznam voleb dialogu (dialog úprav souborů ho nečte vůbec).

## Výstup (exit 0, JSON na stdout)
```json
{"hookSpecificOutput": {"hookEventName": "PermissionRequest",
  "decision": {"behavior": "allow", "updatedInput": {}, "updatedPermissions": []}}}
{"hookSpecificOutput": {"hookEventName": "PermissionRequest",
  "decision": {"behavior": "deny", "message": "proč", "interrupt": false}}}
```
- `updatedInput` (jen allow) nahrazuje celý vstup; validuje se a znovu se porovná
  s pravidly deny/ask. Familiar ho neposílá.
- `updatedPermissions` (jen allow): „vždy povolit“ – hook smí vrátit některý
  z obdržených `permission_suggestions`. `destination` určuje, kam se zapíše
  (`session` jen v paměti, `localSettings`, `projectSettings`, `userSettings`).
- `message` (jen deny) dostane Claude jako důvod; `interrupt: true` Clauda zastaví.
- Allow nepřebije pravidla deny/ask. U nástrojů, které vyžadují interakci
  (`AskUserQuestion`), se allow z hooku ignoruje.
- Exit 0 bez výstupu = žádné rozhodnutí, normální dialog. Exit 2 se u této události
  neuplatní (tok beze změny). Neplatný JSON = chyba hooku, tok beze změny.

## Timeout a souběh s dialogem
- Výchozí timeout command hooku je **600 s** (pole `timeout` v sekundách). Po timeoutu
  Claude hook zruší a výstup zahodí → žádné rozhodnutí (u `onFailure: "block"` by
  timeout povolení zamítl – familiar `onFailure` nenastavuje).
- Hooky jedné události běží paralelně (familiar-emit i povolovací hook).
- **Hlavní session a subagenti v popředí: dialog v terminálu se ukáže hned, hook běží
  souběžně, platí první odpověď.** (Kód 2.1.309: `runHooks` se spouští na pozadí
  vedle dialogu, výsledek se použije, jen když dialog ještě není zodpovězený.)
  Odpověď v terminálu hook neukončí – běží dál až do své odpovědi nebo timeoutu
  a jeho pozdější rozhodnutí se zahodí. Familiar proto musí bublinu zrušit sám
  (další událost téže session, viz níže).
- **Subagenti na pozadí** (`awaitAutomatedChecksBeforeDialog`) a teammates: Claude
  nejdřív počká na hooky, dialog ukáže až potom. Tam bublina dialog zdržuje → pro
  požadavky s `agent_id` krátký timeout (server 15 s, klient nejvýš 20 s, i když daemon visí).
- Bez možnosti dialogu (`-p`, subagenti bez promptu) se hook spustí taky a když nic
  nerozhodne, volání se zamítne – bublina tam nic nepokazí, nanejvýš zdrží.
- Notifikace `permission_prompt` přijde až po ~6 s čekání.

## Návrh familiara
- Samostatný hook, výslovně zapínaný: `familiar install --povoleni` přidá do
  `PermissionRequest` položku `familiar-emit claude-code --povoleni` (timeout 600),
  `familiar install --bez-povoleni` ji odebere, `familiar uninstall` odebere vše.
  Bez volby zůstane stav beze změny. Stávající hook `familiar-emit claude-code`
  se nemění a dál nic nevypisuje.
- Klient (`familiar/povoleni_klient.py`, stejný rychlý spouštěč sh + `python3 -I -S`):
  připojí se ke stream socketu `$XDG_RUNTIME_DIR/familiar-povoleni.sock` (0600),
  pošle jeden řádek JSON a čeká na jeden řádek odpovědi. Daemon neběží, odmítne,
  zavře spojení, timeout nebo jakákoli chyba → exit 0 bez výstupu = dialog v terminálu.
  JSON rozhodnutí vypíše jen po odpovědi `allow`/`deny`/`allow_always` z daemonu.
  `AskUserQuestion` a `ExitPlanMode` přeskočí (nechá na terminálu).
- Požadavek: `{"v": 1, "session", "pid", "agent": bool, "bez_terminalu": bool, "shrnuti":
  {"nastroj", "co", "zkraceno", "dotaz", "vzdy"}}`. `co` je příkaz Bash (řádky zachované,
  mezery sloučené, ≤ 500 znaků), cesta k souboru (domov jako `~`), celá URL, nebo text
  `query`/`skill`; nikdy text promptu ani obsah souboru. `zkraceno` = bublina by neukázala celý
  vstup (delší než 500 znaků, nebo nástroj, jehož vstup neumíme shrnout, např. MCP), `dotaz` =
  URL s query (může nést data ven). `vzdy` popisuje „vždy povolit“ (pravidla, složky, režim
  a kam se zapíšou: `[session]`, `[projekt]` = localSettings, `[projekt, sdílené]` =
  projectSettings); bez povolených návrhů nebo s popisem delším než 300 znaků chybí a tlačítko
  Vždy se neukáže. Návrhy samotné zůstávají v klientovi.
- Odpověď daemonu: `{"rozhodnuti": "allow" | "deny" | "allow_always"}`. Zamítnutí
  posílá Claudovi `message` „Uživatel to zamítl v bublině familiara.“, bez `interrupt`.
  „Vždy“ vrátí jako `updatedPermissions` jen návrhy z allowlistu (níže).

## Co bublina smí povolit (oprava po review, 23. 10.)
- Povolit jde jen to, co uživatel v bublině viděl celé. Bublina ukáže celý `co` (víc řádků,
  neproporcionální písmo, šířka až 110 px skinu, nejvýš 10 řádků, tooltip s celým textem)
  a řádek „Vždy = …“. Když se `co` nevejde, klient poslal `zkraceno`/`dotaz`, nebo server
  najde skryté znaky (řídicí, bidi, formátovací – nahradí je „�“), nabídne jen **Zamítnout**
  a „Celé jen v terminálu – odpověz tam“. Tři pojistky: bublina tlačítka nenakreslí, server
  `odpovez` allow odmítne (`jen_terminal`), klient allow při `zkraceno`/`dotaz` nevypíše.
  Klient bez příznaků (starší verze) = `jen_terminal`.
- Allowlist návrhů pro „Vždy“ (`povoleni_klient._navrh_ok`), ostatní se zahodí:
  - `addRules` jen s `behavior: "allow"`, neprázdnými `rules` (`toolName` řetězec) a
    `destination` `session`, `localSettings` nebo `projectSettings` – typický návrh u Bash,
    WebFetch a MCP („don't ask again … in this project“, ve vzorovém vstupu localSettings). Ne
    `userSettings` (platí pro všechny projekty), `cliArg`, `deny`/`ask` (bublina by měnila
    i zákazy) ani `replaceRules`/`removeRules`.
  - `addDirectories` jen `session` (přístup ke složce mimo projekt do konce session); trvalé
    přidání složky patří do terminálu, kde dialog ukáže, kam se zapíše.
  - `setMode` jen `acceptEdits` a jen `session` („allow all edits during this session“ u Edit/
    Write). Ne `bypassPermissions`, `plan`, `dontAsk` ani změna výchozího režimu v settings.
- Edit/Write: bublina ukáže jen cestu, ne obsah změny (obsah souboru do daemonu nejde);
  kdo chce vidět diff, odpoví v terminálu.
- Proti omylu kliknutím: po novém obsahu (jiný požadavek, třeba B téže postavičky hned po
  vyřízení A), zobrazení nebo skoku polohy jsou tlačítka 0,8 s šedá a neaktivní; rozhoduje
  uvolnění nad tlačítkem téhož požadavku, kde začal stisk; dvojklik se nepočítá. V docku se
  bubliny sousedních buněk nepřekrývají (další začne až za předchozí).
- Session bez terminálu (`claude -p`, Agent SDK): vstup hooku nemá TTY ani příznak
  neinteraktivního běhu (`permission_mode` je i tam `default`), proto klient čte
  `/proc/<pid claude>/fd/0` (není terminál → bez terminálu) a `cmdline` (`-p`, `--print`).
  Pak krátký timeout jako u subagentů (server 15 s, klient 20 s): Claude tam na hook čeká
  a bez rozhodnutí volání zamítne. Nečitelný proces = interaktivní.
- Notifikace „Čeká na povolení“ (odložená o `cekani_po_s`) se zruší i koncem nástroje, na
  který se čeká (`tool.end`/`tool.error` hlavního agenta – povoleno v terminálu), a odpovědí
  v bublině (`Povolovani.odpovez` → `Sluzby.odpovezeno`).
- Textová bublina (činnost, zprávy) je průhledná pro myš: v perch `Qt.WindowTransparentForInput`
  na QWindow (Wayland: prázdná `wl_surface.set_input_region`, ověřeno `WAYLAND_DEBUG=client`;
  zpět na celé okno `set_input_region(nil)`), v docku `WA_TransparentForMouseEvents`.

- Server (`familiar/povoleni.py`, QLocalServer) zruší požadavek, když se klient odpojí,
  po vlastním timeoutu (výchozí 300 s, u subagentů a session bez terminálu 15 s) nebo na pokyn hubu
  (`zrus_pid`) – hub ho má volat při další události téže postavičky (uživatel odpověděl
  v terminálu: `tool.end`, `tool.error`, `tool.denied`, `user.prompt`, `agent.done`,
  `session.end`).

## Integrace (vlna 2)
- `srv = povoleni.Povoleni(parent, timeout_s, timeout_agent_s)`; `srv.start()` až po
  `dock.listen()` (zámek), jen když je funkce zapnutá v configu; `srv.close()` při vypnutí/konci.
  Vypnutý server = klient se nepřipojí a hned skončí (dialog v terminálu).
- `srv.pozadavek(id, session, pid, shrnuti)` → najít familiara podle pid, ukázat
  `bublina.Bublina.povoleni(id, shrnuti)` u postavičky; `bublina.rozhodnuti(id, volba)` →
  `srv.odpovez(id, volba)`; `srv.zruseno(id)` → `bublina.skryj(id)`.
- Hub: při další události familiara s otevřeným požadavkem `srv.zrus_pid(pid)`.

Provedeno v M14 (`dock.Povolovani`, `vrstvy.Zadosti`): místo `zrus_pid` hub ruší jednotlivé
požadavky (`srv.zrus(id)`). Požadavek si při příchodu zapamatuje otevřené nástroje stejného
jména a druhu (hlavní agent / subagent) a zruší se, až všechny skončí (`tool.end`, `tool.error`,
`tool.denied`); konec jiného nástroje ho neruší (paralelní Read při čekajícím Bash). Dále ho
zruší nový stejný nástroj déle než 1 s po požadavku, `tool.start` se `schvaleno`, konec kola
hlavního agenta (`user.prompt`, `agent.done`, přerušení) a `session.end`. Požadavek procesu,
který hub nezná, se zruší hned. Neověřeno naživo.

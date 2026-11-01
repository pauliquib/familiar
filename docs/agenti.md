# Další agenti: Gemini CLI a OpenAI Codex

Familiar umí kromě Claude Code i Gemini CLI a Codex. Každý agent volá z hooků
`familiar-emit <zdroj>` (`claude-code`, `gemini`, `codex`). Emitter pošle daemonu datagram
se zdrojem, daemon vybere adaptér přes registr `familiar/adapters/__init__.py`
(`adapters.translate(zdroj, raw, ts, pid)`). Neznámý zdroj se překládá jako Claude Code.

## Gemini CLI

Ověřeno na verzi 0.62.0 (`/usr/local/bin/gemini`) proti dokumentaci přibalené k balíčku
(`bundle/docs/hooks/`) a zdrojům v bundlu.

- Dokumentace: [hooks/index.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/index.md),
  [hooks/reference.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md),
  [reference/configuration.md](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md) (`hooksConfig`).
- Konfigurace: `~/.gemini/settings.json` (místo HOME platí `GEMINI_CLI_HOME`), klíč `hooks`,
  stejný tvar jako u Claude Code: `{"hooks": {"BeforeTool": [{"matcher": "*", "hooks": [{"name",
  "type": "command", "command", "timeout"}]}]}}`. `timeout` je v **ms**. Hooky vypíná
  `hooksConfig.enabled = false`, jednotlivé `hooksConfig.disabled = ["familiar"]` (podle `name`).
- Vstup: JSON na stdin. Společná pole: `session_id`, `transcript_path` (JSON soubor, ne JSONL),
  `cwd`, `hook_event_name`, `timestamp`. Podle události: `source`, `reason`, `prompt`,
  `tool_name`, `tool_input`, `tool_response {llmContent, returnDisplay, error?}`,
  `notification_type`, `message`, `details`, `trigger`.
- Výstup: stdout se parsuje jako JSON, **prázdný stdout (i stderr) s kódem 0 znamená „povolit“**,
  JSON odpověď není potřeba. Pozor: když je stdout prázdný, Gemini čte **stderr**, a pokud
  v něm něco je, ukáže to jako `systemMessage`. Spouštěč emitteru proto stderr zahazuje.
  Kód 2 by akci zablokoval, jiné kódy jen varují.
- Spouštění: `bash -c "<command>"` s prostředím Gemini. Proměnné, které vypadají jako tajné,
  se mohou odstranit, `XDG_RUNTIME_DIR` a `PATH` zůstávají. Bash jediný příkaz spustí přes exec,
  takže rodičem emitteru je proces `node` Gemini (stálý po celou session). Živá zkouška ukázala
  potomka `node-22` relaunchovaného z hlavního `gemini`, hledání terminálu (`find_terminal`)
  jde výš přes oba.
- Zvláštnosti: `BeforeTool` nemá id volání nástroje. Nástroje se spouští až po schválení celé
  dávky. Exit kód shellu je jen v textu `llmContent` (`Exit Code: N`). `PreCompress` s `auto`
  přichází **před každým kolem** (0.62 volá hook ještě před kontrolou prahu), proto se počítá
  jen `manual` (`/compress`). `AfterModel` chodí pro každý chunk, a proto se neinstaluje.

## OpenAI Codex CLI

Codex na tomto stroji **není nainstalovaný**. Vychází se jen z dokumentace a ze zdrojů,
nic nebylo ověřeno naživo.

- Dokumentace: [Hooks](https://developers.openai.com/codex/hooks) (přesměruje na
  learn.chatgpt.com/docs/hooks), [Config reference](https://developers.openai.com/codex/config-reference),
  JSON schémata vstupů [codex-rs/hooks/schema/generated](https://github.com/openai/codex/tree/main/codex-rs/hooks/schema/generated),
  spouštění [command_runner.rs](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/engine/command_runner.rs),
  starý notify [legacy_notify.rs](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/legacy_notify.rs)
  (stav main k 23. 10. 2026).
- Konfigurace: `~/.codex/hooks.json` (nebo `$CODEX_HOME`), případně inline `[hooks]` v `config.toml`.
  Tvar je stejný jako u Claude Code, `timeout` je v **sekundách**. Hooky jsou zapnuté ve výchozím
  stavu (`[features] hooks`). **Nové hooky ale Codex spustí, až když je uživatel povolí
  (`/hooks`, důvěra podle hashe).** Instalátor na to upozorní.
- Vstup: JSON na stdin. Společná pole: `session_id`, `transcript_path`, `cwd`, `hook_event_name`,
  `model`, dále `turn_id`, `permission_mode`, `tool_name`, `tool_use_id`, `tool_input`,
  `tool_response`, `prompt`, `agent_id`, `agent_type`, `trigger`, `source`, `reason`.
- Výstup: kód 0 bez výstupu znamená pokračovat. U `Stop`, `SubagentStop` a `Interrupt` je
  textový stdout neplatný (čeká se JSON), emitter ale nevypíše nic.
- Spouštění: `$SHELL -lc "<command>"` v nové session. U fish to znamená login shell, asi 13 ms
  navíc mimo emitter, a fish neudělá exec. Rodičem emitteru je tedy krátce žijící shell, proto
  emitter u zdrojů `gemini` a `codex` přeskočí rodiče, který je shell (`/proc/<pid>/stat`),
  a pošle pid agenta.
- Starý `notify = ["familiar-emit", "codex"]` v `config.toml`: spustí se přímo (bez shellu),
  JSON je **poslední argument** (`{"type": "agent-turn-complete", "thread-id", "turn-id", "cwd",
  "input-messages", "last-assistant-message"}`) a stdin je prázdný. Emitter z něj vezme jen
  typ, thread-id a cwd. Vede jen na `agent.done`. Instalátor `notify` nenastavuje, protože
  klíč je jen jeden a uživatel v něm může mít vlastní příkaz. Hooky jsou úplnější.
- Omezení: neúspěšný nástroj `PostToolUse` nespustí (nástroj zůstane otevřený do konce kola).
  Nenulový exit Bash ho spustí, ale `tool_response` je jen výstup, takže `tool.error` z Codexu
  nepřijde. Odmítnuté povolení nemá hook: postavička čeká do `Stop` nebo do dalšího promptu.

## Mapování na události familiara

| událost familiara | Claude Code | Gemini CLI | Codex |
| --- | --- | --- | --- |
| session.start / session.end | SessionStart / SessionEnd | SessionStart / SessionEnd | SessionStart / SessionEnd |
| user.prompt | UserPromptSubmit | BeforeAgent | UserPromptSubmit |
| tool.start / tool.end | PreToolUse / PostToolUse | BeforeTool / AfterTool | PreToolUse / PostToolUse |
| tool.error | PostToolUseFailure | AfterTool s `error` nebo `Exit Code` ≠ 0 | – (nejde poznat) |
| tool.denied | PermissionDenied | – | – |
| agent.waiting | PermissionRequest | Notification `ToolPermission` | PermissionRequest |
| agent.done | Stop | AfterAgent | Stop (notify: agent-turn-complete) |
| agent.failed | StopFailure | – | – |
| agent.interrupted | `is_interrupt`, transcript | AfterTool „Command was cancelled by user“ | Interrupt |
| subagent.start / subagent.done | SubagentStart / SubagentStop | – | SubagentStart / SubagentStop |
| context.compact | PreCompact | PreCompress jen `manual` | PreCompact |

`tool.start` z Gemini nese `schvaleno: True`. Automat (`fsm.py`) díky tomu ukončí čekání
na povolení, protože Gemini spustí nástroj až po schválení. U Claude Code souběžný nástroj
čekání neukončí, tam se nic nemění.

## Co emitter posílá (KEEP)

- Gemini: `hook_event_name`, `session_id`, `cwd`, `source`, `reason`, `tool_name`, `trigger`,
  `notification_type`, `prompt` jen z `BeforeAgent` (nejvýš 2000 znaků jako u Claude Code),
  `command` (prvních 200 znaků `tool_input.command`). Z `tool_response` jen `error` (zpráva
  `error.message`, nejvýš 500 znaků), `exit_code` a `cancelled`. Text odpovědi
  (`prompt_response`, `llmContent`), `details`, `message` ani `transcript_path` se neposílají.
- Codex: `hook_event_name`, `session_id`, `cwd`, `source`, `reason`, `tool_name`, `tool_use_id`,
  `agent_id`, `agent_type`, `trigger`, `prompt` jen z `UserPromptSubmit`, `command` (ne u
  `apply_patch`, kde je to text patche). `last_assistant_message`, `tool_response`, `model`
  a `transcript_path` se neposílají.
- `transcript_path` jde dál jen od Claude Code: sledovač přerušení (`transcript.py`) zná jen jeho
  formát.
- Velký vstup (> 256 kB) se parsuje jen ze začátku a konce, jako u Claude Code. Chyba nástroje
  Gemini s obřím výstupem se pak nepozná a vypadá jako `tool.end`.

## Instalace

```sh
familiar install                     # Claude Code + agenti, jejichž adresář existuje (~/.gemini, ~/.codex)
familiar install --agents gemini     # výslovně (i když adresář ještě není)
familiar install --agents none       # jen Claude Code
familiar install --dry-run --agents all
familiar uninstall --agents gemini   # odebere jen hooky Gemini, zbytek instalace zůstane
familiar uninstall                   # všechno včetně hooků všech agentů
```

- Výchozí `auto` instaluje jen agenty, které uživatel už aspoň jednou spustil (existuje jejich
  adresář nastavení). Samotný spustitelný soubor v PATH nestačí: test je tak deterministický
  a do nastavení agenta, který nikdy neběžel, se nesahá.
- Každý měněný soubor se zálohuje do `~/.local/share/familiar/backup/<čas>/`, zapisuje se
  atomicky a cizí klíče i cizí hooky zůstanou. Opakovaná instalace nic nemění.
- Když soubor agenta nejde přečíst (třeba `settings.json` s komentáři, které Gemini snese),
  instalace ho přeskočí s varováním a Claude Code nainstaluje normálně.
- `uninstall --agents X` zapíše agenta do `agents_off` v `install.json`. Pak ho `auto` (i po
  `familiar upgrade`) znovu nepřidá, dokud uživatel nezadá `--agents X`.
- Soubor `~/.codex/hooks.json`, který založil familiar, odinstalace smaže, když v něm nic jiného
  nezůstalo.
- `familiar doctor` kontroluje hooky jen u agentů, jejichž adresář existuje. Když hooky
  familiara chybí úplně, je to OK s nápovědou, když chybí jen některé, je to CHYBA.

## Klíče configu

```toml
[agenti]
gemini = true        # zobrazovat postavičky pro Gemini CLI (hooky dál řídí familiar install)
codex = true
```

Vypnutý agent: daemon jeho události zahodí (žádná postavička, notifikace ani statistiky),
už běžící postavičky toho agenta po přenačtení configu odejdou. Hooky zůstanou nainstalované,
odebere je `familiar uninstall --agents X`. Proces Gemini/Codex se kontroluje jen podle pid
(jméno procesu je `node`, `codex`), Claude Code dál podle jména `claude`.

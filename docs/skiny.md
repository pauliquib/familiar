# Skiny: vlastní postavička

Familiar umí místo Robo-kuna kreslit jinou postavičku – **skin**. Skin je adresář
s popisem `skin.toml`, PNG sheety a JSON exportovanými z [Aseprite](https://www.aseprite.org/)
a paletami `.gpl`. Tento návod ukazuje, jak ho nakreslit, kam ho uložit a jak ho vyzkoušet.
Na konci je oddíl „Rozhodnutí o formátu“, který vysvětluje, proč se formát místy liší
od náčrtu v kapitole 5 konceptu.

## Kde skiny leží

| Kde | Zdroj | Poznámka |
| --- | --- | --- |
| `~/.local/share/familiar/skins/<id>/` (`$XDG_DATA_HOME/familiar/skins`) | uživatel | tvoje skiny; mají přednost |
| `familiar/skins/<id>/` v balíčku | balíček | `robokun`, `rubin` a další barevné varianty Robo-kuna, `vanoce`, `kvetina`, `ptacek`, `skejtak`, `skejtak2` (viz níže) |
| – | vestavěný | `vestaveny`: Robo-kun kreslený kódem (`familiar/sprites.py`) |

`<id>` je název adresáře (písmena, číslice, `-`, `_`, `.`). Skin se stejným id v uživatelském
adresáři přebije ten z balíčku. Výpis dostupných skinů (`*` = zvolený, u vadného i chyba):

```sh
familiar skins
```

Zvolí se v nabídce postavičky nebo lišty (*Skin*), nebo v `~/.config/familiar/config.toml`
řádkem `skin = "<id>"` (výchozí `robokun`); běžící familiar změnu použije do 1 s bez restartu.

## Vestavěné skiny a licence

| id | Postavička | Autor grafiky | Licence | Zdroj |
| --- | --- | --- | --- | --- |
| `robokun` | Robo-kun (výchozí) | Pixel Familiars | CC BY 4.0 | `familiar/sprites.py` |
| `rubin` | Robo-kun Rubín | Pixel Familiars | CC BY 4.0 | `familiar/sprites.py` |
| `smaragd`, `safir`, `jantar`, `ametyst`, `grafit`, `perla` | Robo-kun Smaragd, Safír, Jantar, Ametyst, Grafit, Perla | Pixel Familiars | CC BY 4.0 | `familiar/sprites.py` |
| `vanoce` | Robo-kun Vánoce | Pixel Familiars | CC BY 4.0 | `familiar/sprites.py`, `familiar/skin_export.py` |
| `kvetina` | Květina v květináči | Pixel Familiars | CC BY 4.0 | `tools/kvetina.py` |
| `ptacek` | Ptáček (sýkorka) | Pixel Familiars | CC BY 4.0 | `tools/ptacek.py` |
| `skejtak` | Skejťák | Pixel Familiars | CC BY 4.0 | `tools/skejtak.py` |
| `skejtak2` | Skejťák v0.2 | Pixel Familiars | CC BY 4.0 | `tools/skejtak2.py` |

### Květina (`kvetina`)

Vlastní dílo projektu, kreslené kódem v [`tools/kvetina.py`](../tools/kvetina.py)
(`python3 -I tools/kvetina.py` balíček vygeneruje znovu; test hlídá, že je aktuální).
Licence CC BY 4.0 (`CREDITS.txt` v adresáři). Květina se šesti lístky v květináči,
obličej na středu květu, 15 barev.

| Stav | Tag | Animace |
| --- | --- | --- |
| idle | `idle` | pohupování stonku a listů, jednou mrkne (20 snímků, 4 fps) |
| listening | `listen` | pravý list se zvedne „k uchu“, oči dokořán (4, 8 fps, jednorázově) |
| thinking | `think` | květ se nakloní, oči nahoru, „…“ (6, 6 fps) |
| working (všechny nástroje) | `work` | listy se střídavě zvedají, květ pokyvuje (6, 8 fps) |
| waiting | `wave` | mávání listem a blikající „!“ (4, 6 fps) |
| success | `hop` | květ se rozvine, listy nahoru, jiskry (6, 8 fps, jednorázově) |
| error | `stumble` | svadnutí: květ klesne a nakloní se, listy svěšené, otřesení, kapka potu, oči > < (6, 8 fps, jednorázově) |
| sleeping, gone | `sleep` | zavřené poupě se zavřenýma očkama, Zzz (4, 2 fps) |

Nálady mění obličej (záplaty `eyes_*`/`mouth_*` jako u Robo-kuna) a paletu okvětí a středu:
radost `warm` (sytější), frustrace `red` (do červena), zmatek `cool` (studenější, levandulová),
únava `faded` (vybledlé okvětí i listy, pomalejší tempo, svěšená víčka). Spící poupě obličej
nálady nemá. Reakce jsou Robo-kunovy přebarvené do palety, drony subagentů jsou včelky
(2 snímky mávání křídly). Klobouky skin nemá (nekreslí se).

### Ptáček (`ptacek`)

Vlastní dílo projektu, kreslené kódem v [`tools/ptacek.py`](../tools/ptacek.py)
(`python3 -I tools/ptacek.py` balíček vygeneruje znovu; test hlídá, že je aktuální).
Licence CC BY 4.0 (`CREDITS.txt` v adresáři). Sýkorka modřinka na větvičce: modrá čepička
a křídla, bílá tvář, žluté bříško, 15 barev. Efekty („…“, „!“, noty, Zzz, pírko) mají tmavý
obrys, takže jsou čitelné na tmavém i světlém titulku.

| Stav | Tag | Animace |
| --- | --- | --- |
| idle | `idle` | sedí a dýchá, dvakrát mrkne, natočí hlavičku doprava a doleva, pak zazpívá: hlavička nahoru, zobáček se otvírá, stoupají noty ♪ ♫ (32 snímků, 4 fps) |
| listening | `listen` | zbystří: natáhne se, hlavička nahoru, oči dokořán, pootevřený zobáček (5, 8 fps, jednorázově) |
| thinking | `think` | hlavička nakloněná, oči nahoru, „…“ (6, 6 fps) |
| working (všechny nástroje) | `work` | letí: vznáší se nad prázdnou větvičkou, plynulý cyklus mávání křídly, tělíčko se s úderem zhoupne (8, 8 fps) |
| waiting | `wave` | mává křídlem, poskakuje, blikající „!“ (4, 6 fps) |
| success | `hop` | na větvičce vykoukne červíček, ptáček k němu skočí, klovne, vyhodí ho do vzduchu, spolkne a spokojeně se načepýří, jiskry (14, 7 fps, jednorázově) |
| error | `stumble` | uklouzne a sjede za větvičku, mává křídly, oči X, vyškrábe se zpátky načepýřený s očima > < a ulétne mu pírko (9, 8 fps, jednorázově) |
| sleeping, gone | `sleep` | načepýřená kulička se zavřenýma očkama, zobáček schovaný v peří, Zzz (4, 2 fps) |
| walking (procházka) | `walk` | poskakování po hraně okna bez větvičky, z profilu doprava (`facing = "right"`, 6, 8 fps) |

Nálady mění obličej (záplaty `eyes_*`/`mouth_*`) a barvu peří: radost `warm` (tyrkysovější
modrá, zlatavé bříško, otevřený zobáček, růžové tvářičky), zvědavost (oči dokořán), frustrace
`red` (peří do červena, zamračené obočí), zmatek `cool` (levandulová, spirálky v očích),
únava `faded` (vybledlé peří, svěšená víčka, pomalejší tempo). Při mrknutí, zpěvu, lovu,
pádu, spánku a procházce určuje výraz animace. Reakce jsou Robo-kunovy přebarvené do palety,
drony subagentů jsou modrá ptáčata (2 snímky mávání). Klobouky skin nemá.

### Skejťák (`skejtak`)

Vlastní dílo projektu, kreslené kódem v [`tools/skejtak.py`](../tools/skejtak.py)
(`python3 -I tools/skejtak.py` balíček vygeneruje znovu; test hlídá, že je aktuální).
Licence CC BY 4.0, `CREDITS.txt` v adresáři. Chibi skateboardista v kšiltovce, mikině
a džínách stojí bokem na prknu a kouká doprava, kam jede (`facing = "right"`, na procházce
opačným směrem se zrcadlí). Obličej je na hlavě pod kšiltem, 15 barev.

| Stav | Tag | Animace |
| --- | --- | --- |
| idle | `idle` | stojí na prknu a pohupuje se v kolenou, mrkne, zadní nohou sleze na zem a dvakrát poklepe, pak šlápne na tail a zhoupne prkno (24 snímků, 4 fps) |
| listening | `listen` | přikrčí se a zbystří: narovná se, oči dokořán, pusa „o“ (5, 8 fps, jednorázově) |
| thinking | `think` | ruka na bradě, oči nahoru, „…“ (6, 6 fps) |
| working: Edit, Write, NotebookEdit a ostatní nástroje | `work_edit` | jede v podřepu s rukama do stran, kolečka se točí, za ním vítr a kamínky na silnici (6, 8 fps) |
| working: Bash | `work_bash` | odráží se zadní nohou od země (6, 8 fps) |
| working: Read, Grep, Glob, WebSearch, WebFetch, ToolSearch | `work_search` | manuál: jede po zadních kolečkách s nosem prkna nahoře, balancuje rukama (6, 8 fps) |
| walking (procházka) | `ride` | odrazí se a pak jede, bez větru (pohyb dělá okno) (8, 8 fps) |
| waiting | `wave` | mává rukou nad hlavou, oči dokořán, blikající „!“ (4, 6 fps) |
| success | `kickflip` | kickflip: přikrčí se, pop (tail o zem), prkno se ve vzduchu otočí pod nohama, chytí ho, dopadne v podřepu s prachem, „hurá“ s rukama nahoře a jiskrami (10, 8 fps, jednorázově) |
| error | `bail` | prkno mu ujede, padá dozadu, sedne si na zadek, oči > <, kolem hlavy krouží hvězdičky, kapka potu, pak vstane a naskočí zpátky na prkno (10, 8 fps, jednorázově) |
| sleeping, gone | `sleep` | sedí na prknu s nohama natáhnutýma, hlava skloněná, zavřené oči, oddechuje, Zzz (4, 2 fps) |

Nálady mění obličej (záplaty `eyes_*`/`mouth_*` jako u Květiny) a paletu mikiny: radost
`warm` (oranžová mikina), frustrace `red` (červená mikina, tmavší kšiltovka), zmatek `cool`
(levandulová mikina, modřejší džíny), únava `faded` (vybledlá celá postavička, svěšená víčka,
pomalejší tempo). Kde výraz určuje animace (mrknutí, trik, pád, mávání, spánek), nálada obličej
nepřepíše. Reakce jsou Robo-kunovy přebarvené do palety, drony subagentů jsou malá skate
prkýnka (2 snímky poskakování). Klobouky skin nemá, nosí vlastní kšiltovku.

### Skejťák v0.2 (`skejtak2`)

Vlastní dílo projektu, kreslené kódem v [`tools/skejtak2.py`](../tools/skejtak2.py)
(`python3 -I tools/skejtak2.py` balíček vygeneruje znovu; test hlídá, že je aktuální).
Licence CC BY 4.0, `CREDITS.txt` v adresáři. Štíhlý skateboardista z profilu v komiksovém stylu:
silné černé obrysy a ploché syté barvy, malá hlava a dlouhé nohy místo chibi proporcí. Má černou
kšiltovku kšiltem dozadu, zpod ní dlouhé rovné blond vlasy, volné tyrkysové triko s černým
spodním rukávem, holé paže, široké červené kalhoty s ohrnutými manžetami a černé tenisky s bílým
pruhem. Prkno má černou desku, stříbrné trucky a žlutá kolečka. Postava je vyšší, takže skin má
plátno 48×56 (`size`), kotva je spodní hrana koleček. Jede doprava (`facing = "right"`, na
procházce opačným směrem se zrcadlí), 15 barev. Postava stojí na kostře, mezi klíčovými pózami
jsou dopočítané mezisnímky, vlasy a lem trika vlají a zpožďují se za pohybem hlavy, kolečka
se točí a prkno se při dopadu prohne.

| Stav | Tag | Animace |
| --- | --- | --- |
| idle | `idle` | stojí bokem, přední nohou na prknu, dýchá, vlasy se pohupují, mrkne, přešlápne, chytí kšilt vzadu a upraví si kšiltovku, podívá se dolů a zhoupne prkno pod nohou, znovu mrkne (44 snímků, 4 fps) |
| listening | `listen` | zbystří: přikrčí se, narovná, hlava nahoru, oko dokořán (7, 8 fps, jednorázově) |
| thinking | `think` | zastaví se, ruka na bradě, poklepe si na ni, oko nahoru, „…“ přibývá (17, 6 fps) |
| working: Edit, Write, NotebookEdit a ostatní nástroje | `work_edit` | odrazí se, naskočí zadní nohou na tail a jede v podřepu, v zatáčkách se houpe, prkno se pruží a naklání; rychlostní čárky a ujíždějící silnice (14, 8 fps) |
| working: Bash | `work_bash` | odrážení: zadní noha se odrazí od země a natáhne dozadu, přední je pokrčená na prknu, trup nakloněný dopředu, ruce před sebou; obláček prachu, rychlostní čárky (7, 8 fps) |
| working: Read, Grep, Glob, WebSearch, WebFetch, ToolSearch | `work_search` | odrazí se a jede manuál po zadních kolečkách s nosem nahoře, balancuje rukama (14, 8 fps) |
| walking (procházka) | `ride` | odrážení bez čárek a silnice (pohyb dělá okno) (6, 8 fps) |
| waiting | `wave` | narovná se a mává rukou nad hlavou, oko dokořán, blikající „!“ (8, 6 fps) |
| success | `kickflip` | naskočí na tail, přikrčí se, pop, prkno se pod ním otočí kolem podélné osy (spodek s bleskem, grip), chytí ho, dopadne do podřepu s prohnutým prknem a prachem, vyskočí s rukama nahoře, jiskry, a sleze zpátky (15, 7 fps, jednorázově) |
| error | `bail` | prkno mu ujede, padá dozadu a sedne si na zadek, oči X, kolem hlavy krouží hvězdičky, pot; prkno přijede zpátky, vstane a postaví se na něj (14, 7 fps, jednorázově) |
| sleeping, gone | `sleep` | sedí na prknu s koleny nahoře a rukama na nich, hlava skloněná, oddechuje, Zzz (4, 2 fps) |

Nálady mění obličej (záplaty oka a pusy z profilu, `eyes_*` / `mouth_*`) a hlavně barvu trička:
radost `warm` (oranžové triko, úsměv), zvědavost (oko dokořán, pusa „o“), frustrace `red` (červené
triko, tmavší kalhoty, zamračené obočí), zmatek `cool` (levandulové triko, fialovější kalhoty),
únava `faded` (vybledlá celá postavička, svěšené víčko, pomalejší tempo). Kde výraz určuje
animace (mrknutí, trik, pád, mávání, spánek), nálada obličej nepřepíše. Reakce jsou Robo-kunovy
přebarvené do palety, drony subagentů jsou ujetá žlutá kolečka z prkna (2 snímky). Klobouky
skin nemá, nosí vlastní kšiltovku.

## Co je v balíčku

```
muj-skin/
  skin.toml          popis skinu (povinný)
  body.png  body.json    postava, tagy = animace (povinné)
  fx.png    fx.json      efekty animací: klávesnice, lupa, „…“, Zzz (volitelné)
  face.png  face.json    výrazy nálady: oči a pusy (volitelné)
  acc.png   acc.json     klobouky podle tématu rozhovoru (volitelné)
  emote.png emote.json   reakce nad hlavou: srdce, ?, ✓, květinka … (volitelné)
  drone.png drone.json   drony subagentů (volitelné)
  pal/base.gpl           paleta, ve které jsou nakreslené PNG (povinná)
  pal/warm.gpl …         další palety pro nálady
```

Ke každému PNG patří JSON se stejným jménem. Nejsnazší start je vyexportovat Robo-kuna
a upravovat ho (příkazy `python3 -m familiar.…` spouštěj z kořene repozitáře):

```sh
python3 -m familiar.skin_export ~/.local/share/familiar/skins/muj-skin
```

## Jak se snímek skládá

Plátno má **32×32 px** (větší postavička smí mít plátno až 64×64, viz `size` v `skin.toml`;
všechny sheety skinu pak mají tuto velikost). Každý snímek se skládá ze šesti vrstev v tomto pořadí
(stejně jako kreslí kód):

1. **body** – snímek animace i s výchozím obličejem (mrknutí, zavřené oči ve spánku…),
2. **face** – záplata očí a pusy podle nálady, položená na řez `eyes` / `mouth`,
3. **acc** – klobouk, položený na řez `head`,
4. **fx** – efekt animace (klávesnice, lupa, tečky…), kreslí se přes klobouk,
5. **drone** – drony subagentů (1–3),
6. **emote** – reakce vlevo nahoře.

Index palety 0 je průhledný. Ve vrstvách 2–6 platí navíc: **neprůhledný pixel v barvě
indexu 0** (u Robo-kuna magenta `#ff00ff`) vyřízne do postavy díru. Tak klobouk schová
anténu, kterou nepřekryje.

## Kreslení v Aseprite

### 1. Paleta

- Nový sprite 32×32, **Color Mode: Indexed**.
- Paleta má nejvýš 16 barev, index 0 je průhledná (v `.gpl` ji zapiš jako magentu).
  Načti ji přes *Palette → Load Palette* (`pal/base.gpl`), nebo ji vytvoř a ulož
  *Save Palette* jako `.gpl`.
- Další palety (`warm`, `cold`, `faded`) mají **stejné pořadí barev** – nálada mění jen
  barvy, ne indexy. Typicky se mění tělo (Robo-kun indexy 2–4): teplá při radosti,
  studená při frustraci, vybledlá při únavě.
- Barvy v PNG musí přesně odpovídat paletě `base`, jinak loader skin odmítne
  (chyba řekne barvu a souřadnice pixelu).

### 2. Postava (`postava.aseprite` → body + fx)

- Vrstvy: `body` (postava i s obličejem), `fx` (efekty, které patří k animaci a mají být
  přes klobouk: klávesnice, papír, lupa, „…“, „!“, pot, Zzz). Pomocné vrstvy klidně přidej,
  při exportu je vynech.
- **Tagy jsou animace.** Jména, která familiar čeká (lze přejmenovat v `[activity]`):

  | Tag | Kdy | Snímků / fps | Typ |
  | --- | --- | --- | --- |
  | `idle` | čeká | libovolně / 4 | smyčka |
  | `listen` | přišel prompt | 4 / 8 | jednorázová |
  | `think` | přemýšlí | 6 / 6 | smyčka |
  | `work_bash`, `work_edit`, `work_search` | nástroje | 6 / 8 | smyčka |
  | `wave` | čeká na povolení | 4 / 6 | smyčka |
  | `hop` | hotovo | 6 / 8 | jednorázová |
  | `stumble` | chyba | 6 / 8 | jednorázová |
  | `sleep` | spí, odchází | 4 / 2 | smyčka |

- **fps** = délka snímku (*Frame Properties → Duration*): 250 ms = 4 fps, 125 ms = 8 fps.
  Loader bere průměr snímků v tagu.
- **Jednorázová animace**: ve vlastnostech tagu *Repeat = 1* (Aseprite 1.3). Starší Aseprite:
  vyjmenuj tagy v `skin.toml` jako `oneshot = ["listen", "hop", "stumble"]` v sekci `[skin]`.
  Směr tagu *Reverse* / *Ping-pong* funguje.
- Každá animace má začínat i končit v neutrální póze (snímek 0), přechody pak neblikají.
- **Řezy (Slice tool, klávesa C)** označují kotvy; řez může mít na každém snímku jiný klíč,
  takže se hýbe s hlavou:
  - `eyes` – obdélník, kam padne záplata očí z face (levý horní roh je kotva),
  - `mouth` – totéž pro pusu,
  - `head` – hlava, k ní se přikládají klobouky.

  Klíč platí od svého snímku do dalšího klíče (jako v Aseprite).

### 3. Výrazy nálady (`oblicej.aseprite` → face)

- Plátno 32×32, jako podklad postava v neutrální póze ve vrstvě `predloha` (při exportu vynech).
- Řezy `eyes` a `mouth` na stejném místě jako na neutrálním snímku postavy.
- Jeden tag na výraz: `eyes_<jméno>` a `mouth_<jméno>` (Robo-kun: `eyes_wide`, `eyes_angry`,
  `eyes_dazed`, `eyes_droopy`, `mouth_smile`, `mouth_o`, `mouth_frown`, `mouth_wave` …).
- Záplata musí **přemalovat i pozadí** pod výchozími očima (u Robo-kuna tmavá obrazovka),
  jinak by pod novýma očima prosvítaly staré.
- Na snímcích, kde výraz určuje animace (mrknutí, spánek, X při zakopnutí), nálada obličej
  nemění – vyjmenuj je v `[face]` (viz níže).

### 4. Klobouky (`klobouky.aseprite` → acc)

- Plátno 32×32, podklad hlava ve vrstvě `predloha`, řez `head` na hlavě.
- Tag = jméno klobouku: `hardhat` (elektronika), `headphones` (kód), `beret` (web),
  `mortarboard` (studium), `explorer` (rešerše), `cap` (systém). Odemykatelné doplňky
  (úrovně a úspěchy, `[postup] doplnek_klobouk`): `straw` (slamák), `tophat` (cylindr), `crown`
  (koruna), `nightcap` (noční čepička), `laurel` (vavřínový věnec), kšiltovka je `cap`.
  Klobouk, který skin nemá (nebo skin bez `acc`), se prostě nekreslí.
- Má-li klobouk v některé animaci vypadat jinak, přidej tag `<klobouk>@<animace>` se stejným
  počtem snímků jako animace (Robo-kunova lampa na helmě svítí barvou antény).
- Co má klobouk schovat (anténa, uši), přemaluj barvou indexu 0.

### 5. Reakce a drony (`emote.aseprite`, `drone.aseprite`)

- `emote`: tag = jméno reakce, 2 snímky (pohupování). Jména: `heart`, `check`, `grawlix`,
  `coffee`, `camera`, `question`, `storm`, `spiral`, `flower`, `star`, `badge`, `swarm`. Kresli je tam, kde mají být
  (Robo-kun vlevo nahoře). Reakci, kterou skin nemá, familiar prostě nekreslí.

  | Reakce | Kdy |
  | --- | --- |
  | `heart` | poděkování v promptu; změna nálady na radost |
  | `check` | prošly testy nebo build |
  | `grawlix` | ostrý tón nebo vulgarismus |
  | `coffee` | limit (rate limit) |
  | `camera` | prompt s obrázkem |
  | `question`, `storm`, `spiral` | změna nálady na zvědavost, frustraci, zmatek |
  | `flower` (květinka) | kolo skončilo bez chyby, zatímco je familiar v radosti |
  | `heart`, `star`, `badge`, `swarm` | odemčené doplňky (srdíčko, hvězdička, zelená fajfka, roj): občas v klidu (`[postup] emoty_v_klidu`) |

  Novou reakci Robo-kuna (sprites.py, jen barvami, které reakce už mají) dostanou balíčkové skiny
  reexportem: `python3 -m familiar.skin_export familiar/skins/robokun` (a barevné varianty
  `familiar/skins/<id> --variant <id>`, viz `VARIANTS` v `skin_export.py`) a vlastní
  skiny jejich generátorem `python3 -I tools/<id>.py` (`kvetina`, `ptacek`, `skejtak`, `skejtak2`).
- `drone`: tagy `drone1`, `drone2`, `drone3`, každý 2 snímky, každý dron na svém místě plátna.

### 6. Export

Každý soubor se exportuje stejnými volbami
`--format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8`:

```sh
aseprite -b postava.aseprite --ignore-layer fx --sheet body.png --data body.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
aseprite -b postava.aseprite --layer fx --sheet fx.png --data fx.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
aseprite -b oblicej.aseprite --ignore-layer predloha --sheet face.png --data face.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
aseprite -b klobouky.aseprite --ignore-layer predloha --sheet acc.png --data acc.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
aseprite -b emote.aseprite --sheet emote.png --data emote.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
aseprite -b drone.aseprite --sheet drone.png --data drone.json --format json-array --list-tags --list-slices --sheet-type rows --sheet-columns 8
```

`--trim` nevadí (loader čte `spriteSourceSize`); `--split-layers` nepoužívej.

## skin.toml

```toml
[skin]
name = "Můj skin"
size = [32, 32]            # plátno [šířka, výška], 32–64 px; všechny sheety mají tuto velikost
anchor = [16, 31]          # bod, kterým postavička sedí na hraně okna (výchozí: střed spodní hrany)
# facing = "right"         # kam kouká chůze (right/left): na procházce opačným směrem se zrcadlí; bez = zepředu
# author = "…"  license = "CC0-1.0"  url = "https://…"   # nepovinné, jen informace o původu
# oneshot = ["listen", "hop", "stumble"]   # jen pro Aseprite bez Repeat u tagů

[layers]                   # povinné je jen body
body = "body.png"
fx = "fx.png"
face = "face.png"
acc = "acc.png"
emote = "emote.png"
drone = "drone.png"

[palettes]                 # base = paleta, ve které jsou PNG
base = "pal/base.gpl"
warm = "pal/warm.gpl"
cold = "pal/cold.gpl"
faded = "pal/faded.gpl"

[activity]                 # stav činnosti → tag; chybějící stav kreslí vestavěný Robo-kun
idle = "idle"
listening = "listen"
thinking = "think"
waiting = "wave"
success = "hop"
error = "stumble"
sleeping = "sleep"
gone = "sleep"
working = { Bash = "work_bash", Edit = "work_edit", Read = "work_search", default = "work_bash" }
# walking = "walk"         # procházka; bez ní klidová animace s poskakováním (Robo-kunova se nepůjčuje)

[mood]                     # nálada → výraz, paleta, reakce při změně, tempo animací
klid = { palette = "base" }
radost = { mouth = "smile", palette = "warm", emote = "heart" }
zvedavost = { eyes = "wide", mouth = "o", emote = "question" }
frustrace = { eyes = "angry", mouth = "frown", palette = "cold", emote = "storm" }
zmatek = { eyes = "dazed", mouth = "wave", emote = "spiral" }
unava = { eyes = "droopy", palette = "faded", tempo = 0.6 }

[face]                     # snímky tagu, kde výraz určuje animace (true = všechny)
keep_eyes = { idle = [13], listen = true, sleep = true }
keep_mouth = { listen = true }
```

Nálady jsou `klid`, `radost`, `zvedavost`, `frustrace`, `zmatek`, `unava`; chybějící nálada
se kreslí jako `klid`. `eyes = "wide"` znamená tag `eyes_wide` ve face.json.

**Přebarvení bez kreslení:** paleta `base` musí sedět na PNG, ale nálady mohou ukazovat
na jiné palety – přidej `noc = "pal/noc.gpl"` a nastav `klid = { palette = "noc" }`.
Skiny `rubin`, `smaragd`, `safir`, `jantar`, `ametyst`, `grafit` a `perla` jsou Robo-kun
s jinými barvami: tělo, obrazovka a oči, nálady mění barvu těla. Palety jsou ve `VARIANTS`
v `familiar/skin_export.py`, skin vygeneruje
`python3 -m familiar.skin_export familiar/skins/<id> --variant <id>`.

Skin `vanoce` je klasický Robo-kun (stejné barvy i nálady) s vánoční výzdobou, kterou
kreslí `DECOR` ve `familiar/skin_export.py`: Santova čepice s bambulí místo antény
(ve výskoku zploštělá, špička vlaje do strany), červeno-zelená šála, v klidu padající
vločky a místo dronů dárky s vrtulkou (červený, zelený, fialový). Čepici nosí pořád,
proto nemá vrstvu `acc` a klobouky témat se u něj nekreslí. Ostatní varianty výzdobu nemají.

## Jak skin vyzkoušet

1. Zkontroluj, že se načte. Chyba řekne soubor a co je špatně; „chybí animace“ jsou stavy,
   které kreslí vestavěný Robo-kun:

   ```sh
   python3 -m familiar.skin                 # výpis dostupných skinů
   python3 -m familiar.skin muj-skin --nahled /tmp/nahled.png
   ```

2. Prohlédni si náhled: řádky jsou nálady (klid, radost, zvědavost, frustrace, zmatek, únava),
   sloupce stavy (idle, listen, think, work, wave, hop, stumble, sleep), s reakcí a jedním dronem.

3. Zapiš `skin = "muj-skin"` do `~/.config/familiar/config.toml`; běžící familiar ho přepne
   za běhu. Soubory zvoleného skinu sleduje (mtime a velikost, každých 0,5 s): po novém exportu
   ho do ~1 s načte znovu. Stejně tak si všimne nového uživatelského skinu se stejným id,
   jaký má skin z balíčku.

Vadný skin familiara nikdy neshodí: celý se nahradí vestavěným Robo-kunem a důvod je v logu.

## Editor familiárů

Skin jde nakreslit i bez Aseprite, v editoru na poslední záložce dialogu nastavení
(*Nastavení… → Editor familiárů*, v nabídce *Skin → Editor familiárů…*, z terminálu
`familiar editor [id]`). Editor čte a zapisuje stejný formát, jaký popisuje tento návod,
takže skin z editoru jde dál upravovat v Aseprite a naopak.

**Lišta nahoře.** Výběr familiara, *Nový…* (prázdný s paletou, reakcemi a drony Robo-kuna,
plátno 32–64 px, nebo kopie existujícího), *Uložit jako…*, *Import…* (to samé jako
`familiar skin-import`), *Smazat* (u tvé kopie balíčkového skinu *Vrátit balíčkový*),
*Složka*, *Zpět*/*Znovu* (Ctrl+Z, Ctrl+Y), *Zahodit změny*, *Uložit skin* (Ctrl+S)
a *Použít jako vzhled*: nastaví pole *Vzhled* na záložce Obecné. V configu se uloží
tlačítkem *Uložit* dole.

**Animace a kreslení.**

- Vlevo jsou vrstva (postava, obličej, klobouky, reakce, drony) a její animace (tagy):
  přidat (s návrhy jmen, která familiar zná), kopie, přejmenovat, smazat, pořadí, fps,
  jednorázová, směr. Pod nimi je vidět, kde se animace používá (stavy, nálady).
- Uprostřed je plátno a pod ním pás snímků: přidat prázdný nebo kopii, smazat, posunout
  snímek, posunout kresbu o pixel, zrcadlit, vyčistit. Klávesy `,` a `.` přepínají snímky.
- Nástroje: tužka (B; pravé tlačítko maže), guma (E), výplň (G), kapátko (I), čára (L),
  obdélník (R) a kotva (K). Kotva posadí řez `eyes` / `mouth` / `head` na snímek, se
  Shiftem na celou animaci. Řezy se na plátně kreslí čárkovaně, červený křížek je kotva
  postavičky.
- U postavy se volí, jestli se kreslí do postavy, nebo do efektů `fx` (kreslí se přes
  klobouk). Zaškrtávátka „oči / pusu určuje animace“ jsou zámky `[face]` pro aktuální
  snímek.
- *Cibule* ukáže předchozí snímek. *Podklad* ukáže postavu pod obličejem, kloboukem
  (u varianty `klobouk@animace` příslušný snímek), efekty, reakcí a dronem.
- Vpravo je paleta (dvojklik změní barvu) a náhled. Náhled přehrává animaci přes
  `skin.render()` s volbou nálady, klobouku, reakce a počtu dronů a sám přepne na to, co
  právě kreslíš.

**Stavy a nálady.** Která animace postavy patří ke stavu činnosti (i nástrojům při práci
a k procházce). Pro každou náladu paleta, oči, pusa, reakce a tempo. Stav bez animace kreslí
vestavěný Robo-kun.

**Palety.** Tabulka palet (řádky) a barev (sloupce). Můžeš přidat, odvodit z base (teplá,
studená, vybledlá varianta barev postavy, jako u importu), přejmenovat a smazat paletu,
přidat nebo odebrat barvu a přemalovat jeden index jiným ve všech snímcích. V paletě base
nesmějí být dvě stejné barvy ani magenta `#ff00ff`, protože by v PNG splynuly.

**Vlastnosti.** Název, autor, licence, odkaz, směr chůze (`facing`), kotva postavičky
a velikost plátna. Při změně plátna zůstane kresba všech vrstev na středu spodní hrany.

**Ukládání.** Skin se ukládá vždy do `~/.local/share/familiar/skins/<id>/`. Skin z balíčku
se uloží jako tvoje kopie se stejným id a balíčkový přebije. Zápis jde nejdřív do
dočasného adresáře a ověří se načtením. Když se skin nenačte, nic se nepřepíše a editor
ukáže proč. Komentáře a neznámé klíče v `skin.toml` i další soubory skinu (`CREDITS.txt`,
zdroje `.aseprite`) zůstanou. Snímky se zapíšou po tagech za sebou, každý tag
s jednotnou délkou snímku podle fps (proměnné délky z Aseprite se zprůměrují, jako je čte
loader). Snímky mimo tagy se vynechají, editor na ně předem upozorní. Běžící familiar
zvolený skin po uložení načte sám.

## Import z Aseprite

Hotovou animovanou postavičku z Aseprite nemusíš rozkládat na vrstvy podle předchozích oddílů:
`familiar skin-import` z ní udělá skin sám (bez obličeje a klobouků, s reakcemi a drony
Robo-kuna přebarvenými do palety).

```sh
familiar skin-import hrdina.aseprite                       # skin "hrdina"
familiar skin-import sheet.json --id hrdina --nahled /tmp/hrdina.png
familiar skin-import sheet.png --mapa mapa.toml --prepsat   # JSON se hledá vedle PNG
```

Skin vznikne v `~/.local/share/familiar/skins/<id>/` (`$XDG_DATA_HOME/familiar/skins`), id je
podle jména souboru (malá písmena bez diakritiky), jinak `--id`. Existující skin se stejným id
(i z balíčku) se přepíše jen s `--prepsat`. Příkaz vypíše, který tag dostal který stav,
a varování (zmenšení, sloučené barvy). Pak stačí `skin = "<id>"` v configu.

**Vstup.** (a) *File → Export Sprite Sheet* s *Output → JSON Data* a zaškrtnutými *Tags*:
formát Hash i Array, libovolné rozložení sheetu, `--trim` nevadí; ne `--split-layers` a rotace.
(b) Přímo `.aseprite`/`.ase`: čte se RGBA, šedá i indexovaná barva, viditelné vrstvy se sloučí
(skrytá vrstva, vrstva ve skryté skupině a referenční vrstva se vynechají), cely raw, zlib
i propojené (linked), z-index celu, krytí celu i vrstvy, tagy se směrem a *Repeat*.
Omezení (b): režimy prolnutí kromě Normal se slučují jako Normal (s varováním), tilemapové
vrstvy se vynechají, řezy (slices), uživatelská data a barevný profil se ignorují. Co neumí (b),
obejdeš exportem (a).

**Tagy → stavy.** Rozhoduje první slovo jména tagu, které je v tabulce (velikost písmen,
diakritika a číslice na konci nevadí, `Run 2`, `Ninja Idle`, `Přemýšlí` projdou):

| Stav | Jména tagů |
| --- | --- |
| idle | idle, stand, neutral, default, breath, klid, stojí, nečinnost |
| listening | listen, hear, alert, notice, poslouchá, poslech, slyší |
| thinking | think, ponder, hmm, myslí, přemýšlí, přemýšlení |
| working | work, tool, run, walk, type, attack, práce, pracuje, nástroj, běh, běží, chůze |
| waiting | wave, wait, ask, attention, mává, mávání, čeká, povolení, otázka |
| success | success, hop, jump, happy, win, victory, celebrate, done, hotovo, úspěch, radost, skok, výskok, hurá |
| error | error, trip, stumble, hit, hurt, damage, fail, chyba, zakopnutí, au, bolest, zásah, pád |
| sleeping | sleep, rest, zzz, spí, spánek, spát, odpočinek |
| gone | gone, leave, exit, bye, odchod, odešel, pryč (jinak jako sleeping) |

Tagy podle nástroje: slovo `bash`/`shell`/`terminal`, `edit`/`write`/`psaní` nebo
`search`/`read`/`grep`/`hledání` (např. `work_bash`, `work_edit`, `work_search`) rozdělí
working podle nástroje jako u Robo-kuna. Chybějící stav se odvodí z animace idle
(výskok, „…“, „!“, poskakování při práci, zatřesení, Zzz); bez idle
se vezme první tag, bez tagů jsou všechny snímky jeden tag idle. Tagy listening, success
a error jsou jednorázové; jinak jen tag s *Repeat = 1*. Směr Reverse a Ping-pong se rozepíše
do snímků. **fps** = průměr délek snímků tagu (*Duration*), jako u loaderu.

**Mapa** (`--mapa mapa.toml`) přebije konvenci; klíče stavů smí být i česky (slova z tabulky):

```toml
name = "Hrdina"            # název skinu (jinak jméno souboru)
meritko = 2                # 2 = zvětšit 2×, 0.5 = zmenšit 2× (jinak automaticky)
oneshot = ["Hurt", "Win"]  # jednorázové tagy; nahradí výchozí listening/success/error
nalady = false             # bez palet nálad (jen base)

[stavy]
idle = "Stand"
chyba = "Hurt"                                   # = error
working = { Bash = "Type", Read = "Look", default = "Run" }
```

**Velikost.** Postava se ořízne na společný obsah všech snímků, celočíselně zvětší, aby co
nejvíc vyplnila plátno 32×32 (16×16 → 2×), a posadí doprostřed na spodní hranu (kotva
`[16, 31]`). Větší se zmenší celočíselně (nejčastější barva bloku, ztrátové – nejlepší je
kreslit do 32×32); co se po `meritko` z mapy nevejde, ořízne se nahoře a po stranách.
Poloprůhledné pixely: krytí aspoň 50 % = plná barva, jinak průhledné.

**Barvy a nálady.** Skin má nejvýš 15 barev (+ průhledná). Víc barev se sloučí (median cut
na nejčastější skutečné barvy, s varováním). Barvy efektů, reakcí a dronů použijí blízkou
barvu postavy, nebo zbylé místo v paletě. Indexy palety zdroje se nepřebírají, paleta `base`
se postaví znovu (seřazená podle jasu). Nálady mění jen barvy postavy: `warm` (radost,
přimíchaný teplý odstín), `cold` (frustrace, studený), `faded` (únava, vybledlá); reakce
a tempo nálad jsou Robo-kunovy. Vlastní palety nálad dopiš do `pal/` a `skin.toml` ručně.

## Rozhraní pro renderer (`familiar/skin.py`)

```python
s = skin.load(skin_id)          # nikdy nevyhodí; při chybě BuiltinSkin s .error
s.id, s.name, s.source, s.size, s.anchor
s.anims                          # {animace: Anim(fps, frames, oneshot)}
s.anim_for(state, tool=None)     # stav činnosti → animace
s.frame_at(anim, t, speed=1.0)   # index snímku v čase t
s.mood_emote(mood), s.mood_tempo(mood)
s.render(anim, i, look)          # (bytes w×h indexů (s.size), barvy "#rrggbb" s None na indexu 0)
skin.available()                 # [(id, název, zdroj)]
skin.PackageSkin.from_parts(id, cfg, palety, {vrstva: skin.Sheet.memory(...)})   # skin z paměti (náhled editoru)
```

`look = (nálada, klobouk, emote, fáze emote, počet dronů, fáze dronů)` jako dosud z hubu.

## Rozhodnutí o formátu

Kapitola 5 konceptu počítala s Aseprite, vrstvami body/face/fx/acc, bodem `face_anchor`
a paletami podle nálady. Robo-kun z kódu ale vše peče do jednoho snímku a některé věci
v náčrtu nesedí. Rozhodnutí:

- **Plátno 32×32, větší volitelně.** Menší postavička se nakreslí na plátno 32×32. Větší
  (např. převzatý sprite 40×36, který by zmenšení zničilo) dostane `size` až 64×64: renderer
  i okna (dock, perch, ikona v nabídce) berou velikost ze skinu; snímek vestavěného Robo-kuna
  místo chybějící animace se posadí kotvou `[16, 31]` na kotvu skinu. `scale` z náčrtu se
  ignoruje, zvětšení řídí renderer.
- **Výchozí obličej je součástí body.** U Robo-kuna výraz často určuje animace (mrknutí,
  zavřené oči ve spánku, X při zakopnutí, úsměv při skoku), ne nálada. Nálada proto
  nekreslí obličej znovu, ale pokládá **záplatu** přes výchozí obličej. Záplata nese
  i pozadí, aby výchozí oči smazala.
- **Dva sloty obličeje (oči, pusa) místo jednoho `face`.** Robo-kun je mění nezávisle
  (radost mění jen pusu, únava jen oči). Jeden obličej se dá nakreslit jako slot `eyes`.
- **Kotvy jsou řezy (slices) Aseprite**, ne vlastní pole `face_anchor`: Aseprite je umí
  měnit po snímcích a exportuje je v json-array (`--list-slices`). Třetí řez `head`
  slouží kloboukům.
- **Zámky výrazu v `[face]` v TOML.** Klíč řezu se v Aseprite na jednom snímku odebrat
  nedá, takže „tady nálada obličej nemění“ (mrknutí v idle, spánek) se píše do TOML.
- **fx = efekty animace** (klávesnice, papír, lupa, „…“, „!“, pot, Zzz, jiskry), samostatný
  sheet se stejnými tagy jako body. Kreslí se až přes klobouk (lupa přes kšilt čepice),
  stejně jako v kódu. V Aseprite je to vrstva ve stejném souboru, exportovaná zvlášť.
- **Reakce mají vlastní vrstvu `emote`** (koncept je řadil do fx), protože je spouští hub
  nezávisle na animaci; 2 snímky = fáze pohupování.
- **Klobouky, reakce a drony patří skinu, nejsou společné.** Musí ležet v paletě skinu
  (indexy) a klobouk musí sedět na tvar hlavy. Chybějící klobouk, reakce nebo dron se
  prostě nekreslí – míchat je z Robo-kuna s cizí paletou nejde.
- **Varianty klobouku `<klobouk>@<animace>`**: lampa Robo-kunovy helmy svítí barvou
  antény, která se mění podle animace. Obecně se to hodí i na klobouk, který se při skoku nadzvedne.
- **Index 0 vyřezává.** Kód na pár místech kreslí průhlednou přes postavu (rohy sluchátek,
  schovaná anténa pod baretem). Bez toho by export nebyl pixel po pixelu shodný.
  Neprůhledná barva indexu 0 (magenta) v překryvné vrstvě proto znamená „vyříznout“.
- **[mood] má klíče `eyes`, `mouth`, `palette`, `emote`, `tempo`** místo `face`/`fx`:
  odpovídá to slotům obličeje a hub potřebuje i reakci při změně nálady a zpomalení (únava).
- **fps z délek snímků, jednorázovost z *Repeat = 1*** (Aseprite 1.3) nebo `[skin] oneshot`.
  Proměnné délky snímků se zprůměrují, renderer jede po celých fps.
- **Záloha:** jakákoli chyba balíčku → celý skin nahradí vestavěný Robo-kun (čitelná chyba
  v logu a v `.error`). Chybějící animace (nebo stav v `[activity]`) → jen ta animace
  z vestavěného skinu, i s jeho paletou; proto `render()` vrací paletu ke každému snímku.
- **PNG čte čistý Python** (RGBA, RGB, indexované 1–8 bitů, bez prokládání), aby skin mohl
  používat i hub bez Qt.
- **id = název adresáře**; pole `id` v `[skin]` není potřeba.
- **Květinka (`flower`) = „daří se“.** Ukáže se, když hlavní agent dokončí kolo bez chyby
  na konci (stejná podmínka jako impulz `kolo_bez_chyb`) a štítek nálady je právě radost.
  Srdíčko patří uživateli (poděkování) a změně nálady, fajfka testům; květinka je jediná
  reakce na konec kola. Podmínka radosti ji drží vzácnou: v běžném klidu by kvetla po
  každém kole. S srdíčkem se nesrazí: poděkování přijde s promptem na začátku kola,
  květinka na jeho konci a pravidlo klidu (`[klid]`) je od sebe oddělí. Jde stejnou
  frontou jako ostatní reakce, takže ji vypne `zobrazit.emoty`, tichý režim i soustředění.
  Subagenti ji nespouštějí.

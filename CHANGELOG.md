# Ændringer

## 0.40.0 (26/11-2026)

- **Bilen fra Telegram:** har I Home Assistant med EV Smart Charging, kan en koblet telefon skrive *"bil"* (klar-tid, planlagt opladning, batteri, elpris), *"klar 7"* eller *"klar 07:30"* (bilen skal være klar næste morgen, kun denne gang), *"klar normal"* (tilbage til fast tid), *"oplad nu"* og *"stop opladning"*. Botten klarer det selv, uden AI, og svarer med det samme.
- `claude -p` kan nu også svare på spørgsmål om huset ud fra Home Assistant (kun læsning) og styre bilen med de samme fem handlinger (nye værktøjer `bil_status`, `bil_klar`, `bil_oplad`). Intet andet i Home Assistant kan ændres.
- Sæt op med `ugeplan-mcp ha-opsaet`: læser et langtidstoken fra udklipsholderen, gemmer det i nøgleringen og tjekker det. Se [docs/MAC.md](docs/MAC.md) trin 9.
- Vagten tillader kun jeres egen Home Assistant på hjemmenettet, kun den adresse, der er sat op, og kun læsning af tilstande, tryk på knapper og klar-tiden. Et tryk på "oplad nu" sendes aldrig to gange.
- Kræver én genstart af Claude-appen (tre nye værktøjer).

## 0.39.0 (25/11-2026)

- **Svar på fri tekst med det samme:** skriver en koblet telefon noget, som botten ikke selv klarer, mens ingen AI-assistent eller madplan er i gang (fx "hvad skal vi have i aften?" eller "hvordan sov jeg?"), spørger lytteren headless Claude Code (`claude -p`) med ugeplan- og Garmin-serverne og sender svaret tilbage på Telegram. Kræver, at `claude` er installeret og logget ind på maskinen (se [docs/MAC.md](docs/MAC.md)). Uden `claude` er alt som før.
- Faste kommandoer (OK UGE-xxxx, ja til bytteforslag, menu, beholdning) klares stadig uden AI.
- `claude -p` får kun værktøjer, der læser: ingen ændringer i kurv, plan, profil eller beholdning, ingen indbyggede værktøjer (Bash, filer, web), og der bestilles og betales aldrig.
- Højst 20 kørsler i timen for hele husstanden. Derefter en kort besked, og beskeden gemmes til AI-assistenten.
- Kører på Claude-abonnementet: en `ANTHROPIC_API_KEY` i miljøet fjernes før kaldet.
- Svaret går kun til den, der spurgte, fordi det kan indeholde helbredsdata.
- Slås fra med `{"fra": true}` i `claude_p.json` i datamappen.

## 0.38.2 (24/11-2026)

- Rettet: `ugeplan-mcp telegram-opsaet udklipsholder` virker nu på Mac (pbpaste). Før kaldte den PowerShell og stoppede med en fejl.
- Rettet: `mac/tjek.zsh` sagde "Claude kører ikke", selvom appen kørte. Tjekket bruger nu `ps` i stedet for `pgrep`.

## 0.38.1 (17/11-2026)

- Rettet: på Windows åbnede Telegram-lytteren et Terminal-vindue, hver gang AI-appen startede. Den starter nu med en skjult konsol.

## 0.38.0 (13/11-2026)

- **Tilbud først:** når madplanen starter, henter koden ugens tilbud i butikkerne, sorterer dem efter det, I faktisk køber (fisk, fugl, kød og de faste varer) og efter profilen (frost, øko, færdigretter, smagsvarianter, fedtprocent, mindst 85 % osv.), og foreslår ugens butik. Menuen bygges på tilbuddene i den butik, så en ret aldrig er bygget på et tilbud, I ikke får.
- Har I kød i fryseren (eget vildt, en kvart ko), tæller kødtilbud ikke med i valget af butik.
- Fugl på lager: et stort tilbud på fugl giver et spørgsmål om at købe ekstra til fryseren.
- Ugens tilbud på fisk, fugl og kød gemmes i `tilbud_historik.json`, så det kan ses, hvor tit der er gode tilbud.

## 0.37.0 (10/11-2026)

- **Garmin er nu en del af ugeplan-mcp.** Den valgfri Garmin-del installeres med `ugeplan-mcp[garmin]` og giver serveren `garmin-mcp` (søvn, hvilepuls, skridt, kalorier, træninger, vægt og dagens belastning, kun læsning). Se [docs/GARMIN.md](docs/GARMIN.md).
- Telegram-lytteren henter dagens niveau direkte fra Garmin-delen, når den er installeret. `garmin-opsaet` behøves ikke længere, men virker stadig.
- `ugeplan-mcp opsaet` spørger, om I vil bruge Garmin, og skriver begge servere ind i jeres AI-app.

## 0.36.0 (10/11-2026)

- **Ugens budget gælder en normal uge** (beskrevet i profilens note). Færre dage hjemme, gæster og andre ændringer tilpasser budgettet, og AI'en skriver, hvordan den regnede.
- **Eget vildt og kød fra fryseren trækkes fra budgettet**, så det kan ses i ugens pris.
- Frost-reglen gælder nu også kød ("kød fra frost"). Husstandens eget vildt fra fryseren må gerne bruges.
- Ny guide: [docs/PROFIL.md](docs/PROFIL.md) forklarer profilens felter, giver gode råd og viser et eksempel.

## 0.35.0 (10/11-2026)

- **Større pakker, færre penge:** `sammenlign_liste` siger i linjens `tip`, når dobbelt mængde af samme vare (større pakke eller mængdetilbud) er mindst 15 % billigere, eller når den valgte pakke allerede dækker to retter.
- Forløbet planlægger efter det: én hovedingrediens til to retter med forskelligt tilbehør, eller samme tilbehør til to forskellige retter. Friskt kød ligger tæt eller fryses halvt, og fersk fisk deles aldrig.

## 0.34.1 (10/11-2026)

- Rettet: `garmin-opsaet` gemmer den fulde sti til uv, så lytteren også finder den på macOS, hvor apps kun får en kort PATH.
- Lytteren logger, når Garmin-niveauet ikke kan hentes (fejltype og personens navn, aldrig tal fra uret).

## 0.34.0 (10/11-2026)

- **Agil plan efter træning** (kræver Garmin-data og en maskine, der er tændt):
  - Når planen laves, lægges energirige retter på de dage, I plejer at træne.
  - I løbet af ugen foreslår botten uden AI at bytte retter, når en dag bliver hårdere eller roligere end planlagt.
  - "ja" bytter retterne og den fastgjorte menu.
  - Fersk fisk flyttes aldrig, og noget, der skal tøs op, flyttes aldrig til i dag. Der kommer højst ét forslag om dagen og en påmindelse kl. 20 om optøning.
- Profilen har fået felterne `garmin` (hvem der har sagt ja) og `aftensmad` (standard 18.30).
- Madplanen gemmer `retinfo` pr. ret: hvilken slags dag retten passer til, om den er fast, og om den skal tøs op.
- Ny kommando: `ugeplan-mcp garmin-opsaet MAPPE [VENV]`.
- Forslag og påmindelser gemmes i `haendelser.json`.
- IDEER.md med idéer til senere.

## 0.33.0 (10/11-2026)

- **Beholdningen fra telefonen:** "skudt et rådyr, ligger i fryseren", "har 2 kg kartofler" og "fortryd" klares af botten selv, med svar med det samme. Mens en madplan er i gang, går beskederne til AI'en som før.
- **Lytteren følger AI-appen:** den starter, når serveren starter, og kører, så længe appen er åben. Den stopper ikke længere efter 24 timer. På en maskine, der altid er tændt, svarer botten altid.
- README: nyt afsnit, *Hvad kræver hvad*, om hvad hvert niveau af udstyr giver.
- Rettet: lytteren kunne ikke starte hos en helt ny bruger, fordi datamappen ikke fandtes endnu.

## 0.32.0 (10/11-2026)

- **Åben for alle AI-apps med MCP.** Guiden spørger, hvilken app du bruger (Claude Desktop, Claude Code, Cursor, VS Code eller en anden), og viser præcis, hvad der skal sættes ind. README'en har en tabel over, hvad der virker.
- Telegram-beskederne siger "AI-assistenten" i stedet for "Claude".

## 0.31.0 (10/11-2026)

- Rettet: skabsvarer i beholdningen (fx kartofler, hvidløg, krydderier) blev regnet med uge efter uge, også når en ret havde brugt dem. Varer noteret før sidste fyldte kurv står nu under "Tjek, at I har", og "har X" gemmes, så de tæller igen.

## 0.30.0 (10/11-2026)

- Rettet: BilkaToGo viste ikke, at en vare var frost. Nu står der "400 g / frost" som hos nemlig, og forløbet forbyder frost, når profilen siger "kun fersk".
- Spørgsmålet om køleskabet beder om ca. mængder, og varer uden mængde kommer på "Tjek, at I har" med den mængde, ugen skal bruge.
- Rettet: når kurven ikke kunne fyldes, så husstanden værktøjets instrukser til Claude på Telegram.
- Rettet: Telegram-lytteren stoppede, når kurven var fyldt, så sene rettelser gik tabt. Den lytter nu videre.
- Rettet: en plan lavet om søndagen med "Søn: …" sidst gav en forkert advarsel om levering, og en aften med rester talte som planens første dag med indkøb.
- Rettet: ændringer i butikkernes kode slog først igennem efter en genstart af Claude Desktop.

## 0.29.0 (9/11-2026)

- **Guide til første opsætning:** `ugeplan-mcp opsaet` tager butikker, Telegram og Claude Desktop ét trin ad gangen. Første "lav madplan" med en tom profil starter en kort samtale om husstanden.
- **Brug kun det, du har:** én butik, ingen butik (nemligs priser og opskrifter som gæst), med eller uden Telegram og andre MCP-servere.
- Rettet: `sammenlign_liste` fejlede helt, hvis der kun var login til den ene butik.
- Rettet: kommandoerne gik ned i Windows-terminaler, der ikke kører UTF-8.

## 0.28.0 (9/11-2026)

- Nyt navn: **ugeplan-mcp**. Kommandoen `handle-mcp` virker stadig.
- Ugeplanen er generel: husstandens egne krav (økologi, kød, fisk) kommer fra profilen.
- Ny README, bidragsguide, sikkerhedspolitik og automatiske tests på GitHub.

## 0.27.x (7/11-2026)

- **Levering:** frister hos nemlig og Bilka, kun hjemlevering. Planen starter ved den første aftensmad, varerne kan nå. Botten sender den billigste leveringstid og bestillingsfristen.
- **Aftenerne før levering:** Claude trækker selv fra køleskabet, hvad de retter bruger.
- **Telegram:** svar vises på alle telefoner, og ugens menu fastgøres med links til opskrifterne.
- Faste måltider vises med indhold og antal dage. Fryservarer markeres kort, fx "(rådyr fra egen fryser)".

## 0.20–0.26 (6/11-2026)

- Favoritretter, basisvarer som system, mængdetilbud på holdbare varer.
- Ny ret, når en vare ikke kan købes, så den passer til profilen.
- Pålidelig sammenligning af butikkerne og deling mellem dem, når det kan betale sig.

## 0.10–0.19 (6/11-2026)

- Ugeplan i fire trin med godkendelse og "bestil".
- Telegram-bot til hele husstanden, gratis. Ønsker fra Telegram huskes i profilen.
- Opskrifter fra Valdemarsro, Arla, DR Mad, Madens Verden, HelloFresh og Årstiderne.
- Ny kode bruges uden at genstarte Claude Desktop.

## 0.1–0.9 (4.–5/11-2026)

- nemlig.com og BilkaToGo: søg, tilbud, kurv, leveringstider og ordrer.
- Sammenligning af en hel indkøbsliste med gebyrer, mængder og økologi.
- Beholdning, profil, budget og købsmønster.

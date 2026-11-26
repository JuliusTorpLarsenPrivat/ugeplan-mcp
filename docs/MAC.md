# En Mac, der altid er tændt

Med en Mac, der altid er tændt (fx en Mac mini), svarer Telegram-botten døgnet rundt. Med Garmin-delen tjekker lytteren desuden hver halve time mellem kl. 6 og 21, om dagen er blevet hård, og foreslår at bytte retter (se *Agil plan efter træning* i [README](../README.md)).

Lytteren kører kun, mens AI-appen er åben. Derfor skal appen starte ved login, og Mac'en må ikke gå i dvale. Guiden bruger Claude Desktop. Andre apps virker på samme måde, men scriptet sætter kun Claude Desktop op.

Alt kører i Terminal (Programmer > Hjælpefunktioner > Terminal).

## 1. Hent scripts

```zsh
xcode-select --install          # git; uv bruger det til at hente fra GitHub. Spring over, hvis det findes.
mkdir -p ~/ugeplan-mac && cd ~/ugeplan-mac
curl -fsSLO https://raw.githubusercontent.com/JuliusTorpLarsenPrivat/ugeplan-mcp/main/mac/installer.zsh
curl -fsSLO https://raw.githubusercontent.com/JuliusTorpLarsenPrivat/ugeplan-mcp/main/mac/tjek.zsh
```

Læs gerne scriptet, før du kører det: `less installer.zsh`.

## 2. Kør installationsscriptet

```zsh
zsh ~/ugeplan-mac/installer.zsh
```

Scriptet:
- installerer [uv](https://docs.astral.sh/uv/)
- installerer `ugeplan-mcp[garmin]` med `uv tool install` i nyeste version. Det giver kommandoerne `ugeplan-mcp` og `garmin-mcp` i `~/.local/bin` i ét fælles miljø, så lytteren kan hente niveauet direkte.
- fletter `ugeplan` og `garmin` ind i `~/Library/Application Support/Claude/claude_desktop_config.json`

Den gamle konfiguration gemmes først som `claude_desktop_config.json.backup-<tid>`, og andre servere bliver ikke rørt.

Scriptet kan køres igen. Det er også sådan, du opdaterer.

Appen starter programmerne direkte fra `~/.local/bin` i stedet for via `uvx`. Så skal intet hentes fra nettet, når Mac'en starter.

Brug ikke `ugeplan-mcp opsaet` til AI-appen på Mac'en. Den viser en `uvx`-opsætning, og scriptet har allerede sat appen op.

## 3. Log ind

Åbn en ny Terminal, så `~/.local/bin` er i PATH.

**Garmin**, én gang for hver person med ur, der har sagt ja:

```zsh
garmin-mcp login --person anna
garmin-mcp status
```

- Email og kode gemmes i macOS-nøgleringen under `garmin-mcp`.
- Tokens gemmes i `~/.local/share/garmin-mcp/<navn>/`.
- Hver person taster selv sin kode.

**Telegram** (botnøglen ligger i nøgleringen og skal tastes igen på en ny maskine):

```zsh
ugeplan-mcp telegram-opsaet
ugeplan-mcp telegram-par         # kun hvis telefonerne ikke allerede er koblet på
```

**Butikker**, hvis kurven skal fyldes fra Mac'en: `ugeplan-mcp login nemlig` og/eller `ugeplan-mcp login bilka`.

**Nøgleringen.** Spørger macOS, om "python" må bruge nøgleringen, så vælg **Tillad altid**. Ellers kan lytteren ikke logge ind, når ingen sidder ved Mac'en. Det kan ske igen efter en opdatering.

**Husstandens data fra en anden maskine** (valgfrit). Profil, beholdning, planer og koblede telefoner ligger i JSON-filer:
- Windows: `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Local\handle-mcp\`, eller `%LOCALAPPDATA%\handle-mcp\`
- Mac: `~/.local/share/handle-mcp/`

Kopiér `*.json` derover. Lock- og logfiler skal ikke med. Har du kopieret `garmin-kommando.json` med, så kør installationsscriptet igen. Den fil peger på den anden maskine, og scriptet lægger den til side.

**Profilen.** Skriv til Claude på Mac'en, fx *"Anna må bruge sine Garmin-data, og vi spiser kl. 18.30"*. Det giver:
- `garmin: [{"navn": "Anna"}]`
- `aftensmad: "18:30"`

Hedder Garmin-personen noget andet end navnet i profilen, fx `standard`, så sig det også. Det bliver gemt som `konto`.

## 4. Claude starter ved login

Scriptet tilbyder at gøre det. Ellers: Systemindstillinger > Generelt > Login-emner > `+` > Claude.

Genstart Claude helt (Cmd+Q) efter installationen. Lytteren starter af sig selv, når appen starter ugeplan-mcp.

Efter strømsvigt starter Mac'en kun igen af sig selv, hvis `autorestart` er slået til (nedenfor). Claude starter kun, hvis Mac'en også logger ind af sig selv:
- Systemindstillinger > Brugere og grupper > Log automatisk ind.
- Det kræver, at FileVault er slået fra. Det er jeres afvejning.

## 5. Ingen dvale

```zsh
sudo pmset -a sleep 0 disksleep 0 displaysleep 10 womp 1 autorestart 1
pmset -g | grep -E ' sleep|autorestart'
```

Skærmen må gerne slukke (`displaysleep`), men Mac'en må ikke sove (`sleep 0`).

## 6. Fjernadgang med Tailscale

Med [Tailscale](https://tailscale.com/download) kan du nå Mac'en, uden at den er åben mod internettet:
- Skærmdeling, så du kan se AI-appen.
- SSH, så du kan køre tjekket og læse loggen.

1. Installér Tailscale på Mac'en og på din egen computer, og log ind med samme konto.
2. Slå "Launch at login" til i Tailscale-menuen på Mac'en.
3. Systemindstillinger > Generelt > Deling: slå **Skærmdeling** og **Fjernlogin** til, kun for din bruger.
4. Forbind med `ssh <bruger>@<mac-navn>`, hvor mac-navnet står i Tailscale.

## 7. Kun én lytter

Telegram giver kun beskeder til én lytter ad gangen. Har en anden computer også ugeplan-mcp i sin AI-app, deler de to maskiner beskederne mellem sig, og svar går tabt.

Fjern derfor ugeplan-serveren fra AI-appen på den anden computer, når Mac'en kører. Tag en kopi af konfigurationen først.

## 8. Svar med det samme (`claude -p`)

Uden dette svarer botten "AI-assistenten er ikke i gang", når I skriver et spørgsmål mellem madplanerne. Med Claude Code installeret på Mac'en svarer den selv med det samme, fx på "hvad skal vi have i aften?" eller "hvordan sov jeg i nat?". Det kører på dit Claude-abonnement (Pro eller Max), ikke på API'en.

Claude-appens indbyggede Code-fane giver ingen `claude`-kommando i Terminal. Installér derfor Claude Code med Anthropics officielle installationsscript. Det lægger `claude` i `~/.local/bin` og opdaterer sig selv:

```zsh
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

Log ind med Claude-kontoen (ikke en API-nøgle):

```zsh
claude
```

Vælg **Claude account with subscription**, log ind i browseren, og afslut med `/exit`. Spørger macOS, om `claude` må bruge nøgleringen, så vælg **Tillad altid**.

Prøv det, som lytteren gør:

```zsh
cd /tmp && claude -p "Svar kun: virker" --tools "" --output-format json
```

Svaret skal have `"is_error":false`. Der skal ikke genstartes noget: lytteren finder `claude` ved næste besked.

Sådan virker det:
- Kun koblede telefoner. Faste kommandoer (OK UGE-xxxx, ja, menu, beholdning) klares stadig uden AI.
- Kun når ingen AI-assistent arbejder, og ingen madplan venter på svar. Ellers går beskeden til assistenten som før.
- Claude får kun værktøjer, der læser (madplan, opskrifter, kurv, beholdning, profil, tilbud, Garmin). Den kan ikke ændre kurven og aldrig bestille eller betale.
- Højst 20 svar i timen for hele husstanden. Derefter siger botten det kort.
- Svaret går kun til den, der spurgte.
- Slå det fra med `{"fra": true}` i `~/.local/share/handle-mcp/claude_p.json`. Ligger `claude` et andet sted, så skriv stien som `{"claude": "/sti/til/claude"}` i samme fil.
- Fejl står i `telegram-lytter.log` (kun fejltypen, aldrig beskeden). Logger `claude` ud, så kør `claude` og log ind igen.

## 9. Bilen fra Telegram (Home Assistant)

Kun hvis I har Home Assistant med EV Smart Charging og klar-tiden fra Smarthome-projektet (`input_datetime.bilen_skal_vaere_klar_kl` og `input_boolean.undtagelse_i_nat`).

1. I Home Assistant: klik på dit navn nederst til venstre → **Sikkerhed** → **Langtidsadgangstokens** → **Opret token**. Kald det "ugeplan-lytter", og kopiér det.
2. I Terminal (tokenet læses fra udklipsholderen og vises ikke):

```zsh
ugeplan-mcp ha-opsaet
```

Kører Home Assistant et andet sted end i VM'en på denne Mac, så skriv adressen bagefter, fx `ugeplan-mcp ha-opsaet http://192.168.1.189:8123`. Kun adresser på hjemmenettet virker.

3. Kommandoen viser bilens status. Genstart Claude-appen, så lytteren og de nye værktøjer kommer med.

Skriv til botten:
- *"bil"*: klar-tid, planlagt opladning, batteri og elpris
- *"klar 7"*, *"klar 07:30"*: bilen skal være klar næste morgen, kun denne gang (rundes ned til kvarter; sat om dagen planlægges det kl. 18)
- *"klar normal"*: tilbage til ugedagens faste tid
- *"oplad nu"*, *"stop opladning"*: laderen kan være et minut om at reagere

Fri tekst ("hvad koster strømmen i aften?") besvares af `claude -p` med Home Assistant (kun læsning). Den må også styre bilen med de samme fem ting, men intet andet. Fjern adgangen igen ved at slette tokenet i Home Assistant.

## Tjekliste til første døgn

Kør tjekket, når alt ovenfor er gjort, og igen næste dag:

```zsh
zsh ~/ugeplan-mac/tjek.zsh
```

Det ændrer intet og viser kun niveauer, aldrig tal fra uret.

| # | Tjek | Hvordan | Grøn når |
|---|---|---|---|
| 1 | Mac'en sover ikke | `tjek.zsh` | "går ikke i dvale" |
| 2 | Claude starter ved login | `tjek.zsh`, og genstart Mac'en én gang | Claude og lytteren kører efter genstart, uden at du gør noget |
| 3 | `belastning --alle` virker | `tjek.zsh` (kører den, som appen gør, med appens korte PATH) | hver person har et niveau, ingen `fejl` |
| 4 | Lytteren får niveauet | `tjek.zsh`: "lytteren får Anna: …" | ikke `ukendt` |
| 5 | Tjek hver 30. min kl. 6-21 | `tjek.zsh` i løbet af dagen: "sidste træningstjek" | under 35 min gammelt mellem kl. 6 og 21 |
| 6 | Bytteforslag på Telegram | en hård dag (fx ≥ 30 min træning med aerob effekt ≥ 2), hvor dagens ret ikke er til en hård dag | forslaget kommer på Telegram, og `tjek.zsh` viser `bytteforslag` |
| 7 | "ja" bytter | svar "ja" på forslaget | botten svarer "Byttet: …", og den fastgjorte ugemenu er opdateret |
| 8 | Påmindelse kl. 20 | dagen før en ret, der skal tøs op | beskeden kommer ca. kl. 20, og `tjek.zsh` viser `paamindelse` |
| 9 | Kun én lytter | den anden computer | ugeplan er fjernet fra AI-appen dér (trin 7) |
| 10 | Fjernadgang | fra din egen computer via Tailscale | skærmdeling og `ssh` virker |
| 11 | Svar med det samme | skriv "hvad skal vi have i aften?" på Telegram, når ingen madplan er i gang | et rigtigt svar inden for et minut, ikke "AI-assistenten er ikke i gang" |

Punkt 6 og 8 kræver, at ugens plan har en ret, der passer. Ellers venter de til den første uge, hvor det sker.

## Fejlfinding

- Lytterens log ligger i `~/.local/share/handle-mcp/telegram-lytter.log`. Garmin-fejl står der også, men aldrig tal fra uret.
- Får lytteren `ukendt`, så kør `tjek.zsh`. Linjen under "Garmin" viser fejlen, fx at et login er udløbet (`garmin-mcp login --person …` igen).
- Claudes egne MCP-logs ligger i `~/Library/Logs/Claude/` (`mcp-server-ugeplan.log`, `mcp-server-garmin.log`).

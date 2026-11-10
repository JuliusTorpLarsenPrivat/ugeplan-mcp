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

Punkt 6 og 8 kræver, at ugens plan har en ret, der passer. Ellers venter de til den første uge, hvor det sker.

## Fejlfinding

- Lytterens log ligger i `~/.local/share/handle-mcp/telegram-lytter.log`. Garmin-fejl står der også, men aldrig tal fra uret.
- Får lytteren `ukendt`, så kør `tjek.zsh`. Linjen under "Garmin" viser fejlen, fx at et login er udløbet (`garmin-mcp login --person …` igen).
- Claudes egne MCP-logs ligger i `~/Library/Logs/Claude/` (`mcp-server-ugeplan.log`, `mcp-server-garmin.log`).

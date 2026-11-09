# ugeplan-mcp

**Ugens madplan for hele husstanden, direkte på telefonen. Claude laver planen, I retter den i Telegram, og kurven bliver fyldt hos nemlig.com eller BilkaToGo. I betaler selv.**

[![Tests](https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp/actions/workflows/ci.yml)
[![MIT](https://img.shields.io/badge/licens-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)

<img src="docs/forloeb.svg" alt="Én uge: 1 køleskabet, 2 menu, 3 pris, 4 bestil, 5 I betaler i butikkens app" width="100%">

> **Den kan aldrig bestille eller betale.** Den kode findes ikke, en vagt blokerer kaldene, og testene fejler, hvis nogen prøver at tilføje dem.

## Sådan ser en uge ud

1. **Søndag:** I skriver "lav madplan" i Claude. Botten spørger på begge jeres telefoner: *"Hvad har I i køleskabet?"* I svarer, som det passer jer, også indtalt.
2. **Menu:** Claude laver en menu ud fra jeres profil, det I har hjemme, ugens tilbud og jeres favoritretter, med et prisskøn mod ugens budget. I retter i Telegram ("ikke fisk tirsdag", "billigere").
3. **Pris:** Hele listen prissættes i begge butikker, med levering, poser og minimumskøb. Den billigste vinder, eller begge, hvis det kan betale sig.
4. **"bestil":** Kurven bliver fyldt med præcis de godkendte varer. Botten sender ugens menu med links til opskrifterne og fastgør den øverst i chatten. Den sender også den billigste leveringstid, der når første aftensmad, og hvornår I senest skal bestille.
5. **I betaler** i butikkens app.

I kan se hinandens svar, og I behøver ikke vente på hinanden.

## Det, der adskiller den

- **Hele husstanden på Telegram.** Flere telefoner, svar ses af alle, gratis og uden AI-udgifter i botten.
- **Den husker jeres hjem.** Køleskab, fryser og skab. Køleskabsvarer forsvinder af sig selv efter en uge, og fryservarer bliver brugt, når det passer.
- **Den kender leveringsreglerne.** Frister hos nemlig og Bilka, kun hjemlevering. Varer, der kommer senest kl. 17, rækker til samme aften. Aftenerne før levering trækkes fra køleskabet af sig selv.
- **Jeres regler, ikke vores.** Budget, økologi, ting I ikke spiser, faste måltider og bestemte varer ("chokolade mindst 85 %") står i jeres egen profil. I ændrer den ved bare at sige det i Telegram ("husk, vi ikke kan lide fennikel").
- **Grundige varevalg.** Mængden tæller ("500 g hakket oksekød"), pakker og tilbud regnes ud, og rå varer foretrækkes frem for færdigretter, panerede eller frosne varer.
- **Opskrifter fra danske sider:** Valdemarsro, Arla, DR Mad, Madens Verden, HelloFresh, Årstiderne og nemlig.

## Det skal du bruge

- En Windows-pc. Mac og Linux burde virke, men er ikke testet.
- [uv](https://docs.astral.sh/uv/) og [Git](https://git-scm.com/downloads).
- [Claude Desktop](https://claude.ai/download).
- En konto hos nemlig.com og/eller BilkaToGo med hjemlevering.
- Telegram, hvis husstanden skal svare fra telefonen. Det er valgfrit, for det virker også i chatten.

## Installér

**1. Log ind i butikkerne.** Login gemmes kun i Windows' nøglering.

```powershell
uvx --from git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.28.0 ugeplan-mcp login nemlig
uvx --from git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.28.0 ugeplan-mcp login bilka
```

**2. Kobl den på Claude Desktop:** Settings → Developer → Edit Config:

```json
{
  "mcpServers": {
    "handle": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.28.0", "ugeplan-mcp"]
    }
  }
}
```

Finder Claude ikke `uvx`, så skriv hele stien, fx `C:\\Users\\<dig>\\.local\\bin\\uvx.exe`.

**3. Genstart Claude Desktop helt**, også i proceslinjen. Hos BilkaToGo skal du vælge hjemlevering én gang på bilkatogo.dk.

**4. Udfyld profilen.** Skriv i Claude: *"Sæt min profil op: vi er 2, budget 1500 kr om ugen, vi vil have øko, og vi spiser ikke svampe."*

## Telegram (valgfrit, anbefalet)

1. Skriv `/newbot` til @BotFather i Telegram, og kopiér botnøglen.
2. Kør `ugeplan-mcp telegram-opsaet udklipsholder`. Nøglen gemmes i nøgleringen, og du får en parringskode.
3. Send koden til botten fra hver telefon, der skal være med.

Kun parrede telefoner kan skrive med botten. Botten lytter, mens Claude Desktop kører.

## Værktøjer

| Værktøj | Ændrer noget? | Hvad |
|---|---|---|
| `ugeplan_forloeb` | nej | Ugeplanens faste forløb, som Claude følger |
| `soeg_varer` | nej | Pris, enhedspris, tilbud og lager. `billigst_foerst=True` gennemsøger flere hits og ugens tilbud |
| `ugens_tilbud` | nej | Ugens tilbud i én butik |
| `sammenlign_liste` | nej | Prissætter en liste i begge butikker med gebyrer og anbefaler den billigste løsning |
| `soeg_opskrifter` / `hent_opskrift` | nej | nemligs opskrifter og varerne til dem |
| `hent_opskrift_fra_link` | nej | Opskrift fra Valdemarsro, Arla, DR Mad, Madens Verden, HelloFresh eller Årstiderne |
| `vis_kurv` | nej | Kurv, gebyrer og minimumskøb |
| `saet_antal_i_kurv` | **ja, kun kurven** | Sætter antal af en vare |
| `fyld_kurv_fra_madplan` | **ja, kun kurven** | Lægger præcis den godkendte plans varer i kurven |
| `leveringstider` | nej | Ledige tider og pris |
| `tidligere_ordrer` | nej | Ordrehistorik |
| `koebsmoenster` | nej | Basisvarer, favoritter og forbrug ud fra tidligere køb |
| `vis_beholdning` / `opdater_beholdning` | kun lokalt | Det, I har hjemme |
| `vis_profil` / `opdater_profil` | kun lokalt | Personer, budget, præferencer, ting at undgå, faste måltider |
| `vis_opskrifter` / `gem_opskrift` / `fjern_opskrift` | kun lokalt | Jeres favoritretter |
| `gem_madplan` / `vis_madplan` | kun lokalt | Ugens plan med kode og præcis indkøbsliste |
| `send_besked` / `vent_paa_svar` / `vis_beskeder` | sender til jeres Telegram | Snakken med husstanden |

## Sikkerhed og privatliv

- Login og botnøgle ligger kun i styresystemets nøglering.
- Profil, beholdning, opskrifter og planer er JSON-filer på din egen computer i `%LOCALAPPDATA%\handle-mcp\`. De sendes aldrig til butikkerne.
- Alle kald går gennem `vagt.py`, som kun tillader butikkernes egne adresser og afviser alt, der ligner bestilling, betaling eller valg af levering.
- Navn, adresse, telefon og e-mail fjernes fra svarene, før Claude ser dem.
- Det, Claude ser, sendes til Anthropic som en del af samtalen.
- Lås installationen til en version (`@v0.28.0`), så koden ikke ændrer sig uden din viden.

## Begrænsninger

- Uofficiel. Den bruger butikkernes egne hjemmeside-API'er og kan holde op med at virke uden varsel.
- Ikke tilknyttet nemlig.com, Salling Group eller Anthropic.
- Kun hjemlevering, ikke afhentning.
- Telegram-botten svarer kun, mens Claude Desktop kører. Til en maskine, der altid er tændt, se *Over netværket* nedenfor.

## Over netværket (HTTP)

Til en maskine, der altid er tændt, fx en mini-pc. Hver forespørgsel kræver en adgangsnøgle.

```powershell
ugeplan-mcp http-noegle               # laver nøglen og viser den én gang
ugeplan-mcp http 100.x.y.z 8765       # fx maskinens Tailscale-adresse
```

Stil den aldrig åbent på internettet. Brug et privat netværk som [Tailscale](https://tailscale.com).

## Udvikling

```sh
uv sync
uv run pytest
```

Ændringer i logikken bruges med det samme, uden genstart (`genindlaes.py`). Nye værktøjer og ændringer i `server.py` kræver en genstart af Claude Desktop. [LÆR.md](LÆR.md) gennemgår, hvordan det hænger sammen. Bidrag er velkomne: se [CONTRIBUTING.md](CONTRIBUTING.md).

Python-pakken hedder internt stadig `handle_mcp`, og kommandoen `handle-mcp` virker stadig.

## Tak

Inspireret af [NJohansen/handle-mcp](https://github.com/NJohansen/handle-mcp) af Niclas Johansen, som viste, at nemlig og BilkaToGo kan bruges fra en AI-agent.

## Licens

[MIT](LICENSE) © 2026 Julius Torp Larsen

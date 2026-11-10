# Sådan hænger garmin-mcp sammen

Garmin-delen af ugeplan-mcp. Samme opbygning som resten (se [LÆR.md](../LÆR.md)), så det, du lærte dér, gælder også her.

## 1. Delene

```
 Dig ──► Claude Desktop ──(MCP over stdio)──► garmin-mcp på din PC ──(HTTPS, kun GET)──► Garmin Connect
                                                  │
                         Windows-nøgleringen (login) + %LOCALAPPDATA%\garmin-mcp (tokens)
```

- **Claude** vælger værktøjet, fx `dagsstatus("i dag")`, og får et lille JSON-svar tilbage.
- **garmin-mcp** henter tallene fra Garmin, skærer dem ned og glemmer dem igen.
- **ugeplan** er den anden server i samme pakke. Claude bruger begge i samme samtale: først dine tal fra Garmin, så varer og priser fra butikkerne. Telegram-lytteren henter dagens niveau direkte fra garmin-delen, uden AI.

## 2. Login og MFA

Garmin har ingen officiel API til privatpersoner. Biblioteket `garminconnect` logger ind som Garmins egen app:

1. `login` spørger om email, kode og (hvis du har MFA) koden fra mail eller app.
2. Garmin giver et **adgangstoken** (kort levetid) og et **refresh-token** (lang levetid). De gemmes i `%LOCALAPPDATA%\garmin-mcp`.
3. Email og kode gemmes i nøgleringen, men først når login er lykkedes.
4. Når Claude spørger, bruger serveren tokens. Udløber adgangstokenet, fornyer biblioteket det selv med refresh-tokenet, uden MFA.
5. Afviser Garmin begge, prøver serveren email og kode. Vil Garmin have en MFA-kode, kan serveren ikke spørge dig (den kører i baggrunden), så Claude siger, at du skal køre `login` igen.

Biblioteket `garth`, som tidligere stod for login, er udgået, fordi Garmin lavede deres login om i 2026. `garminconnect` har sit eget login fra version 0.3.

## 3. Filerne

| Fil | Hvad den gør |
|---|---|
| `src/garmin_mcp/server.py` | De 7 værktøjer. Hver `@mcp.tool` er en "knap" for Claude. Start her. |
| `src/garmin_mcp/sundhed.py` | Henter fra Garmin og omsætter til danske navne og enheder (timer, km, kg). |
| `src/garmin_mcp/niveau.py` | Dagens belastning (rolig → meget hård), personligt ud fra egne 28 dage og hvilestofskifte. |
| `src/garmin_mcp/vagt.py` | Sætter sig foran al netværkstrafik: kun `*.garmin.com`, kun GET mod data-API'et. |
| `src/garmin_mcp/forbindelse.py` | Logger ind én gang og genbruger forbindelsen. Oversætter fejl til dansk. |
| `src/garmin_mcp/login.py` | Nøgleringen og token-mappen, én pr. person. |
| `src/garmin_mcp/cli.py` | `login`, `status`, `test`, `belastning` og `logout`. |
| `tests/` | Tests med en falsk Garmin (`conftest.py`), så de aldrig rører din konto. |

### Hvorfor en "vagt", når biblioteket allerede er fra Garmin-verdenen?

Biblioteket er skrevet af andre og har over 100 funktioner, også nogle der sletter og uploader. Vi stoler på det, men tjekker alligevel. Vagten **monkeypatcher**: den udskifter `requests.Session.send` og `curl_cffi`'s `Session.request` med en version, der først tjekker adressen og så kalder den oprindelige. Det er et nyttigt Python-trick, men brug det sparsomt.

### Hvorfor `asyncio.to_thread`?

MCP-serveren er `async` (den kan håndtere flere ting på én gang), men `garminconnect` er almindelig "blokerende" kode. `to_thread` kører Garmin-kaldet i en baggrundstråd, så serveren ikke fryser imens.

### Hvorfor median og ikke gennemsnit?

En enkelt jagtdag med 600 aktive kalorier trækker et gennemsnit op, så de næste hårde dage ser mindre hårde ud. Medianen (den midterste værdi) er ligeglad med enkelte ekstreme dage. Dage uden ur springes over, ellers ville en glemt opladning gøre alle andre dage "hårde".

## 4. Øvelser

1. **Nyt felt:** Garmin sender `floorsAscended` (etager) i `get_stats`. Tilføj det i `dagstal()` i `sundhed.py`, kør `uv run python -m pytest`, og spørg Claude.
2. **Nyt værktøj:** `g.get_hydration_data(dato)` giver væskeindtag. Lav et værktøj `vaeske` efter samme mønster som `vaegt`. Husk: kun `get_`-metoder, ellers fejler en test.
3. **Se vagten arbejde:** Kør `uv run python -c "from garmin_mcp import vagt; vagt.installer(); import requests; requests.get('https://example.com')"`.

## 5. På en maskine, der altid er tændt

Kør `garmin-mcp login --person <navn>` for hver person på den maskine (tokens og nøglering er pr. maskine og flyttes ikke). Installeres ugeplan-mcp med `[garmin]`, henter lytteren dagens niveau direkte. En guide til en Mac mini, der altid er tændt, kommer.

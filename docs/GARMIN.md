# Garmin: sundhedsdata til madplanen (valgfri)

ugeplan-mcp har en valgfri Garmin-del, `garmin-mcp`. Den giver AI-assistenten adgang til **jeres egne sundhedsdata fra Garmin Connect**: søvn, hvilepuls, skridt, forbrændte kalorier, træninger og vægt. Madplanen bruger dem til at lægge mættende retter på hårde dage, og lytteren foreslår at bytte retter, når en dag bliver hårdere eller roligere end planlagt (se *Agil plan efter træning* i [README](../README.md)).

**Den kan kun læse.** Der findes ingen kode, der ændrer, uploader eller sletter noget i jeres Garmin-konto, og en vagt afviser alt andet end læsekald.

Uofficiel. Bygger på biblioteket [`garminconnect`](https://github.com/cyberjunky/python-garminconnect), som bruger Garmins egne app-adresser. Garmin ændrer dem af og til, så det kan holde op med at virke, indtil biblioteket er opdateret.

## Installér

Garmin-delen installeres med `[garmin]` efter pakkenavnet. Log ind én gang pr. person, der har sagt ja:

```powershell
uvx --from "ugeplan-mcp[garmin] @ git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.37.0" garmin-mcp login --person anna
uvx --from "ugeplan-mcp[garmin] @ git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.37.0" garmin-mcp test --person anna
```

`login` spørger om email, kode og evt. MFA-kode. `test` viser gårsdagens søvn og skridt.

Blokerer Windows Defender `garmin-mcp.exe`, så brug `python -m garmin_mcp.server` i stedet, fx `uvx --from "…" python -m garmin_mcp.server login --person anna`.

### I AI-appen

Læg Garmin-serveren ind ved siden af ugeplan, og brug `[garmin]` i begge, så Telegram-lytteren også kan hente dagens niveau. For Claude Desktop, Cursor m.fl. (`mcpServers`):

```json
{
  "mcpServers": {
    "ugeplan": {
      "command": "uvx",
      "args": ["--from", "ugeplan-mcp[garmin] @ git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.37.0", "ugeplan-mcp"]
    },
    "garmin": {
      "command": "uvx",
      "args": ["--from", "ugeplan-mcp[garmin] @ git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp@v0.37.0", "garmin-mcp"]
    }
  }
}
```

`ugeplan-mcp opsaet` spørger, om I vil bruge Garmin, og skriver den rigtige opsætning til jeres app. Genstart appen bagefter, og sig til assistenten, hvem der må bruges, fx *"Anna må bruge sine Garmin-data"*.

## Værktøjer

Alle tager `fra_dato` og evt. `til_dato` (ÅÅÅÅ-MM-DD, "i dag" eller "i går", højst 31 dage). `dagsstatus` tager én `dato`. Har husstanden flere Garmin-personer, tager alle også `person`.

| Værktøj | Hvad |
|---|---|
| `dagsstatus` | Nattens søvn, dagens skridt, kalorier, hvilepuls, body battery, stress og træninger i går og i dag |
| `soevn` | Timer (dyb, let, REM, vågen), søvnscore, HRV, body battery. Datoen er morgenen, man vågnede |
| `hvilepuls` | Hvilepuls pr. dag og 7-dages gennemsnit |
| `skridt` | Skridt, mål, distance, intensitetsminutter |
| `kalorier` | Forbrændt i alt, aktive og hvile (BMR) |
| `traeninger` | Type, varighed, distance, kalorier, puls, træningseffekt |
| `vaegt` | Vægt, fedtprocent, muskelmasse, BMI |
| `belastning` | Dagens niveau: rolig, normal, hård, meget hård (eller ukendt). Personligt, se nedenfor |

## Kommandoer

```text
garmin-mcp login --person anna      log ind (én gang pr. person)
garmin-mcp status                   hvem er logget ind? (viser aldrig koden)
garmin-mcp test [--person anna]     gårsdagens søvn og skridt
garmin-mcp belastning --alle --dato 2026-11-10   niveau for alle som JSON
garmin-mcp logout --person anna     slet personens login og tokens
```

Et login lavet uden `--person` hedder `standard`.

## Belastning (niveau pr. dag)

Niveauet er **personligt**: det sammenlignes med personens egne seneste 28 dage og med personens hvilestofskifte (BMR), så det passer til både en 30-årig jæger og en 67-årig havemand.

| Niveau | Når |
|---|---|
| meget hård | aktive kalorier ≥ 3 × ens normale dag eller ≥ 30 % af BMR, eller en aktivitet ≥ 4 timer |
| hård | aktive kalorier ≥ 2 × normal eller ≥ 20 % af BMR, skridt ≥ 2 × normal, en aktivitet ≥ 30 min med aerob effekt ≥ 2,0, eller en aktivitet ≥ 2 timer |
| rolig | aktive kalorier ≤ halvdelen af normal (aldrig for i dag, for dagen er ikke slut) |
| normal | ellers |
| ukendt | uret var ikke på |

En hel dag ude i kulden (fx jagt) uden startet aktivitet fanges af de aktive kalorier og skridtene. En persons fejl stopper ikke de andre. Husstanden ser kun niveauet, aldrig de rå tal.

## Sikkerhed og privatliv

Helbredsdata er en særlig kategori af persondata. Derfor:

- **Login** (email og kode) ligger kun i styresystemets nøglering under navnet `garmin-mcp`, én konto pr. person. Aldrig i filer, i app-konfigurationen eller i git.
- **Login-tokens** ligger i `%LOCALAPPDATA%\garmin-mcp\<person>\garmin_tokens.json` (macOS og Linux: `~/.local/share/garmin-mcp/<person>/`). De fornyes automatisk. Udløber de, eller beder Garmin om MFA igen, siger assistenten, at I skal køre `login`.
- **Ingen cache:** sundhedsdata hentes, når der spørges, og gemmes ikke.
- **Kun Garmin:** vagten afviser ethvert kald, der ikke er https til `garmin.com` eller en underadresse, og alt andet end GET mod Garmins data-API.
- **Kun læsning:** ingen skrivende værktøjer. Testene fejler, hvis nogen tilføjer et.
- Det, AI'en ser, sendes til den AI-udbyder, jeres app bruger. Værktøjerne sender kun de få tal, der er brug for.
- `garminconnect` er låst til 0.3.x og præcist i `uv.lock`. Læs ændringerne, før I opdaterer.

## Udvikling

```sh
uv sync --extra garmin
uv run pytest
```

Uden `--extra garmin` springes Garmin-testene over. [GARMIN-LÆR.md](GARMIN-LÆR.md) gennemgår, hvordan det hænger sammen.

# Bidrag

Tak, fordi du vil hjælpe. Fejl og ønsker skal i [Issues](https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp/issues), og kode kommer ind som pull requests.

## Sådan

1. Lav en gren fra `main`, fx `ret/bilka-frist` eller `ny/rema`.
2. Skriv en test, der viser fejlen eller den nye funktion, og lav så ændringen.
3. Kør `uv run pytest`. Alle tests skal være grønne.
4. Åbn en pull request mod `main`, og udfyld skabelonen.

`main` er beskyttet: alt kommer ind via pull request, testene skal være grønne på GitHub (Windows og Linux), og ejeren godkender.

## Faste regler

- **Aldrig bestille, betale eller vælge leveringstid.** Ingen kode må gøre det, og `vagt.py` og testene skal blive ved med at afvise det.
- **Ingen persondata i koden, testene eller git.** Logins hører til i nøgleringen, og husstandens data hører til i de lokale JSON-filer.
- **Kun butikkernes egne adresser.** Nye adresser skal tilføjes i `vagt.py`.
- **Husstandens egne regler hører til i profilen,** ikke i koden.
- **Nye moduler** skal med i `genindlaes.RAEKKEFOLGE`. Det tjekker en test.
- Undgå at ændre `server.py`, når det kan undgås, for det kræver en genstart af Claude Desktop.

## Sprog

Koden, testene og teksterne er på dansk, fordi brugerne og butikkerne er danske. Skriv kort og klart.

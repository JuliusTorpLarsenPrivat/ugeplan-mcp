# Sikkerhed

## Meld et sikkerhedshul

Opret **ikke** et offentligt issue. Brug i stedet [Report a vulnerability](https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp/security/advisories/new) under fanen Security. Du får svar inden for en uge.

## Det lover projektet

- **Ingen kode kan bestille, betale eller vælge leveringstid.** `vagt.py` afviser det, og testene fejler, hvis det tilføjes.
- **Kun butikkernes egne adresser og Telegram** kan kaldes. Alt andet afvises.
- **Logins og nøgler** ligger kun i styresystemets nøglering, aldrig i filer eller i git.
- **Persondata** (navn, adresse, telefon, e-mail) fjernes fra svarene, før AI'en ser dem.
- **Husstandens data** (profil, beholdning, planer) ligger kun lokalt.

## Understøttede versioner

Kun den nyeste version får rettelser.

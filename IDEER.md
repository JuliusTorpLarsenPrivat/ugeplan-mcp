# Idéer til senere

Ting, der er gode, men ikke bygget endnu. Bidrag er velkomne (se [CONTRIBUTING.md](CONTRIBUTING.md)).

## Agil plan efter træning

- **Uden ur:** husstanden melder selv "lang dag i dag" på Telegram, og botten foreslår at bytte ligesom med Garmin-data.
- **Træningsplaner:** brug planlagte træninger (fx et løbeprogram) til at lægge ugens retter, ikke kun mønstret fra de sidste uger.
- **Dashboard og smart home:** forslag og påmindelser ligger allerede i `haendelser.json`. En iPad på køkkenbordet eller en højttaler kan læse den samme liste, fx "husk at tage vildtkødet op".

## Regler, der vækker AI'en (er i gang)

Der kører ingen AI hele tiden. Botten klarer det forudsigelige med faste regler og vækker kun AI'en, når en regel siger, at der er brug for den. Så koster det kun noget, når AI'en faktisk arbejder.

- **Vækning:** lytteren starter AI'en med en bestemt opgave, fx via Claude Code uden vindue (`claude -p "…"`) på abonnementet. AI'en løser opgaven, svarer på Telegram og lukker igen. Det skal afgøres, hvad der må vække den, hvor tit, og hvad den må gøre uden at spørge.
- **"Vi har kort tid i dag":** byt til den hurtigste ret, der er tilbage i ugen. Gemmes tilberedningstiden i retinfo, kan botten gøre det selv, uden AI.
- **Nyt vildt eller kød fra kogræsserlauget:** botten lægger det i fryseren som i dag og vækker AI'en, som tænker det ind i ugens plan og foreslår, hvilken ret det kan erstatte.
- **Beskeder, botten ikke forstår:** i stedet for "skriv fortsæt i chatten" vækkes AI'en og svarer selv, fx "kan vi få noget andet end fisk i morgen?".
- **Udsolgt efter "bestil":** AI'en vækkes, finder en erstatning og skriver den nye total.
- **Fast tid:** fx søndag kl. 12 starter AI'en selv ugens madplan.

## Pengene

- **Tilbud først:** når madplanen starter, henter koden ugens tilbud i begge butikker og vælger ugens butik ud fra tilbud på det, der faktisk købes: fersk vildfanget fisk, fugl og de faste varer. Menuen bygges på de tilbud. Fryseren (eget vildt og kød fra kogræsserlauget) bruges stadig først.
- **Fugl på lager:** store tilbud på øko kylling og and købes og fryses selv, så de står klar til senere uger.
- **Mål tilbuddene:** ugens tilbud på fisk, fugl og øko-kød gemmes hver uge. Efter et par måneder kan vi se, hvor tit der er gode tilbud, og hvor pengene går hen.

## Nemmere at komme i gang

- **PyPI:** udgiv pakken, så installationen bliver `uvx ugeplan-mcp opsaet`, og læg et lille installationsscript ved, der også installerer uv.

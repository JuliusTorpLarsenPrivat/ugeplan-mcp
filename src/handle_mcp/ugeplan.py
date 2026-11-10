"""Madplanens forløb: køleskab → menu → pris → "bestil".

Fundet ved første rigtige brug: Når forløbet bare sagde "brug Telegram, hvis det er sat op",
stillede Claude spørgsmålene i chatten i stedet. Derfor sender `start()` selv det første
spørgsmål til Telegram, og forløbet siger klart, at al snak med husstanden foregår der.

Teksten ligger her (ikke i server.py), så den kan rettes uden at genstarte Claude Desktop.
"""

from __future__ import annotations

from handle_mcp import beholdning, login, persondata, telegram
from handle_mcp.lokal import LokalFejl

FOERSTE_SPOERGSMAAL = (
    "Hej! Ny madplan på vej.\n"
    "1) Hvad skal bruges denne uge? Rester, friske varer der snart skal bruges, og det fra "
    "fryseren I vil have brugt. Skriv ca. hvor meget (fx 500 g kartofler, 3 æg, ½ l mælk), så "
    "jeg ved, hvad det rækker til. Basisvarer (æg, mel, olie …) behøver I ikke nævne, dem tjekker "
    "jeg med jer bagefter.\n"
    "2) Hvor mange aftener skal vi have mad til, og fra hvilken dag?\n"
    "3) Noget særligt denne uge? (gæster, spise ude, vildt)\n"
    "4) Var der en ret sidste uge, I gerne vil have igen? Så gemmer jeg den som favorit.\n"
    "Svar bare her. Tal gerne ind med mikrofonen på tastaturet eller via Siri (ikke som talebesked)."
)

FAELLES = """
BUTIKKERNE (`butikker` fra ugeplan_forloeb: dem, der er login til)
- Brug kun de butikker. Er der kun én, så prissæt og fyld kurven dér, og nævn ikke den anden.
- Er der ingen, så virker nemligs søgning, tilbud, opskrifter og sammenlign_liste stadig som
  gæst (priser uden gebyrer og minimumskøb), men kurven kan ikke fyldes. Lav menuen og en
  indkøbsliste med mængder og priser, grupperet efter afdeling, og læg ca. 36 kr levering og
  18 kr poser til. Trin 4 bliver: send listen, så de selv kan handle. Sig én gang kort, at
  `ugeplan-mcp login nemlig` eller `login bilka` giver en fyldt kurv.
- Mangler et værktøj eller en del (fx garmin, Telegram eller en butik), så spring den del over
  uden at nævne det. Planen skal virke med det, der er sat op.

SVARET OM KØLESKABET ER SANDHEDEN (fundet i test 3: en tærterest fra en anden uge kom med)
- Det, de nævner i køleskabet, ERSTATTER køleskabsdelen af beholdningen: fjern med
  opdater_beholdning(fjern=[…]) de køleskabsvarer og rester, de ikke nævner. Fryser og skab
  bevares, medmindre de siger andet. Brug kun rester, de har nævnt i DETTE svar.

MÆNGDER I SVARET (fundet i uge 46: "kartofler" uden mængde, og ugen skulle bruge 1,5 kg)
- Spørgsmålet beder om ca. mængder. Mangler mængden ved en vare, som ugens retter bruger
  meget af, så gæt aldrig, at det rækker. Skriv den i menubeskeden under "Tjek, at I har"
  med den mængde, ugen skal bruge, fx "kartofler 1,5 kg", så de kan svare "har" eller "køb".
- Står der en mængde, så regn med den og køb kun forskellen.

ANTAL AFTENER (fundet i test 3: kødsovsen blev talt som en ekstra aften)
- "6 aftener" = 6 aftensmåltider i alt, MEDREGNET retter af det, vi har hjemme (fx kødsovs),
  og gæsteaftenen. Læg aldrig en aften til for resterne. Er det uklart, hvilken dag der
  udgår, så vælg selv og skriv det i menubeskeden.

PROFILENS KRAV ER KRAV (økologi, kød, fisk, mærker)
- Følg profilens præferencer, undgaa og vareønsker præcis, også når det koster mere. Siger
  profilen fx "økologi har høj prioritet", så vælg øko, når det findes, og skriv kort i
  prisbeskeden, hvis en vare ikke fandtes som øko.
- FROST: står "frost" i varens navn eller mængde (fx "400 g / frost"), er varen frossen. Siger
  profilen "fisk fra frost" eller "kun fersk", må den vare ALDRIG i kurven, heller ikke på
  tilbud. Skriv kun "fersk", når du har set, at der IKKE står frost. "Rødspætte er altid
  vildfanget" siger intet om, om den er fersk (fundet i uge 46: frosne rødspættefileter).
- Er et krav absolut (fx "kød altid øko", "kun vildfanget fisk"), og kan varen ikke købes
  sådan, så brug en anden protein eller en anden ret (se NÅR EN RET IKKE KAN KØBES
  ORDENTLIGT). Bryd aldrig et absolut krav for at spare.

UGENS BUDGET (regn det ud, før du laver menuen)
- Profilens ugebudget_kr er for en hel uge (7 dage) til profilens antal personer.
- Færre dage: skalér ned (6 af 7 dage → budget × 6/7). Gæster: skalér op efter antal ekstra
  måltider (2 gæster til 1 aftensmad hos 2 personer ≈ + 2 aftensmåltider). Skriv kort, hvordan
  du regnede, og send ugens budget til gem_madplan som valg={"ugebudget_kr": …}.
- Sig altid tydeligt, hvad du sammenligner med: "ugens budget" (ovenstående) eller "normalt
  forbrug" (det vi plejer at bruge ifølge koebsmoenster). De to tal er ikke det samme.

SVARENE ER OFTE INDTALT
- Diktering giver fejl og ingen tegnsætning (fx "en halv tær" kan være en halv tærte eller en
  halv tærtedej). Gæt det mest sandsynlige ud fra sammenhængen, og skriv gættet i menubeskeden
  i stedet for at stille et ekstra spørgsmål.
- Mangler startdagen, så start ved `foerste_aftensmad` i `levering` fra ugeplan_forloeb
  (første aftensmad, varerne kan nå; varer, der kommer senest kl. 17, rækker til samme aften).
  Spørg kun, hvis svaret er helt uklart.

LEVERING OG STARTDAG (søndag kl. 12 ligger der ofte mad til resten af søndag)
- `levering` fra ugeplan_forloeb siger pr. butik: første aftensmad, leveringstid, bestil
  senest og pris. Brug det, regn aldrig selv på frister eller "dagen efter levering".
- Planen starter tidligst ved den første aftensmad. Aftenerne før klarer husstanden med det,
  de har.
- TRÆK SELV FRA, HVAD DE AFTENER BRUGER (husstanden svarer, hvad der er i køleskabet, og du
  tjekker selv, hvad der bliver brugt). `foer_levering` viser hver aften før levering og
  retten fra den igangværende plan (og opskriften, hvis den findes). Det fra køleskabssvaret,
  som den ret skal bruge, regner du som brugt: brug det ikke i den nye plan og gem det ikke i
  beholdningen. Skriv én kort linje i menubeskeden, fx "Laks og kartofler går til søndagens
  ret, så dem regner jeg ikke med". Spørg ikke om det; retter de, så ret.
  Er `ret` null, og har de skrevet, hvad de spiser, så træk det fra på samme måde. Har de
  ikke, så brug det, de nævner.
- Skriv i menubeskeden én linje om levering, fx "Levering mandag kl. 7-14, bestil senest
  søndag kl. 14". Er der `naas_fristen_ikke`, så tilføj kort reserven ("ellers mandag kl.
  15-17, bestil senest søndag kl. 24").
- Siger husstanden en senere startdag, så brug den. Siger de en tidligere, end varerne kan nå,
  så sig det og foreslå den første mulige.
- Kun hjemlevering, aldrig afhentning.

TRIN 2: MENUEN (uden priser, men med et prisskøn)
3. Find retterne på vores opskriftssider (Valdemarsro, Arla, DR Mad, Madens Verden, HelloFresh,
   Årstiderne). Søg på nettet og hent dem med hent_opskrift_fra_link, eller tag dem fra
   vis_opskrifter. Brug det, vi har hjemme, først. Ram profilen og det, vi plejer at købe.
   Tag 1-2 af vores FAVORITTER med (se nedenfor), og marker dem med ★ i menuen.
   Brug vores egne varer (fx vildt fra fryseren) præcis som vi sagde: siger vi "rådyr
   lørdag", så kun lørdag, også selvom der er mere (fundet i en test: rådyr kom også tirsdag).
   Skabsvarer med `status` "tjek: …" må du ikke bygge en ret på, før vi har svaret "har".
   Tager du noget fra den gemte fryser- eller skabsbeholdning, som vi IKKE har nævnt i denne
   omgang, så skriv kort efter retten, fx "(rådyr fra egen fryser)". Intet mere: ingen
   forklaring. Siger vi, at den er brugt, så fjern den med opdater_beholdning.
   Køleskabsvarer ældre end 7 dage er allerede fjernet.
   De faste måltider i profilen (fx morgenmad og weekendfrokost) hører med hver uge og regnes
   for HELE ugen frem til næste levering (7 dage), ikke kun de aftener, vi skal have
   aftensmad. "Morgenmad hver dag" = 7 morgener, "frokost lørdag og søndag" = begge dage
   (fundet i en test: kun 6 morgener, og søndagsfrokosten manglede).
4. Skøn prisen pr. ret ud fra hovedingredienserne og kendte priser (koebsmoenster, tidligere
   søgninger), og skøn de faste måltider for sig. Læg levering og poser til (nemlig ca. 36 kr
   levering + ca. 18 kr poser). Hold det samlede skøn under ugens budget.
5. Send menuen kort: én linje pr. dag med ret, tid og skønnet pris, én linje pr. fast
   måltid med hvad det består af, antal dage og skøn, fx "Frokost 2 dage (lør, søn): rugbrød,
   æg, avocado, tomat – ca. 110 kr". Ikke fordelt på dage. Så det samlede skøn mod ugens budget. Tilføj BASISVARER (se
   nedenfor). Spørg: "Rettelser, eller er menuen god?" Vent på svaret.
6. Ret menuen, til den er god. Beder de om en billigere plan, så skriv med det samme kort, hvad
   der er ændret, og hvad det sparer (fx "Tir: nakkekoteletter i stedet for mørbrad, −40 kr"),
   så de ikke skal spørge (fundet i test 4). En pris, de selv sætter for ugen ("lav en plan til
   ca. 1200"), er ugens budget: brug den i valg={"ugebudget_kr": …}. Gør det en rettelse meget dyrere, så sig det og foreslå et
   alternativ. Følg ØNSKER TIL FREMOVER nedenfor. Først når menuen er godkendt, går du videre.

TRIN 3: PRISEN
7. Lav indkøbslisten ud fra opskrifternes ingredienser og de faste måltider, med mængder til
   vores antal personer og dage, minus det vi har hjemme (og det vi bekræftede i trin 2). Tag
   alle basisvarer fra "Køber" med (se BASISVARER). Prissæt i butikkerne med sammenlign_liste (oekologisk
   efter profilen). Overhold profilens vareønsker (fx kakaoprocent). Vær grundig: gå
   alternativerne igennem, søg igen på usikre linjer, og vælg ud fra pris, mængde og kvalitet.
8. Følg `anbefaling` fra sammenlign_liste: én butik, eller begge, når det samlet er billigst med
   levering, poser, pakning og minimumskøb. Del aldrig for en lille besparelse, som gebyrerne
   æder. Er totalen over ugens budget, så find konkrete billigere udskiftninger og nævn dem.
   Før du følger anbefalingen: søg igen på alle linjer i `tjek_foerst` (usikre match) med en
   bedre søgetekst, og kør sammenlign_liste igen. Mangler en butik få varer, men er den
   ellers klart billigst, så søg efter gode erstatninger netop dér (fx en anden vildfanget
   fisk), før den droppes. Usikre match tæller med den anden butiks pris, så de hverken gør
   en butik kunstigt billig eller smider den ud (fundet live: majsmel blev regnet som
   nakkekoteletter, og Bilka så 430 kr billigere ud end den var).
9. Gem med gem_madplan (gebyrer = alle gebyrer inkl. poser, valg={"ugebudget_kr": ugens budget}). Ved
   deling: butik="begge" og "butik" på hver vare. Send: butik(ker), total inkl. levering og
   poser mod ugens budget, antal varer, de 3-5 vigtigste valg kort, evt. budgetadvarsel, og
   "Skriv bestil, eller ret noget".
   Skriv KUN ét beløb, de skal betale. Den anden butik nævnes som en forskel, fx "(Bilka ville
   være ca. 360 kr dyrere)", aldrig som en total (fundet i test 4: "1.474 kr" og "1.112 kr" i
   samme besked forvirrede).

TRIN 4: BESTIL
10. "bestil" (eller "ok"/"ja") fylder kurven/kurvene og giver besked. Vent på svaret og fortæl,
    hvad der skete. Kommer der rettelser i stedet, så ret, gem en ny plan med gem_madplan (den
    gamle annulleres selv) og send den nye total.
11. Når kurven er fyldt, sender botten selv ugemenuen og et leveringsforslag (den billigste
    tid, der når planens første aftensmad, og hvornår der senest skal bestilles). Send ikke dit
    eget forslag på Telegram. Uden Telegram: slå leveringstider op og foreslå én tid efter
    reglerne i LEVERING OG STARTDAG. De vælger selv tiden og betaler i butikkens app.
12. Retter de i kurven bagefter, så ret med saet_antal_i_kurv og tjek med vis_kurv, at
    kurven er præcis, som den skal være (også at fjernede varer er væk), før du skriver, at
    det er gjort. Bed aldrig husstanden rette kurven selv. Kan noget ikke lade sig gøre, så
    sig præcis hvad og hvorfor.
13. Bestil og betal aldrig selv: vi vælger leveringstid og betaler i butikkens app.

NÅR EN RET IKKE KAN KØBES ORDENTLIGT (også efter at menuen er godkendt)
Fundet i en test: alle laks i Bilka var enten opdrættede, frosne eller kunne ikke leveres.
- Kan en rets hovedingrediens ikke købes, så den passer til profilen (ikke på lager, kan ikke
  leveres, frost/opdræt når profilen siger nej, langt over prisskønnet), så må du skifte
  RETTEN ud. Du skal ikke bare tage den næstbedste vare, der bryder profilen, og ikke lade
  dagen stå tom: der skal stadig være mad til alle de aftener, vi bad om.
- Prøv i denne rækkefølge, og tag den første, der virker:
  1. Samme ret med en anden god udgave af varen (anden størrelse eller mærke, eller den anden
     butik, hvis det samlet stadig er billigst).
  2. En ret med samme tilbehør og en anden protein, der passer til profilen og dagens tid
     (fx laks med kartofler og broccoli → svinemørbrad eller kylling med kartofler og
     broccoli). Undgå en protein, der allerede er på menuen samme uge.
  3. En helt anden ret fra vores opskriftssider til samme dag og tid.
  Hold prisen på niveau med den gamle ret, og fjern de varer, der kun var til den gamle ret.
  Der skal stadig være mad nok til alle, der spiser med: skriv aldrig "lidt stramt", men køb
  nok, eller vælg noget andet (fundet i test 4: én kylling til 4 personer).
- Sker det FØR "bestil" (under prissætningen): skift retten, prissæt den, og skriv øverst i
  prisbeskeden "Ændret: Tor laks → svinemørbrad med kartofler og broccoli (ingen vildfanget
  fersk laks i Bilka)". "bestil" godkender så også ændringen. Ingen ekstra spørgsmål.
- Sker det EFTER "bestil" (botten melder, at en vare ikke kom i kurven): find erstatningen
  efter samme rækkefølge, læg den i kurven med saet_antal_i_kurv, fjern varer der kun var til
  den gamle ret, tjek kurven med vis_kurv, og send én kort besked: hvad der er skiftet,
  hvorfor, og den nye total. Spørg kun først, hvis den nye total bliver over ugens budget,
  eller hvis husstanden selv har bedt om netop den ret.

BASISVARER ("jeg regner med, I har …" er ikke godt nok)
Gæt aldrig stille. Hver basisvare, som ugens retter og faste måltider skal bruge (æg, smør,
mælk, fløde, citron, løg, hvidløg, mel, olie, sukker, salt, peber, bouillon, sennep, ris, pasta
osv.), står i menubeskeden på én af to lister, så vi kan tjekke køleskab og skab, før der
handles, og ikke mangler noget midt i madlavningen:
  Køber til ugen: æg, kartofler, hakkede tomater, …
  Tjek, at I har: smør, mælk, citron, olivenolie, ris, …
  "Skriv 'har X' eller 'køb Y', hvis noget skal flyttes."
  KUN varenavne, ingen begrundelser i parentes (ellers bliver listen lang og uoverskuelig).
  Spørger de, hvad noget skal bruges til, så svar dem.
Sådan fordeles de (brug koebsmoenster → basisvarer_pr_type og svaret om køleskabet):
- Nævnt i svaret om køleskabet, eller i beholdningen uden `status` → ingen af listerne (vi har
  det). Har beholdningsvaren `status` "tjek: …", er den noteret før sidste indkøb og kan være
  brugt (fundet i uge 46: "kartofler 500 g" stod der stadig ugen efter). Så står den under
  Tjek, med den mængde ugen skal bruge, og regnes aldrig med.
- Svarer vi "har X" på Tjek-listen, så gem X i beholdningen (sted "skab" eller "køleskab")
  med opdater_beholdning, så status nulstilles. "Køb Y" gemmes ikke.
- Kølevare (sted "køl": æg, smør, mælk, fløde, citron …) → Køber, medmindre den er "købt for
  nylig". Så står den under Tjek. Vi regner ALDRIG med kølevarer, vi ikke har nævnt.
- Skabsvare (sted "skab": mel, olie, salt, ris …) → Tjek, medmindre den er "snart tom". Så
  står den under Køber. Er den ukendt for os, står den under Tjek (fundet i test 4: salt og
  peber blev købt, fordi de var "ukendte"). Salt, peber og tørrede krydderier køber vi kun,
  når husstanden beder om det.
- Mængden tæller: skal ugen bruge meget (fx 10 æg), så Køber, også selvom den er købt for nylig.
- Retter vi listerne, så følg det i indkøbslisten, og gem et "har altid" i profilen som et
  vareønske (fx "Salt, peber, olie: har vi altid").

FAVORITTER (vis_opskrifter = vores samling af retter, vi kan lide)
- I menuen: tag 1-2 favoritter, der passer til ugen (dage, tid, gæster, profilen), helst dem
  med ældst `sidst_brugt` (eller aldrig brugt). Ikke en, der var med de sidste 14 dage, medmindre
  vi beder om den. Hent opskriften med hent_opskrift_fra_link(link), så mængderne passer. Er
  samlingen tom, så spring det over og nævn det ikke.
- Gem ALTID et link til hver ret fra en opskriftsside med planen: gem_madplan
  valg={"opskrifter": {"Tir: Lasagne": "https://…"}}, med samme tekst som i `retter`. Når kurven
  er fyldt, sender botten selv "Ugens menu" og fastgør den øverst i Telegram, med opskriften
  bag hver rets navn (så den er nem at finde om onsdagen). Rester og egne retter får intet link.
  Skriv ikke menuen eller linkene i din egen sidste besked: det gør botten. Skriver vi "menu",
  sender botten den igen. Linkene bruges også, når en ret bliver favorit.
- Ny favorit: siger vi, at en ret var god, skal være favorit eller skal laves igen (også som svar
  på spørgsmål 4), så find retten i den seneste plan (vis_madplan, feltet `opskrifter` giver
  linket), hent ingredienserne med hent_opskrift_fra_link og gem med gem_opskrift(navn, link,
  ingredienser, personer, tags fx ["hverdag"] eller ["weekend", "gæster"]). Navnet skal være
  kort og genkendeligt, fx "Lasagne", så den kan findes i menuer. Gem kun det, vi beder om.
- "Ikke igen" om en ret: læg den i profilens undgaa som "ret: <navn>", og fjern den fra
  samlingen med fjern_opskrift, hvis den står der.
- Nævn ikke, at du har gemt en favorit, medmindre vi spørger (ligesom ØNSKER TIL FREMOVER).

ØNSKER TIL FREMOVER (gælder hele forløbet)
- Siger husstanden på nogen måde, at noget skal huskes til fremover ("husk", "fra nu af",
  "altid", "aldrig", "vi kan ikke lide …", "næste gang …", "gem det"), så gem det i profilen
  med opdater_profil i det rette felt: vareønsker (en bestemt vare), ting at undgå,
  præferencer (madstil) eller faste måltider. Gør det med det samme, uden at spørge.
- Beskeder med "gemt_i_profilen" har botten allerede lagt i profilens fra_husstanden. Flyt
  dem til det rette felt og ryd fra_husstanden i samme opdater_profil-kald. Handler et af dem
  kun om denne uge (fx "husk gæster lørdag"), så brug det i planen og gem det ikke.
- Nævn ikke for husstanden, hvad du har gemt, medmindre de spørger.
- Spørg kun, om noget skal gemmes, når en rettelse handler om smag eller en vare generelt og
  ikke står i profilen i forvejen, fx "fennikel er ikke lige os" eller "kødet var for fedt
  sidst". Spørg IKKE ved rettelser om denne uge: dage, gæster, tid, lyst, rækkefølge eller
  pris ("ikke fisk tirsdag", "byt torsdag og fredag", "noget hurtigere onsdag").
  Højst ét sådant spørgsmål pr. madplan, som én kort linje sidst i din næste besked, fx
  "Skal jeg huske, at I ikke vil have fennikel?". Ja → gem. Intet svar eller nej → gem ikke."""

FORBEREDELSE = """FORBEREDELSE (stille, uden at spørge nogen)
1. Læs vis_profil (også faste måltider, vareønsker og fra_husstanden), koebsmoenster
   (andel_af_indkoeb fra profilens note), vis_beholdning og vis_opskrifter. Har du
   garmin-værktøjerne, så tag dagsstatus og træninger 14 dage tilbage.
   Gå `beskeder_siden_sidst` (beskeder sendt mellem madplanerne) og profilens fra_husstanden
   igennem efter ØNSKER TIL FREMOVER, og ryd op i profilen, før du laver menuen.
   Tjek kurven i hver butik i `butikker` med vis_kurv. Ligger der varer fra før, så skriv det her i chatten til
   brugeren (ikke på Telegram) og spørg, om de skal tømmes. Fundet i test 4: en gammel
   Bilka-kurv kom tilbage, fordi bilkatogo.dk stod åben i browseren med den gamle kurv."""


def tekst_telegram(sendt_til: int) -> str:
    return f"""Lav vores madplan. Følg trinene i rækkefølge.

VIGTIGT: Al snak med husstanden foregår på Telegram, så de kan svare fra telefonen.
- Spørgsmålet om køleskabet og antal aftener ER ALLEREDE SENDT til {sendt_til} telefon(er).
  Stil det IKKE igen, og stil ingen spørgsmål til husstanden her i chatten.
- Brug send_besked til alt, du vil spørge eller vise dem (menu, total, "skriv bestil").
- Brug vent_paa_svar til at vente på deres svar. Får du "ingen_svar_endnu", så kald den igen,
  i op til 20 minutter pr. spørgsmål.
- AFSLUT ALDRIG midt i samtalen. Efter HVER besked til husstanden (også den sidste med
  leveringsforslaget) kalder du vent_paa_svar igen og bliver ved, til der har været 20
  minutter uden svar. Først da skriver du opsummeringen her i chatten og stopper. Ellers
  bliver deres næste svar ikke læst (fundet i demoen: "Gem i profilen" blev aldrig læst).
- Her i chatten skriver du kun korte statuslinjer til brugeren, fx "Venter på svar om køleskabet".

{FORBEREDELSE}

TRIN 1: KØLESKABET (spørgsmålet er sendt)
2. Vent på svaret med vent_paa_svar. Gem det, de har, med opdater_beholdning, og brug det antal
   aftener, de svarer.
{FAELLES}"""


def tekst_chat(aftener: str = "") -> str:
    aftener = str(aftener or "").strip()
    antal = f"{aftener} aftener" if aftener.isdigit() else "det antal aftener, husstanden svarer"
    spoerg_antal = "" if aftener.isdigit() else " Spørg samtidig, hvor mange aftener vi skal have mad til."
    return f"""Lav vores madplan for {antal}. Følg trinene i rækkefølge. Telegram er ikke sat op, så
snakken med husstanden foregår her i chatten.

{FORBEREDELSE}

TRIN 1: KØLESKABET
2. Spørg kort, hvad vi har i køleskabet, og om der er noget særligt denne uge (gæster,
   aftener ude, egne råvarer som vildt).{spoerg_antal} Gem svaret med opdater_beholdning.
{FAELLES}"""


FOERSTE_GANG = """FØRSTE GANG: LÆR HUSSTANDEN AT KENDE (profilen er tom)
Lav IKKE madplanen endnu. Tag først en kort guide her i chatten, så planen passer til jer fra
første uge. Profilen er det, der gør planerne gode, og den kan rumme alt fra budget til
"chokolade mindst 85 %".

Sådan:
- Byd kort velkommen, og sig, at det tager ca. 3 minutter, og at alt kan springes over og
  rettes senere ved bare at sige det ("husk, vi ikke spiser svampe").
- Stil spørgsmålene i 4 runder, én runde pr. besked, med 2-3 konkrete eksempler hver gang, så
  det er let at svare. Svar må gerne være korte eller indtalte.
- GEM EFTER HVER RUNDE med opdater_profil (se felterne i vis_profil), så intet går tabt.
  Skriv kravene præcist, så de kan følges: absolutte krav som "kød altid øko", ønsker som
  "økologi når det er muligt".

Runde 1, husstanden: Hvor mange er I (og børnenes alder, hvis der er børn)? Hvad må en uges mad
  koste, inkl. levering? Ved de det ikke, så foreslå et beløb ud fra antal personer (og
  koebsmoenster, hvis der er en butik med ordrer) → personer, ugebudget_kr.
Runde 2, smag: Hvad kan I lide (madstil, køkkener, max tid på hverdage)? Hvad spiser I ikke
  (allergier, intolerance, det I ikke kan lide)? Krav til økologi, kød, fisk eller kødfri dage?
  → praeferencer, undgaa.
Runde 3, det faste: Måltider, der er ens hver uge og skal med i indkøbet (morgenmad,
  madpakker, weekendfrokost), med indhold og antal dage? Bestemte varer eller mærker
  (fx "letmælk, ikke skummet", "kaffe: hele bønner")? → faste_maaltider, varepraeferencer.
Runde 4, favoritter (valgfri): Retter, I altid er glade for? Har de et link, så gem dem med
  hent_opskrift_fra_link og gem_opskrift; ellers som præference. Andet, jeg bør vide? → note.

Til sidst: vis profilen kort som punkter, sig at den kan ændres når som helst, og spørg:
"Skal jeg lave ugens madplan nu?" Ja → kald ugeplan_forloeb igen.
Er Telegram sat op, så nævn, at resten af ugeplanen foregår der.
{butikker}"""


def tekst_foerste_gang(butikker: list[str]) -> str:
    if butikker:
        b = f"Butikker med login: {', '.join(butikker)}."
    else:
        b = (
            "Der er ingen butik med login endnu. Sig til sidst kort, at priser og opskrifter fra "
            "nemlig virker uden login, men at `ugeplan-mcp login nemlig` eller `login bilka` i en "
            "terminal også fylder kurven."
        )
    return FOERSTE_GANG.format(butikker=b)


def telegram_klar() -> bool:
    try:
        telegram.hent_token()
    except telegram.TelegramFejl:
        return False
    return bool(telegram.chats())


def _beskeder_siden_sidst() -> list[dict]:
    """Ulæste beskeder fra før denne madplan. Hentes FØR spørgsmålet sendes, så de ikke blandes
    sammen med svaret om køleskabet (og ikke bliver overset)."""
    try:
        return persondata.rens(telegram.beskeder(kun_nye=True))
    except LokalFejl:
        return []


HENT_ORDRER = True  # slås fra i testene (ingen rigtige butikskald)


async def _hent_ordrer() -> None:
    """Jeres ordrer hos nemlig/Bilka tæller med i basisvarernes købsmønster. Fejler det (fx intet
    net), kører madplanen videre uden."""
    try:
        import asyncio

        from handle_mcp import butikker as butik_modul
        from handle_mcp import historik

        await asyncio.wait_for(historik.hent_butiksordrer([butik_modul.hent_butik(n) for n in login.aktive()]), 25)
    except Exception:  # noqa: BLE001
        pass


async def _hent_levering() -> dict:
    """Første mulige aftensmad pr. butik (se levering.py). Fejler en butik, er den bare ikke med."""
    import asyncio
    from datetime import datetime

    from handle_mcp import butikker as butik_modul
    from handle_mcp import levering

    async def en(navn: str) -> tuple[str, dict | None]:
        try:
            tider = await asyncio.wait_for(butik_modul.hent_butik(navn).leveringstider(5), 25)
        except Exception:  # noqa: BLE001
            return navn, None
        return navn, levering.bedste(tider, datetime.now(levering.DK))

    return {n: v for n, v in await asyncio.gather(*(en(n) for n in login.aktive())) if v}


def foer_levering(lev: dict, nu=None) -> list[dict]:
    """Aftenerne før varerne kommer, og hvad den igangværende plan siger, I skal have der.
    Julius: "vi svarer hvad vi har i køleskabet, og du tjekker selv hvad der bliver brugt. Du
    kender selv opskrifter og madplan". Claude trækker de varer fra, som de retter bruger."""
    from datetime import date, datetime

    from handle_mcp import levering, madplan

    if not lev:
        return []
    nu = nu or datetime.now(levering.DK)
    foerste = min(date.fromisoformat(v["dato"]) for v in lev.values())
    try:
        p = madplan.seneste_fyldte(14)
    except LokalFejl:
        p = None
    ud = []
    for d in levering.aftener_foer(foerste, nu):
        ret = None
        if p:
            fra = datetime.fromisoformat(p.oprettet).date()
            ret = next((r for r in p.retter if levering.ret_dato(r, fra) == d), None)
        ud.append({"dag": levering.dag_tekst(d), "ret": ret, "opskrift": madplan.link_til(p, ret) if p and ret else None})
    return ud


def foerste_spoergsmaal(lev: dict, foer: list[dict] | None = None) -> str:
    """Spørgsmålet med den første aften, varerne kan nå. De svarer bare, hvad de har; Claude
    trækker selv fra, hvad aftenerne før levering bruger (se foer_levering)."""
    if not lev:
        return FOERSTE_SPOERGSMAAL
    tidligst = min(lev.values(), key=lambda v: v["dato"])
    tekst = FOERSTE_SPOERGSMAAL.replace(
        "1) Hvad skal bruges denne uge?",
        f"Varerne kan tidligst være her til aftensmaden {tidligst['foerste_aftensmad']}.\n"
        "1) Hvad har I i køleskabet?",
    )
    ukendte = [f["dag"].split()[0] for f in foer or [] if not f["ret"]]
    if ukendte:  # ingen plan for de aftener: så kan Claude ikke selv vide, hvad der bliver brugt
        tekst = tekst.replace(
            "dem tjekker jeg med jer bagefter.",
            f"dem tjekker jeg med jer bagefter. Ved I, hvad I spiser {' og '.join(ukendte)}, så skriv det også.",
        )
    return tekst


HENT_LEVERING = True  # slås fra i testene (ingen rigtige butikskald)
FOERSTE_GANG_AKTIV = True  # slås fra i de fleste tests, som har en tom profil


async def start() -> dict:
    """Start madplanen: send det første spørgsmål på Telegram, hvis det er sat op.
    Første gang (tom profil) kører guiden i chatten i stedet, og intet sendes til Telegram."""
    from handle_mcp import profil

    try:
        if FOERSTE_GANG_AKTIV and profil.er_tom():
            return {"foerste_gang": True, "butikker": login.aktive(), "forloeb": tekst_foerste_gang(login.aktive())}
    except LokalFejl:
        pass
    try:
        beholdning.ryd_gammelt_koeleskab()  # gamle rester må ikke komme med i menuen
    except LokalFejl:
        pass
    if HENT_ORDRER:
        await _hent_ordrer()
    lev = await _hent_levering() if HENT_LEVERING else {}
    foer = foer_levering(lev)
    faelles = {"butikker": login.aktive(), "levering": lev, "foer_levering": foer}
    if telegram_klar():
        tidligere = _beskeder_siden_sidst()
        try:
            n = await telegram.send_til_alle(foerste_spoergsmaal(lev, foer))
        except telegram.TelegramFejl as fejl:
            return {"telegram": f"kunne ikke sende ({fejl})", "beskeder_siden_sidst": tidligere, **faelles, "forloeb": tekst_chat()}
        return {"telegram": f"spørgsmålet er sendt til {n} telefon(er)", "beskeder_siden_sidst": tidligere, **faelles, "forloeb": tekst_telegram(n)}
    return {"telegram": "ikke sat op", **faelles, "forloeb": tekst_chat()}

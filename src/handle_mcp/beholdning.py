"""Det I har hjemme: køleskab, fryser og skab.

I fortæller Claude, hvad der er tilbage ("to løg, en halv pakke smør"), og Claude gemmer det
her. Bagefter kan Claude lave madplan og indkøbsliste ud fra det, der mangler.

Listen ligger i beholdning.json på din egen maskine (se lokal.py). Intet sendes til butikkerne.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import NotRequired, TypedDict
from zoneinfo import ZoneInfo

from handle_mcp.lokal import LokalFejl, laes, noegle, skriv, tekst

TIDSZONE = ZoneInfo("Europe/Copenhagen")
MAKS_VARER = 300  # en grænse, så en fejl ikke kan fylde filen op

BeholdningFejl = LokalFejl  # samme fejltype som resten af den lokale lagring


@dataclass
class Beholdningsvare:
    navn: str
    maengde: str | None  # fri tekst: "2 stk", "en halv pakke", "ca. 300 g"
    sted: str | None  # fx køleskab, fryser, skab
    noteret: str  # hvornår den sidst blev opdateret (ISO-tid)
    status: str | None = None  # regnes ud ved hver læsning (se _med_status), gemmes ikke


class NyVare(TypedDict):
    navn: str
    maengde: NotRequired[str]
    sted: NotRequired[str]


TJEK = "tjek: noteret før sidste indkøb ({kode}), kan være brugt. Sæt den på 'Tjek, at I har'."


def _raa() -> list[Beholdningsvare]:
    return [Beholdningsvare(**{k: v for k, v in d.items() if k != "status"}) for d in laes("beholdning").get("varer", [])]


def _sidste_indkoeb() -> tuple[str, str] | None:
    """(tid, kode) for den nyeste plan, hvis kurv er fyldt."""
    from handle_mcp import madplan

    try:
        fyldte = [p for p in madplan._alle() if p.status == "kurv fyldt"]
    except LokalFejl:
        return None
    if not fyldte:
        return None
    p = fyldte[-1]
    # Tidspunktet, kurven blev fyldt (fx "2026-11-08T17:25+01:00 kurv fyldt …"). Alt noteret før
    # det hørte til den uge, også det, der blev sagt i samme minut, som planen blev lavet (mandler).
    fyldt = next((h.split(" ", 1)[0] for h in reversed(p.historik or []) if "kurv fyldt" in h), None)
    return (fyldt or p.oprettet, p.kode)


def _foer(a: str | None, b: str) -> bool:
    try:
        return bool(a) and datetime.fromisoformat(a) < datetime.fromisoformat(b)
    except (TypeError, ValueError):  # ugyldig eller blandet tid: regn ikke varen for gammel
        return False


def _med_status(varer: list[Beholdningsvare]) -> list[Beholdningsvare]:
    """Skabsvarer, der er noteret før sidste fyldte kurv, kan være brugt af den uges retter.
    Julius, uge 46: "er den skudsikker?" Nej: "kartofler 500 g" fra 8/11 stod der stadig ugen
    efter, og Claude ville have regnet med dem. Nu skal de tjekkes, ikke regnes med."""
    sidste = _sidste_indkoeb()
    for v in varer:
        gammel = sidste and (v.sted or "").lower().startswith("skab") and _foer(v.noteret, sidste[0])
        v.status = TJEK.format(kode=sidste[1]) if gammel else None
    return varer


def hent() -> list[Beholdningsvare]:
    return _med_status(_raa())


def opdater(
    tilfoej: list[NyVare] | None = None, fjern: list[str] | None = None, erstat_alt: bool = False
) -> tuple[list[Beholdningsvare], list[str]]:
    """Tilføj/ret varer og fjern brugte. Giver (ny beholdning, navne der ikke fandtes)."""
    nu = datetime.now(TIDSZONE).isoformat(timespec="minutes")
    varer = {} if erstat_alt else {noegle(v.navn): v for v in _raa()}
    ukendte = []
    for navn in fjern or []:
        if varer.pop(noegle(str(navn)), None) is None:
            ukendte.append(str(navn))
    for ny in tilfoej or []:
        navn = tekst(ny.get("navn"), "navn")
        if not navn:
            raise BeholdningFejl("Hver vare skal have et navn.")
        varer[noegle(navn)] = Beholdningsvare(navn, tekst(ny.get("maengde"), "maengde"), tekst(ny.get("sted"), "sted"), nu)
    if len(varer) > MAKS_VARER:
        raise BeholdningFejl(f"Højst {MAKS_VARER} varer i beholdningen.")
    resultat = sorted(varer.values(), key=lambda v: ((v.sted or "~").lower(), v.navn.lower()))
    skriv("beholdning", {"varer": [{k: x for k, x in asdict(v).items() if k != "status"} for v in resultat]})
    return _med_status(resultat), ukendte


FRISK_DAGE = 7  # rester og friske varer i køleskabet holder ikke længere


def ryd_gammelt_koeleskab(dage: int = FRISK_DAGE) -> list[str]:
    """Fjern køleskabsvarer, der er noteret for mere end `dage` siden. Fundet i test 3: en
    tærterest fra en tidligere uge blev ved med at stå i beholdningen og kom med i menuen."""
    graense = datetime.now(TIDSZONE).timestamp() - dage * 86400
    gamle = [
        v.navn
        for v in hent()
        if (v.sted or "").lower().startswith("køl") and v.noteret and datetime.fromisoformat(v.noteret).timestamp() < graense
    ]
    if gamle:
        opdater(fjern=gamle)
    return gamle

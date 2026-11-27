"""Bilen direkte fra Telegram, uden AI'en:

  bil                      status
  klar 7 / klar 07:30 90%  klar-tid næste morgen (kun denne gang), evt. med ladeniveau
  klar normal              tilbage til fast tid
  klar 5/12 5:30 100%      planlagt undtagelse en bestemt dato (kalenderen)
  undtagelser              de næste planlagte undtagelser
  lad til 90 [i nat]       ladeniveau hver nat, eller kun i nat
  forvarm nu               klimaanlægget nu
  forvarmning til/fra      automatisk forvarmning
  forvarm under 5          temperaturgrænsen for automatikken
  oplad nu / stop opladning

Fortolkningen er bevidst streng: kun hele, korte beskeder i præcis de former. Alt andet går
videre som i dag (fri tekst til `claude -p` eller AI-assistenten).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from handle_mcp import ha

STATUS = {"bil", "bilen", "status", "status bil", "bil status", "bilstatus", "status på bilen"}
NORMAL = {"klar normal", "klar normalt", "fjern undtagelse", "fjern undtagelsen", "klar fast tid", "bil normal"}
OPLAD = {"oplad nu", "lad nu", "start opladning", "start opladning nu", "oplad bilen nu", "lad bilen nu"}
STOP = {"stop opladning", "stop opladningen", "stop ladning", "stop laderen", "stop oplad"}
UNDTAGELSER = {"undtagelser", "planlagte undtagelser", "kommende undtagelser", "vis undtagelser", "bil undtagelser"}
FORVARM = {"forvarm", "forvarm nu", "forvarm bilen", "forvarm bilen nu", "varm bilen op", "varm bilen op nu"}
AUTO_TIL = {"forvarmning til", "automatisk forvarmning til", "slå forvarmning til", "slå automatisk forvarmning til"}
AUTO_FRA = {"forvarmning fra", "automatisk forvarmning fra", "slå forvarmning fra", "slå automatisk forvarmning fra"}

# "slet undtagelsen", "fjern undtagelsen igen", "slet undtagelsen i morgen": helt sikkert bilen
# (fundet 27/11: beholdningens "slet …" tog dem). Med en dato er det ikke sikkert -> claude -p.
SLET_UNDTAGELSE = re.compile(r"^(?:slet|fjern)\s+(?:den\s+|min\s+)?undtagelse(?:n)?(?:\s+(?:igen|i\s+morgen|i\s+nat|til\s+i\s+morgen))*$")

_TID = r"(?:kl\.?\s*)?(\d{1,2})(?:[.:](\d{2}))?"
_PCT = r"(?:\s+(?:lad(?:et)?\s+(?:op\s+)?til\s+)?(\d{2,3})\s*%)?"
KLAR = re.compile(rf"^(?:bil(?:en)?\s+)?(?:skal\s+være\s+)?klar\s+{_TID}{_PCT}$")
DATO = re.compile(rf"^(?:bil(?:en)?\s+)?(?:klar|undtagelse)\s+(?:den\s+)?(\d{{1,2}})[/.](\d{{1,2}})(?:[/.](\d{{2}}|\d{{4}}))?\s+{_TID}{_PCT}$")
LAD = re.compile(r"^(?:lad|oplad)(?:\s+bilen)?\s+(?:op\s+)?til\s+(\d{2,3})\s*%?(\s+i\s+nat)?$")
FORVARM_UNDER = re.compile(r"^(?:automatisk\s+)?forvarm(?:ning)?\s+under\s+(-?\d{1,2})\s*(?:°\s*c?|grader)?$")


@dataclass
class Handling:
    # "status", "klar", "planlaeg", "undtagelser", "lad", "forvarm", "auto_forvarm",
    # "forvarm_under", "oplad", "stop" eller "forbrug"
    hvad: str
    tid: time | None = None
    pct: int | None = None
    dato: date | None = None
    kun_i_nat: bool = False
    til: bool = True
    grader: int | None = None
    periode: str | None = None  # forbrug: None = tabellen, ellers ha.forbrug_svar
    etiket: str = ""


def _rens(tekst: str) -> str:
    return " ".join(tekst.lower().strip(" ?!.").split())


def _tid(timer: str, minutter: str | None) -> time | None:
    t, m = int(timer), int(minutter or 0)
    if t > 23 or m > 59 or (t == 0 and m == 0):
        return None
    return time(t, m)


def _dato(dag: str, maaned: str, aar: str | None, i_dag: date) -> date | None:
    try:
        if aar:
            return date(int(aar) + (2000 if len(aar) == 2 else 0), int(maaned), int(dag))
        d = date(i_dag.year, int(maaned), int(dag))
        return d if d >= i_dag else date(i_dag.year + 1, int(maaned), int(dag))  # "5/1" i december: næste år
    except ValueError:
        return None


# Forbrug: bredt, for ingen kan huske kommandoer (Julius 27/11). Uden periode: tabellen. Med en
# periode, der kan slås sikkert op: én sætning om netop den. Ellers claude -p med samtalen.
# Fundet 27/11 21.10: "Hvad kostede det at lade i nat" fik hele tabellen.
FORBRUG_ORD = re.compile(r"\b(?:forbrug\w*|co2|co₂|kwh|strømforbrug\w*|(?:op)?ladet for)\b")
PRIS_ORD = re.compile(r"\b(?:kost\w*|pris\w*|betal\w*|regning\w*|billig\w*|dyr\w*|udgift\w*)\b")
LAD_ORD = re.compile(r"\b(?:lad\w*|oplad\w*|bil(?:en|ens)?|elbil\w*|strøm\w*)\b")
MAANEDER = ("januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december")
CLAUDE = "claude"  # en periode, genvejen ikke kan slå sikkert op

# (mønster, periode, etiket); første, der passer, vinder. Etiket None = sæt selv.
PERIODER = (
    (r"\b(?:sidste|seneste|forrige) opladning\b", "sidste", "Ved sidste opladning"),
    (r"\b(?:seneste|sidste) (?:24 timer|24 t|døgn)\b", "24t", "De seneste 24 timer"),
    (r"\b(?:seneste|sidste) (?:7|syv) dage\b", "7dage", "De seneste 7 dage"),
    (r"\b(?:i alt|nogensinde|altid|totalt?)\b", "i_alt", "I alt"),
    (r"\b(?:i nat|i morges|natten)\b", "nat", None),
    (r"\bi dag\b", "i_dag", "I dag"),
    (r"\bi går\b", "i_gaar", "I går"),
    (r"\b(?:denne|den her|indeværende) måned\b", "maaned", "Denne måned"),
    (r"\b(?:sidste|forrige) måned\b", "sidste_maaned", "Sidste måned"),
    (r"\bi år\b", "aar", "I år"),
    (r"\b(?:sidste år|i fjor|sidste\s+\w+\s+år)\b", "sidste_aar", None),
    (r"\b(?:uge\w*|weekend\w*|i forgårs|i aftes|i aften|i morgen|i eftermiddag|i formiddag|i weekenden|\d{1,2}[/.]\d{1,2})\b", CLAUDE, None),
    (r"\bnu\b", "nu", None),
)


def forbrug_periode(t: str, nu: datetime) -> tuple[str | None, str] | None:
    """(periode, etiket) for en forbrugsbesked; (None, "") = ingen periode (tabellen).
    None = ikke en forbrugsbesked, eller en periode der skal til claude -p."""
    if len(t) > 80 or not (FORBRUG_ORD.search(t) or (PRIS_ORD.search(t) and LAD_ORD.search(t))):
        return None
    if m := re.search(r"\b(20\d{2})\b", t):
        aar = int(m.group(1))
        if aar < ha.FORBRUG_START.year:
            return "aeldre", ""
        if aar != nu.year or not re.search(r"\bi\s+20\d{2}\b", t):
            return None
        return "aar", f"I {aar}"
    for i, navn in enumerate(MAANEDER, start=1):
        if re.search(rf"\b{navn}\b", t):
            start = date(nu.year if i <= nu.month else nu.year - 1, i, 1)  # seneste gang, det var den måned
            if i == nu.month:
                return "maaned", f"I {navn}"
            forrige = (nu.date().replace(day=1) - timedelta(days=1)).replace(day=1)
            if start == forrige:
                return "sidste_maaned", f"I {navn}"
            return ("aeldre", "") if start < ha.FORBRUG_START.replace(day=1) else None
    for moenster, periode, etiket in PERIODER:
        if re.search(moenster, t):
            if periode == CLAUDE:
                return None
            if periode == "sidste_aar":
                return ("aeldre", "") if nu.year - 1 < ha.FORBRUG_START.year else None
            if periode == "nat":
                if not 6 <= nu.hour < 18:
                    return None  # om aftenen/natten er "i nat" ikke sikker: claude -p
                return "nat", "I morges" if "morges" in t else "I nat"
            return periode, etiket or ""
    return None, ""


def fortolk(tekst: str, i_dag: date | None = None, nu: datetime | None = None) -> Handling | None:
    t = _rens(tekst)
    nu = nu or (datetime.combine(i_dag, time(12), ha.TIDSZONE) if i_dag else datetime.now(ha.TIDSZONE))
    i_dag = nu.date()
    if t not in OPLAD and (FORBRUG_ORD.search(t) or (PRIS_ORD.search(t) and LAD_ORD.search(t))) and len(t) <= 80:
        fp = forbrug_periode(t, nu)  # None: om forbrug, men ikke sikkert -> claude -p
        return Handling("forbrug", periode=fp[0], etiket=fp[1]) if fp else None
    if len(t) > 40:
        return None
    for saet, hvad in ((STATUS, "status"), (NORMAL, "klar"), (OPLAD, "oplad"), (STOP, "stop"), (UNDTAGELSER, "undtagelser"), (FORVARM, "forvarm")):
        if t in saet:
            return Handling(hvad)
    if SLET_UNDTAGELSE.match(t):
        return Handling("klar")
    if t in AUTO_TIL or t in AUTO_FRA:
        return Handling("auto_forvarm", til=t in AUTO_TIL)
    if m := DATO.match(t):
        d = _dato(m.group(1), m.group(2), m.group(3), i_dag or datetime.now(ha.TIDSZONE).date())
        tid = _tid(m.group(4), m.group(5))
        if d and tid:
            return Handling("planlaeg", tid=tid, dato=d, pct=int(m.group(6)) if m.group(6) else None)
        return None
    if m := KLAR.match(t):
        tid = _tid(m.group(1), m.group(2))
        return Handling("klar", tid=tid, pct=int(m.group(3)) if m.group(3) else None) if tid else None
    if m := LAD.match(t):
        return Handling("lad", pct=int(m.group(1)), kun_i_nat=bool(m.group(2)))
    if m := FORVARM_UNDER.match(t):
        return Handling("forvarm_under", grader=int(m.group(1)))
    return None


# --- samtalen: handler en tvetydig besked om bilen? ----------------------------------------
# Julius 27/11: "et menneske havde alle dage forstået hvad 'slet undtagelsen igen' betød".
# Faste kommandoer tager kun det, der er helt sikkert. Nævner beskeden bilen, eller er den kort og
# tvetydig ("slet den igen", "nej, kl. 9 i stedet") lige efter en snak om bilen, går den uden om
# beholdningen til claude -p, som får de seneste beskeder med.

BIL_ORD = re.compile(
    r"\b(?:undtagelse\w*|bil(?:en|ens)?|opladning\w*|oplad\w*|lade\w*|lader\w*|ladning\w*|afgang\w*"
    r"|kalender\w*|forvarm\w*|klar(?:-?tid\w*)?|batteri\w*|elbil\w*|forbrug\w*|co2|kwh|elpris\w*)\b"
)
TVETYDIG = re.compile(r"\b(?:den|det|dem|igen|i stedet|ja|nej|ok|okay|hellere|alligevel|også)\b")
SAMTALE_MIN = 30  # så længe efter en snak om bilen gælder den som emnet
SAMTALE_BESKEDER = 4


def om_bilen(tekst: str, historik: list[dict], nu: datetime | None = None) -> bool:
    """Handler beskeden (sandsynligvis) om bilen, uden at være en sikker fast kommando?"""
    t = _rens(tekst)
    if BIL_ORD.search(t):
        return True
    if len(t) > 60 or not TVETYDIG.search(t):
        return False
    nu = nu or datetime.now(ha.TIDSZONE)
    for b in historik[-SAMTALE_BESKEDER:]:
        try:
            tid = datetime.fromisoformat(str(b.get("tid")))
        except ValueError:
            continue
        if nu - tid <= timedelta(minutes=SAMTALE_MIN) and BIL_ORD.search(str(b.get("tekst", "")).lower()):
            return True
    return False


async def udfoer(h: Handling) -> str:
    """Giver svaret til husstanden. Fejl siges kort, uden detaljer om tokenet."""
    try:
        if h.hvad == "forbrug":
            if h.periode is None:
                return (await ha.forbrug()).tekst()
            return await ha.forbrug_svar(h.periode, h.etiket)
        if h.hvad == "status":
            return (await ha.status()).tekst()
        if h.hvad == "klar":
            return await ha.saet_klar(h.tid, pct=h.pct)
        if h.hvad == "planlaeg":
            return await ha.planlaeg(h.dato, h.tid, h.pct)  # type: ignore[arg-type]
        if h.hvad == "undtagelser":
            return await ha.undtagelser()
        if h.hvad == "lad":
            return await ha.lad_til(h.pct, h.kun_i_nat)  # type: ignore[arg-type]
        if h.hvad == "forvarm":
            return await ha.forvarm()
        if h.hvad == "auto_forvarm":
            return await ha.auto_forvarmning(h.til)
        if h.hvad == "forvarm_under":
            return await ha.forvarm_under(h.grader)  # type: ignore[arg-type]
        return await ha.oplad(start=h.hvad == "oplad")
    except ha.HAFejl as fejl:
        return f"Det lykkedes ikke: {fejl}"

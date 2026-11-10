"""Beholdningen direkte fra Telegram, uden AI'en: "har 2 kg kartofler", "skudt et rådyr, ligger i
fryseren", "fjern mælk" og "fortryd".

Julius, uge 46: "Det er svært at huske søndag, at man lige fik skudt noget siden sidst." Og:
husstanden skal sige, hvad der ER, ikke holde styr på, hvad der er brugt (det regner AI'en selv
ud fra planen, og Tjek-listen fanger resten). "fjern" findes, men er aldrig nødvendig.

Fortolkningen er bevidst forsigtig: kun korte beskeder, der begynder med et af de faste ord.
Alt andet bliver gemt til AI'en som i dag, så intet går tabt, hvis botten ikke forstår det.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from handle_mcp import beholdning
from handle_mcp.lokal import laes, noegle, skriv

MAKS_TEGN = 160  # længere beskeder er svar på madplanen, ikke en hurtig besked om beholdningen

FYLD = r"(?:lige|netop|også|nu|i dag|i går)"
TILFOEJ = re.compile(
    rf"^(?:(?:vi|jeg)\s+)?(?:tilføj|læg|har|skudt|købt|fået|fanget)(?:\s+{FYLD})*(?:\s+(?:skudt|købt|fået|fanget|lagt))?(?:\s+{FYLD})*\s+(.+)$",
    re.I | re.S,
)
FJERN = re.compile(r"^(?:fjern|slet)\s+(.+)$", re.I | re.S)
BRUGT = re.compile(r"^(.+?)\s+(?:er|blev)\s+(?:brugt|spist|opbrugt|væk|sluppet op)(?:\s+op)?$", re.I | re.S)
FORTRYD = {"fortryd", "fortryd det", "fortryd sidste"}
PRONOMENER = {"du", "i", "vi", "jeg", "han", "hun", "man", "de", "den", "det", "nogen", "noget"}
NEGATION = re.compile(r"\b(?:ikke|ingen|intet|aldrig|altid|husk)\b", re.I)  # "husk/altid" er profilønsker

STEDER = (("fryser", "fryser"), ("køleskab", "køleskab"), ("køl", "køleskab"), ("skab", "skab"))
STED_FRASE = re.compile(r",?\s*(?:og\s+)?(?:der |som |de |den |det )?(?:ligger |er |står )?(?:lagt |sat )?i\s+(fryseren|fryser|køleskabet|køleskab|skabet|skab)\b", re.I)
TAL = r"(?:\d+(?:[.,]\d+)?|½|en halv|et halvt|en|et|to|tre|fire|fem|seks)"
ENHED = r"(?:kg|g|gram|l|liter|dl|stk|pakker|pakke|poser|pose|bakker|bakke|dåser|dåse|glas|bundter|bundt)"
MAENGDE = re.compile(rf"^({TAL}(?:\s*{ENHED})?)\s+(.+)$", re.I)
UDEN_MAENGDE = {"en", "et"}
BESTEMT = ("erne", "ene", "en", "et", "ne", "n", "t")


@dataclass
class Handling:
    tilfoej: list[beholdning.NyVare] = field(default_factory=list)
    fjern: list[str] = field(default_factory=list)
    fortryd: bool = False


def _sted(tekst: str, navn: str) -> str | None:
    """Stedet fra beskeden ("i fryseren"), ellers fra varetypen (mælk er køl, mel er skab)."""
    if m := STED_FRASE.search(tekst):
        ord_ = m.group(1).lower()
        return next(sted for start, sted in STEDER if ord_.startswith(start))
    from handle_mcp import historik

    if typ := historik.basistype(navn):
        return "køleskab" if historik.BASISTYPER[typ][0] == "køl" else historik.BASISTYPER[typ][0]
    return None


def _varer(tekst: str) -> list[tuple[str, str | None]]:
    """'2 kg kartofler og et rådyr' -> [('kartofler', '2 kg'), ('rådyr', None)]."""
    tekst = STED_FRASE.sub("", tekst).strip(" .!,")
    ud = []
    for del_ in re.split(r",|\bog\b|\+", tekst):
        del_ = del_.strip(" .!")
        if not del_:
            continue
        maengde = None
        if m := MAENGDE.match(del_):
            maengde, del_ = m.group(1), m.group(2).strip()
            if maengde.lower() in UDEN_MAENGDE:
                maengde = None
        if del_:
            ud.append((del_, maengde))
    return ud


def fortolk(tekst: str) -> Handling | None:
    """Beskeden som en ændring af beholdningen, eller None hvis den ikke tydeligt er det."""
    t = " ".join((tekst or "").split())
    if not t or len(t) > MAKS_TEGN or "?" in t:
        return None
    if t.lower().strip(" .!") in FORTRYD:
        return Handling(fortryd=True)
    if NEGATION.search(t):  # "vi har ikke mere mælk" er ikke en vare, der hedder "ikke mere mælk"
        return None
    for regex in (FJERN, BRUGT):
        if m := regex.match(t.rstrip(" .!")):
            navne = [n for n, _ in _varer(m.group(1))]
            return Handling(fjern=navne) if navne else None
    if m := TILFOEJ.match(t):
        varer = _varer(m.group(1))
        if not varer or any(len(n.split()) > 4 for n, _ in varer):  # en hel sætning, ikke varer
            return None
        if any(n.split()[0].lower() in PRONOMENER for n, _ in varer):  # "har du set …" er et spørgsmål
            return None
        ny = []
        for navn, maengde in varer:
            v: beholdning.NyVare = {"navn": navn}
            if maengde:
                v["maengde"] = maengde
            if sted := _sted(t, navn):
                v["sted"] = sted
            ny.append(v)
        return Handling(tilfoej=ny)
    return None


def _find(navn: str, varer: list[beholdning.Beholdningsvare]) -> beholdning.Beholdningsvare | None:
    """'mælken' finder 'mælk', 'rådyret' finder 'rådyr'."""
    k = noegle(navn)
    for v in varer:
        kv = noegle(v.navn)
        if k == kv or (k.startswith(kv) and k[len(kv):] in BESTEMT):
            return v
    return None


def udfoer(h: Handling) -> str:
    """Ændr beholdningen og giv svaret til Telegram. Gemmer, hvad der skal til for at fortryde."""
    if h.fortryd:
        return _fortryd()
    foer = {noegle(v.navn): v for v in beholdning.hent()}
    fjernes = [v for n in h.fjern if (v := _find(n, list(foer.values())))]
    ikke_fundet = [n for n in h.fjern if not _find(n, list(foer.values()))]
    beholdning.opdater(tilfoej=h.tilfoej, fjern=[v.navn for v in fjernes])
    skriv(
        "beholdning-fortryd",
        {
            "tilfoejet": [n["navn"] for n in h.tilfoej],
            "gammel": [{"navn": v.navn, "maengde": v.maengde, "sted": v.sted} for v in fjernes]
            + [{"navn": o.navn, "maengde": o.maengde, "sted": o.sted} for n in h.tilfoej if (o := foer.get(noegle(n["navn"])))],
        },
    )
    dele = []
    if h.tilfoej:
        dele.append("Lagt i beholdningen: " + ", ".join(_vis(v) for v in h.tilfoej) + ".")
    if fjernes:
        dele.append("Fjernet: " + ", ".join(v.navn for v in fjernes) + ".")
    if ikke_fundet:
        dele.append("Fandt ikke: " + ", ".join(ikke_fundet) + ".")
    if h.tilfoej or fjernes:
        dele.append("Skriv fortryd, hvis det var forkert.")
    return " ".join(dele)


def _vis(v: beholdning.NyVare) -> str:
    tekst = v["navn"] + (f" {v['maengde']}" if v.get("maengde") else "")
    return tekst + (f" ({v['sted']})" if v.get("sted") else "")


def _fortryd() -> str:
    sidst = laes("beholdning-fortryd")
    if not sidst.get("tilfoejet") and not sidst.get("gammel"):
        return "Der er ikke noget at fortryde."
    beholdning.opdater(fjern=sidst.get("tilfoejet") or [])
    if gammel := [{k: x for k, x in v.items() if x} for v in sidst.get("gammel") or []]:
        beholdning.opdater(tilfoej=gammel)
    skriv("beholdning-fortryd", {})
    return "Fortrudt. Beholdningen er som før."

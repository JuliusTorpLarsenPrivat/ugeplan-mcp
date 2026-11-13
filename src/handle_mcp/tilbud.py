"""Tilbud først: før menuen laves, henter koden ugens tilbud i butikkerne og sorterer dem efter
det, husstanden faktisk køber: fisk, fugl, kød og de faste varer (fx morgenmad). Ud fra det
foreslås ugens butik, og menuen bygges på de bedste tilbud dér.

Julius, 12/11: "Giver det ikke mere økonomisk mening at starte med de bedste tilbud på dyre
varer og bagefter lave madplanen ud fra opskrifter med de varer?" Og: det er træls at bygge en
ret på et tilbud, man alligevel ikke får, fordi den anden butik vinder. Derfor vælges ugens
butik FØR menuen, og menuen bygges kun på tilbud i den butik.

Ugens tilbud på fisk, fugl og kød gemmes også (tilbud_historik.json), så det efter et par
måneder kan ses, hvor tit der er gode tilbud. Ingen AI her: kun opslag og regler.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from handle_mcp import historik, profil
from handle_mcp.data import Vare
from handle_mcp.lokal import LokalFejl, laes, skriv
from handle_mcp.maengde import maengdetilbud

TIDSZONE = ZoneInfo("Europe/Copenhagen")
ANKRE_PR_BUTIK = 6
MAKS_HISTORIK = 60  # uger x butikker
FUGL = ("KYLLING", "KALKUN", "ANDEBRYST", "ANDELÅR", "ANDESTEG", "HEL AND", "GÅS", "GÅSE", "HØNS", "PERLEHØNE", "POUSSIN")
FASTE_STOPORD = {
    "hver", "dag", "pers", "med", "og", "kun", "lørdag", "søndag", "hjemme", "frokost", "morgenmad", "aftensmad", "hverdage",
    "spiser", "arbejdet", "mørk", "meget", "mindst", "blandet", "yoghurt", "altid", "ellers",
}  # "yoghurt" står som "græsk yoghurt" og matches som ord nedenfor; "blandet" fangede saft (fundet live)
FORARBEJDET = ("bouillon", "fond", "pålæg", "postej", "salat", "spread", "nuggets", "frikadelle", "panere", "marineret", "personer", "færdigret", "pålægs")
SMAG = ("vanilje", "jordbær", "banan", "passion", "skovbær", "fersken", "hindbær", "blåbær", "kirsebær", "citron", "kokos", "karamel", "mango", "pære")
KOED_I_FRYSER = ("vildt", "okse", "kød", "hjort", "rådyr", "dådyr", "lam", "gris", "svin", "kalv")


def besparelse(v: Vare) -> tuple[Decimal, int] | None:
    """(kr sparet pr. stk, procent) for et tilbud, eller None. Mængdetilbud regnes pr. stk."""
    if v.foer_pris and v.foer_pris > v.pris:
        spar = v.foer_pris - v.pris
        return spar, round(spar / v.foer_pris * 100)
    if (mt := maengdetilbud(v.tilbud)) and mt[1] < v.pris * mt[0]:
        spar = v.pris - mt[1] / mt[0]
        return spar, round(spar / v.pris * 100)
    return None


def faste_ord(p: profil.Profil | None = None) -> set[str]:
    """Varer fra de faste måltider og vareønskerne: "græsk yoghurt med vindruer, mandler og mørk
    chokolade" giver yoghurt, vindruer, mandler, chokolade."""
    p = p or profil.hent()
    tekst = " ".join(m.split(":", 1)[-1] for m in p.faste_maaltider if ":" in m)
    return {o for o in re.findall(r"[a-zæøå]{4,}", tekst.lower()) if o not in FASTE_STOPORD} | ({"yoghurt"} if "yoghurt" in tekst.lower() else set())


def _ord(navn: str) -> list[str]:
    return re.findall(r"[a-zæøå]+", navn.lower())


def _passer_faste(navn: str, faste: set[str]) -> str | None:
    """Ordet matcher et helt ord eller slutningen af et sammensat ord ("pålægschokolade"), men
    ikke starten ("græskarkerner" er ikke græsk). Fundet live."""
    for o in _ord(navn):
        for w in faste:
            if o == w or (len(w) >= 5 and o.endswith(w)):
                return w
    return None


def minimum_pct(p: profil.Profil) -> dict[str, int]:
    """Vareønsker som "Mørk chokolade: meget mørk, mindst 85 %" → {"chokolade": 85}."""
    ud = {}
    for v in p.varepraeferencer:
        if ":" in v and (m := re.search(r"mindst\s*(\d+)\s*%", v)) and (ord_ := _ord(v.split(":", 1)[0])):
            ud[ord_[-1]] = int(m.group(1))
    return ud


def koed_i_fryseren() -> bool:
    """Har vi kød i fryseren (eget vildt, en kvart ko)? Så skal kødtilbud ikke afgøre butikken."""
    from handle_mcp import beholdning

    try:
        for x in beholdning.hent():
            ord_ = _ord(x.navn)
            if (x.sted or "").lower().startswith("fryser") and ("ko" in ord_ or any(k in o for k in KOED_I_FRYSER for o in ord_)):
                return True  # "råvildt kølle", "kvart ko", "hakket okse"
        return False
    except LokalFejl:
        return False


def gruppe(v: Vare, faste: set[str]) -> str | None:
    """fisk, fugl, kød, faste eller None (ikke noget, ugen bygges på)."""
    kat = historik.kategori(v.navn)
    if kat == "fisk":
        return "fisk"
    if kat == "kød":
        navn = v.navn.upper()
        return "fugl" if any(f in navn for f in FUGL) else "kød"
    if _passer_faste(v.navn, faste):
        return "faste"
    return None


def _er_frost(v: Vare) -> bool:
    return "frost" in f"{v.navn} {v.maengde or ''}".lower()


def _er_oeko(v: Vare) -> bool:
    return "øko" in f"{v.navn} {v.maengde or ''} {v.maerke or ''}".lower()


def advarsler(v: Vare, grp: str, p: profil.Profil) -> list[str]:
    """Hvorfor et tilbud måske ikke passer til profilen. AI'en afgør det; koden siger det bare."""
    krav = " ".join(p.praeferencer + p.undgaa).lower()
    ud = []
    if grp in ("fisk", "kød", "fugl") and _er_frost(v) and "frost" in krav:
        ud.append("frost")
    if grp in ("kød", "fugl") and "øko" in krav and "kød" in krav and not _er_oeko(v):
        ud.append("ikke øko")
    if grp == "fisk" and "opdræt" in krav and "laks" in v.navn.lower() and "vild" not in v.navn.lower():
        ud.append("laks er tit opdrættet")
    tekst = f"{v.navn} {v.maengde or ''}".lower()
    if grp in ("fisk", "kød", "fugl") and any(f in tekst for f in FORARBEJDET):
        ud.append("forarbejdet")  # fundet live: "Citron kylling, 2 personer" og kyllingebouillon talte som fugl
    if grp == "faste" and any(sm in _ord(v.navn) or any(o.startswith(sm) for o in _ord(v.navn)) for sm in SMAG):
        ud.append("smagsvariant")  # fundet live: skyr med vanilje og passion
    if grp == "faste" and "fedtprocent" in " ".join(p.varepraeferencer).lower():
        fedt = [float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:fedt)?", tekst) if float(x.replace(",", ".")) < 50]
        if fedt and max(fedt) < 2:
            ud.append("mager")  # "højest mulige fedtprocent": 0,2 % skyr er ikke det, vi køber
    if grp == "faste" and (w := _passer_faste(v.navn, faste_ord(p))) and (mindst := minimum_pct(p).get(w)):
        procenter = [int(x) for x in re.findall(r"(\d+)\s*%", f"{v.navn} {v.maengde or ''}")]
        if not procenter or max(procenter) < mindst:
            ud.append(f"under {mindst} %")
    return ud


def oversigt(tilbud_pr_butik: dict[str, list[Vare]], p: profil.Profil | None = None) -> dict:
    """De bedste tilbud pr. butik, der passer til profilen, og et forslag til ugens butik."""
    p = p or profil.hent()
    faste = faste_ord(p)
    fryser_kød = koed_i_fryseren()
    ud: dict = {"butikker": {}, **({"note": "Der er kød i fryseren: kødtilbud tæller ikke med i valget af ugens butik."} if fryser_kød else {})}
    for butik, varer in tilbud_pr_butik.items():
        ankre = []
        for v in varer:
            if not (grp := gruppe(v, faste)) or not (sp := besparelse(v)) or advarsler(v, grp, p):
                continue
            ankre.append(
                {"gruppe": grp, "navn": v.navn, "maengde": v.maengde, "pris": float(v.pris), "tilbud": v.tilbud, "spar_kr": float(round(sp[0], 2)), "spar_pct": sp[1], "id": v.id}
            )
        # Fisk, fugl og faste varer først; kød sidst, når fryseren har kød (eget vildt, kvart ko)
        ankre.sort(key=lambda a: (fryser_kød and a["gruppe"] == "kød", -a["spar_kr"]))
        bedste = ankre[:ANKRE_PR_BUTIK]
        taeller = [a for a in bedste if not (fryser_kød and a["gruppe"] == "kød")]
        ud["butikker"][butik] = {"ankre": bedste, "sum_spar_kr": round(sum(a["spar_kr"] for a in taeller), 2)}
    if ud["butikker"]:
        vinder = max(ud["butikker"], key=lambda b: ud["butikker"][b]["sum_spar_kr"])
        ud["ugens_butik"] = vinder if ud["butikker"][vinder]["sum_spar_kr"] > 0 else None
    return ud


def gem_historik(tilbud_pr_butik: dict[str, list[Vare]], nu: datetime | None = None) -> None:
    """Ugens tilbud på fisk, fugl og kød, til at se mønstre over tid. Kun det, ugen bygges på."""
    nu = nu or datetime.now(TIDSZONE)
    try:
        uger = laes("tilbud_historik").get("uger", [])
        for butik, varer in tilbud_pr_butik.items():
            rel = []
            for v in varer:
                grp = gruppe(v, set())
                if grp in ("fisk", "fugl", "kød") and (sp := besparelse(v)):
                    rel.append({"gruppe": grp, "navn": v.navn, "maengde": v.maengde, "pris": float(v.pris), "spar_pct": sp[1], "oeko": _er_oeko(v), "frost": _er_frost(v)})
            uger.append({"dato": nu.date().isoformat(), "butik": butik, "varer": rel})
        skriv("tilbud_historik", {"uger": uger[-MAKS_HISTORIK:]})
    except LokalFejl:
        pass


async def hent(butikker: list[str]) -> dict:
    """Hent ugens tilbud i butikkerne (højst 30 sek. pr. butik), gem dem, og giv oversigten."""
    from handle_mcp import butikker as butik_modul

    async def en(navn: str) -> tuple[str, list[Vare]]:
        try:
            return navn, await asyncio.wait_for(butik_modul.hent_butik(navn).tilbud(200), 30)
        except Exception:  # noqa: BLE001  tilbud er en bonus: planen kører videre uden
            return navn, []

    tilbud_pr_butik = dict(await asyncio.gather(*(en(b) for b in butikker)))
    tilbud_pr_butik = {b: v for b, v in tilbud_pr_butik.items() if v}
    if not tilbud_pr_butik:
        return {}
    gem_historik(tilbud_pr_butik)
    return oversigt(tilbud_pr_butik)

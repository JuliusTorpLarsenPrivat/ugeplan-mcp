"""Hvornår kan varerne komme, og fra hvilken aften gælder madplanen?

Julius (7/11): "man står søndag kl. 12 og forklarer hvad man har i køleskabet (der ligger jo mad
til resten af søndag)". Planen skal starte ved den første aftensmad EFTER levering, og dagene
før klarer husstanden sig med det, de har. I en test skrev Claude "første levering er mandag,
så jeg starter dagen efter", men varer, der kommer mandag formiddag, rækker til mandag aften.

Reglerne (slået op 7/11):
- nemlig: levering kl. 7-14 skal bestilles senest kl. 14 dagen før, kl. 15-22 senest kl. 24
  aftenen før. Butikken giver fristen pr. tid.
- Bilka: natlevering kl. 20-06 ("natten til mandag") skal bestilles senest kl. 15 dagen før.
  Fristen står som tekst ("i morgen kl. 15:00", "på mandag kl. 15:00").
- Kun hjemlevering. Bilka-kurven stopper allerede, hvis den står til afhentning.

Alt her er rene funktioner af (tider, nu), så de kan testes med alle tænkelige tidspunkter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from handle_mcp.data import Leveringstid

DK = ZoneInfo("Europe/Copenhagen")
AFTENSMAD = time(17, 0)  # varerne skal være der senest kl. 17, før der laves mad
SPIST_KL = time(19, 0)  # efter kl. 19 er dagens aftensmad overstået
MARGIN_START = timedelta(minutes=90)  # tid til menu, rettelser og "bestil" fra madplanen starter
MARGIN_BETAL = timedelta(minutes=15)  # tid til at betale, når kurven er fyldt
UKENDT_FRIST_FORSPRING = timedelta(hours=36)  # uden kendt frist: kun tider langt nok ude

UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
FORKORT = {d[:3]: i for i, d in enumerate(UGEDAGE)}  # "man", "tir", ... "lør", "søn"
AFHENTNING = re.compile(r"afhent|pick.?up|click|collect", re.I)


def _dk(t: datetime) -> datetime:
    return t.astimezone(DK) if t.tzinfo else t.replace(tzinfo=DK)


# --- fristen ----------------------------------------------------------------------


def frist_fra_tekst(tekst: str | None, nu: datetime) -> datetime | None:
    """Bilkas frist: "i dag kl. 15:00", "i morgen kl. 15:00", "på mandag kl. 15:00" eller
    "12/11 kl. 15:00". Regnes fra `nu` (tidspunktet, svaret blev hentet). Ukendt: None."""
    if not tekst:
        return None
    t = tekst.lower().replace("�", "å")  # Bilka sender til tider "p�" for "på"
    kl = re.search(r"(\d{1,2})[:.](\d{2})", t)
    if not kl:
        return None
    h, m = int(kl.group(1)), int(kl.group(2))
    if h > 23 or m > 59:
        return None
    nu = _dk(nu)
    dag: date | None = None
    if dato := re.search(r"(\d{1,2})/(\d{1,2})", t):
        d, md = int(dato.group(1)), int(dato.group(2))
        for aar in (nu.year, nu.year + 1):
            try:
                kandidat = date(aar, md, d)
            except ValueError:
                return None
            if kandidat >= nu.date() - timedelta(days=1):
                dag = kandidat
                break
    elif "overmorgen" in t:
        dag = nu.date() + timedelta(days=2)
    elif "i morgen" in t or "imorgen" in t:
        dag = nu.date() + timedelta(days=1)
    elif "i dag" in t or "idag" in t:
        dag = nu.date()
    else:
        for i, navn in enumerate(UGEDAGE):
            if re.search(rf"\b{navn}\b", t) or (navn == "lørdag" and "lordag" in t) or (navn == "søndag" and "sondag" in t):
                frem = (i - nu.weekday()) % 7
                dag = nu.date() + timedelta(days=frem)
                if frem == 0 and time(h, m) <= nu.time():
                    dag += timedelta(days=7)  # "på lørdag" sagt lørdag efter fristen = næste lørdag
                break
    if dag is None:
        return None
    return datetime.combine(dag, time(h, m), DK)


# --- første aftensmad -----------------------------------------------------------------


def foerste_aftensmad(t: Leveringstid) -> date:
    """Den første aften, varerne er der til aftensmaden. Senest kl. 17 = samme dag. Natlevering
    (slut kl. 6) = samme dag som slut."""
    slut = _dk(t.slut)
    return slut.date() if slut.time() <= AFTENSMAD else slut.date() + timedelta(days=1)


def er_hjemlevering(t: Leveringstid) -> bool:
    return not AFHENTNING.search(f"{t.type or ''} {t.note or ''}")


def kan_naas(t: Leveringstid, nu: datetime, margin: timedelta) -> bool:
    """Ledig hjemlevering, hvis frist ikke er overskredet, når husstanden har nået at godkende."""
    if not t.ledig or not er_hjemlevering(t):
        return False
    nu = _dk(nu)
    if t.frist is None:
        return _dk(t.start) - nu >= UKENDT_FRIST_FORSPRING
    return _dk(t.frist) - margin >= nu


def _rang(t: Leveringstid) -> tuple:
    pris = float(t.pris) if t.pris is not None else 9999.0
    frist = -_dk(t.frist).timestamp() if t.frist else 0.0
    return (pris, frist)  # billigst, og ved samme pris den med senest frist


# --- tekster ---------------------------------------------------------------------


def dag_tekst(d: date) -> str:
    return f"{UGEDAGE[d.weekday()]} {d.day}/{d.month}"


def kl_tekst(t: datetime) -> str:
    t = _dk(t)
    return f"{t.hour}" if t.minute == 0 else f"{t.hour}:{t.minute:02d}"


def levering_tekst(t: Leveringstid) -> str:
    start, slut = _dk(t.start), _dk(t.slut)
    if slut.time() <= time(6, 0) and (start.time() == time(0, 0) or start.date() < slut.date()):
        return f"natten til {dag_tekst(slut.date())} (kl. 20-{kl_tekst(slut)})"
    return f"{dag_tekst(start.date())} kl. {kl_tekst(start)}-{kl_tekst(slut)}"


def frist_tekst(t: Leveringstid) -> str:
    if t.frist is None:
        return "fristen kan ikke ses, tjek den i appen"
    f = _dk(t.frist)
    if f.time() == time(0, 0):  # "senest 10/11 kl. 00:00" = mandag aften kl. 24
        f -= timedelta(minutes=1)
        return f"{dag_tekst(f.date())} kl. 24"
    return f"{dag_tekst(f.date())} kl. {kl_tekst(f)}"


def valg_dict(t: Leveringstid) -> dict:
    return {
        "butik": t.butik,
        "foerste_aftensmad": dag_tekst(foerste_aftensmad(t)),
        "dato": foerste_aftensmad(t).isoformat(),
        "levering": levering_tekst(t),
        "bestil_senest": frist_tekst(t),
        "pris_kr": float(t.pris) if t.pris is not None else None,
    }


# --- valg -----------------------------------------------------------------------


def bedste(tider: list[Leveringstid], nu: datetime, margin: timedelta = MARGIN_START) -> dict | None:
    """Den tidligste aftensmad, varerne kan nå, og den billigste tid, der giver den. Plus en
    reserve med senere frist til samme aften, hvis den billige frist er tæt på."""
    mulige = [t for t in tider if kan_naas(t, nu, margin)]
    if not mulige:
        return None
    dag = min(foerste_aftensmad(t) for t in mulige)
    samme = sorted((t for t in mulige if foerste_aftensmad(t) == dag), key=_rang)
    valgt = samme[0]
    ud = valg_dict(valgt)
    senere = [t for t in samme if t.frist and valgt.frist and _dk(t.frist) > _dk(valgt.frist)]
    if senere:
        reserve = max(senere, key=lambda t: (_dk(t.frist), -_rang(t)[0]))
        ud["naas_fristen_ikke"] = valg_dict(reserve)
    ud["klarer_jer_selv"] = [UGEDAGE[d.weekday()] for d in aftener_foer(dag, nu)]
    return ud


def aftener_foer(dag: date, nu: datetime) -> list[date]:
    """Aftener fra nu og frem til (ikke med) `dag`, som husstanden selv klarer."""
    nu = _dk(nu)
    d = nu.date() if nu.time() < SPIST_KL else nu.date() + timedelta(days=1)
    ud = []
    while d < dag:
        ud.append(d)
        d += timedelta(days=1)
    return ud


def til_plan(tider: list[Leveringstid], nu: datetime, start: date | None, margin: timedelta = MARGIN_BETAL) -> dict | None:
    """Forslag, når kurven er fyldt: den billigste tid, der når planens første aftensmad, og
    helst ikke dage før (frisk fisk skal ikke ligge i køleskabet i tre dage). Kan ingen tid nå
    den, så den tidligste mulige med en advarsel."""
    mulige = [t for t in tider if kan_naas(t, nu, margin)]
    if not mulige:
        return None
    if start is not None:
        i_tide = [t for t in mulige if foerste_aftensmad(t) <= start]
        if i_tide:
            seneste_dag = max(foerste_aftensmad(t) for t in i_tide)
            valgt = min((t for t in i_tide if foerste_aftensmad(t) == seneste_dag), key=_rang)
            return valg_dict(valgt)
    b = bedste(mulige, nu, margin)
    if b is not None and start is not None:
        b["for_sent"] = f"Varerne kan tidligst være der til aftensmaden {b['foerste_aftensmad']}, men planen starter {dag_tekst(start)}."
    return b


# --- planens første dag ------------------------------------------------------------


def planens_start(retter: list[str], fra: date) -> date | None:
    """Første aften i planen ud fra "Tir: …", "Tir 10/11: …" eller "Fre 13/11 (4 pers.): …".
    Ugedage regnes fra `fra` (dagen planen blev lavet) og frem."""
    dage = [d for ret in retter if (d := ret_dato(ret, fra))]
    return min(dage) if dage else None


def ret_dato(ret: str, fra: date) -> date | None:
    """Datoen for én ret: "Tir 10/11: …" giver 10/11, "Tir: …" den første tirsdag fra `fra`."""
    hoved = ret.split(":", 1)[0].strip().lower() if ":" in ret else ret.strip().lower()[:12]
    if dato := re.search(r"\b(\d{1,2})/(\d{1,2})\b", hoved):
        d, md = int(dato.group(1)), int(dato.group(2))
        for aar in (fra.year, fra.year + 1):
            try:
                kandidat = date(aar, md, d)
            except ValueError:
                return None
            if kandidat >= fra - timedelta(days=1):
                return kandidat
        return None
    if m := re.match(r"(man|tir|ons|tor|fre|lør|lor|søn|son)", hoved):
        nr = FORKORT.get(m.group(1).replace("lor", "lør").replace("son", "søn"))
        if nr is not None:
            return fra + timedelta(days=(nr - fra.weekday()) % 7)
    return None


def forslag_tekst(f: dict) -> str:
    """Én kort linje til Telegram."""
    pris = f" ({f['pris_kr']:.0f} kr)" if f.get("pris_kr") is not None else ""
    linje = f"Levering hos {f['butik']}: {f['levering']}{pris}. Bestil senest {f['bestil_senest']}."
    if f.get("for_sent"):
        linje = f"Obs: {f['for_sent']}\n" + linje
    return linje

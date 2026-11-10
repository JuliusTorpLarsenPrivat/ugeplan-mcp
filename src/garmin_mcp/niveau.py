"""Dagens belastning for én person: rolig, normal, hård eller meget hård.

Niveauet er personligt. Det sammenlignes med personens egne seneste 28 dage, så en hård
dag for en 30-årig jæger og for en 67-årig, der har gravet have hele dagen, begge kan
blive "hård". Kulde kan uret ikke måle direkte, men en hel dag ude giver mange aktive
kalorier og skridt, også uden en startet aktivitet.

Regler (median = personens median over de seneste 28 dage, hvor uret var på;
BMR = personens hvilestofskifte, som Garmin beregner ud fra alder, vægt og køn):
- meget hård: aktive kalorier ≥ 3 × median eller ≥ 30 % af BMR,
              eller en aktivitet på mindst 4 timer
- hård:       aktive kalorier ≥ 2 × median eller ≥ 20 % af BMR, skridt ≥ 2 × median,
              en aktivitet ≥ 30 min med aerob effekt ≥ 2,0, eller en aktivitet ≥ 2 timer

BMR-grænsen sørger for, at en dag med mange ekstra kalorier tæller, selv om de seneste
uger også var aktive (fx midt i jagtsæsonen).
- rolig:      aktive kalorier ≤ 0,5 × median (aldrig for i dag, for dagen er ikke slut)
- normal:     ellers
- ukendt:     uret var ikke på, og der er ingen aktivitet

Med under 7 dage i grundlaget bruges kun reglerne om aktiviteter.
Kun get_-kald. Intet gemmes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from garmin_mcp import sundhed

ROLIG, NORMAL, HAARD, MEGET_HAARD, UKENDT = "rolig", "normal", "hård", "meget hård", "ukendt"
NIVEAUER = (ROLIG, NORMAL, HAARD, MEGET_HAARD)
GRUNDLAG_DAGE = 28
MIN_GRUNDLAG = 7
# Gulve, så en næsten stillesiddende uge ikke gør en kort gåtur til en hård dag.
MIN_KALORIER = 100
MIN_SKRIDT = 3000


def _aktivitet(a: dict[str, Any]) -> dict[str, Any]:
    start = a.get("startTimeLocal")
    sek = a.get("duration") if isinstance(a.get("duration"), (int, float)) else 0
    slut = None
    if start:
        try:
            slut = (datetime.fromisoformat(start) + timedelta(seconds=sek)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            slut = None
    aerob = a.get("aerobicTrainingEffect")
    return {
        "start": start[:16] if start else None,
        "slut": slut,
        "type": (a.get("activityType") or {}).get("typeKey"),
        "varighed_min": round(sek / 60),
        "aerob_effekt": round(aerob, 1) if isinstance(aerob, (int, float)) else None,
    }


def _baaret(kal: float | None, skridt: int | None) -> bool:
    return bool(kal) or bool(skridt)


def _vurder(kal, skridt, aktiviteter, med_kal, med_skridt, bmr, foreloebig) -> tuple[str, str]:
    lange = [a for a in aktiviteter if a["varighed_min"] >= 240]
    if lange:
        return MEGET_HAARD, f"{lange[0]['type']} i {lange[0]['varighed_min']} min"
    if med_kal and kal is not None and kal >= 3 * med_kal:
        return MEGET_HAARD, f"aktive kalorier {kal / med_kal:.1f} × normal"
    if bmr and kal is not None and kal >= 0.3 * bmr:
        return MEGET_HAARD, f"aktive kalorier {kal / bmr:.0%} af hvilestofskiftet"
    for a in aktiviteter:
        if a["varighed_min"] >= 120:
            return HAARD, f"{a['type']} i {a['varighed_min']} min"
        if a["varighed_min"] >= 30 and (a["aerob_effekt"] or 0) >= 2.0:
            return HAARD, f"{a['type']} med aerob effekt {a['aerob_effekt']}"
    if med_kal and kal is not None and kal >= 2 * med_kal:
        return HAARD, f"aktive kalorier {kal / med_kal:.1f} × normal"
    if bmr and kal is not None and kal >= 0.2 * bmr:
        return HAARD, f"aktive kalorier {kal / bmr:.0%} af hvilestofskiftet"
    if med_skridt and skridt is not None and skridt >= 2 * med_skridt:
        return HAARD, f"skridt {skridt / med_skridt:.1f} × normal"
    if not foreloebig and med_kal and kal is not None and kal <= 0.5 * med_kal:
        return ROLIG, f"aktive kalorier {kal / med_kal:.1f} × normal"
    return NORMAL, ""


def beregn_periode(g: Any, dage: list[date]) -> list[dict[str, Any]]:
    """Niveau for hver dag i `dage` (sammenhængende, stigende). 3 kald til Garmin i alt."""
    fra, til = dage[0], dage[-1]
    start = fra - timedelta(days=GRUNDLAG_DAGE)
    skridt = {r.get("calendarDate"): r.get("totalSteps") for r in g.get_daily_steps(start.isoformat(), til.isoformat()) or []}
    kalorier = g.get_calories_daily(start.isoformat(), til.isoformat()) or []
    kal = {r.get("calendarDate"): r.get("active") for r in kalorier}
    hvile = [r.get("resting") for r in kalorier if isinstance(r.get("resting"), (int, float)) and r.get("resting") > 0]
    bmr = median(hvile) if hvile else None
    akt: dict[str, list[dict[str, Any]]] = {}
    for a in g.get_activities_by_date(fra.isoformat(), til.isoformat(), sortorder="asc") or []:
        akt.setdefault((a.get("startTimeLocal") or "")[:10], []).append(_aktivitet(a))

    i_dag = sundhed.i_dag()
    ud = []
    for dag in dage:
        grundlag = [dag - timedelta(days=i) for i in range(1, GRUNDLAG_DAGE + 1)]
        baaret = [d.isoformat() for d in grundlag if _baaret(kal.get(d.isoformat()), skridt.get(d.isoformat()))]
        med_kal = med_skridt = None
        if len(baaret) >= MIN_GRUNDLAG:
            med_kal = max(median(kal.get(d) or 0 for d in baaret), MIN_KALORIER)
            med_skridt = max(median(skridt.get(d) or 0 for d in baaret), MIN_SKRIDT)
        d = dag.isoformat()
        k, s, aktiviteter = kal.get(d), skridt.get(d), akt.get(d, [])
        foreloebig = dag >= i_dag
        if not _baaret(k, s) and not aktiviteter:
            niveau, aarsag = UKENDT, "uret var ikke på"
        else:
            niveau, aarsag = _vurder(k, s, aktiviteter, med_kal, med_skridt, bmr, foreloebig)
        ud.append(
            {
                "dato": d,
                "niveau": niveau,
                "aarsag": aarsag or None,
                "foreloebig": foreloebig,
                "aktive_kalorier": k,
                "skridt": s,
                "normal_aktive_kalorier": round(med_kal) if med_kal else None,
                "normal_skridt": round(med_skridt) if med_skridt else None,
                "hvilestofskifte": round(bmr) if bmr else None,
                "grundlag_dage": len(baaret),
                "aktiviteter": aktiviteter,
            }
        )
    return ud

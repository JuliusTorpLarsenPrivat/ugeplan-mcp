"""Henter sundhedsdata fra Garmin og skærer dem ned til det, en madplan har brug for.

Garmins svar er store (hundredvis af felter). Her vælger vi de få tal, der betyder noget,
og giver dem danske navne og almindelige enheder (timer, km, kg). Funktionerne tager en
Garmin-klient `g` som første argument, så testene kan give en falsk klient i stedet.

Intet gemmes: data hentes, formes og sendes videre til Claude.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TIDSZONE = ZoneInfo("Europe/Copenhagen")
MAKS_DAGE = 31


class DatoFejl(ValueError):
    pass


# ---------- datoer ----------


def i_dag() -> date:
    return datetime.now(TIDSZONE).date()


def dato(tekst: str | None) -> date:
    """'i dag', 'i går', 'i forgårs' eller ÅÅÅÅ-MM-DD."""
    t = (tekst or "i dag").strip().lower().replace(" ", "")
    relativ = {"idag": 0, "today": 0, "igår": 1, "igaar": 1, "yesterday": 1, "iforgårs": 2, "iforgaars": 2}
    if t in relativ:
        return i_dag() - timedelta(days=relativ[t])
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise DatoFejl(f"Ukendt dato '{tekst}'. Brug ÅÅÅÅ-MM-DD, 'i dag' eller 'i går'.") from None


def periode(fra: str | None, til: str | None) -> list[date]:
    """Alle dage fra og med `fra` til og med `til` (højst 31 dage)."""
    start = dato(fra)
    slut = dato(til) if til else start
    if slut < start:
        raise DatoFejl("til_dato ligger før fra_dato.")
    antal = (slut - start).days + 1
    if antal > MAKS_DAGE:
        raise DatoFejl(f"Perioden er {antal} dage. Højst {MAKS_DAGE} dage ad gangen.")
    return [start + timedelta(days=i) for i in range(antal)]


# ---------- små hjælpere ----------


def _timer(sekunder: Any) -> float | None:
    return round(sekunder / 3600, 2) if isinstance(sekunder, (int, float)) else None


def _klokken(ms: Any) -> str | None:
    """Garmins 'lokale' tidsstempler er millisekunder, hvor uret allerede er lokal tid."""
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _km(meter: Any) -> float | None:
    return round(meter / 1000, 2) if isinstance(meter, (int, float)) else None


def _kg(gram: Any) -> float | None:
    return round(gram / 1000, 1) if isinstance(gram, (int, float)) else None


def _uden_tomme(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ---------- søvn ----------


def soevn_dag(g: Any, dag: date) -> dict[str, Any]:
    """Søvnen, der sluttede om morgenen på `dag` (Garmin knytter natten til dagen, du vågnede)."""
    d = g.get_sleep_data(dag.isoformat()) or {}
    s = d.get("dailySleepDTO") or {}
    if not s.get("sleepTimeSeconds"):
        return {"dato": dag.isoformat(), "ingen_data": True}
    samlet = ((s.get("sleepScores") or {}).get("overall")) or {}
    return _uden_tomme(
        {
            "dato": dag.isoformat(),
            "sovet_timer": _timer(s.get("sleepTimeSeconds")),
            "dyb_timer": _timer(s.get("deepSleepSeconds")),
            "let_timer": _timer(s.get("lightSleepSeconds")),
            "rem_timer": _timer(s.get("remSleepSeconds")),
            "vaagen_timer": _timer(s.get("awakeSleepSeconds")),
            "faldt_i_soevn": _klokken(s.get("sleepStartTimestampLocal")),
            "vaagnede": _klokken(s.get("sleepEndTimestampLocal")),
            "soevnscore": samlet.get("value"),
            "soevnkvalitet": samlet.get("qualifierKey"),
            "stress_i_natten": s.get("avgSleepStress"),
            "hvilepuls": d.get("restingHeartRate"),
            "hrv_nat_ms": d.get("avgOvernightHrv"),
            "hrv_status": d.get("hrvStatus"),
            "body_battery_genopladet": d.get("bodyBatteryChange"),
        }
    )


# ---------- dagstal (skridt, kalorier, hvilepuls) ----------


def dagstal(g: Any, dag: date) -> dict[str, Any]:
    """Dagens samlede tal. For i dag er tallene 'indtil nu'."""
    from garminconnect import GarminConnectConnectionError

    try:
        s = g.get_stats(dag.isoformat()) or {}
    except GarminConnectConnectionError:
        # Garmin svarer tomt for dage uden data (fx før uret blev taget i brug).
        return {"dato": dag.isoformat(), "ingen_data": True}
    if not any(s.get(k) is not None for k in ("totalSteps", "totalKilocalories", "restingHeartRate")):
        return {"dato": dag.isoformat(), "ingen_data": True}
    return _uden_tomme(
        {
            "dato": dag.isoformat(),
            "skridt": s.get("totalSteps"),
            "skridtmaal": s.get("dailyStepGoal"),
            "distance_km": _km(s.get("totalDistanceMeters")),
            "kalorier_i_alt": s.get("totalKilocalories"),
            "kalorier_aktive": s.get("activeKilocalories"),
            "kalorier_hvile": s.get("bmrKilocalories"),
            "hvilepuls": s.get("restingHeartRate"),
            "hvilepuls_7_dage_gns": s.get("lastSevenDaysAvgRestingHeartRate"),
            "intensitetsminutter_moderat": s.get("moderateIntensityMinutes"),
            "intensitetsminutter_hoej": s.get("vigorousIntensityMinutes"),
            "stress_gns": s.get("averageStressLevel"),
            "body_battery_nu": s.get("bodyBatteryMostRecentValue"),
            "body_battery_hoejest": s.get("bodyBatteryHighestValue"),
            "body_battery_lavest": s.get("bodyBatteryLowestValue"),
        }
    )


SKRIDT = ("skridt", "skridtmaal", "distance_km", "intensitetsminutter_moderat", "intensitetsminutter_hoej")
KALORIER = ("kalorier_i_alt", "kalorier_aktive", "kalorier_hvile")
HVILEPULS = ("hvilepuls", "hvilepuls_7_dage_gns")


def udvalg(g: Any, dage: list[date], felter: tuple[str, ...]) -> list[dict[str, Any]]:
    ud = []
    for dag in dage:
        tal = dagstal(g, dag)
        ud.append({k: v for k, v in tal.items() if k in felter or k in ("dato", "ingen_data")})
    return ud


# ---------- træninger ----------


def traeninger(g: Any, fra: date, til: date) -> list[dict[str, Any]]:
    aktiviteter = g.get_activities_by_date(fra.isoformat(), til.isoformat(), sortorder="asc") or []
    ud = []
    for a in aktiviteter:
        varighed = a.get("duration")
        ud.append(
            _uden_tomme(
                {
                    "start": a.get("startTimeLocal"),
                    "navn": a.get("activityName"),
                    "type": (a.get("activityType") or {}).get("typeKey"),
                    "varighed_min": round(varighed / 60) if isinstance(varighed, (int, float)) else None,
                    "distance_km": _km(a.get("distance")) or None,
                    "kalorier": a.get("calories"),
                    "puls_gns": a.get("averageHR"),
                    "puls_max": a.get("maxHR"),
                    "traeningseffekt_aerob": a.get("aerobicTrainingEffect"),
                    "traeningseffekt_anaerob": a.get("anaerobicTrainingEffect"),
                    "traeningsbelastning": a.get("activityTrainingLoad"),
                }
            )
        )
    return ud


# ---------- vægt ----------


def vaegt(g: Any, fra: date, til: date) -> list[dict[str, Any]]:
    d = g.get_body_composition(fra.isoformat(), til.isoformat()) or {}
    ud = []
    for m in d.get("dateWeightList") or []:
        ud.append(
            _uden_tomme(
                {
                    "dato": m.get("calendarDate"),
                    "vaegt_kg": _kg(m.get("weight")),
                    "fedtprocent": m.get("bodyFat"),
                    "muskelmasse_kg": _kg(m.get("muscleMass")),
                    "bmi": round(m["bmi"], 1) if isinstance(m.get("bmi"), (int, float)) else None,
                }
            )
        )
    return ud


# ---------- dagsstatus ----------


def dagsstatus(g: Any, dag: date) -> dict[str, Any]:
    """Kort overblik til en madplan: nattens søvn, dagens tal og træning i går og i dag."""
    i_gaar = dag - timedelta(days=1)
    status: dict[str, Any] = {
        "dato": dag.isoformat(),
        "soevn_i_nat": soevn_dag(g, dag),
        "dagen": dagstal(g, dag),
        "traeninger_i_gaar_og_i_dag": traeninger(g, i_gaar, dag),
    }
    if dag == i_dag():
        status["note"] = "Dagens skridt og kalorier er indtil nu, ikke for hele dagen."
    return status

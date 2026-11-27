"""Bilen i Home Assistant: status, klar-tid, ladeniveau, planlagte undtagelser, forvarmning og
"oplad nu" fra Telegram og fra `claude -p`.

Julius, 26/11-2026: "så man kan skrive derinde at den skal x, y og z, og få status for det ene
og det andet data". 27/11-2026: "Ja, udvid den" (ladeniveau, kalender og forvarmning).
Home Assistant styrer laderen via OCPP og EV Smart Charging. Her laves kun disse ting, og kun på
de enheder, der står nedenfor (SKRIV):

  - status: læser klar-tid, planlagt opladning, batteri, elpris og laderen
  - klar-tid: sætter engangstiden `input_datetime.bilen_skal_vaere_klar_kl` og slår
    `input_boolean.undtagelse_i_nat` til (eller fra for ugedagens faste tid). Automatiseringen i
    Home Assistant sætter selv EV Smart Chargings sluttid ud fra dem og slår undtagelsen fra kl. 12.
  - ladeniveau: `input_number.lad_op_til` (hver nat) og `input_number.lad_op_til_i_nat` (når
    undtagelsen er til). `input_number.bil_mal_i_nat` skriver automatiseringen; den læses kun.
  - planlagt undtagelse: en heldagsbegivenhed "HH:MM PCT%" i kalenderen `calendar.bil_afgang`.
    Slet kan REST ikke (kun websocket), så det gøres på dashboardet.
  - forvarmning: `input_boolean.forvarm_bilen_nu` til (Mac-scriptet slukker selv), automatikken
    til/fra og temperaturgrænsen `input_number.forvarm_under`.
  - oplad nu / stop: trykker på EV Smart Chargings knapper for manuel start og stop
Rækkefølgen for tid og % (i nat → kalender → fast ugedag/standard) klarer automatiseringen.

Intet andet i Home Assistant kan ændres herfra (se også vagt.py, der kun tillader netop disse
adresser). Adressen ligger i home_assistant.json i datamappen, tokenet i nøgleringen.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
import keyring
import keyring.errors

from handle_mcp import lokal
from handle_mcp.login import TJENESTE
from handle_mcp.vagt import VagtFejl, ny_klient

TIDSZONE = ZoneInfo("Europe/Copenhagen")
FIL = "home_assistant"
NOEGLE_NAVN = "home-assistant"
STANDARD_URL = "http://192.168.128.2:8123"  # Mac mini'ens interne kort til VM'en
TIMEOUT_SEK = 15

KLAR = "input_datetime.bilen_skal_vaere_klar_kl"
UNDTAGELSE = "input_boolean.undtagelse_i_nat"
FASTE = tuple(f"input_datetime.bil_klar_{d}" for d in ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lordag", "sondag"))
SLUTTID = "select.ev_smart_charging_charge_completion_time"
LADNING = "sensor.ev_smart_charging_charging"
TILKOBLET = "switch.ev_smart_charging_ev_connected"
BATTERI = "sensor.i3s_120_battery_ev_displayed_state_of_charge"
ELPRIS = "sensor.energi_data_service"
LADER = "sensor.lader_status_connector"
START = "button.ev_smart_charging_manually_start_charging"
STOP = "button.ev_smart_charging_manually_stop_charging"
LAD_STANDARD = "input_number.lad_op_til"
LAD_I_NAT = "input_number.lad_op_til_i_nat"
MAAL_I_NAT = "input_number.bil_mal_i_nat"
KALENDER = "calendar.bil_afgang"
KOMMENDE = "input_text.bil_kommende_undtagelser"
FORVARM_NU = "input_boolean.forvarm_bilen_nu"
AUTO_FORVARM = "input_boolean.automatisk_forvarmning"
FORVARM_UNDER = "input_number.forvarm_under"
UDE = "sensor.stue_stue_outside_temperature"

LAESER = (
    KLAR, UNDTAGELSE, *FASTE, SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER,
    LAD_STANDARD, LAD_I_NAT, MAAL_I_NAT, KOMMENDE, AUTO_FORVARM, FORVARM_UNDER, UDE,
)  # fmt: skip
KNAPPER = (START, STOP)
# Det eneste, der kan ændres herfra: service -> de enheder, den må bruges på. Se også vagt.HA_STIER.
SKRIV = {
    "input_datetime/set_datetime": {KLAR},
    "input_boolean/turn_on": {UNDTAGELSE, FORVARM_NU, AUTO_FORVARM},
    "input_boolean/turn_off": {UNDTAGELSE, AUTO_FORVARM},
    "input_number/set_value": {LAD_STANDARD, LAD_I_NAT, FORVARM_UNDER},
    "calendar/create_event": {KALENDER},
    "button/press": set(KNAPPER),
}
LAD_MIN, LAD_MAX = 50, 100  # som hjælperne i Home Assistant (trin på 5)
FORVARM_MIN, FORVARM_MAX = -10, 20

_transport: httpx.AsyncBaseTransport | None = None  # kun til test


class HAFejl(Exception):
    pass


# --- opsætning ---------------------------------------------------------------------


def url() -> str:
    try:
        return str(lokal.laes(FIL).get("url") or STANDARD_URL).rstrip("/")
    except lokal.LokalFejl:
        return STANDARD_URL


def vaert() -> str:
    return httpx.URL(url()).host


def hent_token() -> str:
    try:
        token = keyring.get_password(TJENESTE, NOEGLE_NAVN)
    except keyring.errors.KeyringError:
        token = None
    if not token:
        raise HAFejl("Home Assistant er ikke sat op. Kør i en terminal: ugeplan-mcp ha-opsaet")
    return token


TOKEN_FORMAT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def gem(token: str, adresse: str | None = None) -> None:
    if not TOKEN_FORMAT.fullmatch(token.strip()):
        raise HAFejl("Det ligner ikke et langtidstoken fra Home Assistant (begynder med eyJ…).")
    keyring.set_password(TJENESTE, NOEGLE_NAVN, token.strip())
    if adresse:
        lokal.skriv(FIL, {"url": adresse.rstrip("/")})


def slet() -> None:
    try:
        keyring.delete_password(TJENESTE, NOEGLE_NAVN)
    except keyring.errors.KeyringError:
        pass


def sat_op() -> bool:
    try:
        hent_token()
    except HAFejl:
        return False
    return True


# --- REST ---------------------------------------------------------------------------


def _rens(tekst: str, token: str) -> str:
    return tekst.replace(token, "<token>") if token else tekst


async def _kald(metode: str, sti: str, data: dict | None = None) -> object:
    token = hent_token()
    try:
        async with ny_klient(timeout=TIMEOUT_SEK, transport=_transport) as klient:
            # Ingen gentagelser her (som vagt.send gør): et tryk på "start" må kun sendes én gang.
            svar = await klient.request(metode, url() + sti, json=data, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise HAFejl("Home Assistant svarede ikke inden for 15 sekunder.") from None
    except (httpx.HTTPError, VagtFejl) as fejl:
        raise HAFejl(f"Kunne ikke nå Home Assistant: {_rens(str(fejl), token)}") from None
    if svar.status_code == 401:
        raise HAFejl("Home Assistant afviste tokenet. Lav et nyt og kør: ugeplan-mcp ha-opsaet")
    if svar.status_code >= 400:
        raise HAFejl(f"Home Assistant svarede {svar.status_code}.")
    try:
        return svar.json()
    except ValueError:
        return None


async def tilstand(entitet: str) -> dict:
    if entitet not in LAESER:
        raise HAFejl(f"{entitet} må ikke læses herfra.")
    try:
        return await _kald("GET", f"/api/states/{entitet}")  # type: ignore[return-value]
    except HAFejl as fejl:
        if "404" in str(fejl):
            return {"entity_id": entitet, "state": "unavailable", "attributes": {}}
        raise


async def _service(service: str, entitet: str, **data: object) -> None:
    if entitet not in SKRIV.get(service, ()):
        raise HAFejl(f"{service} på {entitet} må ikke bruges herfra.")
    await _kald("POST", f"/api/services/{service}", {"entity_id": entitet, **data})


async def _tryk(knap: str) -> None:
    if knap not in KNAPPER:
        raise HAFejl(f"{knap} må ikke trykkes herfra.")
    await _service("button/press", knap)


async def _begivenheder(fra: date, til: date) -> list[dict]:
    """Heldagsbegivenhederne i bilens kalender fra og med `fra` til (ikke med) `til`."""
    sti = f"/api/calendars/{KALENDER}?" + urlencode({"start": f"{fra.isoformat()}T00:00:00", "end": f"{til.isoformat()}T00:00:00"})
    try:
        svar = await _kald("GET", sti)
    except HAFejl as fejl:
        if "404" in str(fejl):
            return []
        raise
    return [b for b in (svar or []) if isinstance(b, dict)]  # type: ignore[union-attr]


BEGIVENHED = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s+(\d{2,3})\s*%)?")


def _paa_dato(begivenheder: list[dict], dag: date) -> dict | None:
    for b in begivenheder:
        if str((b.get("start") or {}).get("date", "")) == dag.isoformat() and BEGIVENHED.match(str(b.get("summary", ""))):
            return b
    return None


# --- handlingerne ----------------------------------------------------------------------


DAGE = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")
INGEN_KOMMENDE = "Ingen planlagte undtagelser"


def _hhmm(t: str) -> str:
    """'06:15:00' -> '06.15'."""
    return t[:5].replace(":", ".")


def naeste_morgen(nu: datetime) -> datetime:
    """Samme regel som automatiseringen: efter kl. 12 gælder tiderne i morgen."""
    return nu + timedelta(days=1) if nu.hour >= 12 else nu


def _tid(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(TIDSZONE).strftime("%H.%M")
    except ValueError:
        return None


def _tal(t: object) -> float | None:
    try:
        return float(t)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _pct(v: float | None) -> str:
    return f"{v:.0f} %" if v is not None else "?"


def dato_tekst(d: date) -> str:
    """date(2026, 12, 5) -> 'lørdag 5/12'."""
    return f"{DAGE[d.weekday()]} {d.day}/{d.month}"


@dataclass
class Status:
    klar: str  # "06.15"
    undtagelse: bool  # "Undtagelse i nat" er slået til
    dag: str  # "fredag"
    sluttid: str | None  # EV Smart Chargings sluttid lige nu
    planlagt: bool
    start: str | None
    stop: str | None
    lader_nu: bool
    tilkoblet: bool | None
    batteri: float | None
    elpris: float | None
    lader: str  # laderens egen status, fx "Available" eller "unavailable"
    kalender: bool = False  # næste morgen kommer fra en planlagt undtagelse i kalenderen
    maal: float | None = None  # bil_mal_i_nat, som automatiseringen har sat
    lad_standard: float | None = None
    kommende: str | None = None  # input_text.bil_kommende_undtagelser
    auto_forvarm: bool | None = None
    forvarm_under: float | None = None
    ude: float | None = None

    def tekst(self) -> str:
        if self.undtagelse:
            hvilken = "undtagelse, kun denne gang"
        elif self.kalender:
            hvilken = "planlagt undtagelse"
        else:
            hvilken = f"fast tid {self.dag}"
        linjer = [f"Bilen skal være klar kl. {self.klar} ({hvilken})."]
        if self.maal is not None:
            standard = f" (standard {_pct(self.lad_standard)})" if self.lad_standard is not None and self.lad_standard != self.maal else ""
            linjer.append(f"Mål i nat: {_pct(self.maal)}{standard}.")
        if self.lader_nu:
            linjer.append("Bilen lader nu.")
        elif self.planlagt and self.start and self.stop:
            linjer.append(f"Opladning planlagt {self.start}–{self.stop}.")
        else:
            linjer.append("Ingen opladning planlagt.")
        if self.batteri is not None:
            linjer.append(f"Batteri: {self.batteri:.0f} %.")
        if self.elpris is not None:
            linjer.append(f"Strøm nu: {self.elpris:.2f} kr./kWh".replace(".", ",", 1) + ".")
        if self.lader in ("unavailable", "unknown"):
            linjer.append("Laderen svarer ikke Home Assistant lige nu.")
        elif self.tilkoblet is False:
            linjer.append("Bilen er ikke sat til.")
        ude = f" (ude nu {self.ude:.0f} °C)" if self.ude is not None else ""
        if self.auto_forvarm and self.forvarm_under is not None:
            linjer.append(f"Forvarmning: automatisk under {self.forvarm_under:.0f} °C{ude}.")
        elif self.auto_forvarm is False:
            linjer.append(f"Automatisk forvarmning er slået fra{ude}.")
        if self.kommende and self.kommende not in ("unknown", "unavailable") and not self.kommende.startswith(INGEN_KOMMENDE):
            linjer.append(f"Planlagt: {self.kommende}")
        return "\n".join(linjer)


async def status(nu: datetime | None = None) -> Status:
    nu = nu or datetime.now(TIDSZONE)
    dag = naeste_morgen(nu)
    fast = FASTE[dag.weekday()]
    enheder = (KLAR, UNDTAGELSE, fast, SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER, MAAL_I_NAT, LAD_STANDARD, KOMMENDE, AUTO_FORVARM, FORVARM_UNDER, UDE)
    *navne, begivenheder = await asyncio.gather(*(tilstand(e) for e in enheder), _begivenheder(dag.date(), dag.date() + timedelta(days=1)))
    klar, undt, fast_t, slut, ladning, tilkoblet, batteri, elpris, lader, maal, standard, kommende, auto, under, ude = navne
    undtagelse = undt.get("state") == "on" and klar.get("state") not in ("unknown", "unavailable", None)
    planlagt_b = None if undtagelse else _paa_dato(begivenheder, dag.date())
    if undtagelse:
        tid = str(klar["state"])
    elif planlagt_b and (m := BEGIVENHED.match(str(planlagt_b["summary"]))):
        tid = f"{int(m.group(1)):02d}:{m.group(2)}"
    else:
        tid = str(fast_t.get("state", "06:15:00"))
    attr = ladning.get("attributes") or {}
    return Status(
        klar=_hhmm(tid),
        undtagelse=undtagelse,
        dag=DAGE[dag.weekday()],
        sluttid=slut.get("state") if slut.get("state") not in ("unknown", "unavailable") else None,
        planlagt=bool(attr.get("charging_is_planned")),
        start=_tid(attr.get("charging_start_time")),
        stop=_tid(attr.get("charging_stop_time")),
        lader_nu=ladning.get("state") == "on",
        tilkoblet={"on": True, "off": False}.get(tilkoblet.get("state")),
        batteri=_tal(batteri.get("state")),
        elpris=_tal(elpris.get("state")),
        lader=str(lader.get("state")),
        kalender=planlagt_b is not None,
        maal=_tal(maal.get("state")),
        lad_standard=_tal(standard.get("state")),
        kommende=str(kommende.get("state")) if kommende.get("state") else None,
        auto_forvarm={"on": True, "off": False}.get(auto.get("state")),
        forvarm_under=_tal(under.get("state")),
        ude=_tal(ude.get("state")),
    )


def _tjek_pct(pct: int) -> int:
    if not LAD_MIN <= pct <= LAD_MAX:
        raise HAFejl(f"Ladeniveauet skal være mellem {LAD_MIN} og {LAD_MAX} %.")
    return round(pct / 5) * 5


def _planlaegning(nu: datetime, s: Status) -> str:
    if 6 <= nu.hour < 18:
        return " Opladningen planlægges kl. 18."
    if s.planlagt and s.start and s.stop:
        return f" Opladning planlagt {s.start}–{s.stop}."
    return ""


async def saet_klar(tid: time | None, nu: datetime | None = None, pct: int | None = None) -> str:
    """Engangstid til næste morgen (evt. med ladeniveau), eller None for den faste tid.
    Giver svaret til husstanden."""
    nu = nu or datetime.now(TIDSZONE)
    if tid is None:
        await _service("input_boolean/turn_off", UNDTAGELSE)
        s = await status(nu)
        hvilken = "planlagt undtagelse" if s.kalender else f"fast tid {s.dag}"
        return f"Undtagelsen er fjernet. Bilen skal være klar kl. {s.klar} ({hvilken})." + _planlaegning(nu, s)
    pct = _tjek_pct(pct) if pct is not None else None
    vaerdi = f"{tid.hour:02d}:{tid.minute:02d}:00"
    await _service("input_datetime/set_datetime", KLAR, time=vaerdi)
    if pct is not None:
        await _service("input_number/set_value", LAD_I_NAT, value=pct)
    await _service("input_boolean/turn_on", UNDTAGELSE)
    i_nat = pct if pct is not None else _tal((await tilstand(LAD_I_NAT)).get("state"))
    s = await status(nu)
    kvarter = f"{tid.hour:02d}.{tid.minute // 15 * 15:02d}"
    hvornaar = "i morgen" if naeste_morgen(nu).date() != nu.date() else "i dag"
    ladet = f", ladet til {_pct(i_nat)}" if i_nat is not None else ""
    svar = f"Bilen skal være klar kl. {_hhmm(vaerdi)} {hvornaar}{ladet} (kun denne gang)."
    if kvarter != _hhmm(vaerdi):
        svar += f" Opladningen er færdig kl. {kvarter} (hele kvarter)."
    return svar + _planlaegning(nu, s)


async def lad_til(pct: int, kun_i_nat: bool = False, nu: datetime | None = None) -> str:
    """Ladeniveau hver nat, eller kun i nat (slår undtagelsen til med den tid, der gælder nu)."""
    nu = nu or datetime.now(TIDSZONE)
    pct = _tjek_pct(pct)
    if not kun_i_nat:
        await _service("input_number/set_value", LAD_STANDARD, value=pct)
        return f"Bilen lades nu til {pct} % hver nat (undtagelser kan sætte andet)."
    s = await status(nu)
    if s.undtagelse:
        await _service("input_number/set_value", LAD_I_NAT, value=pct)
        await _service("input_boolean/turn_on", UNDTAGELSE)
        return f"Bilen lades til {pct} % i nat og skal være klar kl. {s.klar} (kun denne gang)." + _planlaegning(nu, s)
    t = datetime.strptime(s.klar, "%H.%M").time()
    return await saet_klar(t, nu, pct)


async def planlaeg(dag: date, tid: time, pct: int | None = None, nu: datetime | None = None) -> str:
    """Planlagt undtagelse en bestemt dato: en heldagsbegivenhed i bilens kalender."""
    nu = nu or datetime.now(TIDSZONE)
    naeste = naeste_morgen(nu).date()
    if dag < naeste:
        raise HAFejl(f"{dato_tekst(dag)} er allerede gået.")
    if dag > nu.date() + timedelta(days=366):
        raise HAFejl("Det er mere end et år frem.")
    if dag == naeste:  # næste morgen: så er det bare en klar-tid til i nat
        return await saet_klar(tid, nu, pct)
    pct = _tjek_pct(pct) if pct is not None else None
    if b := _paa_dato(await _begivenheder(dag, dag + timedelta(days=1)), dag):
        raise HAFejl(f"Der ligger allerede en undtagelse {dato_tekst(dag)} ({b.get('summary')}). Slet den på dashboardet først.")
    titel = f"{tid.hour:02d}:{tid.minute:02d}" + (f" {pct}%" if pct is not None else "")
    await _service("calendar/create_event", KALENDER, summary=titel, start_date=dag.isoformat(), end_date=(dag + timedelta(days=1)).isoformat())
    ladet = f", ladet til {pct} %" if pct is not None else ""
    return f"Planlagt: {dato_tekst(dag)} skal bilen være klar kl. {_hhmm(titel)}{ladet}. Slet den på dashboardet, hvis planen ændrer sig."


async def undtagelser() -> str:
    tekst = str((await tilstand(KOMMENDE)).get("state") or "")
    if not tekst or tekst in ("unknown", "unavailable") or tekst.startswith(INGEN_KOMMENDE):
        return "Ingen planlagte undtagelser. Skriv fx 'klar 5/12 5:30 100%' for at lægge en."
    return f"Planlagte undtagelser: {tekst}"


async def forvarm() -> str:
    await _service("input_boolean/turn_on", FORVARM_NU)
    return "Forvarmningen er sendt til bilen. Den slukker selv igen."


async def auto_forvarmning(til: bool) -> str:
    await _service("input_boolean/turn_on" if til else "input_boolean/turn_off", AUTO_FORVARM)
    if not til:
        return "Automatisk forvarmning er slået fra."
    under = _tal((await tilstand(FORVARM_UNDER)).get("state"))
    return "Automatisk forvarmning er slået til" + (f" (under {under:.0f} °C)." if under is not None else ".")


async def forvarm_under(grader: int) -> str:
    if not FORVARM_MIN <= grader <= FORVARM_MAX:
        raise HAFejl(f"Grænsen skal være mellem {FORVARM_MIN} og {FORVARM_MAX} °C.")
    await _service("input_number/set_value", FORVARM_UNDER, value=grader)
    return f"Bilen forvarmes automatisk, når det er under {grader} °C."


async def oplad(start: bool) -> str:
    await _tryk(START if start else STOP)
    if start:
        return "Opladningen er sendt til laderen. Den kan være et minut om at starte. Skriv 'stop opladning' for at stoppe."
    return "Stop er sendt til laderen. Den kan være et minut om at stoppe."

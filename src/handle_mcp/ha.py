"""Bilen i Home Assistant: status, klar-tid og "oplad nu" fra Telegram og fra `claude -p`.

Julius, 26/11-2026: "så man kan skrive derinde at den skal x, y og z, og få status for det ene
og det andet data". Home Assistant styrer laderen via OCPP og EV Smart Charging. Her laves kun
fem ting, og kun på de enheder, der står nedenfor:

  - status: læser klar-tid, planlagt opladning, batteri, elpris og laderen
  - klar-tid: sætter engangstiden `input_datetime.bilen_skal_vaere_klar_kl` og slår
    `input_boolean.undtagelse_i_nat` til (eller fra for ugedagens faste tid). Automatiseringen i
    Home Assistant sætter selv EV Smart Chargings sluttid ud fra dem og slår undtagelsen fra kl. 12.
  - oplad nu / stop: trykker på EV Smart Chargings knapper for manuel start og stop

Intet andet i Home Assistant kan ændres herfra (se også vagt.py, der kun tillader netop disse
adresser). Adressen ligger i home_assistant.json i datamappen, tokenet i nøgleringen.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
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

LAESER = (KLAR, UNDTAGELSE, *FASTE, SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER)
KNAPPER = (START, STOP)

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


async def _tryk(knap: str) -> None:
    if knap not in KNAPPER:
        raise HAFejl(f"{knap} må ikke trykkes herfra.")
    await _kald("POST", "/api/services/button/press", {"entity_id": knap})


# --- de fem handlinger ----------------------------------------------------------------


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


def _tal(t: str) -> float | None:
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


@dataclass
class Status:
    klar: str  # "06.15"
    undtagelse: bool
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

    def tekst(self) -> str:
        hvilken = "undtagelse, kun denne gang" if self.undtagelse else f"fast tid {self.dag}"
        linjer = [f"Bilen skal være klar kl. {self.klar} ({hvilken})."]
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
        return "\n".join(linjer)


async def status(nu: datetime | None = None) -> Status:
    nu = nu or datetime.now(TIDSZONE)
    dag = naeste_morgen(nu)
    fast = FASTE[dag.weekday()]
    navne = await asyncio.gather(*(tilstand(e) for e in (KLAR, UNDTAGELSE, fast, SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER)))
    klar, undt, fast_t, slut, ladning, tilkoblet, batteri, elpris, lader = navne
    undtagelse = undt.get("state") == "on" and klar.get("state") not in ("unknown", "unavailable", None)
    tid = klar["state"] if undtagelse else fast_t.get("state", "06:15:00")
    attr = ladning.get("attributes") or {}
    return Status(
        klar=_hhmm(str(tid)),
        undtagelse=undtagelse,
        dag=("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")[dag.weekday()],
        sluttid=slut.get("state") if slut.get("state") not in ("unknown", "unavailable") else None,
        planlagt=bool(attr.get("charging_is_planned")),
        start=_tid(attr.get("charging_start_time")),
        stop=_tid(attr.get("charging_stop_time")),
        lader_nu=ladning.get("state") == "on",
        tilkoblet={"on": True, "off": False}.get(tilkoblet.get("state")),
        batteri=_tal(batteri.get("state")),
        elpris=_tal(elpris.get("state")),
        lader=str(lader.get("state")),
    )


async def saet_klar(tid: time | None, nu: datetime | None = None) -> str:
    """Engangstid til næste morgen, eller None for den faste tid. Giver svaret til husstanden."""
    nu = nu or datetime.now(TIDSZONE)
    if tid is None:
        await _kald("POST", "/api/services/input_boolean/turn_off", {"entity_id": UNDTAGELSE})
    else:
        vaerdi = f"{tid.hour:02d}:{tid.minute:02d}:00"
        await _kald("POST", "/api/services/input_datetime/set_datetime", {"entity_id": KLAR, "time": vaerdi})
        await _kald("POST", "/api/services/input_boolean/turn_on", {"entity_id": UNDTAGELSE})
    s = await status(nu)
    if tid is None:
        svar = f"Undtagelsen er fjernet. Bilen skal være klar kl. {s.klar} (fast tid {s.dag})."
    else:
        kvarter = f"{tid.hour:02d}.{tid.minute // 15 * 15:02d}"
        hvornaar = "i morgen" if naeste_morgen(nu).date() != nu.date() else "i dag"
        svar = f"Bilen skal være klar kl. {_hhmm(vaerdi)} {hvornaar} (kun denne gang)."
        if kvarter != _hhmm(vaerdi):
            svar += f" Opladningen er færdig kl. {kvarter} (hele kvarter)."
    if 6 <= nu.hour < 18:
        svar += " Opladningen planlægges kl. 18."
    elif s.planlagt and s.start and s.stop:
        svar += f" Opladning planlagt {s.start}–{s.stop}."
    return svar


async def oplad(start: bool) -> str:
    await _tryk(START if start else STOP)
    if start:
        return "Opladningen er sendt til laderen. Den kan være et minut om at starte. Skriv 'stop opladning' for at stoppe."
    return "Stop er sendt til laderen. Den kan være et minut om at stoppe."

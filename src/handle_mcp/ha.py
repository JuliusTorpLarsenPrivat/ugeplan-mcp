"""Bilen i Home Assistant: status, klar-tid, ladeniveau, planlagte undtagelser, forvarmning og
"oplad nu" fra Telegram og fra `claude -p`.

Julius, 26/11-2026: "så man kan skrive derinde at den skal x, y og z, og få status for det ene
og det andet data". 27/11-2026: "Ja, udvid den" (ladeniveau, kalender og forvarmning).
Home Assistant styrer laderen via OCPP og EV Smart Charging. Her laves kun disse ting, og kun på
de enheder, der står nedenfor (SKRIV):

  - status: læser klar-tid, planlagt opladning, batteri, elpris, laderen og forvarmning
  - klar-tid: en heldagsbegivenhed "HH:MM PCT%" i kalenderen `calendar.bil_afgang` (står under
    "Planlagte undtagelser" på dashboardet). Én pr. dag: en ny erstatter den gamle. Fortryd og
    erstat sletter via websocket (`calendar/event/delete`), da REST ikke kan slette.
    Automatiseringen sætter selv EV Smart Chargings sluttid og mål ud fra kalenderen.
  - ladeniveau: `input_number.lad_op_til` (hver nat). `input_number.bil_mal_i_nat` skriver
    automatiseringen; den læses kun.
  - forvarmning: `input_boolean.forvarm_bilen_nu` til (Mac-scriptet slukker selv), automatikken
    til/fra og temperaturgrænsen `input_number.forvarm_under`.
  - oplad nu / stop: trykker på EV Smart Chargings knapper for manuel start og stop
27/11-2026: "Undtagelse i nat" (input_boolean.undtagelse_i_nat) bruges ikke længere; kun kalenderen.

Intet andet i Home Assistant kan ændres herfra (se også vagt.py, der kun tillader netop disse
adresser). Adressen ligger i home_assistant.json i datamappen, tokenet i nøgleringen.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
import keyring
import keyring.errors
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from handle_mcp import lokal
from handle_mcp.login import TJENESTE
from handle_mcp.vagt import VagtFejl, ny_klient, tjek_ws

TIDSZONE = ZoneInfo("Europe/Copenhagen")
FIL = "home_assistant"
NOEGLE_NAVN = "home-assistant"
STANDARD_URL = "http://192.168.128.2:8123"  # Mac mini'ens interne kort til VM'en
TIMEOUT_SEK = 15

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
MAAL_I_NAT = "input_number.bil_mal_i_nat"
KALENDER = "calendar.bil_afgang"
KOMMENDE = "input_text.bil_kommende_undtagelser"
FORVARM_NU = "input_boolean.forvarm_bilen_nu"
AUTO_FORVARM = "input_boolean.automatisk_forvarmning"
FORVARM_UNDER = "input_number.forvarm_under"
UDE = "sensor.stue_stue_outside_temperature"
ELPRIS_CO2 = "sensor.energi_data_service_co2"  # g/kWh nu
# Opladningsforbrug (Julius 27/11-2026), talt fra 26/11-2026: (navn, kWh, kr., kg CO2)
FORBRUG = (
    ("Sidste opladning", "sensor.lader_energy_session", "input_number.ladning_sidste_kr", "input_number.ladning_sidste_co2"),
    ("Seneste 24 t", "sensor.bil_kwh_seneste_24_t", "sensor.bil_kr_seneste_24_t", "sensor.bil_co2_seneste_24_t"),
    ("Seneste 7 dage", "sensor.bil_kwh_seneste_7_dage", "sensor.bil_kr_seneste_7_dage", "sensor.bil_co2_seneste_7_dage"),
    ("Denne måned", "sensor.bil_kwh_denne_maned", "sensor.bil_kr_denne_maned", "sensor.bil_co2_denne_maned"),
    ("I år", "sensor.bil_kwh_i_ar", "sensor.bil_kr_i_ar", "sensor.bil_co2_i_ar"),
    ("I alt", "input_number.ladning_kwh_i_alt", "input_number.ladning_kr_i_alt", "input_number.ladning_co2_i_alt"),
)
FORBRUG_FRA = "26/11-2026"

LAESER = (
    *FASTE, SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER,
    LAD_STANDARD, MAAL_I_NAT, KOMMENDE, AUTO_FORVARM, FORVARM_UNDER, UDE,
    ELPRIS_CO2, *(e for _, *enheder in FORBRUG for e in enheder),
)  # fmt: skip
KNAPPER = (START, STOP)
# Det eneste, der kan ændres herfra: service -> de enheder, den må bruges på. Se også vagt.HA_STIER.
SKRIV = {
    "input_boolean/turn_on": {FORVARM_NU, AUTO_FORVARM},
    "input_boolean/turn_off": {AUTO_FORVARM},
    "input_number/set_value": {LAD_STANDARD, FORVARM_UNDER},
    "calendar/create_event": {KALENDER},
    "button/press": set(KNAPPER),
}
WS_SKRIV = {"calendar/event/delete": {KALENDER}}  # websocket: kun sletning i bilens kalender
LAD_MIN, LAD_MAX = 50, 100  # som hjælperne i Home Assistant (trin på 5)
FORVARM_MIN, FORVARM_MAX = -10, 20

_transport: httpx.AsyncBaseTransport | None = None  # kun til test
_ws_transport = None  # kun til test: async (besked) -> svar


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


class _UdenOmdirigering(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        return exc  # vagten har tjekket adressen; en omdirigering følges aldrig


async def _ws(besked: dict) -> dict:
    """Én websocket-kommando til Home Assistant (kun dem i WS_SKRIV). Ingen gentagelser."""
    if besked.get("entity_id") not in WS_SKRIV.get(str(besked.get("type")), ()):
        raise HAFejl(f"{besked.get('type')} må ikke bruges herfra.")
    token = hent_token()
    adresse = httpx.URL(url())
    adresse = adresse.copy_with(scheme="wss" if adresse.scheme == "https" else "ws", path="/api/websocket")
    try:
        tjek_ws(adresse)
    except VagtFejl as fejl:
        raise HAFejl(str(fejl)) from None
    if _ws_transport is not None:
        svar = await _ws_transport(besked)
    else:
        try:
            async with asyncio.timeout(TIMEOUT_SEK):
                async with _UdenOmdirigering(str(adresse), max_size=2**20, open_timeout=TIMEOUT_SEK) as ws:
                    await ws.recv()  # auth_required
                    await ws.send(json.dumps({"type": "auth", "access_token": token}))
                    if json.loads(await ws.recv()).get("type") != "auth_ok":
                        raise HAFejl("Home Assistant afviste tokenet. Lav et nyt og kør: ugeplan-mcp ha-opsaet")
                    await ws.send(json.dumps({"id": 1, **besked}))
                    while (svar := json.loads(await ws.recv())).get("id") != 1:
                        pass
        except TimeoutError:
            raise HAFejl("Home Assistant svarede ikke inden for 15 sekunder.") from None
        except (OSError, WebSocketException, ValueError) as fejl:
            raise HAFejl(f"Kunne ikke nå Home Assistant: {_rens(str(fejl), token)}") from None
    if not svar.get("success"):
        raise HAFejl(f"Home Assistant: {(svar.get('error') or {}).get('message', 'ukendt fejl')}")
    return svar


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


def naeste_morgen(nu: datetime) -> date:
    """Den morgen, en klar-tid gælder: i morgen fra kl. 6, ellers i dag."""
    return (nu + timedelta(days=1)).date() if nu.hour >= 6 else nu.date()


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


def _hvornaar(dag: date, nu: datetime) -> str:
    if dag == nu.date():
        return "i dag"
    if dag == nu.date() + timedelta(days=1):
        return "i morgen"
    return dato_tekst(dag)


@dataclass
class Status:
    klar: str  # "06.15"
    planlagt_undtagelse: str | None  # kalenderens titel for næste morgen, fx "07:30 100%"
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
    maal: float | None = None  # bil_mal_i_nat, som automatiseringen har sat
    lad_standard: float | None = None
    kommende: str | None = None  # input_text.bil_kommende_undtagelser
    auto_forvarm: bool | None = None
    forvarm_under: float | None = None
    ude: float | None = None

    def tekst(self) -> str:
        hvilken = "undtagelse, kun denne gang" if self.planlagt_undtagelse else f"fast tid {self.dag}"
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
    enheder = (FASTE[dag.weekday()], SLUTTID, LADNING, TILKOBLET, BATTERI, ELPRIS, LADER, MAAL_I_NAT, LAD_STANDARD, KOMMENDE, AUTO_FORVARM, FORVARM_UNDER, UDE)
    *navne, begivenheder = await asyncio.gather(*(tilstand(e) for e in enheder), _begivenheder(dag, dag + timedelta(days=1)))
    fast_t, slut, ladning, tilkoblet, batteri, elpris, lader, maal, standard, kommende, auto, under, ude = navne
    b = _paa_dato(begivenheder, dag)
    if b and (m := BEGIVENHED.match(str(b["summary"]))):
        tid = f"{int(m.group(1)):02d}:{m.group(2)}"
    else:
        tid = str(fast_t.get("state", "06:15:00"))
    attr = ladning.get("attributes") or {}
    return Status(
        klar=_hhmm(tid),
        planlagt_undtagelse=str(b["summary"]).strip() if b else None,
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


def _planlaegning(dag: date, nu: datetime) -> str:
    if dag != naeste_morgen(nu):
        return ""
    if 6 <= nu.hour < 18:
        return " Opladningen planlægges kl. 18."
    return " Opladningen planlægges om lidt."


async def _slet(b: dict) -> None:
    uid = b.get("uid")
    if not uid:
        raise HAFejl("Begivenheden har intet id.")
    await _ws({"type": "calendar/event/delete", "entity_id": KALENDER, "uid": uid})


def _dashboard(b: dict, dag: date, nu: datetime, fejl: HAFejl) -> HAFejl:
    return HAFejl(f"{fejl} Undtagelsen {_hvornaar(dag, nu)} ({b.get('summary')}) står der stadig. Slet den under Planlagte undtagelser på dashboardet.")


async def planlaeg(dag: date, tid: time, pct: int | None = None, nu: datetime | None = None) -> str:
    """Undtagelse en bestemt morgen: en heldagsbegivenhed i bilens kalender. Én pr. dag: en
    eksisterende slettes først."""
    nu = nu or datetime.now(TIDSZONE)
    if dag < naeste_morgen(nu):
        raise HAFejl(f"{dato_tekst(dag)} er allerede gået.")
    if dag > nu.date() + timedelta(days=366):
        raise HAFejl("Det er mere end et år frem.")
    pct = _tjek_pct(pct) if pct is not None else None
    titel = f"{tid.hour:02d}:{tid.minute:02d}" + (f" {pct}%" if pct is not None else "")
    erstattet = ""
    if b := _paa_dato(await _begivenheder(dag, dag + timedelta(days=1)), dag):
        try:
            await _slet(b)  # først slet, så der aldrig ligger to; fejler oprettelsen, gælder den faste tid
        except HAFejl as fejl:
            raise _dashboard(b, dag, nu, fejl) from None
        erstattet = f" (erstatter {b.get('summary')})"
    await _service("calendar/create_event", KALENDER, summary=titel, start_date=dag.isoformat(), end_date=(dag + timedelta(days=1)).isoformat())
    ladet = f", ladet til {pct} %" if pct is not None else ""
    return f"Bilen skal være klar kl. {_hhmm(titel)} {_hvornaar(dag, nu)}{ladet} (kun denne gang){erstattet}." + _planlaegning(dag, nu)


async def saet_klar(tid: time | None, nu: datetime | None = None, pct: int | None = None) -> str:
    """Klar-tid næste morgen (evt. med ladeniveau), eller None for at fjerne undtagelsen igen."""
    nu = nu or datetime.now(TIDSZONE)
    dag = naeste_morgen(nu)
    if tid is not None:
        return await planlaeg(dag, tid, pct, nu)
    b = _paa_dato(await _begivenheder(dag, dag + timedelta(days=1)), dag)
    if b:
        try:
            await _slet(b)
        except HAFejl as fejl:
            raise _dashboard(b, dag, nu, fejl) from None
    s = await status(nu)
    if not b:
        return f"Der er ingen undtagelse {_hvornaar(dag, nu)}. Bilen skal være klar kl. {s.klar} (fast tid {s.dag})."
    return f"Undtagelsen {_hvornaar(dag, nu)} ({b.get('summary')}) er fjernet. Bilen skal være klar kl. {s.klar} (fast tid {s.dag})." + _planlaegning(dag, nu)


async def lad_til(pct: int, kun_i_nat: bool = False, nu: datetime | None = None) -> str:
    """Ladeniveau hver nat, eller kun i nat (undtagelse næste morgen med den tid, der gælder)."""
    nu = nu or datetime.now(TIDSZONE)
    pct = _tjek_pct(pct)
    if not kun_i_nat:
        await _service("input_number/set_value", LAD_STANDARD, value=pct)
        return f"Bilen lades nu til {pct} % hver nat (undtagelser kan sætte andet)."
    s = await status(nu)
    return await planlaeg(naeste_morgen(nu), datetime.strptime(s.klar, "%H.%M").time(), pct, nu)


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


# --- opladningsforbrug (kun læsning) ---------------------------------------------------------


def _komma(v: float, dec: int) -> str:
    return f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")


@dataclass
class Periode:
    navn: str
    kwh: float | None
    kr: float | None
    co2: float | None  # kg

    @property
    def kr_pr_kwh(self) -> float | None:
        return self.kr / self.kwh if self.kr is not None and self.kwh else None

    def linje(self) -> str:
        dele = [
            f"{_komma(self.kwh, 1)} kWh" if self.kwh is not None else "? kWh",
            f"{_komma(self.kr, 2)} kr." if self.kr is not None else "? kr.",
            f"{_komma(self.co2, 2)} kg CO2" if self.co2 is not None else "? kg CO2",
        ]
        if (p := self.kr_pr_kwh) is not None:
            dele.append(f"{_komma(p, 2)} kr./kWh")
        return f"{self.navn}: " + " · ".join(dele)


@dataclass
class Forbrug:
    perioder: list[Periode]
    elpris: float | None  # kr./kWh nu
    co2_nu: float | None  # g/kWh nu
    billigst: tuple[str, float] | None  # ("03.00", 2,05): billigste kommende time
    snit: float | None  # gennemsnit af de kommende timer, der kendes

    def __post_init__(self) -> None:
        self.kr_pr_kwh = {p.navn: p.kr_pr_kwh for p in self.perioder}

    def tekst(self) -> str:
        linjer = [f"Opladning (talt fra {FORBRUG_FRA}):"] + [p.linje() for p in self.perioder]
        if self.elpris is not None:
            nu = f"Strøm nu: {_komma(self.elpris, 2)} kr./kWh"
            if self.co2_nu is not None:
                nu += f", {self.co2_nu:.0f} g CO2/kWh"
            linjer += ["", nu + "."]
            if self.billigst and self.snit is not None:
                tid, pris = self.billigst
                vurdering = "billigt" if self.elpris <= self.snit * 0.9 else "dyrt" if self.elpris >= self.snit * 1.1 else "middel"
                linjer.append(f"Det er {vurdering} lige nu. Billigste kommende time: kl. {tid} ({_komma(pris, 2)} kr./kWh); snit {_komma(self.snit, 2)}.")
        return "\n".join(linjer)


def _kommende(attr: dict, nu: datetime) -> list[tuple[datetime, float]]:
    ud = []
    for t in list(attr.get("raw_today") or []) + list(attr.get("raw_tomorrow") or []):
        try:
            tid, pris = datetime.fromisoformat(str(t["hour"])).astimezone(TIDSZONE), float(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if tid + timedelta(hours=1) > nu:
            ud.append((tid, pris))
    return ud


async def forbrug(nu: datetime | None = None) -> Forbrug:
    """Opladningens kWh, kr. og CO2 pr. periode, og strømmen nu og de kommende timer."""
    nu = nu or datetime.now(TIDSZONE)
    enheder = [e for _, *tre in FORBRUG for e in tre]
    *vaerdier, pris, co2 = await asyncio.gather(*(tilstand(e) for e in (*enheder, ELPRIS, ELPRIS_CO2)))
    tal = [_tal(v.get("state")) for v in vaerdier]
    perioder = [Periode(navn, *tal[i * 3 : i * 3 + 3]) for i, (navn, *_) in enumerate(FORBRUG)]
    kommende = _kommende(pris.get("attributes") or {}, nu)
    billigst = min(kommende, key=lambda x: x[1]) if kommende else None
    return Forbrug(
        perioder=perioder,
        elpris=_tal(pris.get("state")),
        co2_nu=_tal(co2.get("state")),
        billigst=(billigst[0].strftime("%H.%M"), billigst[1]) if billigst else None,
        snit=sum(p for _, p in kommende) / len(kommende) if kommende else None,
    )


async def oplad(start: bool) -> str:
    await _tryk(START if start else STOP)
    if start:
        return "Opladningen er sendt til laderen. Den kan være et minut om at starte. Skriv 'stop opladning' for at stoppe."
    return "Stop er sendt til laderen. Den kan være et minut om at stoppe."

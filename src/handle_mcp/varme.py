"""Varmepumpen (Panasonic Etherea i stuen) fra Telegram og fra `claude -p`.

Julius 28/11-2026: "udbyg og gør det til at den fatter menneskesprog og ikke kun kommandoer",
og begge telefoner må styre. Vi bruger den kun til varme eller til at blæse (lufte ud).

Almindelige sætninger klares her uden AI ("hvor varmt er der?", "sluk varmen", "sæt varmen til
22", "vi lufter ud", "sov godt"). Alt andet om varmen, og alt med tid, betingelse eller nægtelse
("sluk varmen kl. 22", "lad være med at slukke"), går til `claude -p`, som har de samme
handlinger som værktøjer (server.py: varme_status, varme_styr, varme_sov_godt).

Kun `climate.stue_stue`, sov godt-scriptet og dets timer kan ændres (ha.SKRIV, vagt.HA_STIER).
Køl, affugt og auto bruges ikke og kan ikke vælges herfra.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from handle_mcp import ha

MIN_GRADER, MAX_GRADER = 16.0, 30.0
TILSTANDE = {"heat": "varme", "fan_only": "luft ud (kun blæs)", "off": "slukket", "cool": "køl", "dry": "affugt", "heat_cool": "auto"}
BLAESER = {"auto": "Auto", "lav": "Low", "mellem": "Mid", "høj": "High"}
STYRKE = {"normal": "none", "stille": "quiet", "kraftig": "powerful"}
STYRKE_NAVN = {v: k for k, v in STYRKE.items()}
BLAESER_NAVN = {v: k for k, v in BLAESER.items()} | {"LowMid": "lav-mellem", "HighMid": "mellem-høj"}


# --- status og handlinger -------------------------------------------------------------------


@dataclass
class Status:
    tilstand: str  # heat, fan_only, off, unavailable ...
    varmer_nu: bool
    maal: float | None
    inde: float | None
    ude: float | None
    effekt: float | None  # W, Panasonics skøn
    kwh_i_dag: float | None
    kr_i_dag: float | None
    kr_i_gaar: float | None
    blaeser: str | None
    styrke: str | None
    sov_til: str | None  # "23:15", når sov godt er i gang

    def tekst(self) -> str:
        if self.tilstand in ("unavailable", "unknown"):
            return "Varmepumpen svarer ikke Home Assistant lige nu (Panasonic-skyen)."
        linjer = []
        stue = f"Stuen: {_grader(self.inde)}" if self.inde is not None else "Stuen: ?"
        if self.maal is not None and self.tilstand == "heat":
            stue += f" (mål {_grader(self.maal)})"
        if self.ude is not None:
            stue += f", ude {_grader(self.ude)}"
        linjer.append(stue + ".")
        if self.sov_til:
            linjer.append(f"Sov godt: slukket til kl. {self.sov_til}, så tænder den igen.")
        else:
            drift = TILSTANDE.get(self.tilstand, self.tilstand)
            if self.tilstand == "heat":
                drift += ", varmer nu" if self.varmer_nu else ", hviler"
            ekstra = []
            if self.tilstand != "off" and self.styrke and self.styrke != "none":
                ekstra.append(STYRKE_NAVN.get(self.styrke, self.styrke))
            if self.tilstand != "off" and self.blaeser and self.blaeser != "Auto":
                ekstra.append(f"blæser {BLAESER_NAVN.get(self.blaeser, self.blaeser)}")
            if self.tilstand != "off" and self.effekt is not None:
                ekstra.append(f"{self.effekt:.0f} W")
            linjer.append(f"Varmepumpen: {drift}" + (f" ({', '.join(ekstra)})" if ekstra else "") + ".")
        dag = []
        if self.kwh_i_dag is not None:
            dag.append(f"{ha._komma(self.kwh_i_dag, 1)} kWh")
        if self.kr_i_dag is not None:
            dag.append(f"{ha._komma(self.kr_i_dag, 2)} kr.")
        if dag:
            linjer.append("I dag: " + " og ".join(dag) + (f" (i går {ha._komma(self.kr_i_gaar, 2)} kr.)" if self.kr_i_gaar else "") + ".")
        return "\n".join(linjer)


def _grader(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{ha._komma(v, 0 if float(v).is_integer() else 1)} °C"


def _hhmm(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(ha.TIDSZONE).strftime("%H:%M")
    except ValueError:
        return None


async def status() -> Status:
    c, inde, effekt, kwh, kr, timer, ude = await asyncio.gather(
        *(ha.tilstand(e) for e in (ha.VARME, ha.VARME_INDE, ha.VARME_EFFEKT, ha.VARME_KWH, ha.VARME_KR, ha.SOV_TIMER, ha.UDE))
    )
    a = c.get("attributes") or {}
    return Status(
        tilstand=str(c.get("state")),
        varmer_nu=a.get("hvac_action") == "heating",
        maal=ha._tal(a.get("temperature")),
        inde=ha._tal(inde.get("state")) if ha._tal(inde.get("state")) is not None else ha._tal(a.get("current_temperature")),
        ude=ha._tal(ude.get("state")),
        effekt=ha._tal(effekt.get("state")),
        kwh_i_dag=ha._tal(kwh.get("state")),
        kr_i_dag=ha._tal(kr.get("state")),
        kr_i_gaar=ha._tal((kr.get("attributes") or {}).get("last_period")),
        blaeser=a.get("fan_mode"),
        styrke=a.get("preset_mode"),
        sov_til=_hhmm((timer.get("attributes") or {}).get("finishes_at")) if timer.get("state") == "active" else None,
    )


LAG = " Panasonic-skyen kan være et halvt minut om det."


async def _sover() -> bool:
    return (await ha.tilstand(ha.SOV_TIMER)).get("state") == "active"


async def varme() -> str:
    if await _sover():
        await ha._service("timer/finish", ha.SOV_TIMER)  # automatiseringen tænder som før
        return "Sov godt er stoppet, og varmepumpen tænder igen som før." + LAG
    await ha._service("climate/set_hvac_mode", ha.VARME, hvac_mode="heat")
    maal = ha._tal(((await ha.tilstand(ha.VARME)).get("attributes") or {}).get("temperature"))
    return f"Varmen er tændt{f' ({_grader(maal)})' if maal is not None else ''}." + LAG


async def sluk() -> str:
    await ha._service("climate/set_hvac_mode", ha.VARME, hvac_mode="off")
    return "Varmepumpen er slukket. Skriv 'tænd varmen' for at tænde den igen." + LAG


async def luft_ud() -> str:
    await ha._service("climate/set_hvac_mode", ha.VARME, hvac_mode="fan_only")
    await ha._service("climate/set_fan_mode", ha.VARME, fan_mode="High")
    return "Varmepumpen blæser nu kun luft (høj), uden varme. Skriv 'færdig med at lufte ud' for varme igen." + LAG


async def saet_grader(grader: float) -> str:
    g = round(grader * 2) / 2
    if not MIN_GRADER <= g <= MAX_GRADER:
        raise ha.HAFejl(f"Temperaturen skal være mellem {MIN_GRADER:.0f} og {MAX_GRADER:.0f} °C.")
    await ha._service("climate/set_temperature", ha.VARME, temperature=g, hvac_mode="heat")
    return f"Varmen er sat til {_grader(g)}." + LAG


async def juster(trin: float) -> str:
    maal = ha._tal(((await ha.tilstand(ha.VARME)).get("attributes") or {}).get("temperature"))
    if maal is None:
        raise ha.HAFejl("Kan ikke se den nuværende temperatur. Skriv fx 'varme 22'.")
    return await saet_grader(min(MAX_GRADER, max(MIN_GRADER, maal + trin)))


async def saet_styrke(styrke: str) -> str:
    if styrke not in STYRKE:
        raise ha.HAFejl("Styrken kan være normal, stille eller kraftig.")
    await ha._service("climate/set_preset_mode", ha.VARME, preset_mode=STYRKE[styrke])
    return f"Varmepumpen kører nu {styrke}." + LAG


async def saet_blaeser(hastighed: str) -> str:
    if hastighed not in BLAESER:
        raise ha.HAFejl("Blæseren kan være auto, lav, mellem eller høj.")
    await ha._service("climate/set_fan_mode", ha.VARME, fan_mode=BLAESER[hastighed])
    return f"Blæseren er sat til {hastighed}." + LAG


async def sov_godt(nu: datetime | None = None) -> str:
    if await _sover():
        return "Sov godt er allerede i gang."
    tilstand = (await ha.tilstand(ha.VARME)).get("state")
    if tilstand in ("off", "unavailable", "unknown"):
        return "Varmepumpen er allerede slukket, så sov godt gør ingenting. Sov godt!"
    minutter = int(ha._tal((await ha.tilstand(ha.SOV_MINUTTER)).get("state")) or 45)
    await ha._service("script/turn_on", ha.SOV_GODT)
    igen = ((nu or datetime.now(ha.TIDSZONE)) + timedelta(minutes=minutter)).strftime("%H:%M")
    return f"Varmepumpen slukker nu i {minutter} min og tænder igen som før ca. kl. {igen}. Sov godt!"


async def vaagn() -> str:
    if await _sover():
        await ha._service("timer/finish", ha.SOV_TIMER)
        return "Sov godt er stoppet, og varmepumpen tænder igen som før." + LAG
    return await varme()


# --- almindelig tale -> handling --------------------------------------------------------------


@dataclass
class Handling:
    hvad: str  # status, varme, sluk, luft_ud, grader, juster, styrke, blaeser, sov, vaagn
    grader: float | None = None
    valg: str | None = None


def _rens(tekst: str) -> str:
    return " ".join(tekst.lower().replace("’", "'").strip(" !.").split())


VARME_ORD = re.compile(
    r"\b(?:varme(?:n|ns)?|varmepumpe\w*|aircon\w*|klimaanlæg\w*|stuen|temperatur\w*|grader|varmt|varmere|lunt|lunere"
    r"|koldt|kold|koldere|køligere|luft\w*|udluft\w*|blæs\w*|sov godt|sengetid|i seng)\b|°"
)
# Handler om bilen (bil_*-kommandoerne i ha_besked.py), ikke varmepumpen.
BIL = re.compile(r"\b(?:bil(?:en|ens)?|forvarm\w*|oplad\w*|lade\w*|lader\w*|ladning\w*|elbil\w*)\b")
# Tid, betingelse, nægtelse eller mere end én ting: ikke sikkert -> claude -p.
USIKKER = re.compile(
    r"\b(?:ikke|lad være|hvorfor|hvis|når|indtil|i morgen|i aften|i nat|om \d+|kl\.?|klokken|efter|før|bagefter|og så|men)\b|\d{1,2}[:.]\d{2}"
)
SPOERG = re.compile(r"^(?:er|hvor|hvad|hvordan|kører|står|har|hvilken|hvilke|bruger|koster)\b")
BEDER = re.compile(r"^(?:kan|vil|gider|må)\s+(?:du|i|vi|man|jeg)\b")

SOV = re.compile(r"\b(?:sov godt|(?:vi |jeg )?går i seng|skal (?:i seng|sove)|sengetid|godnat varme\w*)\b")
VAAGN = re.compile(r"\b(?:tænd\w* (?:den |varmen |varmepumpen )?igen|stop sov godt|vågn\w*)\b")
LUFT_SLUT = re.compile(r"\b(?:færdig\w*|stop\w*|slut\w*)\b.*\b(?:luft\w*|udluft\w*)")
LUFT = re.compile(r"\b(?:luft\w* ud|udluft\w*|kun blæs\w*|blæs uden varme|bare blæs\w*)\b")
GRADER = re.compile(r"\b(\d{2}(?:[.,]5)?)\s*(?:°\s*c?|grader)|\b(?:varme(?:n|pumpen)?|temperatur(?:en)?)\s+(?:til\s+|på\s+)?(\d{2}(?:[.,]5)?)\b")
STIL = re.compile(r"\b(?:sæt\w*|skru\w*|stil\w*|indstil\w*|lav\w*|gør\w*)\b")  # "det er 18 grader" er ikke en ordre
OP = re.compile(r"\b(?:varmere|lunere|skru\w* op|hæv\w*|mere varme)\b")
NED = re.compile(r"\b(?:koldere|køligere|skru\w* ned|sænk\w*|mindre varme)\b")
SLUK = re.compile(r"\b(?:sluk\w*|slå\w* (?:\w+ )?fra|varme(?:n|pumpen)? fra|stop\w* varme\w*)\b")
TAEND = re.compile(r"\b(?:tænd\w*|slå\w* (?:\w+ )?til|varme(?:n|pumpen)? til|start\w* varme\w*)\b")
STILLE = re.compile(r"\b(?:stille\w*|larm\w*|støj\w*)\b")
KRAFTIG = re.compile(r"\b(?:kraftig\w*|fuld (?:kraft|skrue|knald)|max\w*|turbo)\b")
NORMAL = re.compile(r"\bnormal\w*\b")
FART = re.compile(r"\bblæs\w*\s+(?:på\s+|til\s+)?(auto|lav|mellem|høj)\b")
STATUS = {"varme", "varmen", "varmepumpe", "varmepumpen", "status varme", "varme status", "temperatur", "temperaturen", "stuen"}


def fortolk(tekst: str) -> Handling | None:
    """En sikker handling på varmepumpen, eller None (ikke om varmen, eller ikke sikkert)."""
    t = _rens(tekst)
    sp = t.endswith("?")
    t = t.rstrip(" ?")
    if len(t) > 80 or not VARME_ORD.search(t) or BIL.search(t):
        return None
    if t in STATUS:
        return Handling("status")
    if USIKKER.search(t):
        return None
    if (sp or SPOERG.match(t)) and not BEDER.match(t):
        return Handling("status")  # "er varmen tændt?", "hvad har varmen kostet i dag?"
    if SOV.search(t):
        return Handling("sov")
    if VAAGN.search(t):
        return Handling("vaagn")
    if LUFT_SLUT.search(t):
        return Handling("varme")
    if LUFT.search(t):
        return Handling("luft_ud")
    if m := FART.search(t):
        return Handling("blaeser", valg=m.group(1))
    if (m := GRADER.search(t)) and (m.group(2) or STIL.search(t) or len(t.split()) <= 3):
        return Handling("grader", grader=float((m.group(1) or m.group(2)).replace(",", ".")))
    if OP.search(t):
        return Handling("juster", grader=1.0)
    if NED.search(t):
        return Handling("juster", grader=-1.0)
    if SLUK.search(t):
        return Handling("sluk")
    if TAEND.search(t):
        return Handling("varme")
    for moenster, valg in ((STILLE, "stille"), (KRAFTIG, "kraftig"), (NORMAL, "normal")):
        if moenster.search(t):
            return Handling("styrke", valg=valg)
    return None


def om_varmen(tekst: str) -> bool:
    """Handler beskeden om varmepumpen, uden at være en sikker handling? Så til claude -p
    (aldrig beholdningen: "sluk varmen kl. 22" er ikke en vare)."""
    t = _rens(tekst)
    return bool(VARME_ORD.search(t)) and not BIL.search(t)


async def udfoer(h: Handling) -> str:
    """Giver svaret til husstanden. Fejl siges kort."""
    try:
        if h.hvad == "status":
            return (await status()).tekst()
        if h.hvad == "grader":
            return await saet_grader(h.grader)  # type: ignore[arg-type]
        if h.hvad == "juster":
            return await juster(h.grader)  # type: ignore[arg-type]
        if h.hvad == "styrke":
            return await saet_styrke(h.valg)  # type: ignore[arg-type]
        if h.hvad == "blaeser":
            return await saet_blaeser(h.valg)  # type: ignore[arg-type]
        handlinger = {"varme": varme, "sluk": sluk, "luft_ud": luft_ud, "sov": sov_godt, "vaagn": vaagn}
        return await handlinger[h.hvad]()
    except ha.HAFejl as fejl:
        return f"Det lykkedes ikke: {fejl}"

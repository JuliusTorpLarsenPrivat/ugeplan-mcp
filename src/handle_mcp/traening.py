"""Agil madplan efter træning: Telegram-lytteren tjekker dagens aktivitet og foreslår at bytte
retter, uden AI. Designet: design-agil-madplan-traening.md (godkendt af Julius 10/11-2026).

- Hver 30. min mellem kl. 6 og 21 henter lytteren dagens niveau (rolig, normal, hård, meget hård)
  fra garmin-mcp for hver person med ja i profilens `garmin`.
- Bliver dagen hård, og dagens ret ikke er til en hård dag, foreslås det at bytte med den mest
  passende hårde ret senere i ugen. Registreret før aftensmad: dagens ret. Efter: morgendagens.
- Er en planlagt hård dag rolig, to timer før aftensmad, foreslås det at gemme den hårde ret.
- Fersk fisk (`fast`) flyttes aldrig, og en ret, der skal tøs op (`optoe`), flyttes aldrig til i
  dag. Højst ét forslag om dagen. Det første "ja" afgør det; intet svar inden aftensmad = intet.
- Dagen før en `optoe`-ret skrives der kl. 20: "husk at tage … op af fryseren".
- Alle forslag og påmindelser gemmes i haendelser.json, så fx et dashboard senere kan læse dem.
- Husstanden ser kun niveauet, aldrig de rå tal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time as _time
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from handle_mcp import levering, madplan, profil
from handle_mcp.lokal import laes, skriv

log = logging.getLogger(__name__)
TIDSZONE = ZoneInfo("Europe/Copenhagen")
RANG = {n: i for i, n in enumerate(madplan.NIVEAUER)}  # rolig 0 … meget hård 3; "ukendt" tæller ikke
HAARD = RANG["hård"]
TJEK_HVER_SEK = 30 * 60
FRA_KL, TIL_KL = 6, 21
PAAMINDELSE_KL = 20
ROLIG_TJEK_FOER_AFTENSMAD = timedelta(hours=2)
MAKS_HAENDELSER = 200
DAGNAVNE = {"man": "mandagens", "tir": "tirsdagens", "ons": "onsdagens", "tor": "torsdagens", "fre": "fredagens", "lør": "lørdagens", "søn": "søndagens"}


# --- hvor lytteren henter niveauet -----------------------------------------------------------


def konfiguration() -> dict | None:
    """Kommandoen til garmin-mcp's `belastning --alle --dato`, sat med `ugeplan-mcp garmin-opsaet`."""
    k = laes("garmin-kommando")
    return k if k.get("kommando") else None


def gem_konfiguration(mappe: str, venv: str | None = None) -> dict:
    k = {
        # Fuld sti til uv: på macOS får programmer, som AI-appen starter, kun PATH=/usr/bin:/bin:…,
        # så "uv" i ~/.local/bin bliver ikke fundet (fundet under Mac mini-opsætningen).
        "kommando": [shutil.which("uv") or "uv", "run", "python", "-m", "garmin_mcp.server", "belastning", "--alle", "--dato"],
        "mappe": mappe,
        "miljoe": {"UV_LINK_MODE": "copy", **({"UV_PROJECT_ENVIRONMENT": venv} if venv else {})},
    }
    skriv("garmin-kommando", k)
    return k


def _udvid(vaerdi: str) -> str:
    """%LOCALAPPDATA% og $HOME, på alle styresystemer (mappen kan være sat op på Windows)."""
    vaerdi = re.sub(r"%(\w+)%", lambda m: os.environ.get(m.group(1), m.group(0)), str(vaerdi))
    return os.path.expandvars(os.path.expanduser(vaerdi))


def garmin_installeret() -> bool:
    import importlib.util

    return importlib.util.find_spec("garminconnect") is not None and importlib.util.find_spec("garmin_mcp") is not None


def _fra_samme_pakke(dag: date, personer: list[dict]) -> dict[str, dict]:
    if not garmin_installeret():
        return {}
    try:
        from garmin_mcp import cli as garmin_cli

        alle = garmin_cli.belastning(dag)["personer"]
    except Exception as fejl:  # noqa: BLE001  fx intet login: lytteren skal blive ved
        log.warning("Garmin-niveau kunne ikke hentes (%s)", type(fejl).__name__)
        return {p["navn"]: {"niveau": "ukendt"} for p in personer}
    return _til_profilnavne(alle, personer)


def _til_profilnavne(alle: dict, personer: list[dict]) -> dict[str, dict]:
    ud = {}
    for p in personer:
        d = alle.get(p.get("konto") or p["navn"]) or alle.get(p["navn"].lower()) or {}
        if d.get("fejl") or not d:
            log.warning("Garmin-niveau for %s mangler: %s", p["navn"], str(d.get("fejl") or "personen findes ikke i garmin-mcp")[:200])
        ud[p["navn"]] = d if d.get("niveau") else {"niveau": "ukendt"}
    return ud


def hent_niveauer(dag: date) -> dict[str, dict]:
    """{profilnavn: {"niveau", "aktiviteter", ...}} for personerne med ja i profilen. Tom uden
    opsætning. En person med fejl får niveau "ukendt"."""
    personer = profil.hent().garmin
    k = konfiguration()
    if not personer:
        return {}
    if not k:  # garmin-delen er installeret i samme pakke: hent direkte, uden ekstra kommando
        return _fra_samme_pakke(dag, personer)
    miljoe = {**os.environ, **{n: _udvid(v) for n, v in (k.get("miljoe") or {}).items()}}
    svar = None
    try:
        svar = subprocess.run(
            [*k["kommando"], dag.isoformat()], cwd=k.get("mappe") or None, env=miljoe, capture_output=True, text=True, encoding="utf-8", timeout=180
        )
        data = json.loads(svar.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as fejl:
        # Kun fejltypen og stderr's sidste linje i loggen, aldrig tal fra uret
        sidst = (getattr(svar, "stderr", "") or "").strip().splitlines()[-1:] or [""]
        log.warning("Garmin-niveau kunne ikke hentes (%s): %s", type(fejl).__name__, sidst[0][:200])
        return {p["navn"]: {"niveau": "ukendt"} for p in personer}
    return _til_profilnavne(data.get("personer") or {}, personer)


# --- selve vurderingen (ren funktion, testes uden Telegram og Garmin) -------------------------


def _kl(tekst: str | None) -> time | None:
    if m := re.search(r"(?:^|T|\s)(\d{1,2}):(\d{2})", str(tekst or "")):
        return time(int(m.group(1)), int(m.group(2)))
    return None


def _aftensmad() -> time:
    t, m = (profil.hent().aftensmad or "18:30").split(":")
    return time(int(t), int(m))


def husstandens_niveau(niveauer: dict[str, dict]) -> int | None:
    kendte = [RANG[d["niveau"]] for d in niveauer.values() if d.get("niveau") in RANG]
    return max(kendte) if kendte else None


def _dagsret(ret: str) -> tuple[str, str]:
    """("fredagens", "Nakkekoteletter med ovnkartofler") fra "Fre 13/11: Nakkekoteletter …"."""
    dag, _, navn = ret.partition(":") if ":" in ret else ("", "", ret)
    return DAGNAVNE.get(dag.strip()[:3].lower(), dag.strip().lower()), navn.strip()


def _kan_flyttes(p: madplan.Madplan, ret: str) -> bool:
    return bool(madplan.info_til(p, ret)) and not madplan.info_til(p, ret).get("fast") and not levering.uden_indkoeb(ret)


def vurder(p: madplan.Madplan, niveauer: dict[str, dict], nu: datetime, aftensmad: time) -> dict | None:
    """Et bytteforslag til husstanden, eller None. Kun med retinfo i planen (ellers ved vi ikke,
    hvad der er fersk fisk eller skal tøs op, og så flyttes intet)."""
    if not p.retinfo:
        return None
    hus = husstandens_niveau(niveauer)
    if hus is None:
        return None
    i_dag = nu.date()
    datoer = levering.ret_datoer(p.retter, datetime.fromisoformat(p.oprettet).date())
    spisetid = datetime.combine(i_dag, aftensmad, nu.tzinfo)

    def plads(d: date) -> int | None:
        return next((k for k, x in enumerate(datoer) if x == d), None)

    def niveau(ret: str) -> int:
        return RANG.get(madplan.info_til(p, ret).get("niveau", "normal"), 1)

    if hus >= HAARD:
        tider = [_kl(a.get("slut") or a.get("start")) for d in niveauer.values() if RANG.get(d.get("niveau"), -1) >= HAARD for a in d.get("aktiviteter") or []]
        tider = [t for t in tider if t]
        foer = any(t <= aftensmad for t in tider) if tider else nu < spisetid
        maal_dato = i_dag if foer else i_dag + timedelta(days=1)
        i = plads(maal_dato)
        if i is None or niveau(p.retter[i]) >= HAARD or not _kan_flyttes(p, p.retter[i]):
            return None
        if foer and madplan.info_til(p, p.retter[i]).get("optoe"):
            return None  # dagens vildt er tøet op: det skal ikke flyttes
        kandidater = [
            j
            for j, d in enumerate(datoer)
            if d and d > maal_dato and niveau(p.retter[j]) >= HAARD and _kan_flyttes(p, p.retter[j])
            and not (foer and madplan.info_til(p, p.retter[j]).get("optoe"))  # kan ikke tøs op til i dag
        ]
        if not kandidater:
            return None
        kandidater.sort(key=lambda j: (-(niveau(p.retter[j]) == hus), datoer[j]))
        j = kandidater[0]
        dag_j, ret_j = _dagsret(p.retter[j])
        _, ret_i = _dagsret(p.retter[i])
        grund = "Meget hård dag" if hus >= RANG["meget hård"] else "Hård dag"
        tekst = f"{grund} i dag: byt {dag_j} {ret_j.lower()} og {'dagens' if foer else 'morgendagens'} {ret_i.lower()}? Svar ja"
        return _forslag(p, i, j, tekst, datetime.combine(maal_dato, aftensmad, nu.tzinfo))

    if spisetid - ROLIG_TJEK_FOER_AFTENSMAD <= nu < spisetid:  # udeblevet træning
        i = plads(i_dag)
        if i is None or niveau(p.retter[i]) < HAARD or not _kan_flyttes(p, p.retter[i]):
            return None
        if madplan.info_til(p, p.retter[i]).get("optoe"):
            return None
        kandidater = [
            j
            for j, d in enumerate(datoer)
            if d and d > i_dag and niveau(p.retter[j]) < HAARD and _kan_flyttes(p, p.retter[j]) and not madplan.info_til(p, p.retter[j]).get("optoe")
        ]
        if not kandidater:
            return None
        j = min(kandidater, key=lambda j: datoer[j])
        dag_j, ret_j = _dagsret(p.retter[j])
        _, ret_i = _dagsret(p.retter[i])
        tekst = f"Rolig dag indtil nu: tag {dag_j} {ret_j.lower()} i dag og gem dagens {ret_i.lower()} til en mere aktiv dag? Svar ja"
        return _forslag(p, i, j, tekst, spisetid)
    return None


def _forslag(p: madplan.Madplan, i: int, j: int, tekst: str, gyldig_til: datetime) -> dict:
    return {"type": "bytteforslag", "kode": p.kode, "i": i, "j": j, "retter": [p.retter[i], p.retter[j]], "tekst": tekst, "gyldig_til": gyldig_til.isoformat(timespec="minutes")}


def paamindelse(p: madplan.Madplan, nu: datetime) -> str | None:
    """Kl. 20 dagen før en ret, der skal tøs op."""
    if nu.hour != PAAMINDELSE_KL:
        return None
    datoer = levering.ret_datoer(p.retter, datetime.fromisoformat(p.oprettet).date())
    i_morgen = nu.date() + timedelta(days=1)
    for ret, d in zip(p.retter, datoer):
        if d == i_morgen and madplan.info_til(p, ret).get("optoe"):
            return f"Husk at tage det, der skal bruges til i morgen, op af fryseren: {_dagsret(ret)[1].lower()}."
    return None


# --- hændelser og tilstand -------------------------------------------------------------------


def haendelser() -> list[dict]:
    return laes("haendelser").get("haendelser", [])


def _gem_haendelse(h: dict, nu: datetime | None = None) -> dict:
    h = {"tid": (nu or datetime.now(TIDSZONE)).isoformat(timespec="minutes"), **h}
    skriv("haendelser", {"haendelser": (haendelser() + [h])[-MAKS_HAENDELSER:]})
    return h


def _opdater_haendelse(tid: str, **felter) -> None:
    alle = haendelser()
    for h in alle:
        if h.get("tid") == tid and h.get("type") == "bytteforslag":
            h.update(felter)
    skriv("haendelser", {"haendelser": alle})


def _i_dag_findes(typ: str, dag: date) -> bool:
    return any(h.get("type") == typ and str(h.get("tid", "")).startswith(dag.isoformat()) for h in haendelser())


def ventende_forslag(nu: datetime | None = None) -> dict | None:
    nu = nu or datetime.now(TIDSZONE)
    for h in reversed(haendelser()):
        if h.get("type") == "bytteforslag":
            if h.get("status", "afventer") == "afventer" and datetime.fromisoformat(h["gyldig_til"]) > nu:
                return h
            return None
    return None


# --- det lytteren kalder ---------------------------------------------------------------------


async def koer(nu: datetime | None = None, hent=hent_niveauer) -> list[str]:
    """Én runde fra lytteren. Selvbegrænsende: gør kun noget hver 30. min mellem kl. 6 og 21.
    Giver logtekster uden tal."""
    from handle_mcp import telegram

    nu = nu or datetime.now(TIDSZONE)
    if not (FRA_KL <= nu.hour < TIL_KL) or not profil.hent().garmin or not (konfiguration() or garmin_installeret()):
        return []
    tilstand = laes("traening")
    if _time.time() - float(tilstand.get("sidste_tjek") or 0) < TJEK_HVER_SEK:
        return []
    skriv("traening", {"sidste_tjek": _time.time()})
    p = madplan.seneste_fyldte()
    if p is None:
        return []
    log = []
    if (tekst := paamindelse(p, nu)) and not _i_dag_findes("paamindelse", nu.date()):
        await telegram.send_fra_botten(tekst)
        _gem_haendelse({"type": "paamindelse", "kode": p.kode, "tekst": tekst}, nu)
        log.append("påmindelse om optøning sendt")
    if _i_dag_findes("bytteforslag", nu.date()):
        return log
    niveauer = hent(nu.date())
    if forslag := vurder(p, niveauer, nu, _aftensmad()):
        await telegram.send_fra_botten(forslag["tekst"])
        _gem_haendelse({**forslag, "status": "afventer", "niveau": {n: d.get("niveau") for n, d in niveauer.items()}}, nu)
        log.append("bytteforslag sendt")
    return log


async def besvar(tekst: str, navn: str) -> str | None:
    """Er beskeden et ja til dagens bytteforslag? Så byt, send den nye menu og bekræft. Ellers None
    (så går beskeden videre til AI'en som andre beskeder)."""
    from handle_mcp import telegram

    h = ventende_forslag()
    if not h or not madplan.er_kort_ja(tekst):
        return None
    p = madplan.hent(h["kode"])
    if [p.retter[h["i"]], p.retter[h["j"]]] != h["retter"]:  # planen er ændret siden: byt ikke blindt
        _opdater_haendelse(h["tid"], status="forældet")
        return None
    p = madplan.byt(h["kode"], h["i"], h["j"], hvem=navn)
    _opdater_haendelse(h["tid"], status="ja", svar_fra=navn)
    dag_i = (p.retter[h["i"]].split(":")[0] or "").strip()
    dag_j = (p.retter[h["j"]].split(":")[0] or "").strip()
    await telegram.send_fra_botten(f"Byttet: {dag_j} ↔ {dag_i}. Ugens menu er opdateret.")
    await telegram.send_ugemenu(p)
    return f"bytteforslag godkendt af {navn}"

"""Kommandoer i terminalen (alle via: uv run python -m garmin_mcp.server ...):

    login --person NAVN       spørger om email, kode og evt. MFA-kode, logger ind og gemmer
                              login i nøgleringen og tokens lokalt (én gang pr. person)
    status                    viser hvilke personer der har login (aldrig selve koden)
    test [--person NAVN]      henter gårsdagens søvn og skridt, så du kan se det virker
    belastning [--person NAVN | --alle] [--dato D]
                              skriver dagens niveau (rolig/normal/hård/meget hård) som JSON.
                              Bruges af ugeplan-mcp's lytter, uden AI.
    logout --person NAVN      sletter personens login og tokens
"""

from __future__ import annotations

import getpass
import json
import sys

from garmin_mcp import forbindelse, login, niveau, sundhed

HJAELP = __doc__


def _mfa() -> str:
    return input("MFA-kode fra Garmin (mail eller app): ").strip()


def _flag(args: list[str], navn: str) -> str | None:
    if navn in args:
        i = args.index(navn)
        if i + 1 < len(args):
            vaerdi = args[i + 1]
            if vaerdi.lower() == "i" and i + 2 < len(args):  # --dato i dag / i går uden anførselstegn
                vaerdi = f"i {args[i + 2]}"
            return vaerdi
        raise login.PersonFejl(f"{navn} mangler en værdi.")
    return None


def kommando(args: list[str]) -> int:
    if not args:
        print(HJAELP)
        return 1
    try:
        person = _flag(args, "--person")
        match args[0]:
            case "login":
                return _login(person)
            case "status":
                return _status()
            case "test":
                return _test(person)
            case "belastning":
                return _belastning(person, "--alle" in args, _flag(args, "--dato"))
            case "logout" if person:
                return _logout(person)
    except (login.PersonFejl, sundhed.DatoFejl) as fejl:
        print(fejl)
        return 1
    print(HJAELP)
    return 1


def _status() -> int:
    alle = login.personer()
    if not alle:
        print("Ingen personer er logget ind.")
    for p in alle:
        try:
            email, _ = login.hent(p)
            print(f"{p}: login i nøgleringen ({email}), tokens i {login.personmappe(p)}")
        except login.IntetLogin:
            print(f"{p}: tokens findes, men intet login i nøgleringen")
    return 0


def _test(person: str | None) -> int:
    try:
        g = forbindelse.ny_klient(login.vaelg(person))
        i_gaar = sundhed.dato("i går")
        svar = {"soevn": sundhed.soevn_dag(g, i_gaar), "skridt": sundhed.udvalg(g, [i_gaar], sundhed.SKRIDT)}
    except Exception as fejl:  # noqa: BLE001
        print(forbindelse.oversaet(fejl))
        return 1
    print(json.dumps(svar, ensure_ascii=False, indent=2))
    return 0


def belastning(dag, navne: list[str] | None = None) -> dict:
    """{"dato": ..., "personer": {navn: {...niveau...} | {"fejl": ...}}} for alle (eller de givne)
    personer. Bruges af kommandoen og direkte af ugeplan-mcp's lytter, når begge er installeret."""
    ud: dict = {"dato": dag.isoformat(), "personer": {}}
    for p in login.personer() if navne is None else navne:
        try:
            (ud["personer"][p],) = niveau.beregn_periode(forbindelse.ny_klient(p), [dag])
        except Exception as fejl:  # noqa: BLE001  én persons fejl må ikke stoppe de andre
            ud["personer"][p] = {"fejl": str(forbindelse.oversaet(fejl))}
    return ud


def _belastning(person: str | None, alle: bool, dato: str | None) -> int:
    """JSON til stdout: {"dato": ..., "personer": {navn: {...niveau...} | {"fejl": ...}}}."""
    dag = sundhed.dato(dato)
    ud = belastning(dag, None if alle else [login.vaelg(person)])
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(ud, ensure_ascii=False))
    return 0 if all("fejl" not in v for v in ud["personer"].values()) else 1


def _logout(person: str) -> int:
    person = login.navn(person)
    print("Login slettet fra nøgleringen." if login.slet(person) else "Der var intet gemt login.")
    fil = login.tokenfil(person)
    if fil.exists():
        fil.unlink()
        print(f"Tokens slettet ({fil}).")
    print("Tokens kan også trækkes tilbage hos Garmin: Konto → Sikkerhed → Forbundne apps/enheder.")
    return 0


def _login(person: str | None) -> int:
    from garminconnect import Garmin

    from garmin_mcp import vagt

    if not person:
        print("Angiv hvem der logger ind, fx: login --person anna")
        return 1
    person = login.navn(person)
    email = input(f"Email til Garmin Connect ({person}): ").strip()
    kode = getpass.getpass("Kode (vises ikke): ")
    if not email or not kode:
        print("Både email og kode skal udfyldes.")
        return 1
    vagt.installer()
    try:
        g = Garmin(email, kode, prompt_mfa=_mfa)
        g.login()  # uden token-mappe: tjekker email og kode direkte hos Garmin
        mappe = login.personmappe(person)
        mappe.mkdir(parents=True, exist_ok=True)
        g.client.dump(str(mappe))
    except Exception as fejl:  # noqa: BLE001  et forkert login må ikke blive gemt
        print(f"Login virkede ikke, så intet er gemt: {forbindelse.oversaet(fejl)}")
        return 1
    login.gem(person, email, kode)
    print(f"Login for {person} virker. Email og kode ligger i nøgleringen (garmin-mcp),")
    print(f"og Garmins tokens ligger i {login.tokenfil(person)}.")
    return 0

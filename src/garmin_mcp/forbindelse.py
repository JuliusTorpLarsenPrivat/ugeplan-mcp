"""Forbindelsen til Garmin Connect, én pr. person.

Første kald for en person logger ind med de gemte tokens fra `login` (ingen MFA). Tokens
fornyes automatisk af biblioteket. Holder de op med at virke, prøver biblioteket med email
og kode fra nøgleringen. Kræver Garmin så en MFA-kode, kan serveren ikke spørge (den
kører i baggrunden), og du får besked om at køre `login` igen i en terminal.

Sundhedsdata gemmes ikke: de hentes, når de skal bruges, og glemmes igen.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from garmin_mcp import login, vagt

log = logging.getLogger(__name__)

_klienter: dict[str, Any] = {}
_laas = threading.Lock()


class GarminFejl(Exception):
    """En fejl, der kan vises direkte til Claude/brugeren."""


def _login_besked(person: str) -> str:
    return f"Kør i en terminal: uv run python -m garmin_mcp.server login --person {person}"


def ny_klient(person: str, prompt_mfa: Callable[[], str] | None = None) -> Any:
    """Log ind som `person` og giv en klar Garmin-klient."""
    from garminconnect import Garmin

    vagt.installer()
    email, kode = login.hent(person)
    mappe = login.personmappe(person)
    mappe.mkdir(parents=True, exist_ok=True)

    def ingen_mfa() -> str:
        raise GarminFejl(f"Garmin beder om en MFA-kode for {person}. {_login_besked(person)}")

    g = Garmin(email, kode, prompt_mfa=prompt_mfa or ingen_mfa)
    g.login(str(mappe))
    return g


def klient(person: str | None = None) -> Any:
    """Den fælles klient for personen (logges ind ved første kald)."""
    p = login.vaelg(person)
    with _laas:
        if p not in _klienter:
            _klienter[p] = ny_klient(p)
        return _klienter[p]


def glem_klient(person: str | None = None) -> None:
    with _laas:
        if person is None:
            _klienter.clear()
        else:
            _klienter.pop(person, None)


def oversaet(fejl: Exception) -> Exception:
    """Gør bibliotekets fejl forståelige. Login-fejl får også klienterne til at blive glemt."""
    from garminconnect import (
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )

    if isinstance(fejl, (GarminFejl, vagt.VagtFejl)):
        return fejl
    if isinstance(fejl, (login.IntetLogin, login.PersonFejl)):
        return GarminFejl(str(fejl))
    if isinstance(fejl, GarminConnectAuthenticationError):
        glem_klient()
        return GarminFejl("Garmin-login virker ikke længere. Kør i en terminal: uv run python -m garmin_mcp.server login --person <navn>")
    if isinstance(fejl, GarminConnectTooManyRequestsError):
        return GarminFejl("Garmin siger, at der er sendt for mange forespørgsler. Vent lidt og prøv igen.")
    if isinstance(fejl, GarminConnectConnectionError):
        return GarminFejl(f"Garmin svarede med en fejl: {fejl}")
    log.warning("Uventet fejl: %s", type(fejl).__name__)
    return GarminFejl(f"Uventet fejl fra Garmin-biblioteket ({type(fejl).__name__}). Prøv igen, eller opdatér garminconnect.")

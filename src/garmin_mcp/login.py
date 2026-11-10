"""Hvor Garmin-login og login-tokens bor, for hver person i husstanden.

- Email og kode ligger i styresystemets nøglering under tjenesten "garmin-mcp" og kontoen
  "person:<navn>" (Windows Credential Manager, macOS Keychain). Nøgleringen krypterer selv,
  og kun brugeren på maskinen kan læse den.
- Garmins login-tokens ligger i en mappe pr. person:
  %LOCALAPPDATA%\\garmin-mcp\\<navn>\\garmin_tokens.json (Windows) eller
  ~/.local/share/garmin-mcp/<navn>/ (macOS/Linux). Ikke i OneDrive.

Den første version havde kun én person uden navn. Det login virker stadig og hedder
"standard".

Login gemmes aldrig i en fil i projektet, i Claude-konfigurationen eller på GitHub.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import keyring
import keyring.errors

TJENESTE = "garmin-mcp"  # navnet du ser i Windows Credential Manager
STANDARD = "standard"
_GAMMEL_KONTO = "garmin-connect"
TOKENFIL = "garmin_tokens.json"
_NAVN = re.compile(r"^[a-z0-9æøå][a-z0-9æøå_-]{0,39}$")


class IntetLogin(Exception):
    pass


class PersonFejl(ValueError):
    pass


def tokenmappe() -> Path:
    """%LOCALAPPDATA%\\garmin-mcp på Windows, ellers ~/.local/share/garmin-mcp."""
    rod = os.environ.get("LOCALAPPDATA")
    if rod:
        return Path(rod) / "garmin-mcp"
    return Path.home() / ".local" / "share" / "garmin-mcp"


def navn(person: str) -> str:
    """'Anna' → 'anna'. Kun bogstaver, tal, - og _, så navnet kan bruges som mappe."""
    n = (person or "").strip().lower()
    if not _NAVN.match(n):
        raise PersonFejl(f"Ugyldigt personnavn '{person}'. Brug fx 'anna' (bogstaver, tal, - og _).")
    return n


def _konto(person: str) -> str:
    return _GAMMEL_KONTO if person == STANDARD else f"person:{person}"


def personmappe(person: str) -> Path:
    person = navn(person)
    return tokenmappe() if person == STANDARD else tokenmappe() / person


def tokenfil(person: str) -> Path:
    return personmappe(person) / TOKENFIL


def personer() -> list[str]:
    """Alle personer med gemte tokens på denne maskine."""
    rod = tokenmappe()
    if not rod.is_dir():
        return []
    ud = [STANDARD] if (rod / TOKENFIL).exists() else []
    ud += sorted(p.name for p in rod.iterdir() if p.is_dir() and (p / TOKENFIL).exists() and _NAVN.match(p.name))
    return ud


def vaelg(person: str | None) -> str:
    """Personen, der skal bruges. Uden navn: den eneste person, ellers en fejl med listen."""
    if person:
        return navn(person)
    alle = personer()
    if len(alle) == 1:
        return alle[0]
    if not alle:
        raise IntetLogin("Intet Garmin-login. Kør i en terminal: uv run python -m garmin_mcp.server login --person <navn>")
    raise PersonFejl(f"Der er flere Garmin-personer. Angiv person: {', '.join(alle)}")


def hent(person: str) -> tuple[str, str]:
    """(email, kode) fra nøgleringen, eller IntetLogin."""
    person = navn(person)
    try:
        gemt = keyring.get_password(TJENESTE, _konto(person))
    except keyring.errors.KeyringError:
        gemt = None
    if gemt:
        data = json.loads(gemt)
        return data["email"], data["kode"]
    raise IntetLogin(f"Intet Garmin-login for {person}. Kør i en terminal: uv run python -m garmin_mcp.server login --person {person}")


def gem(person: str, email: str, kode: str) -> None:
    keyring.set_password(TJENESTE, _konto(navn(person)), json.dumps({"email": email, "kode": kode}))


def slet(person: str) -> bool:
    try:
        keyring.delete_password(TJENESTE, _konto(navn(person)))
        return True
    except keyring.errors.PasswordDeleteError:
        return False

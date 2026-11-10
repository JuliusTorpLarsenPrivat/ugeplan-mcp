"""Kommandoer i terminalen:

    ugeplan-mcp opsaet          guide til første opsætning: butikker, Telegram og din AI-app
    ugeplan-mcp login nemlig   spørger om email og kode, tjekker dem hos butikken og gemmer dem
    ugeplan-mcp logout nemlig   sletter det gemte login
    ugeplan-mcp status          viser hvilke butikker der har et gemt login (aldrig selve koden)
    ugeplan-mcp telegram-opsaet gemmer jeres Telegram-bot og giver en kode til at koble telefoner på
    ugeplan-mcp telegram [timer] lytter efter jeres svar (standard 24 timer). "OK UGE-xxxx" fylder kurven
    ugeplan-mcp telegram-par    ny kode til at koble en telefon på
    ugeplan-mcp telegram-frakobl kobler alle telefoner fra
    ugeplan-mcp garmin-opsaet MAPPE [VENV]
                               lytteren henter dagens træningsniveau fra garmin-mcp i MAPPE
    ugeplan-mcp http-noegle     laver en ny adgangsnøgle til HTTP-tilstand (vises kun én gang)
    ugeplan-mcp http [host] [port]
                               kører serveren over HTTP i stedet for stdio.
                               Standard: 127.0.0.1 8765 (kun denne maskine)
"""

from __future__ import annotations

import asyncio
import getpass
import re

from handle_mcp import login
from handle_mcp.butikker import hent_butik

HJAELP = __doc__


def _udklipsholder() -> str:
    """Teksten i Windows' udklipsholder (uden at vise den)."""
    import subprocess

    svar = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, encoding="utf-8")
    return svar.stdout or ""


async def _telegram_opsaet(fra_udklipsholder: bool = False) -> int:
    from handle_mcp import telegram

    if fra_udklipsholder:
        raa = _udklipsholder()
    else:
        print("1. Åbn Telegram, skriv til @BotFather, send /newbot og følg trinene.")
        print("2. Indsæt den botnøgle, du får (den vises ikke, mens du skriver), og tryk Enter.")
        print("   Driller det? Kopiér nøglen og kør i stedet: ugeplan-mcp telegram-opsaet udklipsholder")
        raa = getpass.getpass("Botnøgle: ")
    # Find selve nøglen, så ekstra tegn fra indsættelsen ikke ødelægger den
    fund = re.findall(r"\d{5,15}:[A-Za-z0-9_-]{30,50}", raa)
    if len(fund) != 1:
        hvad = "ingen nøgle" if not fund else f"{len(fund)} nøgler"
        print(f"Det, der blev indsat ({len(raa.strip())} tegn), indeholder {hvad}. Intet er gemt. Prøv igen.")
        return 1
    token = fund[0]
    print(f"Modtog nøgle til bot nr. {token.split(':')[0]} ({len(token)} tegn). Tjekker den hos Telegram …")
    try:
        navn = await telegram.bot_navn(token)
        telegram.gem_token(token)
    except telegram.TelegramFejl as fejl:
        print(f"Det virkede ikke, og intet er gemt: {fejl}")
        return 1
    kode = telegram.ny_parringskode()
    print(f"\nBotten {navn} er gemt i styresystemets nøglering.")
    print(f"3. Start lytteren: ugeplan-mcp telegram")
    print(f"4. Søg {navn} frem i Telegram på begge telefoner og send koden {kode} (gyldig i 30 minutter).")
    return 0


async def _telegram_lyt(timer: float, foraelder: int | None = None) -> int:
    """Lyt efter beskeder i `timer` timer, eller så længe processen `foraelder` (serveren) kører.
    Stop med Ctrl+C."""
    import time

    from handle_mcp import telegram

    from datetime import datetime

    if not telegram.tag_laas():
        print("En lytter kører allerede. Denne stopper igen.")
        return 0
    try:
        navn = await telegram.bot_navn()
    except telegram.TelegramFejl as fejl:
        print(fejl)
        return 1
    start = datetime.now(telegram.TIDSZONE).isoformat(timespec="minutes")
    hvor_laenge = f"så længe AI-appen kører (proces {foraelder})" if foraelder else f"i højst {timer:g} timer"
    print(f"{time.strftime('%d-%m %H:%M')} Lytter efter beskeder til {navn} {hvor_laenge}. Stop med Ctrl+C.", flush=True)
    print(f"Tilkoblede: {', '.join(telegram.chats().values()) or 'ingen endnu'}", flush=True)
    from handle_mcp import genindlaes

    genindlaes.start()
    slut = time.monotonic() + timer * 3600
    fejl_i_traek = 0
    afsluttet = False
    while time.monotonic() < slut or foraelder:
        if foraelder and not telegram.proces_lever(foraelder):
            print(f"{time.strftime('%H:%M')} AI-appen er lukket. Lytteren stopper.", flush=True)
            return 0
        try:  # ny kode uden at genstarte lytteren (som serveren, se genindlaes.py)
            if nye := genindlaes.tjek():
                print(f"{time.strftime('%H:%M')} Ny kode indlæst: {len(nye)} moduler", flush=True)
        except Exception as fejl:  # noqa: BLE001  en tastefejl må ikke stoppe lytteren
            print(f"{time.strftime('%H:%M')} Ny kode kunne ikke indlæses, kører videre: {fejl}", flush=True)
        try:  # Claude kan selv have fyldt kurven (fx "bestil" lige efter en rettelse)
            if await telegram.send_ugemenu_hvis_mangler():
                print(f"{time.strftime('%H:%M')} Ugemenu sendt og fastgjort", flush=True)
        except Exception as fejl:  # noqa: BLE001
            print(f"{time.strftime('%H:%M')} Ugemenu kunne ikke sendes: {fejl}", flush=True)
        if not afsluttet and telegram.ugen_er_afsluttet(start):
            # Lyt videre: fundet i uge 46 kom der en rettelse 8 min. efter, at kurven var fyldt,
            # og den gik tabt, fordi lytteren stoppede her. Nu bliver den gemt og besvaret.
            afsluttet = True
            print(f"{time.strftime('%H:%M')} Ugens plan er afsluttet. Lytter videre efter rettelser.", flush=True)
        try:  # agil madplan efter træning (selvbegrænsende: hver 30. min kl. 6-21)
            from handle_mcp import traening

            for h in await traening.koer():
                print(f"{time.strftime('%H:%M')} {h}", flush=True)
        except Exception as fejl:  # noqa: BLE001  må aldrig stoppe lytteren
            print(f"{time.strftime('%H:%M')} Træningstjek fejlede: {type(fejl).__name__}", flush=True)
        try:
            for h in await telegram.hent_og_haandter(vent_sekunder=25):
                print(f"{time.strftime('%H:%M')} {h}", flush=True)
            fejl_i_traek = 0
        except telegram.TelegramFejl as fejl:
            fejl_i_traek += 1
            print(f"{time.strftime('%H:%M')} {fejl}", flush=True)
            await asyncio.sleep(min(300, 10 * fejl_i_traek))  # nettet er væk: vent længere og længere
    print("Tiden er gået. Lytteren stopper.")
    return 0


def _login(butik: str) -> int:
    email = input(f"Email til {butik}: ").strip()
    kode = getpass.getpass("Kode (vises ikke): ")
    if not email or not kode:
        print("Både email og kode skal udfyldes.")
        return 1
    login.gem(butik, email, kode)
    try:
        asyncio.run(hent_butik(butik).log_ind())
    except Exception as fejl:  # noqa: BLE001  forkert login skal ikke blive liggende
        login.slet(butik)
        print(f"Login virkede ikke, så intet er gemt: {fejl}")
        return 1
    print(f"Login til {butik} virker og er gemt i styresystemets nøglering.")
    return 0


NAVNE = {"nemlig": "nemlig.com", "bilka": "BilkaToGo"}


def _ja(spoergsmaal: str) -> bool:
    try:
        return input(f"{spoergsmaal} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        print()
        return False


def server_kommando() -> tuple[str, list[str]]:
    """Kommandoen, en AI-app skal starte serveren med (MCP over stdio). Den samme for alle apps."""
    import shutil
    from importlib.metadata import PackageNotFoundError, version

    try:
        v = version("ugeplan-mcp")
    except PackageNotFoundError:
        v = None
    kilde = "git+https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp" + (f"@v{v}" if v else "")
    return shutil.which("uvx") or "uvx", ["--from", kilde, "ugeplan-mcp"]


def claude_config() -> dict:
    """Det, der skal stå i Claude Desktops claude_desktop_config.json (samme form som Cursor m.fl.)."""
    cmd, args = server_kommando()
    return {"mcpServers": {"ugeplan": {"command": cmd, "args": args}}}


# Serveren er almindelig MCP og er ikke bundet til én AI. Julius: "det skal være åbent".
# Hver app har sin egen måde at få den ind på; teksten er den samme kommando i forskellig form.
KLIENTER = {
    "1": "Claude Desktop",
    "2": "Claude Code",
    "3": "Cursor",
    "4": "VS Code (GitHub Copilot)",
    "5": "En anden app med MCP",
}


def klient_vejledning(valg: str) -> str:
    """Hvordan serveren sættes ind i den valgte AI-app."""
    import json
    import os
    import shlex

    cmd, args = server_kommando()
    standard = json.dumps(claude_config(), indent=2, ensure_ascii=False)
    if valg == "1":
        sti = os.path.join(os.environ.get("APPDATA", "~"), "Claude", "claude_desktop_config.json")
        return (
            "I Claude Desktop: Settings > Developer > Edit Config. Læg dette ind under \"mcpServers\"\n"
            f"(filen ligger normalt i {sti}):\n\n{standard}\n\n"
            "Genstart Claude Desktop helt (også ikonet i proceslinjen)."
        )
    if valg == "2":
        linje = "claude mcp add --scope user ugeplan -- " + " ".join(shlex.quote(a) for a in [cmd, *args])
        return f"Kør i en terminal:\n\n  {linje}\n\nStart så en ny Claude Code-session."
    if valg == "3":
        return f"Læg dette i ~/.cursor/mcp.json (eller Cursor Settings > MCP > Add):\n\n{standard}\n\nGenstart Cursor."
    if valg == "4":
        vs = json.dumps({"servers": {"ugeplan": {"type": "stdio", "command": cmd, "args": args}}}, indent=2, ensure_ascii=False)
        return (
            "I VS Code: Kommandopaletten > \"MCP: Open User Configuration\", og læg dette ind:\n\n"
            f"{vs}\n\nBrug Copilot Chat i Agent-tilstand."
        )
    return (
        "Appen skal kunne starte en lokal MCP-server (stdio). Brug denne kommando:\n\n"
        f"  kommando:   {cmd}\n  argumenter: {' '.join(args)}\n\n"
        "Mange apps vil have den i denne form:\n\n"
        f"{standard}\n\n"
        "Kan appen kun forbinde til en server over nettet, så se \"Over netværket\" i README."
    )


def _opsaet() -> int:
    """Første opsætning, ét trin ad gangen. Alt kan springes over og tages senere."""
    print("Velkommen til ugeplan-mcp. Tre korte trin, og alle kan springes over med Enter.\n")

    print("TRIN 1/3: BUTIKKER")
    print("Med login kan AI-assistenten fylde kurven (du betaler altid selv i butikkens app).")
    print("Uden login virker nemligs priser og opskrifter stadig, men kurven kan ikke fyldes.")
    for butik in login.BUTIKKER:
        if login.har_login(butik):
            print(f"  {NAVNE[butik]}: login er allerede gemt.")
        elif _ja(f"  Har du en konto hos {NAVNE[butik]} med hjemlevering, som skal bruges?"):
            while _login(butik) and _ja("  Prøv igen?"):
                pass
    if "bilka" in login.aktive():
        print("  Husk: vælg hjemlevering én gang på bilkatogo.dk, ellers kan der ikke vises leveringstider.")

    print("\nTRIN 2/3: TELEGRAM (valgfrit)")
    print("Så kan hele husstanden svare fra telefonen: hvad der er i køleskabet, rettelser og \"bestil\".")
    print("Uden Telegram foregår det hele i chatten med AI-assistenten.")
    if _ja("  Skal I bruge Telegram?"):
        asyncio.run(_telegram_opsaet())

    print("\nTRIN 3/3: DIN AI-APP")
    print("ugeplan-mcp er en MCP-server og virker med de AI-apps, der kan bruge MCP. Hvilken bruger du?")
    for nr, navn in KLIENTER.items():
        print(f"  {nr}) {navn}")
    try:
        valg = input("Vælg 1-5 [5]: ").strip() or "5"
    except EOFError:
        print()
        valg = "5"
    print("\n" + klient_vejledning(valg))

    print("\nKLAR. Skriv \"lav madplan\" til AI-assistenten. Første gang stiller den et par korte spørgsmål om")
    print("jeres husstand: antal, budget, hvad I kan lide og ikke spiser, faste måltider og")
    print("bestemte varer. Det bliver gemt i jeres profil, kun på denne computer.")
    print("Kør `ugeplan-mcp opsaet` igen, når som helst, eller `ugeplan-mcp status` for at se, hvad der er sat op.")
    return 0


def _sikker_udskrift() -> None:
    """Windows-terminaler, der ikke kører UTF-8, må ikke få kommandoen til at gå ned på æ, ø
    eller en pil (fundet ved første installation udefra)."""
    import sys

    for strøm in (sys.stdout, sys.stderr):
        try:
            strøm.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def kommando(args: list[str]) -> int:
    _sikker_udskrift()
    match args:
        case ["opsaet"] | ["setup"]:
            return _opsaet()
        case ["login", butik] if butik in login.BUTIKKER:
            return _login(butik)
        case ["logout", butik] if butik in login.BUTIKKER:
            print("Slettet." if login.slet(butik) else "Der var intet gemt login.")
            return 0
        case ["status"]:
            for butik in login.BUTIKKER:
                try:
                    email, _ = login.hent(butik)
                    print(f"{butik}: gemt ({email})")
                except login.IntetLogin:
                    print(f"{butik}: intet login")
            return 0
        case ["telegram-opsaet"]:
            return asyncio.run(_telegram_opsaet())
        case ["telegram-opsaet", "udklipsholder"]:
            return asyncio.run(_telegram_opsaet(fra_udklipsholder=True))
        case ["telegram-par"]:
            from handle_mcp import telegram

            print(f"Ny parringskode (gyldig i 30 minutter): {telegram.ny_parringskode()}")
            print("Send koden til botten fra den telefon, der skal kobles på.")
            return 0
        case ["telegram-frakobl"]:
            from handle_mcp import telegram

            print(f"{telegram.frakobl_alle()} telefoner er koblet fra. Kør telegram-par for at koble på igen.")
            return 0
        case ["garmin-opsaet", mappe, *venv] if len(venv) <= 1:
            from handle_mcp import traening

            traening.gem_konfiguration(mappe, venv[0] if venv else None)
            print(f"Lytteren henter nu dagens niveau fra garmin-mcp i {mappe}.")
            print("Husk at sige ja i profilen, fx: \"Julius må bruge sine Garmin-data\" til AI-assistenten.")
            return 0
        case ["telegram", "--foraelder", pid] if pid.isdigit():
            return asyncio.run(_telegram_lyt(24.0, foraelder=int(pid)))
        case ["telegram", *rest] if len(rest) <= 1:
            try:
                timer = float(rest[0]) if rest else 24.0
            except ValueError:
                print("Antal timer skal være et tal, fx: ugeplan-mcp telegram 12")
                return 1
            return asyncio.run(_telegram_lyt(timer))
        case ["http-noegle"]:
            from handle_mcp import netvaerk

            print("Ny adgangsnøgle (den gamle virker ikke længere). Den vises kun nu:")
            print(netvaerk.ny_noegle())
            return 0
        case ["http", *rest] if len(rest) <= 2:
            from handle_mcp import netvaerk
            from handle_mcp.server import mcp

            host = rest[0] if rest else "127.0.0.1"
            try:
                port = int(rest[1]) if len(rest) == 2 else 8765
            except ValueError:
                print("Porten skal være et tal, fx: ugeplan-mcp http 127.0.0.1 8765")
                return 1
            return netvaerk.koer(mcp, host, port)
        case _:
            print(HJAELP)
            return 1

"""Svar på fri tekst med det samme: lytteren spørger headless Claude Code (`claude -p`).

Når ingen AI-assistent er i gang, og en koblet telefon skriver noget, som botten ikke selv
klarer (fx "hvad skal vi have i aften?" eller "hvordan sov jeg?"), kalder lytteren
`claude -p` med ugeplan- og Garmin-serverne og sender svaret tilbage på Telegram.

Regler:
  - Faste kommandoer (OK UGE-xxxx, ja til bytteforslag, menu, beholdning) klares stadig af
    botten selv, uden AI. Dette modul bruges først bagefter.
  - Højst MAKS_PR_TIME kørsler i timen for hele husstanden. Derefter en kort besked.
  - Kun værktøjer, der læser. Claude kan herfra hverken ændre kurven, planen, profilen eller
    beholdningen, og intet i ugeplan-mcp kan bestille eller betale. Eneste undtagelse er bilen
    (bil_*-værktøjerne), når Home Assistant er sat op; resten af Home Assistant kun læsning.
  - Kører på brugerens eget Claude-abonnement (login i Claude Code). En API-nøgle i miljøet
    fjernes, så der aldrig betales pr. kald ved en fejl.
  - Slås fra med {"fra": true} i claude_p.json i datamappen, eller ved at `claude` ikke findes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

from handle_mcp import ha, lokal

log = logging.getLogger(__name__)

AKTIV = True  # slås fra i testene, så de aldrig kalder en rigtig claude
FIL = "claude_p"
MAKS_PR_TIME = 20
TIMEOUT_SEK = 240
HEADLESS_ENV = "UGEPLAN_HEADLESS"  # sat for serverne, som claude -p starter
HISTORIK = 10  # så mange tidligere beskeder får Claude med som sammenhæng
SVAR_TIL = re.compile(r"^\s*(?:svar til [^:\n]{1,40}:\s*)+", re.I)  # bottens egne svar gemmes med det præfiks

GRAENSE_TEKST = (
    f"Jeg har svaret på {MAKS_PR_TIME} beskeder den sidste time og holder en pause. "
    "Beskeden er gemt til AI-assistenten. Prøv igen om lidt."
)
FEJL_TEKST = "Jeg kunne ikke svare lige nu. Beskeden er gemt til AI-assistenten."

# Kun værktøjer, der læser. ugeplan_forloeb er udeladt: den sætter et madplansforløb i gang,
# som kræver skrivende værktøjer og svar fra husstanden.
UGEPLAN_LAES = (
    "vis_madplan",
    "vis_opskrifter",
    "hent_opskrift",
    "hent_opskrift_fra_link",
    "soeg_opskrifter",
    "vis_kurv",
    "vis_beholdning",
    "vis_profil",
    "soeg_varer",
    "sammenlign_liste",
    "ugens_tilbud",
    "leveringstider",
    "tidligere_ordrer",
    "koebsmoenster",
)

# Bilen (ugeplan-mcp's egne værktøjer, se ha.py): de eneste ændringer i Home Assistant, Claude
# kan lave herfra. Julius 26/11-2026: claude -p må læse og styre bilen.
UGEPLAN_BIL = ("bil_status", "bil_forbrug", "bil_klar", "bil_lad_til", "bil_planlaeg", "bil_forvarm", "bil_forvarmning", "bil_oplad")

# Home Assistant-MCP'en (samme som i AI-appen), kun værktøjer der læser. ha_call_service og
# alle andre skrivende værktøjer gives aldrig.
HA_LAES = ("ha_get_state", "ha_search", "ha_get_history", "ha_get_overview", "ha_get_entity", "ha_list_floors_areas")

SYSTEM = """Du svarer husstanden på Telegram gennem deres madplans-bot. Ingen kan svare dig tilbage i denne samtale, så svar færdigt i ét svar.
- Svar kort på dansk i almindelig tekst: ingen tabeller, ingen overskrifter, højst ca. 1.000 tegn.
- Brug værktøjerne til at slå op i madplan, opskrifter, kurv, beholdning, profil, tilbud og Garmin-data, før du svarer. Gæt ikke.
- Du kan herfra ikke ændre kurven, madplanen, profilen eller beholdningen, og der bestilles og betales aldrig. Beder de om en ændring, så sig kort, hvordan de selv gør: "OK UGE-xxxx" godkender en plan, "har 2 kg kartofler" retter beholdningen, og alt andet kan de bede AI-assistenten i appen om.
- Garmin-data er helbredsdata: nævn kun de tal, der svarer på spørgsmålet, og stil ingen diagnoser.
- Bilen (BMW i3s): bil_status viser klar-tid, mål i nat, planlagt opladning, batteri, elpris, forvarmning og planlagte undtagelser. bil_klar sætter, hvornår bilen skal være klar næste morgen (kun denne gang, evt. med %), eller "normal" for tilbage til fast tid (fx "i morgen først kl 8" = bil_klar("08:00")). bil_lad_til sætter ladeniveauet hver nat eller kun i nat. bil_planlaeg lægger en undtagelse en bestemt dato. Én undtagelse pr. dag; en ny erstatter den gamle. bil_forvarm starter klimaanlægget nu; bil_forvarmning slår automatikken til/fra og sætter temperaturgrænsen. bil_oplad starter eller stopper opladningen nu. bil_forbrug giver opladningens kWh, kr., CO2 og kr./kWh (sidste opladning, 24 t, i dag, 7 dage, denne måned, i år, i alt, i går og sidste måned; talt fra 26/11-2026) og strømprisen nu og de kommende timer: brug det til spørgsmål om pris, kWh og CO2 for opladning, og om det er billigt at lade nu. Svar kun på den periode, der spørges om, i én kort sætning, ikke hele tabellen. "I nat"/"i morges" er normalt seneste 24 t (eller i dag, hvis den er 0); sent på aftenen er det den opladning, der sluttede i morges, så brug sidste opladning eller i går og sig, hvad du har brugt. Har tabellen ikke perioden (fx "i oktober" eller "sidste uge"), så sig, hvad den har, og at der kun er tal fra 26/11. Skriv tal med dansk komma. Gør kun det, der bliver bedt om, og sig bagefter, hvad der er sat. De faste beskeder virker også uden dig: "bil", "klar 7", "klar 7 100%", "klar normal", "klar 5/12 5:30 100%", "undtagelser", "lad til 90", "lad til 100 i nat", "forvarm nu", "forvarmning til/fra", "oplad nu", "stop opladning".
- Læs de seneste beskeder: korte beskeder som "slet den igen", "nej, kl. 9 i stedet" eller "ja" handler om det, der lige er skrevet om. Handler det om bilen, så gør det med bil_*-værktøjerne (fx "slet undtagelsen igen" = bil_klar("normal")). Er det stadig uklart, så spørg kort i dit svar i stedet for at gætte.
- Start ikke svaret med "Svar til …": skriv bare svaret.
- Home Assistant (homeassistant-værktøjerne) kan du kun læse i, fx elpris, varmepumpe og temperaturer. Andet end bilen kan ikke ændres herfra."""


def _indstillinger() -> dict:
    try:
        return lokal.laes(FIL)
    except lokal.LokalFejl:
        return {}


def find_claude() -> str | None:
    """Stien til `claude`. Appen giver lytteren en kort PATH, så de officielle steder prøves også."""
    if sti := _indstillinger().get("claude"):
        return sti if Path(sti).is_file() else None
    if sti := shutil.which("claude"):
        return sti
    hjem = Path.home()
    kandidater = [hjem / ".local" / "bin" / "claude", Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    if sys.platform == "win32":
        kandidater = [hjem / ".local" / "bin" / "claude.exe"]
    return next((str(k) for k in kandidater if k.is_file()), None)


def slaaet_til() -> bool:
    return AKTIV and not _indstillinger().get("fra") and find_claude() is not None


def tag_plads(nu: float | None = None) -> bool:
    """Tæl en kørsel med, hvis der er plads i timen. False, når grænsen er nået."""
    nu = time.time() if nu is None else nu
    d = _indstillinger()
    seneste = [t for t in d.get("koersler", []) if nu - t < 3600]
    if len(seneste) >= MAKS_PR_TIME:
        return False
    d["koersler"] = [*seneste, nu]
    lokal.skriv(FIL, d)
    return True


def _desktop_konfig() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home()), "Claude", "claude_desktop_config.json")
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def mcp_konfig() -> dict:
    """De samme servere, som AI-appen starter (ugeplan og garmin), så claude -p bruger samme
    installation. Findes konfigurationen ikke, startes ugeplan med denne Python."""
    try:
        servere = json.loads(_desktop_konfig().read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError):
        servere = {}
    ud = {}
    for navn in ("ugeplan", "garmin", "homeassistant"):
        if isinstance(s := servere.get(navn), dict) and s.get("command"):
            ud[navn] = {"command": s["command"], "args": list(s.get("args", [])), "env": dict(s.get("env", {}))}
    if "ugeplan" not in ud:
        ud["ugeplan"] = {"command": sys.executable, "args": ["-m", "handle_mcp.server"], "env": {}}
    for s in ud.values():
        s["env"][HEADLESS_ENV] = "1"
        if data := os.environ.get("HANDLE_MCP_DATA"):
            s["env"]["HANDLE_MCP_DATA"] = data
    return {"mcpServers": ud}


def tilladte_vaerktoejer(konfig: dict) -> list[str]:
    ud = [f"mcp__ugeplan__{v}" for v in UGEPLAN_LAES]
    if ha.sat_op():
        ud += [f"mcp__ugeplan__{v}" for v in UGEPLAN_BIL]
    if "garmin" in konfig["mcpServers"]:
        ud.append("mcp__garmin")  # Garmin-serveren kan kun læse
    if "homeassistant" in konfig["mcpServers"]:
        ud += [f"mcp__homeassistant__{v}" for v in HA_LAES]
    return ud


def kommando(claude: str, prompt: str, konfig: dict) -> list[str]:
    return [
        claude,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--mcp-config",
        json.dumps(konfig),
        "--strict-mcp-config",
        "--tools",
        "",  # ingen indbyggede værktøjer (Bash, filer, web)
        "--allowedTools",
        ",".join(tilladte_vaerktoejer(konfig)),
        "--permission-mode",
        "dontAsk",  # alt, der ikke er tilladt ovenfor, afvises
        "--no-session-persistence",
        "--append-system-prompt",
        SYSTEM,
    ]


def _miljoe() -> dict[str, str]:
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)  # abonnementet, aldrig betaling pr. kald
    bin_ = str(Path.home() / ".local" / "bin")
    if bin_ not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = bin_ + os.pathsep + env.get("PATH", "")
    return env


def _linje(b: dict) -> str:
    """'[20.36] Julius: …' og bottens svar uden 'Svar til Julius:', så Claude ikke efterligner det."""
    tid = str(b.get("tid", ""))[11:16].replace(":", ".")
    fra, tekst = str(b.get("fra", "?")), str(b.get("tekst", ""))
    if m := SVAR_TIL.match(tekst):
        modtager = m.group(0).strip().rstrip(":")[len("svar til ") :].strip()
        fra, tekst = f"{fra} (til {modtager})", tekst[m.end() :]
    return f"[{tid}] {fra}: {tekst}" if tid else f"{fra}: {tekst}"


def lav_prompt(navn: str, tekst: str, historik: list[dict], nu: str) -> str:
    linjer = [_linje(b) for b in historik[-HISTORIK:]]
    tidligere = "\n".join(linjer) if linjer else "(ingen)"
    return f"Nu: {nu}\n\nDe seneste beskeder i chatten:\n{tidligere}\n\nNy besked fra {navn}:\n{tekst}"


async def _koer(argv: list[str]) -> tuple[int, str]:
    mappe = lokal.mappe() / "claude-p"
    mappe.mkdir(parents=True, exist_ok=True)  # tom arbejdsmappe: ingen projektfiler at læse
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=mappe, env=_miljoe(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        ud, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT_SEK)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, ud.decode("utf-8", "replace")


KOER = _koer  # byttes ud i testene


async def besvar(navn: str, tekst: str, historik: list[dict], nu: str) -> str | None:
    """Claudes svar, eller None hvis det ikke lykkedes (så går beskeden til AI-assistenten som før).
    Logger kun fejltypen, aldrig beskeden eller svaret."""
    claude = find_claude()
    if not claude:
        return None
    argv = kommando(claude, lav_prompt(navn, tekst, historik, nu), mcp_konfig())
    try:
        kode, ud = await KOER(argv)
    except TimeoutError:
        log.warning("claude -p svarede ikke inden for %s sekunder", TIMEOUT_SEK)
        return None
    except OSError as fejl:
        log.warning("claude -p kunne ikke starte: %s", type(fejl).__name__)
        return None
    try:
        svar = json.loads(ud)
    except ValueError:
        log.warning("claude -p gav ikke JSON (kode %s)", kode)
        return None
    if kode or not isinstance(svar, dict) or svar.get("is_error") or not str(svar.get("result", "")).strip():
        log.warning("claude -p fejlede (kode %s, %s)", kode, svar.get("subtype") if isinstance(svar, dict) else "?")
        return None
    return SVAR_TIL.sub("", str(svar["result"])).strip() or None

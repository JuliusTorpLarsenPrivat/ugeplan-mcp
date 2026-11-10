"""MCP-serveren: de værktøjer (knapper), som Claude kan trykke på.

Hver funktion med @mcp.tool bliver et værktøj. Funktionens navn er værktøjets navn,
docstringen er beskrivelsen, som Claude læser, og parametrene bliver værktøjets felter.

Alle værktøjer læser kun. Der findes ingen kode, der ændrer noget i din Garmin-konto, og
vagten (vagt.py) afviser alt andet end GET mod Garmins API.

Serveren taler med Claude Desktop over stdin/stdout ('stdio'). Derfor må intet andet
skrives til stdout: log går til stderr.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from garmin_mcp import forbindelse, niveau, sundhed

mcp = MCPServer(
    name="garmin",
    instructions=(
        "Brugerens egne sundhedsdata fra Garmin-uret: søvn, hvilepuls, skridt, kalorier, "
        "træninger og vægt. Kun læsning. Brug dem til at tilpasse madplaner, fx mere protein "
        "og kulhydrat efter hård træning og lettere mad efter dårlig søvn. Det er helbredsdata: "
        "nævn kun de tal, der er relevante for spørgsmålet, og stil ingen diagnoser. "
        "Datoer: ÅÅÅÅ-MM-DD, 'i dag' eller 'i går'. Dagens tal er indtil nu. "
        "Har husstanden flere Garmin-personer, så angiv `person` (se fejlbeskeden for navnene)."
    ),
)

LAESER = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


async def _koer(funktion: Callable[[Any], Any], person: str | None = None) -> Any:
    """Kør et opslag i en baggrundstråd (biblioteket er ikke async) og gør fejl forståelige."""

    def i_traad() -> Any:
        return funktion(forbindelse.klient(person))

    try:
        return await asyncio.to_thread(i_traad)
    except sundhed.DatoFejl as fejl:
        raise ToolError(str(fejl)) from None
    except Exception as fejl:  # noqa: BLE001  alt fra biblioteket oversættes til en læselig fejl
        raise ToolError(str(forbindelse.oversaet(fejl))) from None


def _dage(fra_dato: str | None, til_dato: str | None) -> list:
    try:
        return sundhed.periode(fra_dato, til_dato)
    except sundhed.DatoFejl as fejl:
        raise ToolError(str(fejl)) from None


@mcp.tool(annotations=LAESER)
async def dagsstatus(dato: str = "i dag", person: str | None = None) -> Any:
    """Kort overblik over én dag: nattens søvn, skridt, kalorier, hvilepuls, body battery,
    stress og træninger i går og i dag. Start her, når du laver en madplan."""
    (dag,) = _dage(dato, None)
    return await _koer(lambda g: sundhed.dagsstatus(g, dag), person)


@mcp.tool(annotations=LAESER)
async def soevn(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Søvn pr. nat: timer (dyb, let, REM, vågen), søvnscore, HRV og body battery.
    Datoen er morgenen, man vågnede: 'i dag' er nattens søvn. Højst 31 dage."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: [sundhed.soevn_dag(g, d) for d in dage], person)


@mcp.tool(annotations=LAESER)
async def hvilepuls(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Hvilepuls pr. dag og gennemsnit for de sidste 7 dage. Højst 31 dage."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: sundhed.udvalg(g, dage, sundhed.HVILEPULS), person)


@mcp.tool(annotations=LAESER)
async def skridt(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Skridt, skridtmål, distance og intensitetsminutter pr. dag. Højst 31 dage."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: sundhed.udvalg(g, dage, sundhed.SKRIDT), person)


@mcp.tool(annotations=LAESER)
async def kalorier(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Forbrændte kalorier pr. dag: i alt, aktive og hvile (BMR). Højst 31 dage.
    Garmins tal er et skøn. For i dag er det indtil nu."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: sundhed.udvalg(g, dage, sundhed.KALORIER), person)


@mcp.tool(annotations=LAESER)
async def traeninger(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Træninger/aktiviteter i perioden: type, varighed, distance, kalorier, puls og
    træningseffekt. Højst 31 dage."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: sundhed.traeninger(g, dage[0], dage[-1]), person)


@mcp.tool(annotations=LAESER)
async def vaegt(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Vejninger i perioden: vægt, fedtprocent, muskelmasse og BMI (hvis registreret).
    Højst 31 dage. Tom liste betyder ingen vejninger."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: sundhed.vaegt(g, dage[0], dage[-1]), person)


@mcp.tool(annotations=LAESER)
async def belastning(fra_dato: str = "i dag", til_dato: str | None = None, person: str | None = None) -> Any:
    """Dagens belastning pr. dag: rolig, normal, hård eller meget hård (eller ukendt, hvis
    uret ikke var på). Personligt: sammenlignet med personens egne seneste 28 dage, så
    også en hel dag ude (fx jagt) uden startet aktivitet tæller. Brug den til madplaner:
    se 2-4 uger tilbage for at finde mønstret pr. ugedag. Højst 31 dage. Vis ikke de rå
    tal til husstanden, kun niveauet."""
    dage = _dage(fra_dato, til_dato)
    return await _koer(lambda g: niveau.beregn_periode(g, dage), person)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for navn in ("garminconnect", "urllib3", "requests"):
        logging.getLogger(navn).setLevel(logging.WARNING)
    if len(sys.argv) > 1:
        from garmin_mcp.cli import kommando

        sys.exit(kommando(sys.argv[1:]))
    mcp.run("stdio")


if __name__ == "__main__":
    main()

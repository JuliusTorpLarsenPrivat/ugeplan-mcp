"""Bilen direkte fra Telegram, uden AI'en: "bil", "klar 7", "klar 07:30", "klar normal",
"oplad nu" og "stop opladning".

Fortolkningen er bevidst streng: kun hele, korte beskeder i præcis de former. Alt andet går
videre som i dag (fri tekst til `claude -p` eller AI-assistenten).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from handle_mcp import ha

STATUS = {"bil", "bilen", "status", "status bil", "bil status", "bilstatus", "status på bilen"}
NORMAL = {"klar normal", "klar normalt", "fjern undtagelse", "fjern undtagelsen", "klar fast tid", "bil normal"}
OPLAD = {"oplad nu", "lad nu", "start opladning", "start opladning nu", "oplad bilen nu", "lad bilen nu"}
STOP = {"stop opladning", "stop opladningen", "stop ladning", "stop laderen", "stop oplad"}
KLAR = re.compile(r"^(?:bil(?:en)?\s+)?(?:skal\s+være\s+)?klar\s+(?:kl\.?\s*)?(\d{1,2})(?:[.:](\d{2}))?$")


@dataclass
class Handling:
    hvad: str  # "status", "klar", "oplad" eller "stop"
    tid: time | None = None


def _rens(tekst: str) -> str:
    return " ".join(tekst.lower().strip(" ?!.").split())


def fortolk(tekst: str) -> Handling | None:
    t = _rens(tekst)
    if len(t) > 40:
        return None
    if t in STATUS:
        return Handling("status")
    if t in NORMAL:
        return Handling("klar")
    if t in OPLAD:
        return Handling("oplad")
    if t in STOP:
        return Handling("stop")
    if m := KLAR.match(t):
        timer, minutter = int(m.group(1)), int(m.group(2) or 0)
        if timer > 23 or minutter > 59 or (timer == 0 and minutter == 0):
            return None
        return Handling("klar", time(timer, minutter))
    return None


async def udfoer(h: Handling) -> str:
    """Giver svaret til husstanden. Fejl siges kort, uden detaljer om tokenet."""
    try:
        if h.hvad == "status":
            return (await ha.status()).tekst()
        if h.hvad == "klar":
            return await ha.saet_klar(h.tid)
        return await ha.oplad(start=h.hvad == "oplad")
    except ha.HAFejl as fejl:
        return f"Det lykkedes ikke: {fejl}"

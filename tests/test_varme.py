"""Varmepumpen (varme.py) mod en falsk Home Assistant. Intet rigtigt kald."""

from datetime import datetime

import httpx
import pytest

from handle_mcp import claude_p, ha, server, telegram, vagt, varme

from test_ha import FalskHA, TOKEN, tg  # noqa: F401  (samme falske Home Assistant og Telegram)
from test_telegram import FalskTelegram, par  # noqa: F401

NU = datetime(2026, 11, 28, 22, 30, tzinfo=ha.TIDSZONE)


@pytest.fixture
def falsk_ha(monkeypatch):
    f = FalskHA()
    f.tilstande.update({
        ha.VARME: {"state": "heat", "attributes": {"temperature": 21, "current_temperature": 20, "hvac_action": "heating", "fan_mode": "Auto", "preset_mode": "none"}},
        ha.VARME_INDE: {"state": "20"},
        ha.VARME_EFFEKT: {"state": "213"},
        ha.VARME_KWH: {"state": "4.89"},
        ha.VARME_KR: {"state": "3.104", "attributes": {"last_period": "9.8"}},
        ha.SOV_TIMER: {"state": "idle"},
        ha.SOV_MINUTTER: {"state": "45.0"},
        ha.UDE: {"state": "0"},
    })  # fmt: skip
    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(ha, "_ws_transport", f.websocket)
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    return f


# --- almindelig tale -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tekst, hvad, ekstra",
    [
        ("varme", "status", None),
        ("Varmepumpen?", "status", None),
        ("hvor varmt er der i stuen?", "status", None),
        ("Er varmen tændt?", "status", None),
        ("hvad har varmen kostet i dag?", "status", None),
        ("er det koldt ude?", "status", None),
        ("tænd varmen", "varme", None),
        ("Kan du tænde varmepumpen?", "varme", None),
        ("slå varmen til", "varme", None),
        ("sluk varmen", "sluk", None),
        ("Slå varmepumpen fra!", "sluk", None),
        ("varmen fra", "sluk", None),
        ("vi lufter ud", "luft_ud", None),
        ("luft ud", "luft_ud", None),
        ("bare blæs uden varme", "luft_ud", None),
        ("færdig med at lufte ud", "varme", None),
        ("stop udluftning", "varme", None),
        ("varme 22", "grader", 22.0),
        ("sæt varmen til 21,5", "grader", 21.5),
        ("22 grader", "grader", 22.0),
        ("skru op for varmen", "juster", 1.0),
        ("lidt koldere i stuen tak", "juster", -1.0),
        ("sov godt", "sov", None),
        ("vi går i seng nu, sluk varmepumpen", "sov", None),
        ("tænd varmen igen", "vaagn", None),
        ("varmepumpen larmer", "styrke", "stille"),
        ("kør varmepumpen kraftig", "styrke", "kraftig"),
        ("blæser på høj", "blaeser", "høj"),
    ],
)
def test_forstaar_almindelig_tale(tekst, hvad, ekstra):
    h = varme.fortolk(tekst)
    assert h is not None and h.hvad == hvad
    if isinstance(ekstra, float):
        assert h.grader == ekstra
    elif ekstra:
        assert h.valg == ekstra


@pytest.mark.parametrize(
    "tekst",
    [
        "sluk varmen kl. 22",  # tid: claude -p
        "lad være med at slukke varmen",
        "hvis det bliver koldt, så tænd varmen",
        "det er 18 grader i stuen",  # en oplysning, ikke en ordre
        "det er koldt herinde",  # claude -p skønner
        "sluk",
        "forvarm bilen",
        "forvarm under 5 grader",
        "varm bilen op",
        "har 2 kg kartofler",
        "hvad skal vi have i aften?",
    ],
)
def test_ikke_sikre_eller_ikke_varmen(tekst):
    assert varme.fortolk(tekst) is None


def test_om_varmen_sender_usikre_til_claude():
    assert varme.om_varmen("sluk varmen kl. 22")
    assert varme.om_varmen("det er koldt herinde")
    assert not varme.om_varmen("forvarm bilen")
    assert not varme.om_varmen("har 2 kg kartofler")


# --- handlinger mod Home Assistant -------------------------------------------------------------


async def test_status(falsk_ha):
    t = (await varme.status()).tekst()
    assert "Stuen: 20 °C (mål 21 °C), ude 0 °C." in t
    assert "Varmepumpen: varme, varmer nu (213 W)." in t
    assert "I dag: 4,9 kWh og 3,10 kr. (i går 9,80 kr.)." in t
    assert falsk_ha.skrivninger() == []


async def test_status_under_sov_godt_og_uden_forbindelse(falsk_ha):
    falsk_ha.tilstande[ha.SOV_TIMER] = {"state": "active", "attributes": {"finishes_at": "2026-11-28T22:15:00+00:00"}}
    assert "slukket til kl. 23:15" in (await varme.status()).tekst()
    falsk_ha.tilstande[ha.VARME] = {"state": "unavailable"}
    assert "svarer ikke" in (await varme.status()).tekst()


async def test_handlinger(falsk_ha):
    assert "tændt (21 °C)" in await varme.udfoer(varme.Handling("varme"))
    await varme.udfoer(varme.Handling("sluk"))
    await varme.udfoer(varme.Handling("luft_ud"))
    await varme.udfoer(varme.Handling("grader", grader=22.3))
    await varme.udfoer(varme.Handling("juster", grader=1.0))
    await varme.udfoer(varme.Handling("styrke", valg="stille"))
    await varme.udfoer(varme.Handling("blaeser", valg="lav"))
    e = {"entity_id": ha.VARME}
    assert falsk_ha.skrivninger() == [
        ("/api/services/climate/set_hvac_mode", {**e, "hvac_mode": "heat"}),
        ("/api/services/climate/set_hvac_mode", {**e, "hvac_mode": "off"}),
        ("/api/services/climate/set_hvac_mode", {**e, "hvac_mode": "fan_only"}),
        ("/api/services/climate/set_fan_mode", {**e, "fan_mode": "High"}),
        ("/api/services/climate/set_temperature", {**e, "temperature": 22.5, "hvac_mode": "heat"}),
        ("/api/services/climate/set_temperature", {**e, "temperature": 22.0, "hvac_mode": "heat"}),  # 21 + 1
        ("/api/services/climate/set_preset_mode", {**e, "preset_mode": "quiet"}),
        ("/api/services/climate/set_fan_mode", {**e, "fan_mode": "Low"}),
    ]


async def test_graenser(falsk_ha):
    assert "mellem 16 og 30" in await varme.udfoer(varme.Handling("grader", grader=35))
    falsk_ha.tilstande[ha.VARME]["attributes"]["temperature"] = 30
    await varme.udfoer(varme.Handling("juster", grader=1.0))
    assert falsk_ha.skrivninger()[-1][1]["temperature"] == 30.0  # aldrig over


async def test_sov_godt_og_vaagn(falsk_ha):
    svar = await varme.sov_godt(nu=NU)
    assert "45 min" in svar and "kl. 23:15" in svar
    assert falsk_ha.skrivninger() == [("/api/services/script/turn_on", {"entity_id": ha.SOV_GODT})]
    falsk_ha.tilstande[ha.SOV_TIMER] = {"state": "active", "attributes": {}}
    assert "allerede i gang" in await varme.sov_godt()
    assert "stoppet" in await varme.vaagn()
    assert falsk_ha.skrivninger()[-1] == ("/api/services/timer/finish", {"entity_id": ha.SOV_TIMER})
    assert "stoppet" in await varme.varme()  # "tænd varmen" under sov godt stopper det også
    falsk_ha.tilstande[ha.SOV_TIMER] = {"state": "idle"}
    falsk_ha.tilstande[ha.VARME]["state"] = "off"
    n = len(falsk_ha.skrivninger())
    assert "allerede slukket" in await varme.sov_godt()
    assert len(falsk_ha.skrivninger()) == n


async def test_kun_varmepumpens_enheder(falsk_ha):
    with pytest.raises(ha.HAFejl):
        await ha._service("climate/set_hvac_mode", "climate.andet_rum", hvac_mode="heat")
    with pytest.raises(ha.HAFejl):
        await ha._service("script/turn_on", "script.noget_andet")
    with pytest.raises(ha.HAFejl):
        await ha._service("timer/finish", "timer.noget_andet")


def test_vagten_tillader_varmepumpens_stier():
    for ok in ("climate/set_hvac_mode", "climate/set_temperature", "climate/set_fan_mode", "climate/set_preset_mode", "script/turn_on", "timer/finish"):
        vagt.tjek_url(httpx.URL(f"http://192.168.128.2:8123/api/services/{ok}"))
    for afvist in ("climate/set_swing_mode", "script/turn_off", "timer/start", "script/reload", "climate/turn_on"):
        with pytest.raises(vagt.VagtFejl):
            vagt.tjek_url(httpx.URL(f"http://192.168.128.2:8123/api/services/{afvist}"))


# --- Telegram, claude -p og serveren ------------------------------------------------------------


async def test_varme_fra_telegram(tg, falsk_ha):  # noqa: F811
    par(tg, 1, 2)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "hvor varmt er der?", navn="Maja")
    assert (await telegram.hent_og_haandter(0))[-1] == "varme (status) fra Maja"
    assert "Stuen: 20 °C" in tg.sendt[-1][1]
    tg.besked(2, "vi lufter ud", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "varme (luft_ud) fra Julius"
    assert falsk_ha.skrivninger()[-1] == ("/api/services/climate/set_fan_mode", {"entity_id": ha.VARME, "fan_mode": "High"})
    tg.besked(1, "hvad er varmens forbrug i dag?", navn="Maja")  # varmen, ikke bilens forbrug
    assert (await telegram.hent_og_haandter(0))[-1] == "varme (status) fra Maja"
    assert telegram.antal_ulaeste() == 0


def test_claude_p_faar_varmen(monkeypatch, tmp_path):
    monkeypatch.setattr(ha, "sat_op", lambda: True)
    tilladt = claude_p.tilladte_vaerktoejer({"mcpServers": {"ugeplan": {}}})
    assert {f"mcp__ugeplan__{v}" for v in claude_p.UGEPLAN_VARME} <= set(tilladt)
    assert "varme_styr" in claude_p.SYSTEM and "luft ud" in claude_p.SYSTEM
    monkeypatch.setattr(ha, "sat_op", lambda: False)
    assert not [t for t in claude_p.tilladte_vaerktoejer({"mcpServers": {"ugeplan": {}}}) if "varme_" in t]


async def test_varmevaerktoejerne_i_serveren(falsk_ha):
    navne = {t.name for t in await server.mcp.list_tools()}
    assert set(claude_p.UGEPLAN_VARME) <= navne
    assert "Stuen: 20 °C" in (await server.varme_status())["tekst"]
    svar = (await server.varme_styr(tilstand="varme", grader=22, styrke="stille"))["svar"]
    assert "22 °C" in svar and "stille" in svar
    assert "blæser nu kun luft" in (await server.varme_styr(tilstand="luft_ud"))["svar"]
    with pytest.raises(Exception):
        await server.varme_styr()
    with pytest.raises(Exception):
        await server.varme_styr(tilstand="køl")
    assert "45 min" in (await server.varme_sov_godt())["svar"]

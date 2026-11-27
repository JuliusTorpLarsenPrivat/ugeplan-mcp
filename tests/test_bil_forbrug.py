"""Opladningsforbrug (v0.41.0): kWh, kr. og CO2 fra Home Assistant, kun læsning.

Julius 27/11: "det er umuligt for os at huske kommandoerne i telegram, så i praksis bliver det
jo til ai". Derfor en bred genvej og værktøjet bil_forbrug til claude -p.
"""

from datetime import datetime

import httpx
import pytest

from handle_mcp import claude_p, ha, ha_besked, server, telegram

from test_ha import FalskHA, TOKEN  # noqa: F401
from test_telegram import FalskTelegram, claude, par, tg  # noqa: F401  (fixtures)

NU = datetime(2026, 11, 27, 21, 30, tzinfo=ha.TIDSZONE)
I_DAG = NU.date()

TAL = {  # som i den rigtige HA 27/11 aften
    "sensor.lader_energy_session": "1.55099999999999", "input_number.ladning_sidste_kr": "5.332", "input_number.ladning_sidste_co2": "0.181",
    "sensor.bil_kwh_seneste_24_t": "0.0", "sensor.bil_kr_seneste_24_t": "0.0", "sensor.bil_co2_seneste_24_t": "0.0",
    "sensor.bil_kwh_seneste_7_dage": "28.715", "sensor.bil_kr_seneste_7_dage": "70.931", "sensor.bil_co2_seneste_7_dage": "4.129",
    "sensor.bil_kwh_denne_maned": "28.715", "sensor.bil_kr_denne_maned": "70.931", "sensor.bil_co2_denne_maned": "4.129",
    "sensor.bil_kwh_i_ar": "28.715", "sensor.bil_kr_i_ar": "70.931", "sensor.bil_co2_i_ar": "4.129",
    "input_number.ladning_kwh_i_alt": "1234.5", "input_number.ladning_kr_i_alt": "2470.0", "input_number.ladning_co2_i_alt": "unavailable",
    "sensor.energi_data_service_co2": "52.0",
}  # fmt: skip
PRISER = {
    "raw_today": [{"hour": "2026-11-27T20:00:00+01:00", "price": 3.413}, {"hour": "2026-11-27T21:00:00+01:00", "price": 2.785}, {"hour": "2026-11-27T22:00:00+01:00", "price": 2.516}],
    "raw_tomorrow": [{"hour": "2026-11-28T03:00:00+01:00", "price": 2.049}, {"hour": "2026-11-28T08:00:00+01:00", "price": 2.234}],
}


@pytest.fixture
def falsk_ha(monkeypatch):
    f = FalskHA()
    f.tilstande.update({e: {"state": v} for e, v in TAL.items()})
    f.tilstande[ha.ELPRIS] = {"state": "2.785", "attributes": PRISER}
    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(ha, "_ws_transport", f.websocket)
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    return f


async def test_forbrugstabellen(falsk_ha):
    f = await ha.forbrug(NU)
    assert f.tekst() == (
        "Opladning (talt fra 26/11-2026):\n"
        "Sidste opladning: 1,6 kWh · 5,33 kr. · 0,18 kg CO2 · 3,44 kr./kWh\n"
        "Seneste 24 t: 0,0 kWh · 0,00 kr. · 0,00 kg CO2\n"
        "Seneste 7 dage: 28,7 kWh · 70,93 kr. · 4,13 kg CO2 · 2,47 kr./kWh\n"
        "Denne måned: 28,7 kWh · 70,93 kr. · 4,13 kg CO2 · 2,47 kr./kWh\n"
        "I år: 28,7 kWh · 70,93 kr. · 4,13 kg CO2 · 2,47 kr./kWh\n"
        "I alt: 1 234,5 kWh · 2 470,00 kr. · ? kg CO2 · 2,00 kr./kWh\n"
        "\n"
        "Strøm nu: 2,79 kr./kWh, 52 g CO2/kWh.\n"
        "Det er dyrt lige nu. Billigste kommende time: kl. 03.00 (2,05 kr./kWh); snit 2,40."
    )
    assert falsk_ha.skrivninger() == [] and falsk_ha.ws == []  # kun læsning


async def test_billigt_og_dyrt(falsk_ha):
    falsk_ha.tilstande[ha.ELPRIS]["state"] = "2.0"
    assert "Det er billigt lige nu." in (await ha.forbrug(NU)).tekst()
    falsk_ha.tilstande[ha.ELPRIS]["state"] = "2.4"
    assert "Det er middel lige nu." in (await ha.forbrug(NU)).tekst()
    falsk_ha.tilstande[ha.ELPRIS]["state"] = "4.0"
    assert "Det er dyrt lige nu." in (await ha.forbrug(NU)).tekst()


async def test_kun_bilens_forbrugssensorer_kan_laeses(falsk_ha):
    for _, *enheder in ha.FORBRUG:
        assert set(enheder) <= set(ha.LAESER)
    with pytest.raises(ha.HAFejl):
        await ha.tilstand("sensor.varmepumpe_kwh")
    assert not [e for e in ha.SKRIV.values() if e & {x for _, *t in ha.FORBRUG for x in t}]  # intet af det kan skrives


@pytest.mark.parametrize(
    "tekst",
    ["hvor meget har vi ladet for i november?", "hvor meget CO2 i år?", "er det billigt at lade nu?", "forbrug", "Hvad har opladningen kostet?",
     "kwh", "hvad koster det at lade bilen?", "bilens strømforbrug"],
)  # fmt: skip
def test_bred_genvej(tekst):
    assert ha_besked.fortolk(tekst, I_DAG) == ha_besked.Handling("forbrug")


@pytest.mark.parametrize(
    "tekst",
    ["hvad kostede det i nat?", "hvad har opladningen kostet i oktober?", "hvad kostede opladningen i går?", "CO2 sidste måned",
     "hvad koster mælk?", "oplad nu", "lad nu"],
)  # fmt: skip
def test_ikke_sikker_eller_ikke_forbrug(tekst):
    h = ha_besked.fortolk(tekst, I_DAG)
    assert h is None or h.hvad != "forbrug"


async def test_forbrug_fra_telegram_uden_ai(tg, falsk_ha):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "hvor meget CO2 i år?", navn="Maja")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (forbrug) fra Maja"
    assert "I år: 28,7 kWh · 70,93 kr. · 4,13 kg CO2" in tg.sendt[-1][1]


async def test_anden_periode_gaar_til_claude_uden_om_beholdningen(tg, falsk_ha, claude):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    claude.svar = "Der er kun tal fra 26/11."
    tg.besked(1, "hvad kostede opladningen i oktober?", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "fri tekst fra Julius besvaret af claude -p"
    assert "mcp__ugeplan__bil_forbrug" in claude.flag("--allowedTools").split(",")


def test_claude_p_faar_bil_forbrug_og_ved_hvornaar():
    assert "bil_forbrug" in claude_p.UGEPLAN_BIL
    assert "bil_forbrug giver opladningens kWh, kr., CO2" in claude_p.SYSTEM


async def test_bil_forbrug_i_serveren(falsk_ha):
    navne = {t.name: t for t in await server.mcp.list_tools()}
    assert navne["bil_forbrug"].annotations.read_only_hint
    ud = await server.bil_forbrug()
    assert ud["perioder"][0]["navn"] == "Sidste opladning" and round(ud["perioder"][0]["kr_pr_kwh"], 2) == 3.44
    assert ud["tekst"].startswith("Opladning (talt fra 26/11-2026):")

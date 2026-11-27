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
    "sensor.bil_kwh_i_dag": "28.171", "sensor.bil_kr_i_dag": "68.648", "sensor.bil_co2_i_dag": "4.037",
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
    # som i den rigtige HA 27/11 aften: målerne blev oprettet kl. 21.11, så i går/sidste måned er ikke sikre
    for e in ("sensor.bil_kwh_i_dag", "sensor.bil_kr_i_dag", "sensor.bil_co2_i_dag", "sensor.bil_kwh_denne_maned", "sensor.bil_kr_denne_maned", "sensor.bil_co2_denne_maned"):
        f.tilstande[e]["attributes"] = {"last_period": "0", "last_reset": "2026-11-27T20:11:50.59+00:00"}
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
        "I dag: 28,2 kWh · 68,65 kr. · 4,04 kg CO2 · 2,44 kr./kWh\n"
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
    ["forbrug", "Hvad har opladningen kostet?", "kwh", "hvad koster det at lade bilen?", "bilens strømforbrug"],
)  # fmt: skip
def test_bred_genvej_uden_periode_giver_tabellen(tekst):
    assert ha_besked.fortolk(tekst, I_DAG) == ha_besked.Handling("forbrug")


@pytest.mark.parametrize(
    "tekst",
    ["hvad kostede det i nat?", "hvad koster mælk?", "oplad nu", "lad nu", "co2 denne uge", "kwh sidste uge", "hvad koster strømmen i morgen?"],
)  # fmt: skip
def test_ikke_sikker_eller_ikke_forbrug(tekst):
    h = ha_besked.fortolk(tekst, I_DAG)
    assert h is None or h.hvad != "forbrug"


async def test_forbrug_fra_telegram_uden_ai(tg, falsk_ha):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "forbrug", navn="Maja")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (forbrug) fra Maja"
    assert "I år: 28,7 kWh · 70,93 kr. · 4,13 kg CO2" in tg.sendt[-1][1]


async def test_anden_periode_gaar_til_claude_uden_om_beholdningen(tg, falsk_ha, claude):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    claude.svar = "Der er kun tal fra 26/11."
    tg.besked(1, "hvad kostede opladningen sidste uge?", navn="Julius")
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


# --- perioder (v0.41.1): én sætning om netop den periode -------------------------------------
# Fundet 27/11 21.10: "Hvad kostede det at lade i nat" fik hele tabellen.

AFTEN = datetime(2026, 11, 27, 21, 10, tzinfo=ha.TIDSZONE)
MORGEN = datetime(2026, 11, 28, 9, 0, tzinfo=ha.TIDSZONE)


@pytest.mark.parametrize(
    "tekst, nu, periode",
    [
        ("Hvad kostede det at lade i nat", MORGEN, "nat"),
        ("hvad kostede opladningen i morges?", MORGEN, "nat"),
        ("kwh i dag", AFTEN, "i_dag"),
        ("co2 i går", AFTEN, "i_gaar"),
        ("hvor meget har vi ladet for i november?", AFTEN, "maaned"),
        ("hvad kostede opladningen sidste måned", AFTEN, "sidste_maaned"),
        ("hvad kostede opladningen i oktober?", AFTEN, "sidste_maaned"),
        ("hvor meget CO2 i år?", AFTEN, "aar"),
        ("er det billigt at lade nu?", AFTEN, "nu"),
        ("kwh i alt", AFTEN, "i_alt"),
        ("co2 i marts", AFTEN, "aeldre"),
        ("hvad kostede opladningen i 2025", AFTEN, "aeldre"),
    ],
)
def test_perioder(tekst, nu, periode):
    h = ha_besked.fortolk(tekst, nu=nu)
    assert h and h.hvad == "forbrug" and h.periode == periode


@pytest.mark.parametrize("tekst", ["Hvad kostede det at lade i nat", "kwh denne uge", "co2 sidste uge", "hvad koster det at lade i morgen?", "kwh 24/11"])
def test_usikre_perioder_gaar_til_claude(tekst):
    assert ha_besked.fortolk(tekst, nu=AFTEN) is None  # kl. 21.10 er "i nat" ikke sikkert


async def test_i_nat_om_morgenen_er_seneste_24_t(falsk_ha):
    falsk_ha.tilstande["sensor.bil_kwh_seneste_24_t"]["state"] = "12.0"
    falsk_ha.tilstande["sensor.bil_kr_seneste_24_t"]["state"] = "24.6"
    falsk_ha.tilstande["sensor.bil_co2_seneste_24_t"]["state"] = "0.6"
    svar = await ha.forbrug_svar("nat", "I nat", MORGEN)
    assert svar == "I nat er der ladet 12,0 kWh for 24,60 kr. (2,05 kr./kWh), 0,60 kg CO2."
    assert "\n" not in svar  # én sætning, ikke tabellen


async def test_i_nat_bruger_i_dag_naar_24_t_er_0(falsk_ha):
    svar = await ha.forbrug_svar("nat", "I nat", MORGEN)  # seneste 24 t = 0
    assert svar == "I nat er der ladet 28,2 kWh for 68,65 kr. (2,44 kr./kWh), 4,04 kg CO2."


async def test_i_nat_unavailable_bruger_i_dag(falsk_ha):
    falsk_ha.tilstande["sensor.bil_kwh_seneste_24_t"]["state"] = "unavailable"
    assert (await ha.forbrug_svar("nat", "I morges", MORGEN)).startswith("I morges er der ladet 28,2 kWh")


async def test_i_dag_og_maaned_og_aar(falsk_ha):
    assert (await ha.forbrug_svar("i_dag", "I dag", AFTEN)).startswith("I dag er der ladet 28,2 kWh for 68,65 kr.")
    assert (await ha.forbrug_svar("maaned", "I november", AFTEN)).startswith("I november er der ladet 28,7 kWh for 70,93 kr.")
    assert (await ha.forbrug_svar("aar", "I år", AFTEN)).startswith("I år er der ladet 28,7 kWh")


async def test_i_gaar_fra_last_period(falsk_ha):
    for e, v in (("sensor.bil_kwh_i_dag", "10.0"), ("sensor.bil_kr_i_dag", "20.0"), ("sensor.bil_co2_i_dag", "0.5")):
        falsk_ha.tilstande[e]["attributes"] = {"last_period": v, "last_reset": "2026-11-27T23:00:00+00:00"}  # 00.00 dansk tid
    assert await ha.forbrug_svar("i_gaar", "I går", MORGEN) == "I går er der ladet 10,0 kWh for 20,00 kr. (2,00 kr./kWh), 0,50 kg CO2."


async def test_i_gaar_uden_sikker_nulstilling(falsk_ha):
    # nulstillet kl. 21.11, ikke ved midnat: tallet dækker ikke hele i går
    assert (await ha.forbrug_svar("i_gaar", "I går", AFTEN)).startswith("Home Assistant har ikke et sikkert tal for i går")
    assert await ha.forbrug_svar("i_gaar", "I går", datetime(2026, 11, 26, 9, 0, tzinfo=ha.TIDSZONE)) == ha.AELDRE  # i går = 25/11


async def test_forrige_maaned(falsk_ha):
    assert await ha.forbrug_svar("sidste_maaned", "I oktober", AFTEN) == ha.AELDRE  # før 26/11
    for e, v in (("sensor.bil_kwh_denne_maned", "120.0"), ("sensor.bil_kr_denne_maned", "260.0"), ("sensor.bil_co2_denne_maned", "8.0")):
        falsk_ha.tilstande[e]["attributes"] = {"last_period": v, "last_reset": "2026-11-30T23:00:00+00:00"}  # 1/12 00.00
    svar = await ha.forbrug_svar("sidste_maaned", "I november", datetime(2026, 12, 3, 12, 0, tzinfo=ha.TIDSZONE))
    assert svar == "I november er der ladet 120,0 kWh for 260,00 kr. (2,17 kr./kWh), 8,00 kg CO2."


async def test_aeldre_er_aerligt_og_spoerger_ikke_ha(falsk_ha):
    assert await ha.forbrug_svar("aeldre", "", AFTEN) == "Jeg har kun tal for opladningen fra 26/11-2026, så den periode kan jeg ikke svare på."
    assert falsk_ha.kald == []


async def test_ingen_opladning_og_prisen_nu(falsk_ha):
    assert await ha.forbrug_svar("24t", "De seneste 24 timer", AFTEN) == "De seneste 24 timer er der ikke ladet."
    assert await ha.forbrug_svar("nu", "", NU) == "Strøm nu: 2,79 kr./kWh, det er dyrt. Billigste kommende time er kl. 03.00 (2,05 kr./kWh)."


async def test_i_nat_fra_telegram_er_en_saetning(tg, falsk_ha, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ha_besked, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: MORGEN)}))
    monkeypatch.setattr(ha, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: MORGEN)}))
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "Hvad kostede det at lade i nat", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (forbrug) fra Julius"
    assert tg.sendt[-1] == (1, "I nat er der ladet 28,2 kWh for 68,65 kr. (2,44 kr./kWh), 4,04 kg CO2.")


async def test_i_nat_om_aftenen_gaar_til_claude(tg, falsk_ha, claude, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ha_besked, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: AFTEN)}))
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    claude.svar = "I nat blev der ladet 28,2 kWh."
    tg.besked(1, "Hvad kostede det at lade i nat", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "fri tekst fra Julius besvaret af claude -p"


def test_nye_sensorer_kan_kun_laeses():
    for e in ("sensor.bil_kwh_i_dag", "sensor.bil_kr_i_dag", "sensor.bil_co2_i_dag"):
        assert e in ha.LAESER and not [s for s in ha.SKRIV.values() if e in s]

"""Bilen i Home Assistant (ha.py, ha_besked.py) mod en falsk Home Assistant. Intet rigtigt kald."""

import json
from datetime import datetime, time

import httpx
import pytest

from handle_mcp import claude_p, ha, ha_besked, server, telegram, vagt

from test_telegram import FalskTelegram, par  # noqa: F401  (samme falske Telegram)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ0ZXN0In0.abcDEF123_-"
NU = datetime(2026, 11, 26, 20, 0, tzinfo=ha.TIDSZONE)  # torsdag aften: tiderne gælder fredag


class FalskHA:
    def __init__(self):
        self.tilstande = {
            ha.KLAR: {"state": "07:30:00"},
            ha.UNDTAGELSE: {"state": "off"},
            "input_datetime.bil_klar_fredag": {"state": "06:15:00"},
            "input_datetime.bil_klar_torsdag": {"state": "06:15:00"},
            ha.SLUTTID: {"state": "06:15"},
            ha.LADNING: {"state": "off", "attributes": {"charging_is_planned": True, "charging_start_time": "2026-11-27T03:00:00+01:00", "charging_stop_time": "2026-11-27T06:00:00+01:00"}},
            ha.TILKOBLET: {"state": "on"},
            ha.BATTERI: {"state": "44.6"},
            ha.ELPRIS: {"state": "4.0483"},
            ha.LADER: {"state": "Available"},
            ha.LAD_STANDARD: {"state": "80.0"},
            ha.LAD_I_NAT: {"state": "100.0"},
            ha.MAAL_I_NAT: {"state": "80.0"},
            ha.KOMMENDE: {"state": "Ingen planlagte undtagelser"},
            ha.AUTO_FORVARM: {"state": "on"},
            ha.FORVARM_NU: {"state": "off"},
            ha.FORVARM_UNDER: {"state": "7.0"},
            ha.UDE: {"state": "2"},
        }
        self.begivenheder: list[dict] = []
        self.kald: list[tuple[str, str, dict | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "192.168.128.2" and request.headers["Authorization"] == f"Bearer {TOKEN}"
        data = json.loads(request.content) if request.content else None
        self.kald.append((request.method, request.url.path, data))
        if request.url.path.startswith("/api/states/"):
            e = request.url.path.rsplit("/", 1)[-1]
            if e not in self.tilstande:
                return httpx.Response(404, json={"message": "Entity not found."})
            return httpx.Response(200, json={"entity_id": e, "attributes": {}, **self.tilstande[e]})
        if request.url.path == f"/api/calendars/{ha.KALENDER}":
            fra, til = request.url.params["start"][:10], request.url.params["end"][:10]
            return httpx.Response(200, json=[b for b in self.begivenheder if fra <= b["start"]["date"] < til])
        if request.url.path == "/api/services/calendar/create_event":
            self.begivenheder.append({"summary": data["summary"], "start": {"date": data["start_date"]}, "end": {"date": data["end_date"]}})
        if request.url.path == "/api/services/input_number/set_value":
            self.tilstande[data["entity_id"]]["state"] = f"{float(data['value'])}"
        if request.url.path == "/api/services/input_datetime/set_datetime":
            self.tilstande[data["entity_id"]]["state"] = data["time"]
        if request.url.path.startswith("/api/services/input_boolean/"):
            self.tilstande[data["entity_id"]]["state"] = "on" if request.url.path.endswith("turn_on") else "off"
        return httpx.Response(200, json=[])

    def skrivninger(self):
        return [(s, d) for m, s, d in self.kald if m == "POST"]


@pytest.fixture
def falsk_ha(monkeypatch):
    f = FalskHA()
    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    return f


# --- fortolkning ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "tekst, hvad, tid",
    [
        ("bil", "status", None),
        ("Status?", "status", None),
        ("klar 7", "klar", time(7, 0)),
        ("klar 07:30", "klar", time(7, 30)),
        ("Klar kl. 6.45", "klar", time(6, 45)),
        ("bilen skal være klar 8", "klar", time(8, 0)),
        ("klar normal", "klar", None),
        ("Fjern undtagelse", "klar", None),
        ("oplad nu", "oplad", None),
        ("Oplad nu!", "oplad", None),
        ("stop opladning", "stop", None),
    ],
)
def test_faste_bil_kommandoer(tekst, hvad, tid):
    h = ha_besked.fortolk(tekst)
    assert h and h.hvad == hvad and h.tid == tid


@pytest.mark.parametrize("tekst", ["klar 25", "klar 7:75", "klar 0", "er bilen klar?", "stop", "hvornår er bilen klar til i morgen", "har 2 kg kartofler", "ok uge-1234"])
def test_andet_er_ikke_bil_kommandoer(tekst):
    assert ha_besked.fortolk(tekst) is None


# --- status og handlinger ------------------------------------------------------------


async def test_status(falsk_ha):
    s = await ha.status(NU)
    assert s.tekst() == (
        "Bilen skal være klar kl. 06.15 (fast tid fredag).\n"
        "Mål i nat: 80 %.\n"
        "Opladning planlagt 03.00–06.00.\n"
        "Batteri: 45 %.\n"
        "Strøm nu: 4,05 kr./kWh.\n"
        "Forvarmning: automatisk under 7 °C (ude nu 2 °C)."
    )
    assert falsk_ha.skrivninger() == []  # status læser kun


async def test_status_med_undtagelse_og_lader_offline(falsk_ha):
    falsk_ha.tilstande[ha.UNDTAGELSE]["state"] = "on"
    falsk_ha.tilstande[ha.LADER]["state"] = "unavailable"
    falsk_ha.tilstande[ha.LADNING] = {"state": "off", "attributes": {"charging_is_planned": False}}
    tekst = (await ha.status(NU)).tekst()
    assert "klar kl. 07.30 (undtagelse, kun denne gang)" in tekst
    assert "Ingen opladning planlagt." in tekst and "Laderen svarer ikke" in tekst


async def test_status_om_formiddagen_gaelder_i_dag(falsk_ha):
    falsk_ha.tilstande["input_datetime.bil_klar_torsdag"]["state"] = "08:00:00"
    s = await ha.status(datetime(2026, 11, 26, 5, 0, tzinfo=ha.TIDSZONE))
    assert s.dag == "torsdag" and s.klar == "08.00"


async def test_klar_saetter_engangstiden(falsk_ha):
    svar = await ha.saet_klar(time(7, 10), NU)
    assert falsk_ha.skrivninger() == [
        ("/api/services/input_datetime/set_datetime", {"entity_id": ha.KLAR, "time": "07:10:00"}),
        ("/api/services/input_boolean/turn_on", {"entity_id": ha.UNDTAGELSE}),
    ]
    assert svar.startswith("Bilen skal være klar kl. 07.10 i morgen, ladet til 100 % (kun denne gang).")
    assert "færdig kl. 07.00 (hele kvarter)" in svar


async def test_klar_om_dagen_planlaegges_kl_18(falsk_ha):
    svar = await ha.saet_klar(time(7, 0), datetime(2026, 11, 26, 14, 0, tzinfo=ha.TIDSZONE))
    assert "planlægges kl. 18" in svar


async def test_klar_normal(falsk_ha):
    falsk_ha.tilstande[ha.UNDTAGELSE]["state"] = "on"
    svar = await ha.saet_klar(None, NU)
    assert falsk_ha.skrivninger() == [("/api/services/input_boolean/turn_off", {"entity_id": ha.UNDTAGELSE})]
    assert svar.startswith("Undtagelsen er fjernet. Bilen skal være klar kl. 06.15 (fast tid fredag).")


@pytest.mark.parametrize("start, knap", [(True, ha.START), (False, ha.STOP)])
async def test_oplad_og_stop_trykker_een_gang(falsk_ha, start, knap):
    await ha.oplad(start)
    assert falsk_ha.skrivninger() == [("/api/services/button/press", {"entity_id": knap})]


async def test_langsom_lader_giver_kort_fejl_og_intet_nyt_tryk(monkeypatch):
    tryk = []

    def langsom(request):
        tryk.append(request.url.path)
        raise httpx.ReadTimeout("for langsom")

    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(langsom))
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    svar = await ha_besked.udfoer(ha_besked.Handling("oplad"))
    assert svar.startswith("Det lykkedes ikke: Home Assistant svarede ikke") and len(tryk) == 1


async def test_kun_bilens_enheder(falsk_ha):
    with pytest.raises(ha.HAFejl):
        await ha.tilstand("lock.hoveddoer")
    with pytest.raises(ha.HAFejl):
        await ha._tryk("button.noget_andet")
    assert falsk_ha.kald == []


async def test_token_vises_aldrig_i_fejl(monkeypatch):
    def nede(request):
        raise httpx.ConnectError(f"fejl med {request.headers['Authorization']}")

    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(nede))
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    with pytest.raises(ha.HAFejl) as fejl:
        await ha.tilstand(ha.BATTERI)
    assert TOKEN not in str(fejl.value)


def test_forkert_token_gemmes_ikke(monkeypatch):
    monkeypatch.setattr(ha.keyring, "set_password", lambda *a: pytest.fail("må ikke gemmes"))
    with pytest.raises(ha.HAFejl):
        ha.gem("ikke et token")


# --- vagten ----------------------------------------------------------------------------


def test_vagten_tillader_kun_home_assistants_bilstier():
    vagt.tjek_url(httpx.URL(f"http://192.168.128.2:8123/api/states/{ha.BATTERI}"))
    vagt.tjek_url(httpx.URL("http://192.168.128.2:8123/api/services/button/press"))
    for afvist in (
        "http://192.168.128.2:8123/api/services/lock/unlock",
        "http://192.168.128.2:8123/api/services/input_boolean/toggle",
        "http://192.168.128.2:8123/api/config",
        "http://192.168.1.50:8123/api/states/sensor.x",  # anden adresse på hjemmenettet
        "http://evil.example.com/api/services/button/press",
    ):
        with pytest.raises(vagt.VagtFejl):
            vagt.tjek_url(httpx.URL(afvist))


# --- Telegram ----------------------------------------------------------------------------


@pytest.fixture
def tg(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDLE_MCP_DATA", str(tmp_path))
    falsk = FalskTelegram()
    monkeypatch.setattr(telegram, "_transport", httpx.MockTransport(falsk))
    monkeypatch.setattr(telegram, "hent_token", lambda: "123456789:" + "A" * 35)
    monkeypatch.setattr(telegram, "AUTOSTART", False)
    return falsk


async def test_bil_fra_telegram(tg, falsk_ha):
    par(tg, 1, 2)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "bil", navn="Maja")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (status) fra Maja"
    assert tg.sendt[-1][0] == 1 and "Batteri: 45 %." in tg.sendt[-1][1]
    assert (2, "Maja: bil") in tg.sendt  # den anden telefon ser, hvad der blev skrevet
    tg.besked(2, "oplad nu", navn="Julius")
    await telegram.hent_og_haandter(0)
    assert falsk_ha.skrivninger()[-1] == ("/api/services/button/press", {"entity_id": ha.START})
    assert telegram.antal_ulaeste() == 0  # klaret: AI-assistenten skal ikke tage dem


async def test_uden_home_assistant_er_bil_almindelig_tekst(tg):
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "oplad nu")
    assert "bil" not in (await telegram.hent_og_haandter(0))[-1]
    assert telegram.antal_ulaeste() == 1


# --- claude -p og serveren ---------------------------------------------------------------


def test_claude_p_faar_bilen_og_ha_kun_laesning(monkeypatch, tmp_path):
    konfig_fil = tmp_path / "claude_desktop_config.json"
    konfig_fil.write_text(json.dumps({"mcpServers": {"homeassistant": {"command": "uvx", "args": ["mcp-proxy", "http://x"]}}}))
    monkeypatch.setattr(claude_p, "_desktop_konfig", lambda: konfig_fil)
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    konfig = claude_p.mcp_konfig()
    assert "homeassistant" in konfig["mcpServers"]
    tilladt = claude_p.tilladte_vaerktoejer(konfig)
    assert {f"mcp__ugeplan__{v}" for v in claude_p.UGEPLAN_BIL} | {"mcp__homeassistant__ha_get_state"} <= set(tilladt)
    assert not [t for t in tilladt if t.startswith("mcp__homeassistant__") and t.removeprefix("mcp__homeassistant__") not in claude_p.HA_LAES]
    assert "mcp__homeassistant" not in tilladt  # aldrig hele serveren (ha_call_service)


def test_claude_p_uden_home_assistant_faar_ingen_bil():
    tilladt = claude_p.tilladte_vaerktoejer({"mcpServers": {"ugeplan": {}}})
    assert not [t for t in tilladt if "bil_" in t or "homeassistant" in t]


async def test_bilvaerktoejerne_findes_i_serveren(falsk_ha):
    navne = {t.name for t in await server.mcp.list_tools()}
    assert set(claude_p.UGEPLAN_BIL) <= navne
    assert (await server.bil_klar("07:30"))["svar"].startswith("Bilen skal være klar kl. 07.30")


# --- udvidelsen 27/11: ladeniveau, planlagte undtagelser og forvarmning ---------------------

I_DAG = NU.date()


@pytest.mark.parametrize(
    "tekst, forventet",
    [
        ("klar 07:30 90%", ha_besked.Handling("klar", tid=time(7, 30), pct=90)),
        ("klar 7.30", ha_besked.Handling("klar", tid=time(7, 30))),
        ("klar 5/12 5:30 100%", ha_besked.Handling("planlaeg", tid=time(5, 30), pct=100, dato=datetime(2026, 12, 5).date())),
        ("Undtagelse 24.12 6", ha_besked.Handling("planlaeg", tid=time(6, 0), dato=datetime(2026, 12, 24).date())),
        ("klar 5/1 7", ha_besked.Handling("planlaeg", tid=time(7, 0), dato=datetime(2027, 1, 5).date())),
        ("undtagelser", ha_besked.Handling("undtagelser")),
        ("lad til 90", ha_besked.Handling("lad", pct=90)),
        ("Lad til 100% i nat", ha_besked.Handling("lad", pct=100, kun_i_nat=True)),
        ("forvarm nu", ha_besked.Handling("forvarm")),
        ("forvarmning fra", ha_besked.Handling("auto_forvarm", til=False)),
        ("automatisk forvarmning til", ha_besked.Handling("auto_forvarm", til=True)),
        ("forvarm under -3 grader", ha_besked.Handling("forvarm_under", grader=-3)),
    ],
)
def test_nye_faste_kommandoer(tekst, forventet):
    assert ha_besked.fortolk(tekst, I_DAG) == forventet


@pytest.mark.parametrize("tekst", ["klar 31/2 7", "lad til", "forvarm bilen i morgen tidlig", "varm maden op"])
def test_nye_kommandoer_er_strenge(tekst):
    assert ha_besked.fortolk(tekst, I_DAG) is None


async def test_klar_med_procent(falsk_ha):
    svar = await ha.saet_klar(time(7, 30), NU, pct=90)
    assert falsk_ha.skrivninger() == [
        ("/api/services/input_datetime/set_datetime", {"entity_id": ha.KLAR, "time": "07:30:00"}),
        ("/api/services/input_number/set_value", {"entity_id": ha.LAD_I_NAT, "value": 90}),
        ("/api/services/input_boolean/turn_on", {"entity_id": ha.UNDTAGELSE}),
    ]
    assert svar.startswith("Bilen skal være klar kl. 07.30 i morgen, ladet til 90 % (kun denne gang).")


@pytest.mark.parametrize("pct", [40, 101])
async def test_ladeniveau_uden_for_graenserne_skrives_ikke(falsk_ha, pct):
    with pytest.raises(ha.HAFejl):
        await ha.lad_til(pct)
    assert falsk_ha.skrivninger() == []


async def test_lad_til_hver_nat(falsk_ha):
    svar = await ha.lad_til(92, nu=NU)  # rundes til trin på 5
    assert falsk_ha.skrivninger() == [("/api/services/input_number/set_value", {"entity_id": ha.LAD_STANDARD, "value": 90})]
    assert svar.startswith("Bilen lades nu til 90 % hver nat")


async def test_lad_til_i_nat_bruger_den_tid_der_gaelder(falsk_ha):
    svar = await ha.lad_til(100, kun_i_nat=True, nu=NU)
    assert falsk_ha.skrivninger() == [
        ("/api/services/input_datetime/set_datetime", {"entity_id": ha.KLAR, "time": "06:15:00"}),  # fast tid fredag
        ("/api/services/input_number/set_value", {"entity_id": ha.LAD_I_NAT, "value": 100}),
        ("/api/services/input_boolean/turn_on", {"entity_id": ha.UNDTAGELSE}),
    ]
    assert "klar kl. 06.15 i morgen, ladet til 100 %" in svar


async def test_lad_til_i_nat_med_undtagelse_beholder_tiden(falsk_ha):
    falsk_ha.tilstande[ha.UNDTAGELSE]["state"] = "on"
    svar = await ha.lad_til(85, kun_i_nat=True, nu=NU)
    assert [s for s, _ in falsk_ha.skrivninger()] == ["/api/services/input_number/set_value", "/api/services/input_boolean/turn_on"]
    assert "85 % i nat og skal være klar kl. 07.30" in svar


async def test_planlaeg_laegger_heldagsbegivenhed(falsk_ha):
    svar = await ha.planlaeg(datetime(2026, 12, 5).date(), time(5, 30), 100, NU)
    assert falsk_ha.skrivninger() == [
        ("/api/services/calendar/create_event", {"entity_id": ha.KALENDER, "summary": "05:30 100%", "start_date": "2026-12-05", "end_date": "2026-12-06"})
    ]
    assert svar.startswith("Planlagt: lørdag 5/12 skal bilen være klar kl. 05.30, ladet til 100 %.")


async def test_planlaeg_uden_procent(falsk_ha):
    await ha.planlaeg(datetime(2026, 12, 5).date(), time(6, 0), None, NU)
    assert falsk_ha.skrivninger()[0][1]["summary"] == "06:00"


async def test_planlaeg_samme_dag_to_gange_afvises(falsk_ha):
    falsk_ha.begivenheder.append({"summary": "06:00 90%", "start": {"date": "2026-12-05"}, "end": {"date": "2026-12-06"}})
    svar = await ha_besked.udfoer(ha_besked.Handling("planlaeg", tid=time(5, 30), dato=datetime(2026, 12, 5).date()))
    assert "allerede en undtagelse lørdag 5/12 (06:00 90%)" in svar and "dashboardet" in svar
    assert falsk_ha.skrivninger() == []


async def test_planlaeg_i_fortiden_afvises(falsk_ha):
    with pytest.raises(ha.HAFejl):
        await ha.planlaeg(datetime(2026, 11, 20).date(), time(6, 0), None, NU)
    assert falsk_ha.skrivninger() == []


async def test_planlaeg_naeste_morgen_er_klar_tid(falsk_ha):
    await ha.planlaeg(datetime(2026, 11, 27).date(), time(5, 30), None, NU)  # torsdag aften -> fredag
    assert [s for s, _ in falsk_ha.skrivninger()] == ["/api/services/input_datetime/set_datetime", "/api/services/input_boolean/turn_on"]
    assert falsk_ha.begivenheder == []


async def test_status_viser_planlagt_undtagelse_fra_kalenderen(falsk_ha):
    falsk_ha.begivenheder.append({"summary": "05:30 100%", "start": {"date": "2026-11-27"}, "end": {"date": "2026-11-28"}})
    falsk_ha.tilstande[ha.MAAL_I_NAT]["state"] = "100.0"
    falsk_ha.tilstande[ha.KOMMENDE]["state"] = "fre 27/11 05:30 100%"
    tekst = (await ha.status(NU)).tekst()
    assert "klar kl. 05.30 (planlagt undtagelse)" in tekst
    assert "Mål i nat: 100 % (standard 80 %)." in tekst
    assert "Planlagt: fre 27/11 05:30 100%" in tekst


async def test_undtagelser(falsk_ha):
    assert (await ha.undtagelser()).startswith("Ingen planlagte undtagelser.")
    falsk_ha.tilstande[ha.KOMMENDE]["state"] = "lør 5/12 05:30 100%"
    assert await ha.undtagelser() == "Planlagte undtagelser: lør 5/12 05:30 100%"


async def test_forvarmning(falsk_ha):
    assert "slukker selv" in await ha.forvarm()
    assert "slået fra" in await ha.auto_forvarmning(False)
    assert "under 5 °C" in await ha.forvarm_under(5)
    assert falsk_ha.skrivninger() == [
        ("/api/services/input_boolean/turn_on", {"entity_id": ha.FORVARM_NU}),
        ("/api/services/input_boolean/turn_off", {"entity_id": ha.AUTO_FORVARM}),
        ("/api/services/input_number/set_value", {"entity_id": ha.FORVARM_UNDER, "value": 5}),
    ]
    with pytest.raises(ha.HAFejl):
        await ha.forvarm_under(30)


async def test_kun_de_tilladte_services_paa_de_tilladte_enheder(falsk_ha):
    for service, entitet in (
        ("input_boolean/turn_off", ha.FORVARM_NU),  # Mac-scriptet slukker selv
        ("input_number/set_value", ha.MAAL_I_NAT),  # skrives kun af automatiseringen
        ("input_boolean/turn_on", "input_boolean.noget_andet"),
        ("calendar/create_event", "calendar.familie"),
        ("lock/unlock", "lock.hoveddoer"),
    ):
        with pytest.raises(ha.HAFejl):
            await ha._service(service, entitet)
    assert falsk_ha.kald == []


def test_vagten_tillader_de_nye_stier():
    for ok in (
        "http://192.168.128.2:8123/api/services/input_number/set_value",
        "http://192.168.128.2:8123/api/services/calendar/create_event",
        f"http://192.168.128.2:8123/api/calendars/{ha.KALENDER}?start=2026-12-05T00:00:00",
    ):
        vagt.tjek_url(httpx.URL(ok))
    for afvist in (
        "http://192.168.128.2:8123/api/services/calendar/delete_event",
        "http://192.168.128.2:8123/api/services/script/turn_on",
        "http://192.168.128.2:8123/api/services/input_number/increment",
    ):
        with pytest.raises(vagt.VagtFejl):
            vagt.tjek_url(httpx.URL(afvist))


async def test_nye_kommandoer_fra_telegram(tg, falsk_ha):
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "lad til 90", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (lad) fra Julius"
    assert "90 % hver nat" in tg.sendt[-1][1]
    tg.besked(1, "forvarm nu", navn="Julius")
    await telegram.hent_og_haandter(0)
    assert falsk_ha.skrivninger()[-1] == ("/api/services/input_boolean/turn_on", {"entity_id": ha.FORVARM_NU})


async def test_nye_bilvaerktoejer_i_serveren(falsk_ha, monkeypatch):
    monkeypatch.setattr(ha, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: NU)}))
    navne = {t.name for t in await server.mcp.list_tools()}
    assert set(claude_p.UGEPLAN_BIL) <= navne
    assert "ladet til 90 %" in (await server.bil_klar("07:30", 90))["svar"]
    assert "hver nat" in (await server.bil_lad_til(85))["svar"]
    assert (await server.bil_planlaeg("2026-12-05", "05:30", 100))["svar"].startswith("Planlagt: lørdag 5/12")
    assert "slukker selv" in (await server.bil_forvarm())["svar"]
    assert "under 3 °C" in (await server.bil_forvarmning(automatisk=True, under_grader=3))["svar"]
    with pytest.raises(Exception):
        await server.bil_planlaeg("5/12", "05:30")

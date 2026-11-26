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
        }
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
        "Opladning planlagt 03.00–06.00.\n"
        "Batteri: 45 %.\n"
        "Strøm nu: 4,05 kr./kWh."
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
    assert svar.startswith("Bilen skal være klar kl. 07.10 i morgen (kun denne gang).")
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
    assert {"mcp__ugeplan__bil_status", "mcp__ugeplan__bil_klar", "mcp__ugeplan__bil_oplad", "mcp__homeassistant__ha_get_state"} <= set(tilladt)
    assert not [t for t in tilladt if t.startswith("mcp__homeassistant__") and t.removeprefix("mcp__homeassistant__") not in claude_p.HA_LAES]
    assert "mcp__homeassistant" not in tilladt  # aldrig hele serveren (ha_call_service)


def test_claude_p_uden_home_assistant_faar_ingen_bil():
    tilladt = claude_p.tilladte_vaerktoejer({"mcpServers": {"ugeplan": {}}})
    assert not [t for t in tilladt if "bil_" in t or "homeassistant" in t]


async def test_bilvaerktoejerne_findes_i_serveren(falsk_ha):
    navne = {t.name for t in await server.mcp.list_tools()}
    assert set(claude_p.UGEPLAN_BIL) <= navne
    assert (await server.bil_klar("07:30"))["svar"].startswith("Bilen skal være klar kl. 07.30")

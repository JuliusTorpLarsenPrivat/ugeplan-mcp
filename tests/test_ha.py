"""Bilen i Home Assistant (ha.py, ha_besked.py) mod en falsk Home Assistant. Intet rigtigt kald."""

import json
from datetime import date, datetime, time

import httpx
import pytest

from handle_mcp import claude_p, ha, ha_besked, server, telegram, vagt

from test_telegram import FalskTelegram, par  # noqa: F401  (samme falske Telegram)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ0ZXN0In0.abcDEF123_-"
NU = datetime(2026, 11, 26, 20, 0, tzinfo=ha.TIDSZONE)  # torsdag aften: klar-tiden gælder fredag
I_DAG = NU.date()
OPRET = "/api/services/calendar/create_event"


def begivenhed(dag: str, titel: str, uid: str = "uid-1") -> dict:
    return {"summary": titel, "start": {"date": dag}, "end": {"date": dag}, "uid": uid}


class FalskHA:
    def __init__(self):
        self.tilstande = {
            "input_datetime.bil_klar_fredag": {"state": "06:15:00"},
            "input_datetime.bil_klar_torsdag": {"state": "06:15:00"},
            ha.SLUTTID: {"state": "06:15"},
            ha.LADNING: {"state": "off", "attributes": {"charging_is_planned": True, "charging_start_time": "2026-11-27T03:00:00+01:00", "charging_stop_time": "2026-11-27T06:00:00+01:00"}},
            ha.SAT_TIL: {"state": "on"},
            ha.BATTERI_ESTIMAT: {"state": "44.6"},
            ha.BATTERI: {"state": "44.6"},
            ha.ELPRIS: {"state": "4.0483"},
            ha.LADER: {"state": "Available"},
            ha.LAD_STANDARD: {"state": "80.0"},
            ha.MAAL_I_NAT: {"state": "80.0"},
            ha.KOMMENDE: {"state": "Ingen planlagte undtagelser"},
            ha.AUTO_FORVARM: {"state": "on"},
            ha.FORVARM_NU: {"state": "off"},
            ha.FORVARM_UNDER: {"state": "7.0"},
            ha.UDE: {"state": "2"},
        }
        self.begivenheder: list[dict] = []
        self.kald: list[tuple[str, str, dict | None]] = []
        self.ws: list[dict] = []
        self.ws_fejl = False
        self._uid = 0

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
        if request.url.path == OPRET:
            self._uid += 1
            self.begivenheder.append(begivenhed(data["start_date"], data["summary"], f"ny-{self._uid}"))
        if request.url.path == "/api/services/input_number/set_value":
            self.tilstande[data["entity_id"]]["state"] = f"{float(data['value'])}"
        if request.url.path.startswith("/api/services/input_boolean/"):
            self.tilstande[data["entity_id"]]["state"] = "on" if request.url.path.endswith("turn_on") else "off"
        return httpx.Response(200, json=[])

    async def websocket(self, besked: dict) -> dict:
        self.ws.append(besked)
        if self.ws_fejl:
            raise ha.HAFejl("Kunne ikke nå Home Assistant: forbindelsen blev afbrudt.")
        self.begivenheder = [b for b in self.begivenheder if b["uid"] != besked["uid"]]
        return {"id": 1, "type": "result", "success": True}

    def skrivninger(self):
        return [(s, d) for m, s, d in self.kald if m == "POST"]


@pytest.fixture
def falsk_ha(monkeypatch):
    f = FalskHA()
    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(ha, "_ws_transport", f.websocket)
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    return f


# --- fortolkning ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "tekst, forventet",
    [
        ("bil", ha_besked.Handling("status")),
        ("Status?", ha_besked.Handling("status")),
        ("klar 7", ha_besked.Handling("klar", tid=time(7, 0))),
        ("klar 07:30", ha_besked.Handling("klar", tid=time(7, 30))),
        ("Klar kl. 6.45", ha_besked.Handling("klar", tid=time(6, 45))),
        ("bilen skal være klar 8", ha_besked.Handling("klar", tid=time(8, 0))),
        ("klar 07:30 90%", ha_besked.Handling("klar", tid=time(7, 30), pct=90)),
        ("klar normal", ha_besked.Handling("klar")),
        ("Fjern undtagelse", ha_besked.Handling("klar")),
        ("klar 5/12 5:30 100%", ha_besked.Handling("planlaeg", tid=time(5, 30), pct=100, dato=date(2026, 12, 5))),
        ("Undtagelse 24.12 6", ha_besked.Handling("planlaeg", tid=time(6, 0), dato=date(2026, 12, 24))),
        ("klar 5/1 7", ha_besked.Handling("planlaeg", tid=time(7, 0), dato=date(2027, 1, 5))),
        ("undtagelser", ha_besked.Handling("undtagelser")),
        ("lad til 90", ha_besked.Handling("lad", pct=90)),
        ("Lad til 100% i nat", ha_besked.Handling("lad", pct=100, kun_i_nat=True)),
        ("forvarm nu", ha_besked.Handling("forvarm")),
        ("forvarmning fra", ha_besked.Handling("auto_forvarm", til=False)),
        ("automatisk forvarmning til", ha_besked.Handling("auto_forvarm", til=True)),
        ("forvarm under -3 grader", ha_besked.Handling("forvarm_under", grader=-3)),
        ("oplad nu", ha_besked.Handling("oplad")),
        ("Oplad nu!", ha_besked.Handling("oplad")),
        ("stop opladning", ha_besked.Handling("stop")),
    ],
)
def test_faste_bil_kommandoer(tekst, forventet):
    assert ha_besked.fortolk(tekst, I_DAG) == forventet


@pytest.mark.parametrize(
    "tekst",
    ["klar 25", "klar 7:75", "klar 0", "er bilen klar?", "stop", "hvornår er bilen klar til i morgen", "har 2 kg kartofler", "ok uge-1234",
     "klar 31/2 7", "lad til", "forvarm bilen i morgen tidlig", "varm maden op"],
)  # fmt: skip
def test_andet_er_ikke_bil_kommandoer(tekst):
    assert ha_besked.fortolk(tekst, I_DAG) is None


# --- status ----------------------------------------------------------------------------


async def test_status(falsk_ha):
    s = await ha.status(NU)
    assert s.tekst() == (
        "Bilen skal være klar kl. 06.15 (fast tid fredag).\n"
        "Mål i nat: 80 %.\n"
        "Opladning planlagt 03.00–06.00.\n"
        "Batteri: 45 %.\n"
        "Strøm nu: 4,05 kr./kWh.\n"
        "Bilen er sat til laderen.\n"
        "Forvarmning: automatisk under 7 °C (ude nu 2 °C)."
    )
    assert falsk_ha.skrivninger() == []  # status læser kun
    assert not [s for _, s, _ in falsk_ha.kald if "undtagelse_i_nat" in s or "bilen_skal_vaere_klar_kl" in s]


async def test_status_med_undtagelse_og_lader_offline(falsk_ha):
    falsk_ha.begivenheder.append(begivenhed("2026-11-27", "05:30 100%"))
    falsk_ha.tilstande[ha.MAAL_I_NAT]["state"] = "100.0"
    falsk_ha.tilstande[ha.KOMMENDE]["state"] = "fre 27/11 05:30 100%"
    falsk_ha.tilstande[ha.LADER]["state"] = "unavailable"
    falsk_ha.tilstande[ha.LADNING] = {"state": "off", "attributes": {"charging_is_planned": False}}
    tekst = (await ha.status(NU)).tekst()
    assert "klar kl. 05.30 (undtagelse, kun denne gang)" in tekst
    assert "Mål i nat: 100 % (standard 80 %)." in tekst
    assert "Planlagt: fre 27/11 05:30 100%" in tekst
    assert "Ingen opladning planlagt." in tekst
    assert "Bilen er sat til laderen. Laderen svarer dog ikke Home Assistant lige nu." in tekst  # BMW-reserven siger sat til


async def test_status_kl_5_gaelder_i_dag(falsk_ha):
    falsk_ha.tilstande["input_datetime.bil_klar_torsdag"]["state"] = "08:00:00"
    s = await ha.status(datetime(2026, 11, 26, 5, 0, tzinfo=ha.TIDSZONE))
    assert s.dag == "torsdag" and s.klar == "08.00"


async def test_status_kl_7_gaelder_i_morgen(falsk_ha):
    s = await ha.status(datetime(2026, 11, 26, 7, 0, tzinfo=ha.TIDSZONE))
    assert s.dag == "fredag"


# --- klar-tid via kalenderen -------------------------------------------------------------


async def test_klar_laegger_undtagelse_i_kalenderen(falsk_ha):
    svar = await ha.saet_klar(time(7, 30), NU)
    assert falsk_ha.skrivninger() == [(OPRET, {"entity_id": ha.KALENDER, "summary": "07:30", "start_date": "2026-11-27", "end_date": "2026-11-28"})]
    assert svar == "Bilen skal være klar kl. 07.30 i morgen (kun denne gang). Opladningen planlægges om lidt."
    assert falsk_ha.ws == []


async def test_klar_med_procent(falsk_ha):
    svar = await ha.saet_klar(time(7, 30), NU, pct=90)
    assert falsk_ha.skrivninger()[0][1]["summary"] == "07:30 90%"
    assert svar.startswith("Bilen skal være klar kl. 07.30 i morgen, ladet til 90 % (kun denne gang).")


async def test_klar_om_dagen_planlaegges_kl_18(falsk_ha):
    svar = await ha.saet_klar(time(7, 0), datetime(2026, 11, 26, 14, 0, tzinfo=ha.TIDSZONE))
    assert "i morgen" in svar and "planlægges kl. 18" in svar


async def test_klar_om_natten_gaelder_i_dag(falsk_ha):
    svar = await ha.saet_klar(time(7, 0), datetime(2026, 11, 26, 2, 0, tzinfo=ha.TIDSZONE))
    assert falsk_ha.skrivninger()[0][1]["start_date"] == "2026-11-26" and "i dag" in svar


async def test_klar_igen_erstatter_den_gamle(falsk_ha):
    await ha.saet_klar(time(7, 0), NU)
    svar = await ha.saet_klar(time(8, 0), NU, pct=100)
    assert falsk_ha.ws == [{"type": "calendar/event/delete", "entity_id": ha.KALENDER, "uid": "ny-1"}]
    assert [b["summary"] for b in falsk_ha.begivenheder] == ["08:00 100%"]  # kun én pr. dag
    assert "(erstatter 07:00)" in svar


async def test_kan_den_gamle_ikke_slettes_oprettes_ingen_ny(falsk_ha, monkeypatch):
    monkeypatch.setattr(ha, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: NU)}))
    falsk_ha.begivenheder.append(begivenhed("2026-11-27", "07:00"))
    falsk_ha.ws_fejl = True
    svar = await ha_besked.udfoer(ha_besked.Handling("klar", tid=time(8, 0)))
    assert svar.startswith("Det lykkedes ikke:") and "Slet den under Planlagte undtagelser på dashboardet" in svar
    assert falsk_ha.skrivninger() == []


async def test_klar_normal_sletter_undtagelsen(falsk_ha):
    falsk_ha.begivenheder.append(begivenhed("2026-11-27", "07:30 100%", "abc"))
    svar = await ha.saet_klar(None, NU)
    assert falsk_ha.ws == [{"type": "calendar/event/delete", "entity_id": ha.KALENDER, "uid": "abc"}]
    assert falsk_ha.skrivninger() == [] and falsk_ha.begivenheder == []
    assert svar.startswith("Undtagelsen i morgen (07:30 100%) er fjernet. Bilen skal være klar kl. 06.15 (fast tid fredag).")


async def test_klar_normal_uden_undtagelse(falsk_ha):
    svar = await ha.saet_klar(None, NU)
    assert svar == "Der er ingen undtagelse i morgen. Bilen skal være klar kl. 06.15 (fast tid fredag)."
    assert falsk_ha.ws == [] and falsk_ha.skrivninger() == []


async def test_klar_normal_roerer_ikke_andre_dage(falsk_ha):
    falsk_ha.begivenheder.append(begivenhed("2026-12-05", "05:30 100%"))
    await ha.saet_klar(None, NU)
    assert falsk_ha.ws == [] and len(falsk_ha.begivenheder) == 1


# --- planlagte dage, ladeniveau og forvarmning ---------------------------------------------


async def test_planlaeg_en_dato(falsk_ha):
    svar = await ha.planlaeg(date(2026, 12, 5), time(5, 30), 100, NU)
    assert falsk_ha.skrivninger() == [(OPRET, {"entity_id": ha.KALENDER, "summary": "05:30 100%", "start_date": "2026-12-05", "end_date": "2026-12-06"})]
    assert svar == "Bilen skal være klar kl. 05.30 lørdag 5/12, ladet til 100 % (kun denne gang)."


async def test_planlaeg_uden_procent(falsk_ha):
    await ha.planlaeg(date(2026, 12, 5), time(6, 0), None, NU)
    assert falsk_ha.skrivninger()[0][1]["summary"] == "06:00"


async def test_planlaeg_samme_dag_erstatter(falsk_ha):
    falsk_ha.begivenheder.append(begivenhed("2026-12-05", "06:00 90%", "gammel"))
    await ha.planlaeg(date(2026, 12, 5), time(5, 30), None, NU)
    assert falsk_ha.ws[0]["uid"] == "gammel" and [b["summary"] for b in falsk_ha.begivenheder] == ["05:30"]


async def test_planlaeg_i_fortiden_afvises(falsk_ha):
    with pytest.raises(ha.HAFejl):
        await ha.planlaeg(date(2026, 11, 20), time(6, 0), None, NU)
    assert falsk_ha.skrivninger() == []


@pytest.mark.parametrize("pct", [40, 101])
async def test_ladeniveau_uden_for_graenserne_skrives_ikke(falsk_ha, pct):
    with pytest.raises(ha.HAFejl):
        await ha.lad_til(pct)
    with pytest.raises(ha.HAFejl):
        await ha.saet_klar(time(7, 0), NU, pct)
    assert falsk_ha.skrivninger() == []


async def test_lad_til_hver_nat(falsk_ha):
    svar = await ha.lad_til(92, nu=NU)  # rundes til trin på 5
    assert falsk_ha.skrivninger() == [("/api/services/input_number/set_value", {"entity_id": ha.LAD_STANDARD, "value": 90})]
    assert svar.startswith("Bilen lades nu til 90 % hver nat")


async def test_lad_til_i_nat_bruger_den_faste_tid(falsk_ha):
    svar = await ha.lad_til(100, kun_i_nat=True, nu=NU)
    assert falsk_ha.skrivninger() == [(OPRET, {"entity_id": ha.KALENDER, "summary": "06:15 100%", "start_date": "2026-11-27", "end_date": "2026-11-28"})]
    assert svar.startswith("Bilen skal være klar kl. 06.15 i morgen, ladet til 100 %")


async def test_lad_til_i_nat_beholder_undtagelsens_tid(falsk_ha):
    falsk_ha.begivenheder.append(begivenhed("2026-11-27", "07:30"))
    await ha.lad_til(85, kun_i_nat=True, nu=NU)
    assert [b["summary"] for b in falsk_ha.begivenheder] == ["07:30 85%"]


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


# --- kun bilens enheder ----------------------------------------------------------------------


async def test_kun_bilens_enheder(falsk_ha):
    with pytest.raises(ha.HAFejl):
        await ha.tilstand("lock.hoveddoer")
    with pytest.raises(ha.HAFejl):
        await ha._tryk("button.noget_andet")
    for service, entitet in (
        ("input_boolean/turn_on", "input_boolean.undtagelse_i_nat"),  # bruges ikke længere
        ("input_boolean/turn_off", ha.FORVARM_NU),  # Mac-scriptet slukker selv
        ("input_number/set_value", ha.MAAL_I_NAT),  # skrives kun af automatiseringen
        ("input_number/set_value", "input_number.lad_op_til_i_nat"),
        ("input_datetime/set_datetime", "input_datetime.bilen_skal_vaere_klar_kl"),
        ("calendar/create_event", "calendar.familie"),
        ("lock/unlock", "lock.hoveddoer"),
    ):
        with pytest.raises(ha.HAFejl):
            await ha._service(service, entitet)
    for besked in (
        {"type": "calendar/event/delete", "entity_id": "calendar.familie", "uid": "x"},
        {"type": "calendar/event/update", "entity_id": ha.KALENDER, "uid": "x"},
        {"type": "call_service", "entity_id": ha.KALENDER},
    ):
        with pytest.raises(ha.HAFejl):
            await ha._ws(besked)
    assert falsk_ha.kald == [] and falsk_ha.ws == []


async def test_token_vises_aldrig_i_fejl(monkeypatch):
    def nede(request):
        raise httpx.ConnectError(f"fejl med {request.headers['Authorization']}")

    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(nede))
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    with pytest.raises(ha.HAFejl) as fejl:
        await ha.tilstand(ha.BATTERI)
    assert TOKEN not in str(fejl.value)


async def test_websocket_uden_ha_giver_kort_fejl(monkeypatch):
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    monkeypatch.setattr(ha, "url", lambda: "http://127.0.0.1:9")  # ingen lytter her
    monkeypatch.setattr(vagt, "_ha_vaert", lambda: "127.0.0.1")
    with pytest.raises(ha.HAFejl) as fejl:
        await ha._ws({"type": "calendar/event/delete", "entity_id": ha.KALENDER, "uid": "x"})
    assert str(fejl.value).startswith("Kunne ikke nå Home Assistant") and TOKEN not in str(fejl.value)


def test_forkert_token_gemmes_ikke(monkeypatch):
    monkeypatch.setattr(ha.keyring, "set_password", lambda *a: pytest.fail("må ikke gemmes"))
    with pytest.raises(ha.HAFejl):
        ha.gem("ikke et token")


# --- vagten ----------------------------------------------------------------------------


def test_vagten_tillader_kun_home_assistants_bilstier():
    for ok in (
        f"http://192.168.128.2:8123/api/states/{ha.BATTERI}",
        "http://192.168.128.2:8123/api/services/button/press",
        "http://192.168.128.2:8123/api/services/input_number/set_value",
        "http://192.168.128.2:8123/api/services/calendar/create_event",
        f"http://192.168.128.2:8123/api/calendars/{ha.KALENDER}?start=2026-12-05T00:00:00",
    ):
        vagt.tjek_url(httpx.URL(ok))
    for afvist in (
        "http://192.168.128.2:8123/api/services/lock/unlock",
        "http://192.168.128.2:8123/api/services/input_boolean/toggle",
        "http://192.168.128.2:8123/api/services/input_datetime/set_datetime",
        "http://192.168.128.2:8123/api/services/calendar/delete_event",
        "http://192.168.128.2:8123/api/services/script/turn_on",
        "http://192.168.128.2:8123/api/config",
        "http://192.168.1.50:8123/api/states/sensor.x",  # anden adresse på hjemmenettet
        "http://evil.example.com/api/services/button/press",
    ):
        with pytest.raises(vagt.VagtFejl):
            vagt.tjek_url(httpx.URL(afvist))


def test_vagten_tillader_kun_home_assistants_websocket():
    vagt.tjek_ws(httpx.URL("ws://192.168.128.2:8123/api/websocket"))
    for afvist in (
        "ws://192.168.128.2:8123/api/andet",
        "ws://192.168.1.50:8123/api/websocket",
        "wss://evil.example.com/api/websocket",
        "http://192.168.128.2:8123/api/websocket",
    ):
        with pytest.raises(vagt.VagtFejl):
            vagt.tjek_ws(httpx.URL(afvist))


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


async def test_nye_kommandoer_fra_telegram(tg, falsk_ha):
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    tg.besked(1, "lad til 90", navn="Julius")
    assert (await telegram.hent_og_haandter(0))[-1] == "bil (lad) fra Julius"
    assert "90 % hver nat" in tg.sendt[-1][1]
    tg.besked(1, "forvarm nu", navn="Julius")
    await telegram.hent_og_haandter(0)
    assert falsk_ha.skrivninger()[-1] == ("/api/services/input_boolean/turn_on", {"entity_id": ha.FORVARM_NU})


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


async def test_bilvaerktoejerne_i_serveren(falsk_ha, monkeypatch):
    monkeypatch.setattr(ha, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: NU)}))
    navne = {t.name for t in await server.mcp.list_tools()}
    assert set(claude_p.UGEPLAN_BIL) <= navne
    assert (await server.bil_klar("07:30", 90))["svar"].startswith("Bilen skal være klar kl. 07.30 i morgen, ladet til 90 %")
    assert "er fjernet" in (await server.bil_klar("normal"))["svar"]
    assert "hver nat" in (await server.bil_lad_til(85))["svar"]
    assert "lørdag 5/12" in (await server.bil_planlaeg("2026-12-05", "05:30", 100))["svar"]
    assert "slukker selv" in (await server.bil_forvarm())["svar"]
    assert "under 3 °C" in (await server.bil_forvarmning(automatisk=True, under_grader=3))["svar"]
    with pytest.raises(Exception):
        await server.bil_planlaeg("5/12", "05:30")


# --- sat til laderen: én fælles kilde (v0.41.0) -------------------------------------------------


@pytest.mark.parametrize(
    "sat_til, lader, linje",
    [
        ("on", "Charging", "Bilen er sat til laderen."),
        ("off", "Available", "Bilen er ikke sat til."),
        ("unavailable", "unavailable", "Ved ikke, om bilen er sat til (laderen svarer ikke)."),
        ("unknown", "Available", "Ved ikke, om bilen er sat til (laderen svarer ikke)."),
        ("on", "unavailable", "Bilen er sat til laderen. Laderen svarer dog ikke Home Assistant lige nu."),
    ],
)
async def test_sat_til_laderen(falsk_ha, sat_til, lader, linje):
    falsk_ha.tilstande[ha.SAT_TIL]["state"] = sat_til
    falsk_ha.tilstande[ha.LADER]["state"] = lader
    tekst = (await ha.status(NU)).tekst()
    assert linje in tekst.splitlines()
    if sat_til != "off":
        assert "ikke sat til." not in tekst  # aldrig "ikke sat til", når den sidder i eller vi ikke ved det


async def test_sat_til_kommer_kun_fra_den_faelles_kilde(falsk_ha):
    falsk_ha.tilstande["switch.ev_smart_charging_ev_connected"] = {"state": "off"}  # en indstilling, ikke en måling
    falsk_ha.tilstande["sensor.i3s_120_charging_port_plug_state"] = {"state": "DISCONNECTED"}
    assert "Bilen er sat til laderen." in (await ha.status(NU)).tekst()
    laest = {s.rsplit("/", 1)[-1] for _, s, _ in falsk_ha.kald}
    assert ha.SAT_TIL in laest
    assert not laest & {"switch.ev_smart_charging_ev_connected", "sensor.i3s_120_charging_port_plug_state"}
    for e in ("switch.ev_smart_charging_ev_connected", "sensor.i3s_120_charging_port_plug_state"):
        assert e not in ha.LAESER
        with pytest.raises(ha.HAFejl):
            await ha.tilstand(e)


# --- batteri-% fra estimatet (v0.42.1) -----------------------------------------------------------
# 28/11: BMW's % opdateres ikke under opladning, så bilen blev ladet til 95 % i stedet for 80 %.


async def test_batteri_fra_estimatet_under_opladning(falsk_ha):
    falsk_ha.tilstande[ha.BATTERI]["state"] = "62.0"  # BMW's sidste tal, før opladningen
    falsk_ha.tilstande[ha.BATTERI_ESTIMAT]["state"] = "79.6"
    s = await ha.status(NU)
    assert s.batteri == 79.6 and not s.batteri_fra_bmw
    assert "Batteri: 80 %." in s.tekst().splitlines()


@pytest.mark.parametrize("estimat", ["unavailable", "unknown"])
async def test_batteri_uden_estimat_bruger_bmw_og_siger_det(falsk_ha, estimat):
    falsk_ha.tilstande[ha.BATTERI_ESTIMAT]["state"] = estimat
    falsk_ha.tilstande[ha.BATTERI]["state"] = "62.0"
    s = await ha.status(NU)
    assert s.batteri == 62.0 and s.batteri_fra_bmw
    assert "Batteri: 62 % (BMW, kan være gammelt)." in s.tekst().splitlines()


async def test_batteri_ingen_af_dem(falsk_ha):
    falsk_ha.tilstande[ha.BATTERI_ESTIMAT]["state"] = "unavailable"
    falsk_ha.tilstande[ha.BATTERI]["state"] = "unavailable"
    s = await ha.status(NU)
    assert s.batteri is None and not s.batteri_fra_bmw and "Batteri" not in s.tekst()


async def test_estimatet_kan_kun_laeses(falsk_ha):
    assert ha.BATTERI_ESTIMAT in ha.LAESER
    assert not [e for e in ha.SKRIV.values() if ha.BATTERI_ESTIMAT in e]
    await ha.tilstand(ha.BATTERI_ESTIMAT)
    assert falsk_ha.skrivninger() == []


async def test_bil_status_vaerktoejet_giver_estimatet(falsk_ha):
    falsk_ha.tilstande[ha.BATTERI_ESTIMAT]["state"] = "79.6"
    ud = await server.bil_status()
    assert ud["batteri"] == 79.6 and ud["batteri_fra_bmw"] is False and "Batteri: 80 %." in ud["tekst"]


def test_claude_p_ved_at_estimatet_er_batteriet():
    assert "batteri (et estimat" in claude_p.SYSTEM

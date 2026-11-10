import pytest
from mcp.server.mcpserver.exceptions import ToolError

from garmin_mcp import cli, forbindelse, login, server


async def test_vaerktoejer_med_falsk_garmin(garmin):
    (s,) = await server.soevn("2026-11-04")
    assert s["sovet_timer"] == 7.25
    skridt = await server.skridt("2026-11-01", "2026-11-03")
    assert [d["dato"] for d in skridt] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    (puls,) = await server.hvilepuls("2026-11-04")
    assert puls == {"dato": "2026-11-04", "hvilepuls": 48, "hvilepuls_7_dage_gns": 49}
    (kal,) = await server.kalorier("2026-11-04")
    assert kal["kalorier_aktive"] == 790.0
    (t,) = await server.traeninger("2026-11-01", "2026-11-04")
    assert t["type"] == "running"
    assert ("get_activities_by_date", "2026-11-01", "2026-11-04") in garmin.kald
    (v,) = await server.vaegt("2026-11-04")
    assert v["vaegt_kg"] == 78.5
    status = await server.dagsstatus("i dag")
    assert "note" in status


async def test_forkert_dato_giver_laeselig_fejl(garmin):
    with pytest.raises(ToolError, match="Ukendt dato"):
        await server.skridt("sidste uge")
    with pytest.raises(ToolError, match="Højst 31"):
        await server.soevn("2026-01-01", "2026-03-01")
    assert garmin.kald == []  # intet sendt til Garmin


async def test_uden_login_faar_claude_besked_om_login():
    with pytest.raises(ToolError, match="garmin_mcp.server login"):
        await server.dagsstatus()


async def test_udloebet_login_glemmer_klienten(monkeypatch):
    from garminconnect import GarminConnectAuthenticationError

    class Udloebet:
        def get_stats(self, cdate):
            raise GarminConnectAuthenticationError("401")

    glemt = []
    monkeypatch.setattr(forbindelse, "klient", lambda person=None: Udloebet())
    monkeypatch.setattr(forbindelse, "glem_klient", lambda person=None: glemt.append(True))
    with pytest.raises(ToolError, match="virker ikke længere"):
        await server.skridt("2026-11-04")
    assert glemt


def test_status_viser_aldrig_koden(capsys):
    login.gem("anna", "anna@eksempel.dk", "superhemmelig")
    login.personmappe("anna").mkdir(parents=True)
    login.tokenfil("anna").write_text("{}")
    assert cli.kommando(["status"]) == 0
    ud = capsys.readouterr().out
    assert "anna@eksempel.dk" in ud and "superhemmelig" not in ud


def test_forkert_login_gemmes_ikke(monkeypatch, capsys):
    import garminconnect

    svar = iter(["anna@eksempel.dk"])
    monkeypatch.setattr("builtins.input", lambda _: next(svar))
    monkeypatch.setattr("getpass.getpass", lambda _: "forkert")

    class AfvisendeGarmin:
        def __init__(self, *a, **kw):
            pass

        def login(self, *a, **kw):
            raise garminconnect.GarminConnectAuthenticationError("401")

    monkeypatch.setattr(garminconnect, "Garmin", AfvisendeGarmin)
    assert cli.kommando(["login", "--person", "anna"]) == 1
    with pytest.raises(login.IntetLogin):
        login.hent("anna")
    assert not login.tokenfil("anna").exists()


def test_logout_sletter_login_og_tokens(capsys):
    login.gem("anna", "a@b.dk", "x")
    login.personmappe("anna").mkdir(parents=True)
    login.tokenfil("anna").write_text("{}")
    assert cli.kommando(["logout", "--person", "Anna"]) == 0
    assert not login.tokenfil("anna").exists()
    with pytest.raises(login.IntetLogin):
        login.hent("anna")


async def test_serveren_starter_og_viser_vaerktoejer():
    """Starter serveren som et rigtigt program, sådan som Claude Desktop gør."""
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    p = StdioServerParameters(command=sys.executable, args=["-m", "garmin_mcp.server"])
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        vaerktoejer = (await s.list_tools()).tools
    assert {t.name for t in vaerktoejer} == {"dagsstatus", "soevn", "hvilepuls", "skridt", "kalorier", "traeninger", "vaegt", "belastning"}
    assert all(t.annotations.read_only_hint for t in vaerktoejer)

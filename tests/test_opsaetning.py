"""Folk sætter det op forskelligt: én butik, ingen butik, uden Telegram eller Garmin.
Alt skal virke med det, der er sat op, og første gang guides husstanden igennem profilen."""

from decimal import Decimal

import pytest

from handle_mcp import cli, login, profil, sammenlign, telegram, ugeplan
from handle_mcp.butikker.nemlig import Nemlig
from handle_mcp.data import Kurv, Vare


def _med_login(monkeypatch, *butikker):
    monkeypatch.setattr(login, "har_login", lambda b: b in butikker)


class Butik:
    def __init__(self, navn, pris=10, gaest=False, med_login=True):
        self.navn, self.pris, self.med_login = navn, Decimal(pris), med_login
        self.priser_som_gaest = gaest

    async def kurv(self):
        if not self.med_login:
            raise login.IntetLogin(f"Intet login til {self.navn}")
        return Kurv(self.navn, [], Decimal(0), {"levering": Decimal(36)}, None, Decimal(300))

    async def tilbud(self, antal=25):
        return []

    async def soeg(self, tekst, antal=10):
        return [Vare(self.navn, "1", "Letmælk 1 l", self.pris, "1 l")]


def test_aktive_er_kun_butikker_med_login(monkeypatch):
    assert login.aktive() == []
    _med_login(monkeypatch, "bilka")
    assert login.aktive() == ["bilka"]


async def test_kun_en_butik_sammenligner_kun_den(monkeypatch):
    _med_login(monkeypatch, "bilka")
    r = await sammenlign.sammenlign([Butik("nemlig"), Butik("bilka")], [("letmælk", 1)])
    assert [x.butik for x in r] == ["bilka"] and r[0].fejl is None


async def test_manglende_login_vaelter_ikke_sammenligningen():
    r = await sammenlign.sammenlign([Butik("bilka", med_login=False)], [("letmælk", 1)])
    assert "Intet login" in r[0].fejl


async def test_nemlig_som_gaest_giver_priser_uden_kurv():
    (r,) = await sammenlign.sammenlign([Butik("nemlig", gaest=True, med_login=False)], [("letmælk", 1)])
    assert r.fejl is None and r.linjer[0].valgt and r.minimumskoeb is None


async def test_nemlig_gaest_kun_ved_laesning(monkeypatch):
    n = Nemlig()
    kaldt = []

    async def tokens():
        n._token = "gaest"
        kaldt.append("tokens")

    async def raa(metode, url, **kw):
        return {"ok": url}

    monkeypatch.setattr(n, "_nye_tokens", tokens)
    monkeypatch.setattr(n, "_raa", raa)
    assert await n._kald("GET", gaest_ok=True, url="https://x/soeg") == {"ok": "https://x/soeg"}
    assert kaldt == ["tokens"] and not n._logget_ind
    with pytest.raises(login.IntetLogin):  # kurv, levering og ordrer kræver login
        await n._kald("GET", "https://x/kurv")


def test_flowet_naevner_ikke_begge_butikker_som_krav():
    t = ugeplan.tekst_chat("5")
    assert "begge butikker" not in t and "begge kurve" not in t
    assert "BUTIKKERNE" in t and "spring den del over" in t


def test_garmin_er_valgfrit():
    assert "garmin-værktøjerne, så" in ugeplan.tekst_chat("5")


async def test_foerste_gang_koerer_guiden_og_sender_intet(monkeypatch):
    monkeypatch.setattr(ugeplan, "FOERSTE_GANG_AKTIV", True)
    monkeypatch.setattr(ugeplan, "telegram_klar", lambda: True)

    async def maa_ikke_sende(_):
        raise AssertionError("guiden må ikke skrive til Telegram")

    monkeypatch.setattr(telegram, "send_til_alle", maa_ikke_sende)
    svar = await ugeplan.start()
    assert svar["foerste_gang"] and svar["butikker"] == []
    f = svar["forloeb"]
    for ord_ in ("Runde 1", "Runde 4", "GEM EFTER HVER RUNDE", "uden login"):
        assert ord_ in f


async def test_guiden_stopper_naar_profilen_er_udfyldt(monkeypatch):
    monkeypatch.setattr(ugeplan, "FOERSTE_GANG_AKTIV", True)
    profil.opdater(personer=2)
    svar = await ugeplan.start()
    assert "foerste_gang" not in svar and "KØLESKABET" in svar["forloeb"]


def test_profilen_kan_gennemgaas_igen():
    assert "4 korte runder" in profil.vis()["gennemgang"]


def test_opsaet_kan_springes_helt_over(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert cli.kommando(["opsaet"]) == 0
    ud = capsys.readouterr().out
    assert "TRIN 1/3" in ud and "TRIN 3/3" in ud and '"mcpServers"' in ud and "lav madplan" in ud


def test_claude_config_peger_paa_repoet():
    k = cli.claude_config()["mcpServers"]["ugeplan"]
    assert k["args"][0] == "--from" and "ugeplan-mcp" in k["args"][1] and k["args"][2] == "ugeplan-mcp"


def test_guiden_er_ikke_bundet_til_claude(monkeypatch, capsys):
    """Julius: "vi dikterer ikke, at der SKAL bruges Claude". Alle apps får samme kommando."""
    cmd, args = cli.server_kommando()
    for valg in cli.KLIENTER:
        tekst = cli.klient_vejledning(valg)
        assert args[1] in tekst, valg  # samme kilde (git+…@vX) i alle apps
    assert "claude mcp add" in cli.klient_vejledning("2")
    assert '"servers"' in cli.klient_vejledning("4") and '"type": "stdio"' in cli.klient_vejledning("4")
    assert "Over netværket" in cli.klient_vejledning("5")
    monkeypatch.setattr("builtins.input", lambda *_: "3")
    cli.kommando(["opsaet"])
    ud = capsys.readouterr().out
    assert "Cursor" in ud and "Claude Desktop helt" not in ud and "TRIN 3/3: DIN AI-APP" in ud


def test_telegram_taler_ikke_om_claude():
    from handle_mcp import telegram

    for t in (telegram.IKKE_LYTTER, telegram.IKKE_I_GANG_FORTSAET, telegram.ERSTATNING_LYTTER, telegram.ERSTATNING_IKKE_LYTTER, telegram.BESTIL_EFTER_RETTELSE):
        assert "Claude" not in t


def test_guiden_med_garmin_lægger_begge_servere_ind(monkeypatch, capsys):
    k = cli.claude_config(garmin=True)["mcpServers"]
    assert set(k) == {"ugeplan", "garmin"}
    assert k["ugeplan"]["args"][1].startswith("ugeplan-mcp[garmin] @ git+") and k["garmin"]["args"][-1] == "garmin-mcp"
    assert set(cli.claude_config()["mcpServers"]) == {"ugeplan"}  # uden Garmin: som før
    assert cli.klient_vejledning("2", garmin=True).count("claude mcp add") == 2
    assert '"garmin"' in cli.klient_vejledning("4", garmin=True)
    svar = iter(["", "", "", "j", "1"])  # nemlig nej, bilka nej, telegram nej, garmin ja, Claude Desktop
    monkeypatch.setattr("builtins.input", lambda *_: next(svar, ""))
    cli.kommando(["opsaet"])
    ud = capsys.readouterr().out
    assert "garmin-mcp login --person <navn>" in ud and '"garmin"' in ud

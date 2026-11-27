"""Bilen i samtalen (v0.40.1): beskederne fra den rigtige test 27/11 20.34-20.37.

"Slet undtagelsen igen" og "Slet undtagelsen i morgen" blev taget af beholdningens "slet …"
("Fandt ikke: undtagelsen igen."), og claude -p's svar startede med "Svar til Julius: Svar til
Julius:". Julius: "et menneske havde alle dage forstået hvad 'slet undtagelsen igen' betød".
"""

import pytest

from handle_mcp import claude_p, ha, ha_besked, lokal, telegram

from test_ha import FalskHA, TOKEN, begivenhed  # noqa: F401
from test_telegram import FalskTelegram, claude, par, tg  # noqa: F401  (fixtures)


@pytest.fixture
def bil(monkeypatch, tg):  # noqa: F811
    import httpx

    f = FalskHA()
    monkeypatch.setattr(ha, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(ha, "_ws_transport", f.websocket)
    monkeypatch.setattr(ha, "hent_token", lambda: TOKEN)
    # næste morgen efter det rigtige ur: der ligger en undtagelse "08:00 100%"
    from datetime import datetime

    nu = datetime.now(ha.TIDSZONE)
    f.dag = ha.naeste_morgen(nu)
    f.tilstande[ha.FASTE[f.dag.weekday()]] = {"state": "06:15:00"}
    f.begivenheder.append(begivenhed(f.dag.isoformat(), "08:00 100%", "abc"))
    return f


async def _skriv(tg, tekst, navn="Julius"):  # noqa: F811
    tg.besked(1, tekst, navn=navn)
    return (await telegram.hent_og_haandter(0))[-1]


@pytest.mark.parametrize("tekst", ["Slet undtagelsen igen", "Slet undtagelsen i morgen", "fjern undtagelsen", "slet undtagelsen."])
async def test_slet_undtagelsen_er_bilen_ikke_beholdningen(tg, bil, tekst):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    assert await _skriv(tg, tekst) == "bil (klar) fra Julius"
    assert bil.ws == [{"type": "calendar/event/delete", "entity_id": ha.KALENDER, "uid": "abc"}]
    assert "Undtagelsen i morgen (08:00 100%) er fjernet" in tg.sendt[-1][1]
    assert not [s for _, s in tg.sendt if "Fandt ikke" in s]


@pytest.mark.parametrize("tekst", ["slet den igen", "nej, kl. 9 i stedet", "slet det igen", "slet undtagelsen 5/12"])
async def test_tvetydigt_efter_snak_om_bilen_gaar_til_claude_med_samtalen(tg, bil, claude, tekst):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    await _skriv(tg, "klar 8 100%")
    claude.svar = "Svar til Julius: Svar til Julius: Undtagelsen i morgen er fjernet."
    assert await _skriv(tg, tekst) == "fri tekst fra Julius besvaret af claude -p"
    prompt = claude.kald[-1][2]
    assert "Julius: klar 8 100%" in prompt and "handle-botten (til Julius): Bilen skal være klar kl. 08.00" in prompt
    assert prompt.rstrip().endswith(tekst)
    assert tg.sendt[-1] == (1, "Undtagelsen i morgen er fjernet.")  # præfikset fjernet
    gemt = lokal.laes("beskeder")["beskeder"][-1]["tekst"]
    assert gemt == "Svar til Julius: Undtagelsen i morgen er fjernet."  # kun én gang
    tilladt = claude.flag("--allowedTools").split(",")
    assert "mcp__ugeplan__bil_klar" in tilladt and "mcp__homeassistant" not in tilladt


async def test_beholdningen_virker_stadig_efter_snak_om_bilen(tg, bil):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    await _skriv(tg, "bil")
    assert await _skriv(tg, "har 2 kg kartofler") == "beholdning ændret af Julius"
    assert await _skriv(tg, "fjern kartofler") == "beholdning ændret af Julius"


async def test_tvetydigt_uden_snak_om_bilen_roeres_ikke(tg, bil, claude):  # noqa: F811
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    await _skriv(tg, "slet den igen")
    assert bil.kald == [] and bil.ws == []  # bilen blev ikke spurgt


def test_om_bilen():
    from datetime import datetime

    nu = datetime(2026, 11, 27, 20, 40, tzinfo=ha.TIDSZONE)
    snak = [{"tid": "2026-11-27T20:35+01:00", "fra": "handle-botten", "tekst": "Svar til Julius: Bilen skal være klar kl. 08.00 i morgen"}]
    gammel = [{"tid": "2026-11-27T18:00+01:00", "fra": "handle-botten", "tekst": "Bilen skal være klar kl. 08.00"}]
    assert ha_besked.om_bilen("slet undtagelsen 5/12", [], nu)
    assert ha_besked.om_bilen("slet den igen", snak, nu)
    assert not ha_besked.om_bilen("slet den igen", gammel, nu)  # for længe siden
    assert not ha_besked.om_bilen("slet den igen", [], nu)
    assert not ha_besked.om_bilen("fjern mælk", snak, nu)
    assert not ha_besked.om_bilen("har 2 kg kartofler", snak, nu)
    assert not ha_besked.om_bilen("fjern bilka-mælken", snak, nu)  # "bilka" er ikke "bil"


def test_svar_til_praefikset_fjernes_og_vises_ikke_for_claude():
    assert claude_p.SVAR_TIL.sub("", "Svar til Julius: Svar til Julius: Hej") == "Hej"
    linje = claude_p._linje({"tid": "2026-11-27T20:37+01:00", "fra": "handle-botten", "tekst": "Svar til Julius: Undtagelsen er fjernet."})
    assert linje == "[20.37] handle-botten (til Julius): Undtagelsen er fjernet."

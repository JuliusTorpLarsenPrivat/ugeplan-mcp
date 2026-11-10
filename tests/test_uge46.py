"""Fund fra brug i uge 46: frosne rødspætter i kurven, mængder i køleskabssvaret,
værktøjstekst på Telegram og en forkert advarsel om levering."""

from datetime import date

from handle_mcp import levering, telegram, ugeplan
from handle_mcp.butikker import bilka

HIT = {
    "objectID": "110001",
    "name": "Rødspættefileter",
    "netcontent": "400 g",
    "properties": ["Nøglehul", "Frost"],
    "price": 6050,
    "storeData": {"1": {"price": 4900, "inStock": True}},
}


def test_bilkas_frostvarer_viser_frost_i_maengden():
    v = bilka.vare_fra_hit(HIT, "1")
    assert v.maengde == "400 g / frost"
    fersk = bilka.vare_fra_hit({**HIT, "properties": ["Nøglehul"]}, "1")
    assert fersk.maengde == "400 g"
    assert bilka.maengde_fra_hit({"properties": ["Frost"]}) == "frost"


def test_forloebet_forbyder_frost_og_falsk_fersk():
    tekst = ugeplan.FAELLES
    assert '"400 g / frost"' in tekst and "ALDRIG i kurven" in tekst
    assert "Skriv kun \"fersk\"" in tekst


def test_spoergsmaalet_beder_om_maengder():
    assert "Skriv ca. hvor meget" in ugeplan.FOERSTE_SPOERGSMAAL
    lev = {"bilka": {"dato": "2026-11-10", "foerste_aftensmad": "tirsdag 10/11"}}
    assert "Skriv ca. hvor meget" in ugeplan.foerste_spoergsmaal(lev)
    assert "MÆNGDER I SVARET" in ugeplan.FAELLES and "kartofler 1,5 kg" in ugeplan.FAELLES


def test_ikke_fyldt_viser_ikke_vaerktoejets_instrukser(monkeypatch):
    fejl = (
        "Kurven hos bilka er ikke tom (1 x Zinfandel). Spørg brugeren, om de varer skal blive, "
        "og kald igen med kurven_maa_have_andet=True, eller bed dem tømme kurven."
    )
    monkeypatch.setattr(telegram, "claude_lytter", lambda: True)
    tekst = telegram.ikke_fyldt_tekst(fejl)
    assert "Zinfandel" in tekst and "kurven_maa_have_andet" not in tekst and "Spørg brugeren" not in tekst
    monkeypatch.setattr(telegram, "claude_lytter", lambda: False)
    assert "fortsæt i chatten med AI-assistenten" in telegram.ikke_fyldt_tekst(fejl)


def test_rester_er_ikke_planens_start():
    retter = ["Man: Rester", "Tir: Wok med svinemørbrad", "Søn: Rødspætte"]
    assert levering.planens_start(retter, date(2026, 11, 8)) == date(2026, 11, 10)
    assert levering.planens_start(["Lør: ingen aftensmad hjemme", "Søn: Steg"], date(2026, 11, 13)) == date(2026, 11, 15)
    # rester med noget nyt til skal stadig have varerne
    assert levering.planens_start(["Man: Rest af chili med ris og avocado", "Tir: Wok"], date(2026, 11, 8)) == date(2026, 11, 9)


def test_ny_butikskode_giver_ny_forekomst(monkeypatch):
    """Efter genindlæsning af bilka.py skal den gemte butik bruge den nye klasse."""
    import importlib

    from handle_mcp import butikker
    from handle_mcp.butikker import bilka as bilka_modul

    monkeypatch.setattr(butikker, "_butikker", {})
    foer = butikker.hent_butik("bilka")
    assert butikker.hent_butik("bilka") is foer  # samme forekomst, så login genbruges
    importlib.reload(bilka_modul)
    efter = butikker.hent_butik("bilka")
    assert efter is not foer and type(efter) is bilka_modul.Bilka

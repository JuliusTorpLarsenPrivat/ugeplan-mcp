"""Beholdningen direkte fra Telegram, uden AI'en. Julius' eksempler: vildt, mælk, kartofler, fortryd."""

import pytest

from handle_mcp import beholdning, beholdning_besked as bb


def _navne():
    return {v.navn: v for v in beholdning.hent()}


@pytest.mark.parametrize(
    ("tekst", "forventet"),
    [
        ("Skudt et rådyr, ligger i fryseren", [{"navn": "rådyr", "sted": "fryser"}]),
        ("har 2 kg kartofler", [{"navn": "kartofler", "maengde": "2 kg", "sted": "skab"}]),
        ("tilføj mælk og 10 æg", [{"navn": "mælk", "sted": "køleskab"}, {"navn": "æg", "maengde": "10", "sted": "køleskab"}]),
        ("Vi har 2 grågæs i fryseren", [{"navn": "grågæs", "maengde": "2", "sted": "fryser"}]),
        ("har hvidløg", [{"navn": "hvidløg", "sted": "skab"}]),
        ("Har lige skudt 2 ænder, de ligger i fryseren", [{"navn": "ænder", "maengde": "2", "sted": "fryser"}]),
        ("Jeg har fået en hare og den ligger i fryseren", [{"navn": "hare", "sted": "fryser"}]),
        ("vi har købt 1 kg hakket oksekød", [{"navn": "hakket oksekød", "maengde": "1 kg"}]),
    ],
)
def test_tilfoej(tekst, forventet):
    h = bb.fortolk(tekst)
    assert h and h.tilfoej == forventet and not h.fjern


@pytest.mark.parametrize(("tekst", "navne"), [("fjern mælk", ["mælk"]), ("mælken er brugt", ["mælken"]), ("Rådyret er spist.", ["Rådyret"])])
def test_fjern(tekst, navne):
    h = bb.fortolk(tekst)
    assert h and h.fjern == navne and not h.tilfoej


@pytest.mark.parametrize(
    "tekst",
    [
        "vi har ikke mere mælk",  # benægtelse: ikke en vare
        "husk vi har altid salt",  # profilønske, ikke beholdning
        "har I husket at købe mælk?",  # spørgsmål
        "Hej vi har rester til mandag og jeg har kartofler citron løg hvidløg forårsløg jeg har også 2 kg græsk yoghurt og en pose gulerødder, 2 æbler og 3 æg og en halv liter mælk",  # et svar til planen
        "tak for maden",
        "Har du set min telefon i køleskabet",  # spørgsmål uden spørgsmålstegn
        "Bestil",
    ],
)
def test_alt_andet_gaar_til_ai_en(tekst):
    assert bb.fortolk(tekst) is None


def test_udfoer_og_fortryd():
    beholdning.opdater(tilfoej=[{"navn": "mælk", "maengde": "1 l", "sted": "køleskab"}])
    svar = bb.udfoer(bb.fortolk("skudt et rådyr, ligger i fryseren"))
    assert "rådyr (fryser)" in svar and "fortryd" in svar
    assert _navne()["rådyr"].sted == "fryser"
    assert bb.udfoer(bb.fortolk("mælken er brugt")).startswith("Fjernet: mælk")
    assert "mælk" not in _navne()
    assert bb.udfoer(bb.fortolk("fortryd")) == "Fortrudt. Beholdningen er som før."
    assert _navne()["mælk"].maengde == "1 l"  # mælken er tilbage, med mængde og sted
    assert bb.udfoer(bb.fortolk("fortryd")) == "Der er ikke noget at fortryde."


def test_fortryd_af_ret_mængde_giver_den_gamle_tilbage():
    beholdning.opdater(tilfoej=[{"navn": "kartofler", "maengde": "500 g", "sted": "skab"}])
    bb.udfoer(bb.fortolk("har 2 kg kartofler"))
    assert _navne()["kartofler"].maengde == "2 kg"
    bb.udfoer(bb.fortolk("fortryd"))
    assert _navne()["kartofler"].maengde == "500 g"


def test_ukendt_vare_siges():
    assert bb.udfoer(bb.fortolk("fjern safran")) == "Fandt ikke: safran."

"""Ugens budget: profilens beløb gælder en normal uge; færre dage, gæster og egne varer ændrer det."""

from handle_mcp import ugeplan


def test_budgettet_gælder_en_normal_uge_og_tilpasses():
    t = ugeplan.FAELLES
    assert "gælder en NORMAL uge" in t and "beskrivelse af den normale uge i profilens note" in t
    assert "Gæster" in t and "Færre aftener hjemme" in t


def test_eget_vildt_trækkes_fra_budgettet():
    t = ugeplan.FAELLES
    assert "EGNE VARER SKAL KUNNE SES I UGENS BUDGET" in t and "rådyr fra egen fryser" in t

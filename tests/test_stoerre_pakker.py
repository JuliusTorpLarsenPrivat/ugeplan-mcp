"""Større pakker og mængdetilbud: når dobbelt mængde er mærkbart billigere, siger linjens tip det,
så AI'en kan lægge to retter på ét køb. Julius: "det er billigere pr. kyllingelår at købe 8 stk end 2 stk"."""

from decimal import Decimal

from handle_mcp import ugeplan
from handle_mcp.data import Vare
from handle_mcp.maengde import Maengde
from handle_mcp.sammenlign import Linje


def vare(id_, navn, pris, maengde, tilbud=None):
    return Vare("bilka", id_, navn, Decimal(str(pris)), maengde=maengde, tilbud=tilbud)


def test_stor_pakke_hakket_okse_billigere_pr_kg():
    lille = vare("1", "Hakket oksekød 8-12 %", 45, "400 g")
    stor = vare("2", "Hakket oksekød 8-12 %", 69, "800 g")
    ln = Linje("400 g hakket oksekød", 1, lille, [], True, Maengde(400, "g"), [lille, stor])
    assert ln.tip.startswith("Større køb er billigere: 800 g koster 69.00 kr (Hakket oksekød 8-12 % 800 g) mod 90.00 kr")
    assert "spar 21 kr" in ln.tip


def test_kyllingelår_pr_stk():
    to = vare("1", "Kyllingeunderlår", 30, "2 stk")
    otte = vare("2", "Kyllingeunderlår", 80, "8 stk")
    ln = Linje("4 stk kyllingeunderlår", 1, to, [], True, Maengde(4, "stk"), [to, otte])
    assert "8 stk koster 80.00 kr" in ln.tip and "mod 120.00 kr" in ln.tip


def test_mængdetilbud_tæller_med():
    kylling = vare("1", "Kyllingebrystfilet", 49.95, "280 g", tilbud="Mix 2 for 79,00")
    ln = Linje("280 g kyllingebryst", 1, kylling, [], True, Maengde(280, "g"), [kylling])
    assert "560 g koster 79.00 kr (samme vare)" in ln.tip


def test_intet_tip_når_besparelsen_er_lille_eller_matchet_usikkert():
    lille = vare("1", "Hakket oksekød", 45, "400 g")
    stor = vare("2", "Hakket oksekød", 85, "800 g")  # kun 5,6 % billigere
    assert Linje("400 g hakket oksekød", 1, lille, [], True, Maengde(400, "g"), [lille, stor]).tip is None
    billig = vare("3", "Hakket oksekød", 60, "800 g")
    assert Linje("400 g hakket oksekød", 1, lille, [], False, Maengde(400, "g"), [lille, billig]).dobbelt is None  # usikkert match
    assert Linje("hakket oksekød", 1, lille, [], True, None, [lille, billig]).dobbelt is None  # uden mængde


def test_forløbet_planlægger_to_retter_på_ét_køb():
    t = ugeplan.FAELLES
    assert "ÉT KØB TIL TO RETTER" in t and "8 kyllingelår" in t and "Større køb er billigere" in t
    assert "Fersk fisk deles aldrig over flere dage" in t


def test_kun_samme_vare_i_anden_størrelse():
    oeko = Vare("bilka", "1", "Hakket oksekød 8-12% fedt", Decimal("62.95"), maengde="0.4 kg", maerke="Salling ØKO")
    andet_maerke = Vare("bilka", "2", "Hakket oksekød 8-12% fedt", Decimal("42.95"), maengde="0.4 kg", maerke="Slagteren")
    roeget = Vare("bilka", "3", "Røget kyllingebryst", Decimal("11"), maengde="100 g", maerke="Salling")
    assert Linje("400 g hakket oksekød", 1, oeko, [andet_maerke, roeget], True, Maengde(400, "g"), [oeko, andet_maerke, roeget]).dobbelt is None


def test_pakke_der_allerede_dækker_to_retter():
    stor = vare("1", "Hele kyllingelår", 64.95, "1.6 kg")
    ln = Linje("600 g kyllingelår", 1, stor, [], True, Maengde(600, "g"), [stor])
    assert ln.dobbelt.startswith("Pakken (1.6 kg) dækker 1200 g: resten kan bruges til en ret mere")


def test_parret_bygges_af_rigtige_opskrifter_og_står_tydeligt_i_menuen():
    t = ugeplan.FAELLES
    assert "OPFIND IKKE NYE OPSKRIFTER" in t and "lav dobbelt portion kartofler, til tirsdag" in t
    assert "Gem linket til den" in t

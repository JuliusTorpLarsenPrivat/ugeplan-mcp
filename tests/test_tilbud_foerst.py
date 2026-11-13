"""Tilbud først: ugens tilbud på det, husstanden køber, sorteret efter profilen, og ugens butik."""

import json
from decimal import Decimal

from handle_mcp import lokal, profil, tilbud, ugeplan
from handle_mcp.data import Vare


def v(id_, navn, pris, foer=None, maengde=None, tilbud_=None, maerke=None):
    return Vare("x", id_, navn, Decimal(str(pris)), maengde=maengde, maerke=maerke, tilbud=tilbud_, foer_pris=Decimal(str(foer)) if foer else None)


def _profil():
    profil.opdater(
        praeferencer=["høj kødkvalitet: kød altid øko eller vores eget vildt"],
        undgaa=["opdrættet fisk (kun vildfanget)", "fisk fra frost (kun fersk fisk)", "kød fra frost"],
        faste_maaltider=["Morgenmad hver dag, 2 pers.: græsk yoghurt med vindruer, mandler og mørk chokolade"],
    )


def test_besparelse_rabat_og_mængdetilbud():
    assert tilbud.besparelse(v("1", "Kyllingebryst øko", 70, foer=100)) == (Decimal(30), 30)
    sp = tilbud.besparelse(v("2", "Kyllingebrystfilet", "43.95", tilbud_="Mix 2 for 79,00"))
    assert round(sp[0], 2) == Decimal("4.45") and sp[1] == 10
    assert tilbud.besparelse(v("3", "Mælk", 12)) is None


def test_grupper_og_faste_varer():
    _profil()
    faste = tilbud.faste_ord()
    assert {"yoghurt", "vindruer", "mandler", "chokolade"} <= faste
    assert tilbud.gruppe(v("1", "Torskefilet", 60), faste) == "fisk"
    assert tilbud.gruppe(v("2", "Kyllingebryst øko", 60), faste) == "fugl"
    assert tilbud.gruppe(v("3", "Hakket oksekød øko", 60), faste) == "kød"
    assert tilbud.gruppe(v("4", "Græsk yoghurt 10 % øko", 30), faste) == "faste"
    assert tilbud.gruppe(v("5", "Toiletpapir", 30), faste) is None


def test_oversigt_sorterer_profilbrud_fra_og_vælger_ugens_butik():
    _profil()
    nemlig = [
        v("1", "Kyllingebryst øko", 70, foer=100),  # fugl, øko: 30 kr
        v("2", "Torskefilet", 50, foer=60, maengde="400 g / frost"),  # frost: ud
        v("3", "Hakket oksekød", 40, foer=60),  # ikke øko: ud
        v("4", "Laks", 60, foer=90),  # opdrættet: ud
        v("5", "Græsk yoghurt øko", 25, foer=35),  # faste: 10 kr
    ]
    bilka = [v("6", "Fersk sej", 45, foer=55)]  # fisk: 10 kr
    o = tilbud.oversigt({"nemlig": nemlig, "bilka": bilka})
    navne = [a["navn"] for a in o["butikker"]["nemlig"]["ankre"]]
    assert navne == ["Kyllingebryst øko", "Græsk yoghurt øko"]
    assert o["butikker"]["nemlig"]["sum_spar_kr"] == 40 and o["ugens_butik"] == "nemlig"
    assert o["butikker"]["bilka"]["ankre"][0]["gruppe"] == "fisk"


def test_historikken_gemmer_fisk_fugl_og_kød():
    tilbud.gem_historik({"bilka": [v("1", "Kyllingebryst øko", 70, foer=100), v("2", "Toiletpapir", 30, foer=40)]})
    uger = json.loads((lokal.mappe() / "tilbud_historik.json").read_text(encoding="utf-8"))["uger"]
    assert uger[-1]["butik"] == "bilka" and [x["navn"] for x in uger[-1]["varer"]] == ["Kyllingebryst øko"]
    assert uger[-1]["varer"][0] == {"gruppe": "fugl", "navn": "Kyllingebryst øko", "maengde": None, "pris": 70.0, "spar_pct": 30, "oeko": True, "frost": False}


def test_forløbet_bygger_på_tilbud_i_ugens_butik():
    t = ugeplan.FAELLES
    assert "TILBUD FØRST" in t and "Byg kun på tilbud i ugens butik" in t and "FUGL PÅ LAGER" in t
    assert "Læs `tilbud`" in ugeplan.FORBEREDELSE


def test_faste_varer_matcher_præcist_og_følger_vareønsket():
    profil.opdater(
        faste_maaltider=["Morgenmad hver dag, 2 pers.: græsk yoghurt blandet med skyr, vindruer og mørk chokolade"],
        varepraeferencer=["Mørk chokolade: meget mørk, mindst 85 %"],
    )
    f = tilbud.faste_ord()
    assert tilbud.gruppe(v("1", "Græskarkernestykker", 15), f) is None  # "græsk" er ikke græskar
    assert tilbud.gruppe(v("2", "Blandet saft", 15), f) is None
    assert tilbud.gruppe(v("3", "Skyr naturel øko", 20), f) == "faste"
    p = profil.hent()
    assert tilbud.advarsler(v("4", "Mælkepålægschokolade 26% kakao", 42, foer=50), "faste", p) == ["under 85 %"]
    assert tilbud.advarsler(v("5", "Mørk chokolade 85 % øko", 20, foer=25), "faste", p) == []


def test_kød_i_fryseren_tæller_ikke_med_i_valget_af_butik():
    from handle_mcp import beholdning

    _profil()
    beholdning.opdater(tilfoej=[{"navn": "råvildt kølle", "maengde": "4 stk", "sted": "fryser"}])
    o = tilbud.oversigt({"nemlig": [v("1", "Angus culottesteg øko", 360, foer=515)], "bilka": [v("2", "Fersk sej", 45, foer=55)]})
    assert o["ugens_butik"] == "bilka" and "kød i fryseren" in o["note"]
    assert o["butikker"]["nemlig"]["sum_spar_kr"] == 0 and o["butikker"]["nemlig"]["ankre"][0]["gruppe"] == "kød"


def test_færdigretter_smag_og_mager_sorteres_fra():
    profil.opdater(
        faste_maaltider=["Morgenmad: græsk yoghurt 10 % blandet med øko skyr og vindruer"],
        varepraeferencer=["Mejeriprodukter: altid højest mulige fedtprocent"],
    )
    p = profil.hent()
    assert "forarbejdet" in tilbud.advarsler(v("1", "Citron kylling øko", 110, maengde="730 g / 2 personer"), "fugl", p)
    assert "forarbejdet" in tilbud.advarsler(v("2", "Kyllingebouillon øko", 15), "fugl", p)
    assert "smagsvariant" in tilbud.advarsler(v("3", "Skyr m. vanilje", 24), "faste", p)
    assert "mager" in tilbud.advarsler(v("4", "Skyr naturel 0,2% fedt", 24, maengde="1 kg"), "faste", p)
    assert tilbud.advarsler(v("5", "Skyr naturel øko 2,5%", 24), "faste", p) == []
    assert tilbud.advarsler(v("6", "Kyllingebrystfilet øko", 58, maengde="240 g"), "fugl", p) == []

"""Agil madplan efter træning (design-agil-madplan-traening.md): forslag uden AI, når en dag går
anderledes, med reglerne om fersk fisk og optøning, højst ét forslag om dagen og "ja" fra Telegram."""

import json
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from handle_mcp import madplan, profil, traening
from handle_mcp.lokal import LokalFejl

TZ = ZoneInfo("Europe/Copenhagen")
AFTEN = time(18, 30)
# Planen er lavet søndag 8/11; tirsdag 10/11 er "i dag" i testene
RETTER = ["Man: Rester", "Tir: Shakshuka med feta", "Ons: Stegt rødspætte", "Tor: Pasta med kødsovs", "Fre: Nakkekoteletter med ovnkartofler", "Lør: Rådyrsteg med rodfrugter", "Søn: Kalkun i kokosmælk"]
INFO = {
    "Tir: Shakshuka med feta": {"niveau": "rolig"},
    "Ons: Stegt rødspætte": {"niveau": "normal", "fast": True},
    "Tor: Pasta med kødsovs": {"niveau": "normal"},
    "Fre: Nakkekoteletter med ovnkartofler": {"niveau": "hård"},
    "Lør: Rådyrsteg med rodfrugter": {"niveau": "meget hård", "optoe": True},
    "Søn: Kalkun i kokosmælk": {"niveau": "hård"},
}


def _plan(retinfo=INFO, retter=RETTER):
    linjer = [{"vare_id": "1", "navn": "Æg", "antal": 1, "pris": 30.0}]
    p = madplan.gem("bilka", retter, linjer, 39, opskrifter={"Fre: Nakkekoteletter med ovnkartofler": "https://x.dk/nakke", "Tir: Shakshuka med feta": "https://x.dk/shak"}, retinfo=retinfo)
    planer = madplan._alle()
    planer[-1].oprettet = "2026-11-08T12:00+01:00"
    planer[-1].status = "kurv fyldt"
    madplan._gem_alle(planer)
    return madplan.hent(p.kode)


def kl(t, m=0, dag=10):
    return datetime(2026, 11, dag, t, m, tzinfo=TZ)


def niv(niveau, slut=None):
    return {"Julius": {"niveau": niveau, "aktiviteter": [{"start": slut, "slut": slut, "type": "løb"}] if slut else []}}


# --- profil og madplan ---------------------------------------------------------------------


def test_profilens_nye_felter():
    p = profil.opdater(garmin=[{"navn": "Julius", "konto": "standard"}, "Maja"], aftensmad="18.30")
    assert p.garmin == [{"navn": "Julius", "konto": "standard"}, {"navn": "Maja"}] and p.aftensmad == "18:30"
    assert profil.hent().aftensmad == "18:30"
    with pytest.raises(LokalFejl):
        profil.opdater(aftensmad="sent")
    assert profil.opdater_fra_dict({"garmin": []}).garmin == []
    assert "garmin" in profil.vis()["felter"] and "aftensmad" in profil.vis()["felter"]


def test_retinfo_valideres():
    with pytest.raises(LokalFejl, match="niveau"):
        _plan({"Tir: Shakshuka med feta": {"niveau": "brutal"}})
    assert _plan().retinfo["Ons: Stegt rødspætte"] == {"niveau": "normal", "fast": True, "optoe": False}


def test_byt_flytter_retter_links_og_retinfo():
    p = _plan()
    ny = madplan.byt(p.kode, 1, 4, hvem="Maja")
    assert ny.retter[1] == "Tir: Nakkekoteletter med ovnkartofler" and ny.retter[4] == "Fre: Shakshuka med feta"
    assert madplan.link_til(ny, ny.retter[1]) == "https://x.dk/nakke"
    assert madplan.info_til(ny, ny.retter[1])["niveau"] == "hård" and madplan.info_til(ny, ny.retter[4])["niveau"] == "rolig"
    assert "byttet: Tir ↔ Fre (Maja)" in ny.historik[-1]


# --- vurderingen -----------------------------------------------------------------------------


def test_hård_morgen_bytter_dagens_ret():
    f = traening.vurder(_plan(), niv("hård", "07:40"), kl(9), AFTEN)
    assert f and (f["i"], f["j"]) == (1, 4)  # tirsdagens shakshuka ↔ fredagens nakkekoteletter (første hårde, ikke fisk, ikke optø)
    assert f["tekst"] == "Hård dag i dag: byt fredagens nakkekoteletter med ovnkartofler og dagens shakshuka med feta? Svar ja"
    assert f["gyldig_til"].startswith("2026-11-10T18:30")


def test_træning_efter_aftensmad_bytter_morgendagens():
    p = _plan({**INFO, "Ons: Stegt rødspætte": {"niveau": "normal"}})  # ikke fast denne gang
    f = traening.vurder(p, niv("hård", "20:15"), kl(20, 30), AFTEN)
    assert f and f["i"] == 2 and "morgendagens stegt rødspætte" in f["tekst"]


def test_fersk_fisk_flyttes_aldrig():
    assert traening.vurder(_plan(), niv("hård", "20:15"), kl(20, 30), AFTEN) is None  # i morgen er fisk


def test_optø_ret_flyttes_aldrig_til_i_dag_men_gerne_til_i_morgen():
    p = _plan({**INFO, "Fre: Nakkekoteletter med ovnkartofler": {"niveau": "normal"}, "Søn: Kalkun i kokosmælk": {"niveau": "normal"}, "Ons: Stegt rødspætte": {"niveau": "normal"}})
    assert traening.vurder(p, niv("meget hård", "07:00"), kl(9), AFTEN) is None  # kun rådyret er hårdt, og det skal tøs op
    f = traening.vurder(p, niv("meget hård", "20:00"), kl(20, 30), AFTEN)
    assert f and f["j"] == 5  # i morgen: tid til at tø op i nat


def test_meget_hård_dag_foretrækker_meget_hård_ret():
    p = _plan({**INFO, "Ons: Stegt rødspætte": {"niveau": "normal"}})
    f = traening.vurder(p, niv("meget hård", "20:00"), kl(20, 30), AFTEN)
    assert f["j"] == 5 and f["tekst"].startswith("Meget hård dag i dag")


def test_dagens_ret_passer_allerede():
    assert traening.vurder(_plan(), niv("hård", "07:00"), kl(9, dag=13), AFTEN) is None  # fredag: nakkekoteletter


def test_udeblevet_træning_gemmer_den_hårde_ret():
    p = _plan()
    assert traening.vurder(p, niv("normal"), kl(12, dag=13), AFTEN) is None  # for tidligt på dagen
    f = traening.vurder(p, niv("rolig"), kl(16, 45, dag=13), AFTEN)
    assert f is None  # ingen lettere ret senere, der kan flyttes (lør skal tøs op, søn er hård)
    p2 = _plan({**INFO, "Søn: Kalkun i kokosmælk": {"niveau": "normal"}})
    f = traening.vurder(p2, niv("rolig"), kl(16, 45, dag=13), AFTEN)
    assert f and (f["i"], f["j"]) == (4, 6) and f["tekst"].startswith("Rolig dag indtil nu")


def test_intet_uden_retinfo_eller_kendt_niveau():
    assert traening.vurder(_plan(retinfo={}), niv("hård", "07:00"), kl(9), AFTEN) is None
    assert traening.vurder(_plan(), {"Julius": {"niveau": "ukendt"}}, kl(9), AFTEN) is None


def test_flere_personer_det_højeste_niveau_tæller():
    n = {"Julius": {"niveau": "hård", "aktiviteter": [{"slut": "2026-11-10T07:30:00"}]}, "Maja": {"niveau": "rolig", "aktiviteter": []}}
    assert traening.vurder(_plan(), n, kl(9), AFTEN)["j"] == 4


def test_ingen_tal_i_teksterne():
    f = traening.vurder(_plan(), niv("hård", "07:40"), kl(9), AFTEN)
    assert not any(c.isdigit() for c in f["tekst"])


def test_påmindelse_om_optøning_kl_20():
    p = _plan()
    assert traening.paamindelse(p, kl(20, 10, dag=13)) == "Husk at tage det, der skal bruges til i morgen, op af fryseren: rådyrsteg med rodfrugter."
    assert traening.paamindelse(p, kl(19, 50, dag=13)) is None
    assert traening.paamindelse(p, kl(20, 10, dag=12)) is None


# --- lytterens runde og "ja" -----------------------------------------------------------------


@pytest.fixture
def sendt(monkeypatch):
    from handle_mcp import telegram

    ud = []

    async def send(tekst):
        ud.append(tekst)
        return 2

    async def menu(p, fastgoer=True):
        ud.append(f"MENU {p.retter[1]}")
        return 2

    monkeypatch.setattr(telegram, "send_fra_botten", send)
    monkeypatch.setattr(telegram, "send_ugemenu", menu)
    profil.opdater(garmin=[{"navn": "Julius"}])
    traening.gem_konfiguration("C:/garmin-mcp")
    return ud


async def test_lytterens_runde_højst_et_forslag_om_dagen(sendt, monkeypatch):
    _plan()
    monkeypatch.setattr(traening.madplan, "seneste_fyldte", lambda: madplan._alle()[-1])
    hent = lambda d: niv("hård", "07:40")  # noqa: E731
    assert await traening.koer(kl(9), hent) == ["bytteforslag sendt"]
    assert sendt[-1].endswith("Svar ja")
    traening.skriv("traening", {})  # som om der er gået 30 min
    assert await traening.koer(kl(9, 40), hent) == []  # allerede ét forslag i dag
    assert traening.haendelser()[-1]["status"] == "afventer" and traening.haendelser()[-1]["niveau"] == {"Julius": "hård"}


async def test_runden_gør_intet_uden_for_tidsrummet_eller_uden_ja(sendt, monkeypatch):
    _plan()
    monkeypatch.setattr(traening.madplan, "seneste_fyldte", lambda: madplan._alle()[-1])
    hent = lambda d: niv("hård", "07:40")  # noqa: E731
    assert await traening.koer(kl(5, 30), hent) == []
    profil.opdater(garmin=[])
    assert await traening.koer(kl(9), hent) == [] and sendt == []


async def test_ja_bytter_og_sender_ny_menu(sendt, monkeypatch):
    p = _plan()
    monkeypatch.setattr(traening.madplan, "seneste_fyldte", lambda: madplan._alle()[-1])
    monkeypatch.setattr(traening, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: kl(10))}))
    await traening.koer(kl(9), lambda d: niv("hård", "07:40"))
    assert await traening.besvar("hej", "Maja") is None  # ikke et ja: går til AI'en
    assert await traening.besvar("Ja", "Maja") == "bytteforslag godkendt af Maja"
    assert madplan.hent(p.kode).retter[1] == "Tir: Nakkekoteletter med ovnkartofler"
    assert "Byttet: Fre ↔ Tir. Ugens menu er opdateret." in sendt and sendt[-1] == "MENU Tir: Nakkekoteletter med ovnkartofler"
    assert await traening.besvar("ja", "Julius") is None  # den første, der svarer, afgør det


async def test_ja_efter_aftensmad_gør_intet(sendt, monkeypatch):
    p = _plan()
    monkeypatch.setattr(traening.madplan, "seneste_fyldte", lambda: madplan._alle()[-1])
    await traening.koer(kl(9), lambda d: niv("hård", "07:40"))
    monkeypatch.setattr(traening, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: kl(19))}))
    assert await traening.besvar("ja", "Maja") is None
    assert madplan.hent(p.kode).retter[1] == "Tir: Shakshuka med feta"


def test_niveauer_hentes_fra_garmin_mcp(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/test/AppData/Local")  # også på Linux i CI
    profil.opdater(garmin=[{"navn": "Julius", "konto": "standard"}, {"navn": "Maja"}])
    traening.gem_konfiguration("C:/garmin-mcp", "%LOCALAPPDATA%/garmin-mcp-venv")
    kaldt = {}

    def run(kommando, **kw):
        kaldt.update(kommando=kommando, cwd=kw["cwd"], env=kw["env"])
        ud = {"dato": "2026-11-10", "personer": {"standard": {"niveau": "hård", "aktiviteter": []}, "maja": {"fejl": "intet login"}}}
        return type("S", (), {"stdout": json.dumps(ud), "returncode": 1})()

    monkeypatch.setattr(traening.subprocess, "run", run)
    n = traening.hent_niveauer(datetime(2026, 11, 10).date())
    assert n == {"Julius": {"niveau": "hård", "aktiviteter": []}, "Maja": {"niveau": "ukendt"}}
    assert kaldt["kommando"][-4:] == ["belastning", "--alle", "--dato", "2026-11-10"] and kaldt["cwd"] == "C:/garmin-mcp"
    assert kaldt["env"]["UV_LINK_MODE"] == "copy" and "%" not in kaldt["env"]["UV_PROJECT_ENVIRONMENT"]


def test_uden_opsætning_hentes_intet():
    profil.opdater(garmin=[{"navn": "Julius"}])
    assert traening.hent_niveauer(datetime(2026, 11, 10).date()) == {}

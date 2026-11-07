"""Levering og startdag (levering.py). Julius: "test alverdens scenarier og gør det robust".

Tiderne bygges efter de rigtige regler (slået op 7/11-2026):
- nemlig: ingen levering om søndagen. Kl. 7-14 skal bestilles senest kl. 14 dagen før, kl.
  15-22 senest kl. 24 aftenen før.
- Bilka: natlevering kl. 20-06 ("natten til D", gemt som D kl. 0-6), bestil senest kl. 15
  dagen før.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from handle_mcp import levering, madplan, telegram, ugeplan
from handle_mcp.butikker import bilka, nemlig
from handle_mcp.data import Leveringstid
from test_telegram import par, tg  # noqa: F401  tg er en fixture

DK = levering.DK


def kl(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), DK)


def nemlig_tider(fra: date, dage: int = 7, udsolgt: set = frozenset()) -> list[Leveringstid]:
    tider = []
    for i in range(dage):
        d = fra + timedelta(days=i)
        if d.weekday() == 6:
            continue  # ingen søndagslevering
        for s, e, pris in ((7, 14, 21), (10, 14, 33), (15, 17, 46), (15, 22, 35), (18, 22, 42)):
            frist = kl(d - timedelta(days=1), 14) if s < 15 else kl(d, 0)
            tider.append(Leveringstid("nemlig", kl(d, s), kl(d, e), Decimal(pris), (d, s) not in udsolgt, "Personlig", None, frist))
    return tider


def bilka_tider(fra: date, dage: int = 7) -> list[Leveringstid]:
    tider = []
    for i in range(dage):
        d = fra + timedelta(days=i)
        tider.append(Leveringstid("bilka", kl(d, 0), kl(d, 6), Decimal(39), d.weekday() != 6, "Nat", None, kl(d - timedelta(days=1), 15)))
    return tider


LOER = date(2026, 11, 7)  # lørdag
SOEN = date(2026, 11, 8)
MAN = date(2026, 11, 9)
TIR = date(2026, 11, 10)


# --- Julius' eksempel: søndag kl. 12 ----------------------------------------------------


def test_soendag_kl_12_nemlig_mandag_formiddag():
    b = levering.bedste(nemlig_tider(LOER), kl(SOEN, 12))
    assert b["foerste_aftensmad"] == "mandag 9/11"
    assert b["levering"] == "mandag 9/11 kl. 7-14" and b["pris_kr"] == 21
    assert b["bestil_senest"] == "søndag 8/11 kl. 14"
    assert b["klarer_jer_selv"] == ["søndag"]  # søndag aften er det, de har
    # reserven, hvis de ikke når kl. 14: samme aften, frist kl. 24
    assert b["naas_fristen_ikke"]["levering"] == "mandag 9/11 kl. 15-17"
    assert b["naas_fristen_ikke"]["bestil_senest"] == "søndag 8/11 kl. 24"


def test_soendag_kl_13_er_formiddagen_for_taet_paa():
    """Med 90 minutter til menu og "bestil" når de ikke kl. 14, men kl. 15-17 når stadig mandag."""
    b = levering.bedste(nemlig_tider(LOER), kl(SOEN, 13))
    assert b["foerste_aftensmad"] == "mandag 9/11" and b["levering"] == "mandag 9/11 kl. 15-17"
    assert b["bestil_senest"] == "søndag 8/11 kl. 24"


def test_soendag_kl_23_bliver_det_tirsdag():
    b = levering.bedste(nemlig_tider(LOER), kl(SOEN, 23))
    assert b["foerste_aftensmad"] == "tirsdag 10/11"
    assert b["klarer_jer_selv"] == ["mandag"]  # søndag aften er spist


def test_loerdag_aften_som_i_testen_mandag_aften_tæller_med():
    """Testen 7/11: Claude skrev "første levering mandag, så jeg starter tirsdag". Forkert."""
    b = levering.bedste(nemlig_tider(LOER), kl(LOER, 20, 30))
    assert b["foerste_aftensmad"] == "mandag 9/11"
    assert b["klarer_jer_selv"] == ["søndag"]


def test_bilka_nat_til_mandag():
    b = levering.bedste(bilka_tider(LOER), kl(LOER, 20, 30))
    assert b["foerste_aftensmad"] == "mandag 9/11"
    assert b["levering"] == "natten til mandag 9/11 (kl. 20-6)"
    assert b["bestil_senest"] == "søndag 8/11 kl. 15"


def test_bilka_soendag_kl_14_naar_ikke_kl_15():
    b = levering.bedste(bilka_tider(LOER), kl(SOEN, 14))
    assert b["foerste_aftensmad"] == "tirsdag 10/11" and b["bestil_senest"] == "mandag 9/11 kl. 15"


# --- reglerne én for én ------------------------------------------------------------


@pytest.mark.parametrize(
    ("slut_kl", "samme_dag"),
    [(14, True), (17, True), (18, False), (22, False)],
)
def test_aftensmad_kl_17(slut_kl, samme_dag):
    t = Leveringstid("nemlig", kl(MAN, 7), kl(MAN, slut_kl), Decimal(1), True)
    assert levering.foerste_aftensmad(t) == (MAN if samme_dag else TIR)


def test_udsolgt_og_afhentning_tæller_ikke():
    tider = nemlig_tider(LOER, udsolgt={(MAN, 7), (MAN, 10), (MAN, 15)})
    tider.append(Leveringstid("nemlig", kl(MAN, 8), kl(MAN, 9), Decimal(0), True, "Afhentning", None, kl(SOEN, 22)))
    b = levering.bedste(tider, kl(SOEN, 12))
    assert b["foerste_aftensmad"] == "tirsdag 10/11"  # mandag er udsolgt indtil kl. 17, og afhentning er udelukket


def test_ukendt_frist_kraever_god_tid():
    naer = Leveringstid("bilka", kl(MAN, 0), kl(MAN, 6), Decimal(39), True)
    fjern = Leveringstid("bilka", kl(TIR, 0), kl(TIR, 6), Decimal(39), True)
    b = levering.bedste([naer, fjern], kl(SOEN, 12))
    assert b["foerste_aftensmad"] == "tirsdag 10/11"
    assert b["bestil_senest"] == "fristen kan ikke ses, tjek den i appen"


def test_ingen_mulige_tider():
    assert levering.bedste([], kl(SOEN, 12)) is None
    assert levering.til_plan(nemlig_tider(LOER, udsolgt={(d, s) for d in (MAN, TIR) for s in (7, 10, 15, 18)})[:0], kl(SOEN, 12), MAN) is None


@pytest.mark.parametrize(("time_", "aftener"), [(18, ["søndag"]), (19, []), (20, [])])
def test_klarer_jer_selv_i_aften(time_, aftener):
    assert [levering.UGEDAGE[d.weekday()] for d in levering.aftener_foer(MAN, kl(SOEN, time_))] == aftener


def test_billigst_og_ved_lige_pris_senest_frist():
    a = Leveringstid("nemlig", kl(MAN, 7), kl(MAN, 14), Decimal(30), True, None, None, kl(SOEN, 14))
    b = Leveringstid("nemlig", kl(MAN, 15), kl(MAN, 17), Decimal(30), True, None, None, kl(MAN, 0))
    assert levering.bedste([a, b], kl(SOEN, 9))["levering"] == "mandag 9/11 kl. 15-17"


# --- fristen som tekst (Bilka) ------------------------------------------------------


@pytest.mark.parametrize(
    ("tekst", "nu", "forventet"),
    [
        ("i morgen kl. 15:00", kl(LOER, 20), kl(SOEN, 15)),
        ("i dag kl. 15:00", kl(SOEN, 9), kl(SOEN, 15)),
        ("p� mandag kl. 15:00", kl(LOER, 20), kl(MAN, 15)),  # Bilkas ødelagte "på"
        ("på mandag kl. 15:00", kl(LOER, 20), kl(MAN, 15)),
        ("på lørdag kl. 15:00", kl(LOER, 9), kl(LOER, 15)),
        ("på lørdag kl. 15:00", kl(LOER, 16), kl(LOER + timedelta(days=7), 15)),
        ("på søndag kl. 15.00", kl(LOER, 9), kl(SOEN, 15)),
        ("i overmorgen kl. 9:30", kl(LOER, 9), kl(MAN, 9, 30)),
        ("12/11 kl. 15:00", kl(LOER, 9), kl(date(2026, 11, 12), 15)),
        ("2/1 kl. 15:00", kl(date(2026, 12, 30), 9), kl(date(2027, 1, 2), 15)),
        ("31/12 kl. 15:00", kl(date(2026, 12, 30), 9), kl(date(2026, 12, 31), 15)),
    ],
)
def test_frist_fra_tekst(tekst, nu, forventet):
    assert levering.frist_fra_tekst(tekst, nu) == forventet


@pytest.mark.parametrize("tekst", [None, "", "snart", "i morgen", "i morgen kl. 25:00", "31/2 kl. 15:00", "på fredag"])
def test_frist_fra_tekst_ukendt(tekst):
    assert levering.frist_fra_tekst(tekst, kl(LOER, 9)) is None


def test_bilka_svar_som_det_kom_7_11():
    """Udsnit af Bilkas rigtige svar, hentet lørdag 7/11 kl. 20:30."""
    data = {
        "availableIntervals": [
            {"date": "2026-11-08", "intervals": [], "availability_bit": 4, "closed_text": "udsolgt"},
            {
                "date": "2026-11-09",
                "intervals": [
                    {
                        "intervalStart": "00:00",
                        "intervalEnd": "06:00",
                        "availability_bit": 1,
                        "closed": 0,
                        "orderBeforeTime": "i morgen kl. 15:00",
                        "info": [{"message": "Levering vil ske <strong>natten til mandag</strong>."}],
                    }
                ],
            },
            {
                "date": "2026-11-10",
                "intervals": [
                    {
                        "intervalStart": "00:00",
                        "intervalEnd": "06:00",
                        "availability_bit": 1,
                        "closed": 0,
                        "orderBeforeTime": "p� mandag kl. 15:00",
                        "info": [{"message": "For at benytte det valgte tidsrum, skal du bestille senest p� mandag kl. 15:00, bem�rk"}],
                    }
                ],
            },
            {
                "date": "2026-11-11",
                "intervals": [
                    {
                        "intervalStart": "00:00",
                        "intervalEnd": "06:00",
                        "availability_bit": 1,
                        "closed": 0,
                        "info": [{"message": "skal du bestille senest på tirsdag kl. 15:00, bemærk"}],
                    }
                ],
            },
        ]
    }
    tider = bilka.leveringstider_fra_svar(data, Decimal(39), kl(LOER, 20, 30))
    assert [t.frist for t in tider] == [kl(SOEN, 15), kl(MAN, 15), kl(TIR, 15)]  # den sidste fra teksten
    assert levering.bedste(tider, kl(LOER, 20, 30))["foerste_aftensmad"] == "mandag 9/11"


def test_nemlig_frist_med_tidszone():
    data = {"DayRangeHours": [{"DayHours": [{"Date": "2026-11-09T00:00:00", "StartHour": 7, "EndHour": 14, "DeliveryPrice": 21, "Availability": 0, "Type": 0, "Deadline": "2026-11-08T14:00:00"}]}]}
    (t,) = nemlig.leveringstider_fra_svar(data)
    assert t.frist == kl(SOEN, 14) and t.frist.tzinfo is not None


def test_frist_kl_24():
    t = Leveringstid("nemlig", kl(MAN, 15), kl(MAN, 17), Decimal(46), True, None, None, kl(MAN, 0))
    assert levering.frist_tekst(t) == "søndag 8/11 kl. 24"


# --- planens første dag og forslaget, når kurven er fyldt ---------------------------------


@pytest.mark.parametrize(
    ("retter", "fra", "forventet"),
    [
        (["Man 9/11: Chili", "Tir 10/11: Laks"], LOER, MAN),
        (["Tir: Kylling", "Ons: Shakshuka"], LOER, TIR),
        (["Lør 14/11: ingen aftensmad hjemme", "Fre 13/11 (4 pers.): Kylling"], LOER, date(2026, 11, 13)),
        (["Søn: Grågås"], SOEN, SOEN),
        (["Fre 1/1: Rester"], date(2026, 12, 30), date(2027, 1, 1)),
        (["Kylling med kartofler"], LOER, None),
    ],
)
def test_planens_start(retter, fra, forventet):
    assert levering.planens_start(retter, fra) == forventet


def test_til_plan_vaelger_den_billigste_der_naar_foerste_aften_uden_at_komme_dage_for_tidligt():
    f = levering.til_plan(nemlig_tider(LOER), kl(SOEN, 12), date(2026, 11, 11))  # planen starter onsdag
    assert f["foerste_aftensmad"] == "onsdag 11/11" and f["levering"] == "onsdag 11/11 kl. 7-14"


def test_til_plan_for_sent():
    assert levering.til_plan(nemlig_tider(LOER), kl(SOEN, 23), MAN)["levering"] == "mandag 9/11 kl. 15-17"  # kl. 23 når de det
    f = levering.til_plan(nemlig_tider(LOER), kl(SOEN, 23, 50), MAN)
    assert f["foerste_aftensmad"] == "tirsdag 10/11" and "planen starter mandag 9/11" in f["for_sent"]
    assert levering.forslag_tekst(f).startswith("Obs:")


def test_til_plan_kort_margin_naar_kurven_er_fyldt():
    """Er kurven fyldt kl. 13:40, når de stadig formiddagen (15 min margin, ikke 90)."""
    f = levering.til_plan(nemlig_tider(LOER), kl(SOEN, 13, 40), MAN)
    assert f["levering"] == "mandag 9/11 kl. 7-14"


def test_over_sommertid_skift():
    soen = date(2026, 10, 25)  # sommertid slutter
    b = levering.bedste(nemlig_tider(soen - timedelta(days=1)), kl(soen, 12))
    assert b["foerste_aftensmad"] == "mandag 26/10" and b["bestil_senest"] == "søndag 25/10 kl. 14"


# --- alle tidspunkter i to uger: reglerne holder altid ------------------------------------


@pytest.mark.parametrize("butik", ["nemlig", "bilka"])
def test_hver_halve_time_i_to_uger(butik):
    fra = date(2026, 11, 2)
    tider = nemlig_tider(fra, 21) if butik == "nemlig" else bilka_tider(fra, 21)
    nu = kl(fra, 0)
    while nu < kl(fra + timedelta(days=14), 0):
        b = levering.bedste(tider, nu)
        assert b is not None, nu
        dag = date.fromisoformat(b["dato"])
        mulige = [t for t in tider if levering.kan_naas(t, nu, levering.MARGIN_START)]
        # ingen tid, der kan nås, giver en tidligere aftensmad
        assert dag == min(levering.foerste_aftensmad(t) for t in mulige), nu
        # fristen er ikke overskredet, når de har haft tid til menuen
        valgt = next(t for t in mulige if levering.levering_tekst(t) == b["levering"] and float(t.pris) == b["pris_kr"])
        assert valgt.frist - levering.MARGIN_START >= nu
        # aftenerne før hænger sammen med den første aftensmad
        selv = levering.aftener_foer(dag, nu)
        assert not selv or selv[-1] == dag - timedelta(days=1)
        assert dag - nu.date() <= timedelta(days=3), nu  # aldrig mere end 3 dage
        nu += timedelta(minutes=30)


# --- koblet på madplanen og Telegram -------------------------------------------------


def test_foerste_spoergsmaal_naevner_leveringen():
    lev = {"nemlig": levering.bedste(nemlig_tider(LOER), kl(SOEN, 12)), "bilka": levering.bedste(bilka_tider(LOER), kl(SOEN, 12))}
    tekst = ugeplan.foerste_spoergsmaal(lev, [{"dag": "søndag 8/11", "ret": "Søn: Rådyrsteg", "opskrift": None}])
    assert "tidligst være her til aftensmaden mandag 9/11" in tekst
    assert "1) Hvad har I i køleskabet?" in tekst
    assert "spiser" not in tekst  # retten er kendt fra planen, så ingen ekstra spørgsmål
    assert ugeplan.foerste_spoergsmaal({}) == ugeplan.FOERSTE_SPOERGSMAAL


def test_foerste_spoergsmaal_uden_plan_for_aftenen():
    lev = {"nemlig": levering.bedste(nemlig_tider(LOER), kl(SOEN, 12))}
    tekst = ugeplan.foerste_spoergsmaal(lev, [{"dag": "søndag 8/11", "ret": None, "opskrift": None}])
    assert "Ved I, hvad I spiser søndag, så skriv det også." in tekst


def _plan_fyldt(retter, opskrifter=None):
    p = madplan.gem("nemlig", retter, [{"vare_id": "1", "navn": "x", "antal": 1, "pris": 1.0}], opskrifter=opskrifter)
    madplan.saet_status(p.kode, "kurv fyldt", "test")
    return p


def test_foer_levering_finder_aftenens_ret_i_planen():
    """Julius: "du tjekker selv hvad der bliver brugt, du kender selv opskrifter og madplan"."""
    i_dag = datetime.now(DK).date()
    fork = levering.UGEDAGE[i_dag.weekday()][:3].capitalize()
    i_morgen = i_dag + timedelta(days=1)
    _plan_fyldt(
        [f"{fork} {i_dag.day}/{i_dag.month}: Laks med kartofler", f"{levering.UGEDAGE[i_morgen.weekday()][:3].capitalize()}: Lasagne"],
        {f"{fork} {i_dag.day}/{i_dag.month}: Laks med kartofler": "https://www.valdemarsro.dk/laks/"},
    )
    lev = {"nemlig": {"dato": (i_dag + timedelta(days=2)).isoformat()}}
    foer = ugeplan.foer_levering(lev, kl(i_dag, 12))
    assert [f["ret"] for f in foer] == [f"{fork} {i_dag.day}/{i_dag.month}: Laks med kartofler", f"{levering.UGEDAGE[i_morgen.weekday()][:3].capitalize()}: Lasagne"]
    assert foer[0]["opskrift"] == "https://www.valdemarsro.dk/laks/"
    assert ugeplan.foer_levering(lev, kl(i_dag, 20))[0]["dag"] == levering.dag_tekst(i_morgen)  # i aften er spist


def test_foer_levering_uden_plan():
    i_dag = datetime.now(DK).date()
    foer = ugeplan.foer_levering({"bilka": {"dato": (i_dag + timedelta(days=1)).isoformat()}}, kl(i_dag, 12))
    assert foer == [{"dag": levering.dag_tekst(i_dag), "ret": None, "opskrift": None}]
    assert ugeplan.foer_levering({}) == []


def test_levering_samme_aften_ingen_aftener_foer():
    i_dag = datetime.now(DK).date()
    assert ugeplan.foer_levering({"nemlig": {"dato": i_dag.isoformat()}}, kl(i_dag, 9)) == []


async def test_forslag_sendes_til_begge(tg):
    par(tg, 1, 2)
    await telegram.hent_og_haandter(0)
    p = madplan.gem("nemlig", ["Man 9/11: Chili", "Tir 10/11: Laks"], [{"vare_id": "1", "navn": "x", "antal": 1, "pris": 1.0}])
    tg.sendt.clear()
    assert await telegram.send_leveringsforslag(p, {"nemlig": nemlig_tider(LOER)}, nu=kl(SOEN, 12))
    (tekst,) = {t for _, t in tg.sendt}
    assert tekst.startswith("Levering hos nemlig: mandag 9/11 kl. 7-14 (21 kr). Bestil senest søndag 8/11 kl. 14.")
    assert {c for c, _ in tg.sendt} == {1, 2}


async def test_intet_forslag_uden_tider(tg):
    par(tg, 1)
    await telegram.hent_og_haandter(0)
    p = madplan.gem("nemlig", ["Man: Chili"], [{"vare_id": "1", "navn": "x", "antal": 1, "pris": 1.0}])
    assert not await telegram.send_leveringsforslag(p, {"nemlig": []}, nu=kl(SOEN, 12))

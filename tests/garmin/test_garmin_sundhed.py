from datetime import date, timedelta

import pytest
from conftest import D, FalskGarmin

from garmin_mcp import sundhed


def test_soevn_omregnes_til_timer_og_klokkeslaet():
    s = sundhed.soevn_dag(FalskGarmin(), D)
    assert s["sovet_timer"] == 7.25
    assert s["dyb_timer"] == 1.5 and s["rem_timer"] == 1.75
    assert s["faldt_i_soevn"] == "2025-11-03 22:00"
    assert s["soevnscore"] == 82 and s["hrv_nat_ms"] == 61.0
    assert "sleepMovement" not in s  # de store rå data sendes ikke videre


def test_nat_uden_soevn():
    assert sundhed.soevn_dag(FalskGarmin(tom_dag="2026-11-04"), D) == {"dato": "2026-11-04", "ingen_data": True}


def test_dagstal_viser_kun_relevante_tal_uden_profil():
    t = sundhed.dagstal(FalskGarmin(), D)
    assert t["skridt"] == 11234 and t["distance_km"] == 8.95
    assert t["kalorier_i_alt"] == 2810.0 and t["hvilepuls"] == 48
    assert "displayName" not in t and "userProfileId" not in t


def test_dag_uden_data_giver_markering_ikke_fejl():
    assert sundhed.dagstal(FalskGarmin(tom_dag="2026-11-04"), D)["ingen_data"] is True


def test_udvalg_af_felter():
    (skridt,) = sundhed.udvalg(FalskGarmin(), [D], sundhed.SKRIDT)
    assert set(skridt) == {"dato", "skridt", "skridtmaal", "distance_km", "intensitetsminutter_moderat", "intensitetsminutter_hoej"}
    (kal,) = sundhed.udvalg(FalskGarmin(), [D], sundhed.KALORIER)
    assert set(kal) == {"dato", "kalorier_i_alt", "kalorier_aktive", "kalorier_hvile"}


def test_traeninger():
    (a,) = sundhed.traeninger(FalskGarmin(), D, D)
    assert a == {
        "start": "2026-11-04 17:30:00",
        "navn": "Løb om søerne",
        "type": "running",
        "varighed_min": 45,
        "distance_km": 8.01,
        "kalorier": 610.0,
        "puls_gns": 152.0,
        "puls_max": 176.0,
        "traeningseffekt_aerob": 3.4,
        "traeningseffekt_anaerob": 1.2,
        "traeningsbelastning": 140.5,
    }


def test_vaegt_i_kg():
    (m,) = sundhed.vaegt(FalskGarmin(), D, D)
    assert m == {"dato": "2026-11-04", "vaegt_kg": 78.5, "fedtprocent": 15.2, "muskelmasse_kg": 36.1, "bmi": 23.4}


def test_dagsstatus_samler_det_hele():
    g = FalskGarmin()
    s = sundhed.dagsstatus(g, D)
    assert s["soevn_i_nat"]["sovet_timer"] == 7.25
    assert s["dagen"]["skridt"] == 11234
    assert ("get_activities_by_date", "2026-11-03", "2026-11-04") in g.kald
    assert "note" not in s  # ikke i dag


def test_datoer():
    i_dag = sundhed.i_dag()
    assert sundhed.dato("i dag") == i_dag
    assert sundhed.dato("I går") == i_dag - timedelta(days=1)
    assert sundhed.dato("2026-11-04") == date(2026, 11, 4)
    with pytest.raises(sundhed.DatoFejl):
        sundhed.dato("på fredag")


def test_periode_graenser():
    assert len(sundhed.periode("2026-10-01", "2026-10-31")) == 31
    with pytest.raises(sundhed.DatoFejl):
        sundhed.periode("2026-10-01", "2026-11-01")
    with pytest.raises(sundhed.DatoFejl):
        sundhed.periode("2026-11-04", "2026-11-03")

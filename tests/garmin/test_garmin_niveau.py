import json
from datetime import date, timedelta

import pytest

from garmin_mcp import cli, forbindelse, login, niveau

# Tal, der ligner en aktiv person i en efterårsmåned (opdigtede tal): almindelige dage med 30-190 aktive kcal,
# jagtdage uden startet aktivitet med 480-620 aktive kcal og 13-17.000 skridt.
NORMALE = [125, 35, 120, 50, 118, 70, 30, 140, 40, 158, 130, 188, 124, 131, 170, 108, 99, 147, 138, 155]


class NiveauGarmin:
    def __init__(self, dage: dict[str, tuple[float | None, int | None]], aktiviteter=(), bmr=None):
        self.dage = dage
        self.bmr = bmr
        self.aktiviteter = list(aktiviteter)
        self.kald = []

    def _periode(self, start, end):
        d, slut = date.fromisoformat(start), date.fromisoformat(end)
        while d <= slut:
            yield d.isoformat()
            d += timedelta(days=1)

    def get_daily_steps(self, start, end):
        self.kald.append("get_daily_steps")
        return [{"calendarDate": d, "totalSteps": self.dage[d][1]} for d in self._periode(start, end) if d in self.dage]

    def get_calories_daily(self, start, end):
        self.kald.append("get_calories_daily")
        return [{"calendarDate": d, "active": self.dage[d][0], "resting": self.bmr} for d in self._periode(start, end) if d in self.dage]

    def get_activities_by_date(self, startdate, enddate=None, activitytype=None, sortorder=None):
        self.kald.append("get_activities_by_date")
        return [a for a in self.aktiviteter if startdate <= a["startTimeLocal"][:10] <= (enddate or startdate)]


DAG = date(2026, 11, 8)


def grundlag(**ekstra):
    """28 dage før DAG med normale tal (ca. 6.000 skridt), plus de givne dage."""
    dage = {}
    for i in range(1, 29):
        d = (DAG - timedelta(days=i)).isoformat()
        dage[d] = (NORMALE[i % len(NORMALE)], 6000)
    dage.update({k.replace("_", "-")[1:]: v for k, v in ekstra.items()})
    return dage


def en_dag(tal, aktiviteter=(), dag=DAG):
    g = NiveauGarmin(grundlag(**{"d" + dag.isoformat().replace("-", "_"): tal}), aktiviteter)
    (r,) = niveau.beregn_periode(g, [dag])
    return r


def test_jagtdag_uden_aktivitet_er_meget_haard():
    r = en_dag((540, 12800))
    assert r["niveau"] == "meget hård"
    assert "aktive kalorier" in r["aarsag"]
    assert r["grundlag_dage"] == 28 and 115 <= r["normal_aktive_kalorier"] <= 135


def test_aktiv_dag_er_haard_og_almindelig_dag_normal():
    assert en_dag((309, 10941))["niveau"] == "hård"
    assert en_dag((150, 6000))["niveau"] == "normal"


def test_mange_skridt_alene_er_haard():
    assert en_dag((200, 13000))["niveau"] == "hård"


def test_stille_dag_er_rolig():
    assert en_dag((32, 3000))["niveau"] == "rolig"


def test_uret_ikke_paa_er_ukendt():
    assert en_dag((0, None))["niveau"] == "ukendt"


def test_aktiviteter():
    loeb = {"startTimeLocal": "2026-11-08 17:30:00", "duration": 2700, "aerobicTrainingEffect": 3.1, "activityType": {"typeKey": "running"}}
    r = en_dag((150, 6000), [loeb])
    assert r["niveau"] == "hård"
    assert r["aktiviteter"] == [{"start": "2026-11-08 17:30", "slut": "2026-11-08 18:15", "type": "running", "varighed_min": 45, "aerob_effekt": 3.1}]
    gaatur = {"startTimeLocal": "2026-11-08 11:35:34", "duration": 8050, "aerobicTrainingEffect": 0.6, "activityType": {"typeKey": "walking"}}
    assert en_dag((150, 6000), [gaatur])["niveau"] == "hård"  # over 2 timer
    jagt = {"startTimeLocal": "2026-11-08 07:00:00", "duration": 8 * 3600, "activityType": {"typeKey": "hunting"}}
    assert en_dag((150, 6000), [jagt])["niveau"] == "meget hård"


def test_niveauet_er_personligt():
    """Samme dag er hård for en stillesiddende person og normal for en meget aktiv."""
    stille = NiveauGarmin({**{(DAG - timedelta(days=i)).isoformat(): (110, 4000) for i in range(1, 29)}, DAG.isoformat(): (260, 7000)})
    aktiv = NiveauGarmin({**{(DAG - timedelta(days=i)).isoformat(): (600, 15000) for i in range(1, 29)}, DAG.isoformat(): (260, 7000)})
    assert niveau.beregn_periode(stille, [DAG])[0]["niveau"] == "hård"
    assert niveau.beregn_periode(aktiv, [DAG])[0]["niveau"] == "rolig"


def test_aktiv_periode_skjuler_ikke_en_dag_med_mange_kalorier():
    """Midt i en aktiv periode (median 300) er 545 aktive kcal stadig over 20 % af BMR."""
    dage = {(DAG - timedelta(days=i)).isoformat(): (300, 9000) for i in range(1, 29)}
    dage[DAG.isoformat()] = (545, 13500)
    (r,) = niveau.beregn_periode(NiveauGarmin(dage, bmr=2000), [DAG])
    assert r["niveau"] == "hård" and "hvilestofskiftet" in r["aarsag"]
    dage[DAG.isoformat()] = (330, 9000)
    assert niveau.beregn_periode(NiveauGarmin(dage, bmr=1350), [DAG])[0]["niveau"] == "hård"  # lavere BMR, fx 67 år
    assert niveau.beregn_periode(NiveauGarmin(dage, bmr=2000), [DAG])[0]["niveau"] == "normal"


def test_dato_uden_anfoerselstegn():
    assert cli._flag(["belastning", "--dato", "i", "går"], "--dato") == "i går"


def test_for_lidt_grundlag_bruger_kun_aktiviteter():
    g = NiveauGarmin({DAG.isoformat(): (900, 20000)})
    (r,) = niveau.beregn_periode(g, [DAG])
    assert r["niveau"] == "normal" and r["grundlag_dage"] == 0


def test_i_dag_er_aldrig_rolig_men_foreloebig():
    i_dag = niveau.sundhed.i_dag()
    r = en_dag((10, 500), dag=i_dag)
    assert r["foreloebig"] is True and r["niveau"] == "normal"


def test_en_hel_periode_koster_tre_kald():
    g = NiveauGarmin(grundlag())
    dage = [DAG - timedelta(days=i) for i in range(27, -1, -1)]
    ud = niveau.beregn_periode(g, dage)
    assert len(ud) == 28 and sorted(g.kald) == ["get_activities_by_date", "get_calories_daily", "get_daily_steps"]


# ---------- personer ----------


def lav_person(p):
    login.gem(p, f"{p}@eksempel.dk", "kode")
    login.personmappe(p).mkdir(parents=True, exist_ok=True)
    login.tokenfil(p).write_text("{}")


def test_personer_og_valg():
    assert login.personer() == []
    with pytest.raises(login.IntetLogin):
        login.vaelg(None)
    lav_person("anna")
    assert login.vaelg(None) == "anna"
    lav_person("bo")
    assert login.personer() == ["anna", "bo"]
    with pytest.raises(login.PersonFejl, match="anna, bo"):
        login.vaelg(None)
    assert login.vaelg("Bo") == "bo"
    with pytest.raises(login.PersonFejl):
        login.navn("../windows")


def test_foerste_versions_login_hedder_standard():
    login.tokenmappe().mkdir(parents=True)
    (login.tokenmappe() / "garmin_tokens.json").write_text("{}")
    assert login.personer() == ["standard"]
    assert login.tokenfil("standard") == login.tokenmappe() / "garmin_tokens.json"


def test_belastning_kommando_for_alle(monkeypatch, capsys):
    lav_person("anna")
    lav_person("bo")
    anna = NiveauGarmin(grundlag(d2026_11_08=(540, 12800)))

    def klient(p):
        if p == "bo":
            from garminconnect import GarminConnectAuthenticationError

            raise GarminConnectAuthenticationError("401")
        return anna

    monkeypatch.setattr(forbindelse, "ny_klient", klient)
    assert cli.kommando(["belastning", "--alle", "--dato", "2026-11-08"]) == 1  # bo fejler
    ud = json.loads(capsys.readouterr().out)
    assert ud["dato"] == "2026-11-08"
    assert ud["personer"]["anna"]["niveau"] == "meget hård"
    assert "login" in ud["personer"]["bo"]["fejl"]


async def test_belastning_vaerktoej(monkeypatch):
    from garmin_mcp import server

    g = NiveauGarmin(grundlag(d2026_11_08=(309, 10941)))
    monkeypatch.setattr(forbindelse, "klient", lambda person=None: g)
    (r,) = await server.belastning("2026-11-08")
    assert r["niveau"] == "hård"

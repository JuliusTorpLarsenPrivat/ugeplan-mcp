"""Fælles test-hjælpere: en falsk Garmin og en falsk nøglering, så testene aldrig rører
din rigtige konto eller Windows Credential Manager."""

from __future__ import annotations

from datetime import date

import keyring
import keyring.backend
import keyring.errors
import pytest

pytest.importorskip("garminconnect")  # Garmin-delen er valgfri: uv sync --extra garmin

from garmin_mcp import forbindelse  # noqa: E402


class FalskNoegelring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError("findes ikke")
        del self.data[(service, username)]


@pytest.fixture(autouse=True)
def falsk_noegelring(tmp_path, monkeypatch):
    gammel = keyring.get_keyring()
    ring = FalskNoegelring()
    keyring.set_keyring(ring)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    forbindelse.glem_klient()
    yield ring
    keyring.set_keyring(gammel)
    forbindelse.glem_klient()


SOEVN = {
    "dailySleepDTO": {
        "calendarDate": "2026-11-04",
        "sleepTimeSeconds": 26100,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 14400,
        "remSleepSeconds": 6300,
        "awakeSleepSeconds": 900,
        "sleepStartTimestampLocal": 1762207200000,  # 2025-11-03 22:00 "lokal"
        "sleepEndTimestampLocal": 1762234200000,
        "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
        "avgSleepStress": 14.0,
    },
    "restingHeartRate": 48,
    "avgOvernightHrv": 61.0,
    "hrvStatus": "BALANCED",
    "bodyBatteryChange": 55,
    "sleepMovement": [{"lots": "of data we don't want"}],
}

STATS = {
    "totalSteps": 11234,
    "dailyStepGoal": 9000,
    "totalDistanceMeters": 8950,
    "totalKilocalories": 2810.0,
    "activeKilocalories": 790.0,
    "bmrKilocalories": 2020.0,
    "restingHeartRate": 48,
    "lastSevenDaysAvgRestingHeartRate": 49,
    "moderateIntensityMinutes": 20,
    "vigorousIntensityMinutes": 35,
    "averageStressLevel": 28,
    "bodyBatteryMostRecentValue": 61,
    "bodyBatteryHighestValue": 90,
    "bodyBatteryLowestValue": 22,
    "userProfileId": 123456,
    "displayName": "hemmeligt-navn",
}

AKTIVITET = {
    "activityId": 1,
    "activityName": "Løb om søerne",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-11-04 17:30:00",
    "duration": 2712.4,
    "distance": 8012.3,
    "calories": 610.0,
    "averageHR": 152.0,
    "maxHR": 176.0,
    "aerobicTrainingEffect": 3.4,
    "anaerobicTrainingEffect": 1.2,
    "activityTrainingLoad": 140.5,
    "ownerFullName": "Må ikke komme med",
}

VAEGT = {
    "dateWeightList": [
        {"calendarDate": "2026-11-04", "weight": 78450.0, "bodyFat": 15.2, "muscleMass": 36100.0, "bmi": 23.41},
    ]
}


class FalskGarmin:
    """Svarer som Garmin, men fra tabellerne ovenfor. Husker alle kald."""

    def __init__(self, tom_dag: str | None = None):
        self.kald = []
        self.tom_dag = tom_dag

    def get_sleep_data(self, cdate):
        self.kald.append(("get_sleep_data", cdate))
        return {"dailySleepDTO": {}} if cdate == self.tom_dag else SOEVN

    def get_stats(self, cdate):
        self.kald.append(("get_stats", cdate))
        if cdate == self.tom_dag:
            from garminconnect import GarminConnectConnectionError

            raise GarminConnectConnectionError("No data received from server")
        return STATS

    def get_activities_by_date(self, startdate, enddate=None, activitytype=None, sortorder=None):
        self.kald.append(("get_activities_by_date", startdate, enddate))
        return [AKTIVITET]

    def get_body_composition(self, startdate, enddate=None):
        self.kald.append(("get_body_composition", startdate, enddate))
        return VAEGT


@pytest.fixture
def garmin(monkeypatch):
    g = FalskGarmin()
    monkeypatch.setattr(forbindelse, "klient", lambda person=None: g)
    return g


D = date(2026, 11, 4)

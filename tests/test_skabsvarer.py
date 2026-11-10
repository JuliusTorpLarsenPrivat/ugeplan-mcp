"""Skabsvarer fra før sidste indkøb kan være brugt: de skal tjekkes, ikke regnes med.
Julius, uge 46: "er den skudsikker?" (enebær, kartofler, hvidløg …)."""

import json

from handle_mcp import beholdning, lokal, ugeplan


def _sidste(monkeypatch, tid="2026-11-08T17:23+01:00", kode="UGE-8059"):
    monkeypatch.setattr(beholdning, "_sidste_indkoeb", lambda: (tid, kode))


def _gem(varer):
    lokal.skriv("beholdning", {"varer": varer})


GAMMEL = {"navn": "kartofler", "maengde": "500 g", "sted": "skab", "noteret": "2026-11-08T17:17+01:00"}


def test_gammel_skabsvare_skal_tjekkes(monkeypatch):
    _sidste(monkeypatch)
    _gem([GAMMEL, {"navn": "æg", "maengde": "3 stk", "sted": "køleskab", "noteret": "2026-11-08T17:10+01:00"}])
    v = {x.navn: x for x in beholdning.hent()}
    assert v["kartofler"].status.startswith("tjek:") and "UGE-8059" in v["kartofler"].status
    assert v["æg"].status is None  # køleskabet ryddes efter 7 dage og svares på hver uge


def test_ny_skabsvare_og_har_nulstiller(monkeypatch):
    _sidste(monkeypatch)
    _gem([GAMMEL])
    varer, _ = beholdning.opdater(tilfoej=[{"navn": "kartofler", "maengde": "1 kg", "sted": "skab"}])
    assert varer[0].status is None and varer[0].maengde == "1 kg"


def test_uden_fyldt_kurv_ingen_status(monkeypatch):
    monkeypatch.setattr(beholdning, "_sidste_indkoeb", lambda: None)
    _gem([GAMMEL])
    assert beholdning.hent()[0].status is None


def test_status_gemmes_ikke_i_filen(monkeypatch):
    _sidste(monkeypatch)
    _gem([GAMMEL])
    beholdning.opdater(tilfoej=[{"navn": "enebær", "sted": "skab"}])
    gemt = json.loads((lokal.mappe() / "beholdning.json").read_text(encoding="utf-8"))
    assert all("status" not in v for v in gemt["varer"])


def test_ugyldig_tid_vaelter_ikke(monkeypatch):
    _sidste(monkeypatch)
    _gem([{**GAMMEL, "noteret": "ukendt"}])
    assert beholdning.hent()[0].status is None


def test_forloebet_regner_ikke_med_gamle_skabsvarer():
    t = ugeplan.FAELLES
    assert '`status` "tjek: …"' in t and "regnes aldrig med" in t
    assert 'Svarer vi "har X"' in t


def test_tid_for_fyldt_kurv_bruges(monkeypatch):
    from handle_mcp import madplan

    class P:
        status, kode, oprettet = "kurv fyldt", "UGE-8059", "2026-11-08T17:23+01:00"
        historik = ["2026-11-08T17:23+01:00 oprettet", "2026-11-08T17:25+01:00 kurv fyldt efter godkendelse: 'bestil'"]

    monkeypatch.setattr(madplan, "_alle", lambda: [P()])
    assert beholdning._sidste_indkoeb() == ("2026-11-08T17:25+01:00", "UGE-8059")
    _gem([{"navn": "mandler", "maengde": None, "sted": "skab", "noteret": "2026-11-08T17:23+01:00"}])
    assert beholdning.hent()[0].status.startswith("tjek:")

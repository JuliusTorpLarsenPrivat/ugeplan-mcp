"""Testene, der skal fejle, hvis nogen (også en AI) bryder sikkerhedsreglerne."""

import ast
from pathlib import Path

import pytest

from garmin_mcp import login, vagt

SRC = Path(__file__).parents[2] / "src" / "garmin_mcp"


@pytest.mark.parametrize(
    "url",
    ["https://sso.garmin.com/mobile/api/login", "https://connectapi.garmin.com/x", "https://diauth.garmin.com/token", "https://garmin.com"],
)
def test_garmin_adresser_tilladt(url):
    vagt.tjek_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://garmin.com.evil.net/",
        "https://evilgarmin.com/",
        "http://connectapi.garmin.com/",  # ikke https
        "https://user:pw@connectapi.garmin.com/",
        "https://garmin.cn/",
    ],
)
def test_fremmede_adresser_afvises(url):
    with pytest.raises(vagt.VagtFejl):
        vagt.tjek_url(url)


@pytest.mark.parametrize("metode", ["POST", "PUT", "DELETE", "patch"])
def test_api_kun_get(metode):
    with pytest.raises(vagt.VagtFejl):
        vagt.tjek_api_metode(metode)
    vagt.tjek_api_metode("GET")


def test_vagten_stopper_rigtige_kald_foer_de_sendes():
    import requests
    from curl_cffi import requests as cffi_requests
    from garminconnect.client import Client

    vagt.installer()
    vagt.installer()  # to gange må ikke pakke ind to gange
    with pytest.raises(vagt.VagtFejl):
        requests.Session().get("https://example.com/")
    with pytest.raises(vagt.VagtFejl):
        cffi_requests.Session().request("GET", "https://example.com/")
    with pytest.raises(vagt.VagtFejl):
        cffi_requests.post("https://example.com/", data={"email": "x"})
    c = Client()
    with pytest.raises(vagt.VagtFejl):
        c._run_request("DELETE", "/activity-service/activity/1")
    with pytest.raises(vagt.VagtFejl):
        c.post("connectapi", "/weight-service/user-weight", json={})


SKRIVENDE_ORD = ("add_", "delete", "upload", "set_", "update_", "create_", "remove", "put(", "post(", "schedule", "import_")


def test_koden_kalder_kun_laesende_garmin_metoder():
    """Alle kald på Garmin-klienten (g.xxx) skal være get_-metoder."""
    kaldte = set()
    for fil in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(fil.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "g":
                    kaldte.add(node.func.attr)
    assert kaldte, "fandt ingen Garmin-kald: testen er gået i stykker"
    assert all(n.startswith("get_") for n in kaldte - {"login"}), kaldte


def test_ingen_skrivende_vaerktoejer():
    from garmin_mcp.server import mcp

    vaerktoejer = mcp._tool_manager.list_tools()
    assert len(vaerktoejer) == 8
    for v in vaerktoejer:
        assert v.annotations.read_only_hint is True
        assert not any(o in v.name for o in SKRIVENDE_ORD), v.name


def test_sundhedsdata_skrives_aldrig_til_fil():
    """Kun cli.logout må røre filer (og kun token-filen). Intet modul må åbne/skrive filer."""
    for fil in SRC.glob("*.py"):
        tekst = fil.read_text(encoding="utf-8")
        for forbudt in ("open(", "write_text", "write_bytes", "json.dump(", "pickle", "sqlite", "shelve"):
            assert forbudt not in tekst, f"{fil.name} indeholder {forbudt}"


def test_tokens_ligger_i_localappdata_ikke_onedrive(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert login.tokenmappe() == Path(r"C:\Users\x\AppData\Local") / "garmin-mcp"  # samme på Linux i CI
    assert login.tokenfil("anna").parent.name == "anna"
    assert "onedrive" not in str(login.tokenfil("anna")).lower()


def test_login_i_noegleringen(falsk_noegelring):
    with pytest.raises(login.IntetLogin):
        login.hent("anna")
    login.gem("Anna", "a@b.dk", "hemmelig")
    login.gem("bo", "b@b.dk", "andet")
    assert ("garmin-mcp", "person:anna") in falsk_noegelring.data
    assert login.hent("anna") == ("a@b.dk", "hemmelig")
    assert login.hent("bo") == ("b@b.dk", "andet")
    assert login.slet("anna") and not login.slet("anna")
    login.gem("standard", "gammel@b.dk", "x")  # første version uden personer
    assert ("garmin-mcp", "garmin-connect") in falsk_noegelring.data


def test_ingen_hemmeligheder_i_repoet():
    rod = Path(__file__).parents[2]
    ignorer = (rod / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignorer
    for fil in rod.rglob("*"):
        if fil.is_file() and ".venv" not in fil.parts and ".git" not in fil.parts:
            assert fil.name != "garmin_tokens.json"

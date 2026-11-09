import pytest


@pytest.fixture(autouse=True)
def egen_datamappe(tmp_path, monkeypatch):
    """Ingen test må røre de rigtige filer i LOCALAPPDATA/handle-mcp eller logge ind hos butikkerne."""
    monkeypatch.setenv("HANDLE_MCP_DATA", str(tmp_path / "handle-mcp-data"))
    # Ingen rigtige logins: testene skal opføre sig ens hos Julius og på GitHub
    from handle_mcp import login as _login

    monkeypatch.setattr(_login.keyring, "get_password", lambda *a: None)
    for b in _login.BUTIKKER:
        for k in ("EMAIL", "KODE"):
            monkeypatch.delenv(f"KURV_{b.upper()}_{k}", raising=False)
    from handle_mcp import ugeplan

    monkeypatch.setattr(ugeplan, "HENT_ORDRER", False)
    # Første-gangs-guiden kører kun ved tom profil; den testes for sig (test_opsaetning.py)
    monkeypatch.setattr(ugeplan, "FOERSTE_GANG_AKTIV", False)
    monkeypatch.setattr(ugeplan, "HENT_LEVERING", False)
    from handle_mcp import telegram as _tg

    monkeypatch.setattr(_tg, "HENT_LEVERING", False)

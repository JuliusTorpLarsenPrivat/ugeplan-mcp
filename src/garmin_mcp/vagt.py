"""Vagten: den eneste vej ud på nettet.

garmin-mcp bruger biblioteket `garminconnect`, som sender sine kald med to HTTP-biblioteker
(`requests` og `curl_cffi`). Vagten sætter sig foran begge, inden noget bliver sendt, og
tjekker to ting:

1. At adressen er https og hører til Garmin (garmin.com eller en underadresse som
   sso.garmin.com). Alt andet afvises. Så kan dit login og dine data aldrig ende et
   ukendt sted, heller ikke ved en fejl i biblioteket.
2. At kald til Garmins data-API (connectapi) kun læser (GET). garmin-mcp må aldrig
   ændre, uploade eller slette noget i din Garmin-konto.

Login (som skal sende email og kode) går til sso.garmin.com og diauth.garmin.com og er
derfor stadig tilladt. Vagten er bevidst streng: hellere et kald for meget afvist end et
for lidt.
"""

from __future__ import annotations

import functools
from urllib.parse import urlsplit

GARMIN_DOMAENE = "garmin.com"


class VagtFejl(Exception):
    """Et kald, vagten ikke vil sende."""


def tjek_url(url: str) -> None:
    dele = urlsplit(str(url))
    vaert = (dele.hostname or "").lower()
    if dele.scheme != "https":
        raise VagtFejl(f"Afvist: kun https er tilladt ({dele.scheme or 'ingen'}://).")
    if dele.username or dele.password:
        raise VagtFejl("Afvist: adressen må ikke indeholde login.")
    if vaert != GARMIN_DOMAENE and not vaert.endswith("." + GARMIN_DOMAENE):
        raise VagtFejl(f"Afvist: {vaert or 'ukendt vært'} er ikke en Garmin-adresse.")


def tjek_api_metode(metode: str) -> None:
    if str(metode).upper() != "GET":
        raise VagtFejl(f"Afvist: garmin-mcp må kun læse fra Garmin, ikke {str(metode).upper()}.")


_installeret = False


def installer() -> None:
    """Sæt vagten foran alle HTTP-kald i denne proces. Kan kaldes flere gange."""
    global _installeret
    if _installeret:
        return

    import requests
    from curl_cffi import requests as cffi_requests
    from garminconnect.client import Client

    # requests: send() kaldes for hvert kald, også for hver omdirigering.
    oprindelig_send = requests.Session.send

    @functools.wraps(oprindelig_send)
    def send(self, request, **kw):
        tjek_url(request.url)
        return oprindelig_send(self, request, **kw)

    requests.Session.send = send

    # curl_cffi: request() bruges af både sessioner og cffi_requests.post/get.
    # libcurl følger selv omdirigeringer, så vi tjekker også den endelige adresse.
    oprindelig_cffi = cffi_requests.Session.request

    @functools.wraps(oprindelig_cffi)
    def cffi_request(self, method, url, *a, **kw):
        tjek_url(url)
        svar = oprindelig_cffi(self, method, url, *a, **kw)
        tjek_url(svar.url)
        return svar

    cffi_requests.Session.request = cffi_request

    # Garmins data-API: kun GET.
    oprindelig_api = Client._run_request

    @functools.wraps(oprindelig_api)
    def api_kald(self, method, path, **kw):
        tjek_api_metode(method)
        return oprindelig_api(self, method, path, **kw)

    Client._run_request = api_kald
    _installeret = True

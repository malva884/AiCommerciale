"""Fetch aggiudicazioni TED (contract award notices) - API pubblica UE.

Il vincitore di una commessa e' il cliente potenziale: chi si e' aggiudicato
l'appalto dovra' comprare i cavi per realizzarlo.
Richiede TED_API_KEY come fetch_ted; senza chiave ritorna lista vuota.
"""
import os

import requests

from config import (TED_API_URL, TED_COUNTRIES, TED_CPV_CODES,
                    TED_KEYWORDS, TED_MAX_RESULTS, COUNTRY_TO_AREA)
from fetchers.ted import _flatten


def fetch_ted_awards(verbose: bool = True) -> list[dict]:
    """Aggiudicazioni UE: il campo winner-name = azienda cliente potenziale."""
    api_key = os.environ.get("TED_API_KEY")
    if not api_key:
        if verbose:
            print("  [ted-award] TED_API_KEY non impostata, fonte saltata.")
        return []

    cpv = " OR ".join(f"PC = {c}" for c in TED_CPV_CODES)
    kw = " OR ".join(f'FT ~ "{k}"' for k in TED_KEYWORDS)
    payload = {
        "query": f"form-type IN (result) AND (({cpv}) OR ({kw}))",
        "fields": ["notice-title", "buyer-name", "publication-number",
                   "publication-date", "winner-name",
                   "description-proc", "description-lot",
                   "place-of-performance-country-lot"],
        "limit": min(TED_MAX_RESULTS, 100),
        "scope": "ALL",
        "paginationMode": "PAGE_NUMBER",
        "onlyLatestVersions": True,
    }
    if TED_COUNTRIES:
        countries = " OR ".join(f"CY = {c}" for c in TED_COUNTRIES)
        payload["query"] += f" AND ({countries})"
    payload["query"] += " SORT BY publication-date DESC"

    try:
        resp = requests.post(
            TED_API_URL,
            params={"apiKey": api_key},
            json=payload,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        if verbose:
            print(f"  [ted-award] errore API: {exc}")
        return []

    items = []
    for notice in resp.json().get("notices", []):
        pub_num = notice.get("publication-number", "")
        winners = _flatten(notice.get("winner-name"))
        country = _flatten(notice.get("place-of-performance-country-lot"))
        if not country or len(country) != 3:
            country = ("ITA" if "italia" in _flatten(
                notice.get("notice-title")).lower() else None)

        first_winner = winners.split(" | ")[0].strip() if winners else ""
        items.append({
            "source": "ted_award",
            "external_id": f"ted-award:{pub_num}",
            "title": _flatten(notice.get("notice-title")),
            "url": f"https://ted.europa.eu/it/notice/-/detail/{pub_num}",
            "published": notice.get("publication-date"),
            "country": country,
            "area_manager": COUNTRY_TO_AREA.get(country) if country else None,
            "target_company": first_winner or None,
            "text": " ".join(filter(None, [
                f"Aggiudicatario: {winners}" if winners else "",
                "Committente: " + _flatten(notice.get("buyer-name")),
                f"Paese lavori: {country}" if country else "",
                _flatten(notice.get("description-proc")),
                _flatten(notice.get("description-lot")),
            ])),
        })
    return items

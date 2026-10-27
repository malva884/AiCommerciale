"""Fetch bandi da TED (Tenders Electronic Daily) - API pubblica UE.

Richiede API key gratuita (registrazione su https://ted.europa.eu):
    setx TED_API_KEY "la-tua-chiave"      # Windows, poi riaprire terminale
Senza chiave la funzione ritorna lista vuota senza bloccare la pipeline.
"""
import os

import requests

from config import (TED_API_URL, TED_COUNTRIES, TED_CPV_CODES,
                    TED_KEYWORDS, TED_MAX_RESULTS, COUNTRY_TO_AREA)


_PREFERRED_LANGS = ("ita", "eng", "fra", "deu", "spa")


def _flatten(value) -> str:
    """I campi TED sono dict per lingua, liste o stringhe semplici."""
    if isinstance(value, dict):
        for lang in _PREFERRED_LANGS:
            if value.get(lang):
                return str(value[lang])
        return " | ".join(str(v) for v in value.values())
    if isinstance(value, list):
        return " | ".join(p for p in (_flatten(v) for v in value) if p)
    return str(value) if value else ""


def fetch_ted(verbose: bool = True) -> list[dict]:
    api_key = os.environ.get("TED_API_KEY")
    if not api_key:
        if verbose:
            print("  [ted] TED_API_KEY non impostata, fonte saltata.")
        return []

    cpv = " OR ".join(f"PC = {c}" for c in TED_CPV_CODES)
    kw = " OR ".join(f'FT ~ "{k}"' for k in TED_KEYWORDS)
    payload = {
        "query": f"({cpv}) OR ({kw})",
        "fields": ["notice-title", "buyer-name", "publication-number",
                   "publication-date", "deadline-receipt-tender-date-lot",
                   "description-proc", "description-lot",
                   "place-of-performance-country-lot"],
        "limit": min(TED_MAX_RESULTS, 100),
        "scope": "ACTIVE",
        "paginationMode": "PAGE_NUMBER",
        "onlyLatestVersions": True,
    }
    if TED_COUNTRIES:
        countries = " OR ".join(f"CY = {c}" for c in TED_COUNTRIES)
        payload["query"] += f" AND ({countries})"

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
            print(f"  [ted] errore API: {exc}")
        return []

    items = []
    for notice in resp.json().get("notices", []):
        pub_num = notice.get("publication-number", "")
        country = _flatten(notice.get("place-of-performance-country-lot"))
        if not country or len(country) != 3:
            # fallback: cerca country di 3 lettere nel testo
            country = "ITA" if "italia" in _flatten(notice.get("notice-title")).lower() else None
        area = COUNTRY_TO_AREA.get(country) if country else None

        items.append({
            "source": "ted",
            "external_id": f"ted:{pub_num}",
            "title": _flatten(notice.get("notice-title")),
            "url": f"https://ted.europa.eu/it/notice/-/detail/{pub_num}",
            "published": notice.get("publication-date"),
            "country": country,
            "area_manager": area,
            "text": " ".join(filter(None, [
                "Acquirente: " + _flatten(notice.get("buyer-name")),
                f"Paese lavori: {country}" if country else "",
                _flatten(notice.get("description-proc")),
                _flatten(notice.get("description-lot")),
                "Scadenza: " + _flatten(
                    notice.get("deadline-receipt-tender-date-lot")),
            ])),
        })
    return items

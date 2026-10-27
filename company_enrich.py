"""Arricchimento dati aziendali da fonti pubbliche (Wikidata, licenza CC0).

Per ogni azienda cliente potenziale estrae:
- fatturato per anno (ultimi 3 esercizi disponibili) con valuta
- numero dipendenti
- crescita YoY del fatturato
- sede, settori, anno di fondazione, sito web

Nessuna API key richiesta; non vengono inviati dati interni dell'azienda,
solo il nome pubblico del prospect da cercare.
"""
import time

import requests

_API = "https://www.wikidata.org/w/api.php"
_HEADERS = {"User-Agent": "SalesAgentCommerciale/1.0 (progetto interno)"}
_TIMEOUT = 15

# Parole nella descrizione Wikidata che indicano un'azienda vera e propria
_COMPANY_WORDS = (
    "company", "corporation", "manufacturer", "enterprise", "group",
    "holding", "multinational", "azienda", "societ", "rail", "shipyard",
    "aerospace", "defense", "defence", "telecom", "energy", "construction",
)

# QID Wikidata -> simbolo valuta (per il fatturato)
_CURRENCIES = {
    "Q4916": "€",     # euro
    "Q4917": "$",     # dollaro USA
    "Q25224": "£",    # sterlina
    "Q25344": "CHF ",  # franco svizzero
    "Q122922": "SEK ",  # corona svedese
    "Q123213": "PLN ",  # zloty
    "Q131473": "DKK ",  # corona danese
    "Q132643": "NOK ",  # corona norvegese
    "Q8146": "JPY ",   # yen giapponese
}


def _get(params: dict, retries: int = 3) -> dict:
    """GET su Wikidata con pausa tra chiamate e retry su errori/rate limit."""
    time.sleep(0.4)  # politeness: evita il throttling sulle chiamate in batch
    for attempt in range(retries):
        try:
            r = requests.get(_API, params=params, headers=_HEADERS,
                             timeout=_TIMEOUT)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == retries - 1:
                print(f"  [enrich] errore API Wikidata: {exc}")
            else:
                time.sleep(1.5 * (attempt + 1))
    return {}


def _search_entity(name: str) -> dict | None:
    """Prima entity Wikidata che sembra un'azienda (o il primo risultato)."""
    data = _get({
        "action": "wbsearchentities", "search": name, "language": "en",
        "uselang": "en", "format": "json", "limit": 6, "type": "item",
    })
    results = data.get("search", [])
    if not results:
        return None
    for r in results:
        desc = (r.get("description") or "").lower()
        if any(w in desc for w in _COMPANY_WORDS):
            return r
    # Nessuna entita' aziendale trovata: meglio nessun dato che dati sbagliati
    return None


def _time_year(claim: dict) -> int | None:
    """Anno dal qualifier 'point in time' (P585) della claim."""
    try:
        t = claim["qualifiers"]["P585"][0]["datavalue"]["value"]["time"]
        return int(t[1:5])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _amount(claim: dict) -> float | None:
    try:
        return float(claim["mainsnak"]["datavalue"]["value"]["amount"])
    except (KeyError, TypeError, ValueError):
        return None


def _series(claims: list) -> dict:
    """{anno: valore} dalle claim con qualifier temporale."""
    out = {}
    for c in claims:
        y, a = _time_year(c), _amount(c)
        if y and a is not None:
            out[y] = a
    return out


def _entity_ids(claims: list, cap: int = 4) -> list[str]:
    ids = []
    for c in claims[:cap]:
        try:
            nid = c["mainsnak"]["datavalue"]["value"]["numeric-id"]
            ids.append(f"Q{nid}")
        except (KeyError, TypeError):
            continue
    return ids


def _labels(qids: list[str]) -> dict:
    """QID -> label leggibile (preferenza italiano, fallback inglese)."""
    if not qids:
        return {}
    data = _get({"action": "wbgetentities", "ids": "|".join(qids),
                 "props": "labels", "languages": "it|en", "format": "json"})
    out = {}
    for qid, e in data.get("entities", {}).items():
        lab = e.get("labels", {})
        out[qid] = (lab.get("it") or lab.get("en") or {}).get("value")
    return out


def enrich_company(name: str) -> dict:
    """Dati pubblici dell'azienda. Ritorna {} se non trovata o errore rete."""
    hit = _search_entity(name)
    if not hit:
        return {}
    qid = hit["id"]

    data = _get({"action": "wbgetentities", "ids": qid,
                 "props": "claims|descriptions|labels",
                 "languages": "it|en", "format": "json"})
    entity = data.get("entities", {}).get(qid)
    if not entity:
        return {}
    claims = entity.get("claims", {})

    # P2139 fatturato: ultimi 3 esercizi nella STESSA valuta del piu' recente
    rev_points = []
    for c in claims.get("P2139", []):
        y, a = _time_year(c), _amount(c)
        try:
            unit = c["mainsnak"]["datavalue"]["value"]["unit"]
        except (KeyError, TypeError):
            continue
        if y and a is not None:
            rev_points.append((y, a, unit.rsplit("/", 1)[-1]))

    revenue = {}
    currency = "€"
    if rev_points:
        latest_unit = max(rev_points, key=lambda p: p[0])[2]
        currency = _CURRENCIES.get(latest_unit)
        if currency is None and latest_unit != "1":
            # valuta non mappata: risolvi il nome reale (es. 'Saudi riyal')
            currency = (_labels([latest_unit]).get(latest_unit) or "?") + " "
        currency = currency or "€"
        same_unit = {y: a for y, a, u in rev_points if u == latest_unit}
        revenue = dict(sorted(same_unit.items(), reverse=True)[:3])

    # P1128 dipendenti (piu' recente; fallback su valore senza data)
    emp_series = _series(claims.get("P1128", []))
    employees = emp_series.get(max(emp_series)) if emp_series else None
    if employees is None:
        for c in claims.get("P1128", []):
            a = _amount(c)
            if a:
                employees = int(a)
                break
    if employees is not None:
        employees = int(employees)

    # P571 anno di fondazione
    founded = None
    for c in claims.get("P571", []):
        try:
            founded = int(c["mainsnak"]["datavalue"]["value"]["time"][1:5])
            break
        except (KeyError, TypeError, ValueError):
            continue

    # P856 sito ufficiale
    website = None
    for c in claims.get("P856", []):
        try:
            website = c["mainsnak"]["datavalue"]["value"]
            break
        except (KeyError, TypeError):
            continue

    # P159 sede, P452 settori -> risoluzione label in batch
    hq_ids = _entity_ids(claims.get("P159", []), cap=1)
    ind_ids = _entity_ids(claims.get("P452", []), cap=3)
    labels = _labels(hq_ids + ind_ids)

    # Crescita YoY fra i due esercizi piu' recenti disponibili
    growth = None
    years = sorted(revenue)
    if len(years) >= 2:
        prev, last = revenue[years[-2]], revenue[years[-1]]
        if prev:
            growth = round((last - prev) / prev * 100, 1)

    lab = entity.get("labels", {})
    desc = entity.get("descriptions", {})
    return {
        "wikidata_id": qid,
        "name": (lab.get("it") or lab.get("en") or {}).get("value", name),
        "description": (desc.get("it") or desc.get("en") or {}).get("value"),
        "revenue_history": {str(y): v for y, v in revenue.items()},
        "currency": currency,
        "growth_pct": growth,
        "employees": employees,
        "hq": labels.get(hq_ids[0]) if hq_ids else None,
        "industries": [labels[i] for i in ind_ids if labels.get(i)],
        "founded": founded,
        "website": website,
        "source": "wikidata",
    }


def format_amount(v: float | None, symbol: str = "€") -> str:
    """18_692_900_000 -> '18.7 Mrd€'."""
    if v is None:
        return "-"
    abs_v = abs(v)
    if abs_v >= 1e9:
        return f"{symbol}{v / 1e9:.1f} Mrd"
    if abs_v >= 1e6:
        return f"{symbol}{v / 1e6:.0f} M"
    if abs_v >= 1e3:
        return f"{symbol}{v / 1e3:.0f} k"
    return f"{symbol}{v:.0f}"

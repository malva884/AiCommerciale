"""Scoring delle opportunita' con LLM locale (Ollama).

Estrae:
- Score di rilevanza commerciale (0-100)
- Settore target (Data Center, Telco, Ferroviario, Navale, Avio, Altro)
- Normative tecniche rilevate (EN 45545-2, CPR B2ca, RINA, DNV, MIL-DTL, ecc.)
- Assegnazione Area Manager (DACH, IBERIA, FRANCE, ITALY, NORDICS, UK_IE, CEE)
- Motivazione sintetica e Prossima azione commerciale
- Bozza email di primo contatto adattata al tone of voice del Paese
"""
import json
import re

import requests

from config import (AZIENDA, COUNTRY_TO_AREA, KEYWORD_SCORE,
                    OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL)

SYSTEM_PROMPT = f"""Sei il Lead Commercial Analyst & Sales Engineer di un'azienda europea.
{AZIENDA}

Il tuo compito e' valutare segnali pubblici (bandi TED, aggiudicazioni, notizie di mercato) per trovare a QUALI AZIENDE vendere cavi speciali in EUROPA.

Regola chiave: il cliente potenziale NON e' l'ente pubblico che bandisce la gara, ma l'AZIENDA che vince o realizzera' la commessa (prime contractor, OEM, EPC, system integrator). Se il segnale e' un bando ancora aperto, il cliente potenziale e' l'azienda che probabilmente lo vincera' o che ci lavorera' come fornitore.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido su una riga con questi campi:
{{
  "score": <int 0-100>,
  "sector": "<Data Center|Telecom/Provider|Ferroviario|Navale|Avio/Difesa|Altro>",
  "target_company": "<nome dell'azienda potenziale cliente: il vincitore dell'appalto o chi realizzera' la commessa (es. Leonardo, Alstom, Fincantieri, EPC contractor), oppure null>",
  "country": "<codice ISO a 3 lettere es. ITA, DEU, FRA, ESP, GBR, SWE, POL, ecc., oppure null se ignoto>",
  "area_manager": "<DACH|IBERIA|FRANCE|ITALY|NORDICS|UK_IE|CEE|null>",
  "norms": "<normative citate o richieste es. EN 45545-2 HL3, CPR B2ca, RINA, DNV, MIL-DTL, oppure null>",
  "motivation": "<max 2 frasi in italiano: perche' questa azienda comprera' cavi>",
  "action": "<azione concreta: chi contattare presso target_company e con quale proposta>",
  "email_draft": "<bozza email di primo contatto di 4-6 righe indirizzata a target_company, nella lingua del Paese o in inglese>"
}}

Criteri di scoring (vendita al vincitore):
- 80-100: Azienda europea si e' aggiudicata o sta realizzando una commessa che richiede cavi speciali: treni, navi, velivoli, data center, reti. Target vendita chiaro e nominato.
- 50-79: Grande progetto o commessa in corso in Europa che richiedera' lotti cavi; fornitore identificabile o gara in corso con partecipanti noti.
- 20-49: Bando aperto rilevante (vendita possibile a chi partecipera') o notizia di settore generica.
- 0-19: Irrilevante, fuori tema, fuori dall'Europa o nessun target vendita identificabile.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Prime contractor noti (fallback euristico per il cliente potenziale)
_KNOWN_PRIMES = {
    "leonardo": "Leonardo", "alstom": "Alstom", "fincantieri": "Fincantieri",
    "hitachi rail": "Hitachi Rail", "siemens mobility": "Siemens Mobility",
    "stadler": "Stadler", "talgo": "Talgo", "saab": "Saab",
    "thales": "Thales", "rheinmetall": "Rheinmetall", "navantia": "Navantia",
    "hensoldt": "Hensoldt", "babcock": "Babcock", "ansaldo": "Ansaldo",
    "equinix": "Equinix", "open fiber": "Open Fiber",
    "siemens": "Siemens", "caf": "CAF", "webuild": "Webuild",
    "ghella": "Ghella", "pizzarotti": "Pizzarotti",
    "trenitalia": "Trenitalia", "hitachi": "Hitachi Rail",
}

# Pattern "X wins/secures/awarded..." e "aggiudicatario X / X si aggiudica"
_WIN_RES = [
    re.compile(r"^\W*([A-Z][\w&'.() -]{1,45}?)\s+"
               r"(?:wins?|secures?|awarded|bags?|signs?|lands?|gets?)\b"),
    re.compile(r"\baggiudicatari[oa]\s+([A-Z][\w&'.() -]{1,45}?)\s+"
               r"(?:l'appalto|la commessa|il contratto|dell'appalto|per\b)"),
    re.compile(r"\b([A-Z][\w&'.() -]{1,45}?)\s+"
               r"(?:vince|si aggiudica|ottiene)\s+"
               r"(?:l'appalto|la commessa|il contratto|un contratto)"),
]


def _extract_target(title: str, text: str = "") -> str | None:
    """Nome dell'azienda potenziale cliente (vincitore commessa) dal titolo/testo."""
    for rx in _WIN_RES:
        m = rx.search(title or "")
        if m:
            return m.group(1).strip(" –—:,.-")
    haystack = f"{title} {text}".lower()
    for kw, name in _KNOWN_PRIMES.items():
        if kw in haystack:
            return name
    return None


def ollama_available() -> bool:
    try:
        r = requests.get(OLLAMA_URL.rsplit("/api", 1)[0], timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _score_ollama(title: str, text: str, country_hint: str | None = None) -> dict | None:
    prompt = f"TITOLO: {title}\nPAESE_SUGGERITO: {country_hint or 'sconosciuto'}\n\nTESTO:\n{text[:2500]}"
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "stream": False, "format": "json",
                  "messages": [
                      {"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt},
                  ]},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        data = json.loads(_JSON_RE.search(content).group(0))

        c = data.get("country")
        area = data.get("area_manager") or (COUNTRY_TO_AREA.get(c) if c else None)

        return {
            "score": max(0, min(100, int(data.get("score", 0)))),
            "sector": data.get("sector") or "Altro",
            "target_company": data.get("target_company"),
            "country": c,
            "area_manager": area,
            "norms": data.get("norms"),
            "motivation": data.get("motivation", ""),
            "action": data.get("action", ""),
            "email_draft": data.get("email_draft", ""),
            "scored_by": "ollama",
        }
    except (requests.RequestException, ValueError, AttributeError):
        return None


def _score_heuristic(title: str, text: str, country_hint: str | None = None) -> dict:
    haystack = f"{title} {text}".lower()
    raw = sum(w for kw, w in KEYWORD_SCORE.items() if kw in haystack)

    # Identificazione settore euristica
    sector = "Altro"
    if any(k in haystack for k in ["data center", "datacenter", "hyperscale"]):
        sector = "Data Center"
    elif any(k in haystack for k in ["ferroviar", "railway", "rfi", "alstom", "treno",
                                     "rolling stock", "materiale rotabile", "rotabili",
                                     "segnalamento", "signalling", "ertms", "etcs",
                                     "catenaria", "catenary", "metropolitana", "tram"]):
        sector = "Ferroviario"
    elif any(k in haystack for k in ["naval", "shipyard", "fincantieri", "nave", "sommergibile"]):
        sector = "Navale"
    elif any(k in haystack for k in ["aerospace", "difesa", "defense", "avio", "aeronaut"]):
        sector = "Avio/Difesa"
    elif any(k in haystack for k in ["telecom", "ftth", "5g", "fibra ottica", "provider", "open fiber", "fibercop"]):
        sector = "Telecom/Provider"

    # Norme euristica
    detected_norms = []
    for n in ["EN 45545", "CPR B2ca", "CPR", "RINA", "DNV", "MIL-DTL", "LSZH", "MPO",
              "OM4", "OM5", "EN 50306", "EN 50355", "EN 50264", "EN 50200",
              "EN 50173", "EN 61034", "IEC 60332", "EN 60331", "Cat 6A", "Cat 7", "Cat 8"]:
        if n.lower() in haystack:
            detected_norms.append(n)

    area = COUNTRY_TO_AREA.get(country_hint) if country_hint else None

    return {
        "score": min(100, raw),
        "sector": sector,
        "country": country_hint,
        "area_manager": area,
        "norms": ", ".join(detected_norms) if detected_norms else None,
        "target_company": _extract_target(title, text or ""),
        "motivation": None,
        "action": None,
        "email_draft": None,
        "scored_by": "heuristic",
    }


def score_opportunity(title: str, text: str, country_hint: str | None = None) -> dict:
    """LLM locale se disponibile, altrimenti euristico."""
    result = _score_ollama(title, text, country_hint)
    return result if result else _score_heuristic(title, text, country_hint)


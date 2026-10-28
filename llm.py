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

SYSTEM_PROMPT = f"""Sei il Lead Commercial Analyst & Sales Engineer di un'azienda europea produttrice di cavi speciali (Fibra Ottica e Rame).
{AZIENDA}

Il tuo compito e' valutare segnali pubblici (bandi TED, aggiudicazioni, notizie di mercato) per trovare OPPORTUNITA' COMMERCIALI CONCRETE di vendita cavi in EUROPA.

DUE TIPI DI OPPORTUNITA' VALIDE:
1. GARE DIRETTE / CLIENTI ISTITUZIONALI: Enti e grandi aziende che acquistano direttamente a capitolato/accordo quadro o per cui siamo fornitori qualificati (es. RFI - Rete Ferroviaria Italiana, Marina Militare, Leonardo, Trenitalia, Fincantieri, Ministero Difesa, Enel/Terna per cavi rete, operatori metropolitane). In questo caso l'opportunita' e' partecipare direttamente alla gara o rinnovare l'accordo.
2. VENDITA AGLI ESECUTORI / PRIME CONTRACTOR: Grandi commesse pubbliche o private (es. Comuni per fibra, posa reti, parchi dati/data center, linee ferroviarie, tratte navali) dove il cliente a cui VENDERE e' l'AZIENDA ESECUTRICE/VINCITRICE (General Contractor, EPC, System Integrator, Sirti, Valtellina, Alstom, Hitachi Rail, Webuild, ecc.) che dovra' comprare le bobine di cavo per realizzare i lavori.

REGOLA ASSOLUTA SUL RUMORE (SCORE = 0-15):
- Articoli di cronaca generica, polemiche locali, inchieste giudiziarie, incidenti, politica, disagi per scavi stradali, droni bellici o notizie generiche senza una commessa specifica da fornire devono avere SCORE ZERO o < 20 e venire scartati.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido su una riga con questi campi:
{{
  "score": <int 0-100>,
  "sector": "<Data Center|Telecom/Provider|Ferroviario|Navale|Avio/Difesa|Altro>",
  "target_company": "<nome dell'azienda/ente a cui vendere o proporre l'offerta (es. RFI, Marina Militare, Leonardo, Alstom, Sirti, Fincantieri, Webuild...), oppure null>",
  "country": "<codice ISO a 3 lettere es. ITA, DEU, FRA, ESP, GBR, SWE, POL, ecc., oppure null se ignoto>",
  "area_manager": "<DACH|IBERIA|FRANCE|ITALY|NORDICS|UK_IE|CEE|null>",
  "norms": "<normative citate o richieste es. EN 45545-2 HL3, CPR B2ca, RINA, DNV, MIL-DTL, EN 50264, oppure null>",
  "motivation": "<max 2 frasi in italiano: spiegazione commerciale su cosa e perche' compreranno>",
  "action": "<azione commerciale precisa: chi contattare o che bando presidiare>",
  "email_draft": "<bozza email di primo contatto di 4-6 righe, nella lingua del Paese o in inglese, oppure bozza nota commerciale>"
}}

Criteri di scoring:
- 85-100: Bando diretto di fornitura cavi di grande ente (RFI, Marina, Leonardo, ecc.) OPPURE aggiudicazione confermata a General Contractor noto che deve comprare lotti cavi.
- 60-84: Nuova commessa/cantiere in avvio in Europa con fabbisogno evidente di cavi speciali (ferrovie, navale, data center, FTTH) e target identificabile.
- 25-59: Bando aperto per infrastruttura in corso di definizione o segnale di mercato con potenziale fornitura.
- 0-24: Notizia di cronaca, politica, gossip, nessun fabbisogno di cavi, fuori Europa, o nessun target identificabile.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Prime contractor ed enti target diretti
_KNOWN_PRIMES = {
    # Enti e clienti diretti
    "rfi": "RFI - Rete Ferroviaria Italiana",
    "rete ferroviaria italiana": "RFI - Rete Ferroviaria Italiana",
    "marina militare": "Marina Militare",
    "trenitalia": "Trenitalia",
    "difesa": "Ministero della Difesa",
    "aeronautica militare": "Aeronautica Militare",
    # Prime contractor / Integratori / OEM
    "leonardo": "Leonardo", "alstom": "Alstom", "fincantieri": "Fincantieri",
    "hitachi rail": "Hitachi Rail", "siemens mobility": "Siemens Mobility",
    "stadler": "Stadler", "talgo": "Talgo", "saab": "Saab",
    "thales": "Thales", "rheinmetall": "Rheinmetall", "navantia": "Navantia",
    "hensoldt": "Hensoldt", "babcock": "Babcock", "ansaldo": "Ansaldo",
    "equinix": "Equinix", "open fiber": "Open Fiber", "fibercop": "FiberCop",
    "sirti": "Sirti", "valtellina": "Valtellina", "ceit": "Ceit",
    "siemens": "Siemens", "caf": "CAF", "webuild": "Webuild",
    "ghella": "Ghella", "pizzarotti": "Pizzarotti", "hitachi": "Hitachi Rail",
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
    """Nome dell'azienda o ente potenziale cliente dal titolo/testo."""
    haystack = f"{title} {text}".lower()
    for kw, name in _KNOWN_PRIMES.items():
        if kw in haystack:
            return name
    for rx in _WIN_RES:
        m = rx.search(title or "")
        if m:
            return m.group(1).strip(" –—:,.-")
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
    
    # 1. Filtro Rumore Cronaca / Politica / Gossip / Incidenti
    junk_keywords = [
        "inchiesta", "maestrale", "clan", "spiazzano", "droni", "dron", "hezbollah", 
        "guerra", "attacco", "polemica", "polemiche", "disagi", "residenti", "traffico",
        "multa", "truffa", "arresto", "arresti", "confedilizia"
    ]
    if any(j in haystack for j in junk_keywords):
        return {
            "score": 0,
            "sector": "Altro",
            "country": country_hint,
            "area_manager": None,
            "norms": None,
            "target_company": None,
            "motivation": "Scartato: notizia di cronaca / incidenti non commerciale",
            "action": None,
            "email_draft": None,
            "scored_by": "heuristic_filtered",
        }

    target = _extract_target(title, text or "")
    
    # Ha intent commerciale/appalto?
    commercial_terms = [
        "bando", "gara", "appalto", "commessa", "fornitura", "tender", "contract",
        "aggiudicat", "vince", "awarded", "accordo quadro", "framework agreement",
        "lavori", "posa", "cablaggio", "cavi", "cable", "fibra", "rame", "ertms", "segnalamento"
    ]
    has_commercial = any(k in haystack for k in commercial_terms)
    
    if not target and not has_commercial:
        return {
            "score": 0,
            "sector": "Altro",
            "country": country_hint,
            "area_manager": None,
            "norms": None,
            "target_company": None,
            "motivation": "Scartato: nessun target ne' commessa commerciale identificabile",
            "action": None,
            "email_draft": None,
            "scored_by": "heuristic_filtered",
        }

    raw = sum(w for kw, w in KEYWORD_SCORE.items() if kw in haystack)
    if target:
        raw += 35  # Bonus alto se c'e' un cliente diretto o prime contractor identificato

    # Identificazione settore euristica
    sector = "Altro"
    if any(k in haystack for k in ["data center", "datacenter", "hyperscale"]):
        sector = "Data Center"
    elif any(k in haystack for k in ["ferroviar", "railway", "rfi", "alstom", "treno",
                                     "rolling stock", "materiale rotabile", "rotabili",
                                     "segnalamento", "signalling", "ertms", "etcs",
                                     "catenaria", "catenary", "metropolitana", "tram"]):
        sector = "Ferroviario"
    elif any(k in haystack for k in ["naval", "shipyard", "fincantieri", "nave", "sommergibile", "marina militare"]):
        sector = "Navale"
    elif any(k in haystack for k in ["aerospace", "difesa", "defense", "avio", "aeronaut", "leonardo"]):
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
        "target_company": target,
        "motivation": f"Opportunita' di fornitura cavi per {target}" if target else "Commessa / Bando con potenziale acquisto cavi",
        "action": f"Contattare referente acquisti / ufficio gare di {target}" if target else "Identificare l'aggiudicatario dei lavori",
        "email_draft": None,
        "scored_by": "heuristic",
    }


def score_opportunity(title: str, text: str, country_hint: str | None = None) -> dict:
    """LLM locale se disponibile, altrimenti euristico."""
    result = _score_ollama(title, text, country_hint)
    return result if result else _score_heuristic(title, text, country_hint)


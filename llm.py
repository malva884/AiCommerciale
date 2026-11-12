"""Scoring delle opportunita' con LLM locale (Ollama).

Estrae:
- Score di rilevanza commerciale (0-100)
- Settore target (Data Center, Telco, Ferroviario, Navale, Avio, Altro)
- Normative tecniche rilevate (EN 45545-2, CPR B2ca, RINA, DNV, MIL-DTL, ecc.)
- Assegnazione Area Manager (DACH, IBERIA, FRANCE, ITALY, NORDICS, UK_IE, CEE)
- Motivazione sintetica e Prossima azione commerciale
- Bozza email di primo contatto adattata al tone of voice del Paese
"""
import hashlib
import json
import re
import time

import requests

import db
from config import (AZIENDA, COUNTRY_TO_AREA, DISABLE_OLLAMA_FALLBACK,
                    GEMINI_API_KEY, GEMINI_API_KEYS, GEMINI_API_URL,
                    GEMINI_DAILY_LIMIT, GEMINI_MIN_INTERVAL, GEMINI_MODEL,
                    GEMINI_TIMEOUT, KEYWORD_SCORE, LLM_PROVIDER,
                    OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL)

# Runtime overrides (impostabili dinamicamente da UI Streamlit o da script)
_RUNTIME_PROVIDER = None
_RUNTIME_GEMINI_KEY = None
_RUNTIME_GEMINI_MODEL = None
_RUNTIME_OLLAMA_MODEL = None
_RUNTIME_GEMINI_KEYS = []         # rotazione impostata da UI (set_gemini_keys)
_GEMINI_KEYS_EXHAUSTED = set()   # key_id esauriti oggi (429 o budget)
_LAST_GEMINI_CALL = 0.0           # timestamp ultima chiamata (pacing RPM)
_RUNTIME_OLLAMA_FALLBACK = None   # override UI: False = niente fallback su Ollama


def set_active_provider(provider: str, api_key: str | None = None,
                        gemini_model: str | None = None,
                        ollama_model: str | None = None):
    """Configura a runtime il provider LLM attivo e i relativi parametri."""
    global _RUNTIME_PROVIDER, _RUNTIME_GEMINI_KEY, _RUNTIME_GEMINI_MODEL, _RUNTIME_OLLAMA_MODEL
    _RUNTIME_PROVIDER = provider.lower() if provider else None
    if api_key is not None:
        _RUNTIME_GEMINI_KEY = api_key.strip()
    if gemini_model is not None:
        _RUNTIME_GEMINI_MODEL = gemini_model.strip()
    if ollama_model is not None:
        _RUNTIME_OLLAMA_MODEL = ollama_model.strip()


def set_gemini_keys(keys):
    """Imposta da UI la lista di chiavi Gemini per la rotazione.
    Lista vuota -> si torna alle chiavi da variabili d'ambiente."""
    global _RUNTIME_GEMINI_KEYS
    _RUNTIME_GEMINI_KEYS = [k.strip() for k in keys if k and k.strip()]


def set_ollama_fallback(enabled: bool):
    """Abilita/disabilita a runtime il fallback automatico su Ollama
    (usato quando il provider attivo e' Gemini e la chiamata fallisce)."""
    global _RUNTIME_OLLAMA_FALLBACK
    _RUNTIME_OLLAMA_FALLBACK = bool(enabled)


def ollama_fallback_enabled() -> bool:
    """True se Ollama puo' essere usato come fallback di Gemini."""
    if _RUNTIME_OLLAMA_FALLBACK is not None:
        return _RUNTIME_OLLAMA_FALLBACK
    return not DISABLE_OLLAMA_FALLBACK


def get_active_provider() -> str:
    """Restituisce il provider corrente ('ollama' o 'gemini')."""
    return (_RUNTIME_PROVIDER or LLM_PROVIDER or "ollama").lower()

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


def _gemini_keys(api_key: str | None = None) -> list[str]:
    """Chiavi attive: param esplicito > lista UI (set_gemini_keys) > env."""
    if api_key and api_key.strip():
        return [api_key.strip()]
    if _RUNTIME_GEMINI_KEYS:
        return list(dict.fromkeys(_RUNTIME_GEMINI_KEYS))
    if _RUNTIME_GEMINI_KEY and _RUNTIME_GEMINI_KEY.strip():
        return [_RUNTIME_GEMINI_KEY.strip()]
    keys = [GEMINI_API_KEY.strip()] if GEMINI_API_KEY.strip() else []
    keys += GEMINI_API_KEYS
    return list(dict.fromkeys(keys))  # dedup preservando l'ordine


def _key_id(key: str) -> str:
    """Id anonimo della chiave per il contatore quota (no leak nei dati)."""
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def gemini_keys_count() -> int:
    """Numero di chiavi Gemini configurate (capacita' giornaliera totale)."""
    return len(_gemini_keys())


def gemini_key_usage() -> list[dict]:
    """Consumo odierno per ogni chiave configurata (vista quota in dashboard)."""
    usage = db.llm_usage_today()
    return [
        {
            "key_id": _key_id(k),
            "tail": k[-4:],
            "calls": usage.get(_key_id(k), 0),
            "exhausted": _key_id(k) in _GEMINI_KEYS_EXHAUSTED,
        }
        for k in _gemini_keys()
    ]


def gemini_available(api_key: str | None = None) -> bool:
    """Verifica se e' configurata una API key per Google Gemini aziendale."""
    return bool(_gemini_keys(api_key))


def is_llm_available(provider: str | None = None, api_key: str | None = None) -> bool:
    """Verifica la disponibilita' del provider LLM selezionato."""
    p = (provider or get_active_provider()).lower()
    if p == "gemini":
        return gemini_available(api_key)
    return ollama_available()


def gemini_quota_exhausted() -> bool:
    """True se TUTTE le chiavi Gemini hanno esaurito il budget giornaliero."""
    keys = _gemini_keys()
    return bool(keys) and all(
        _key_id(k) in _GEMINI_KEYS_EXHAUSTED
        or db.llm_calls_today(_key_id(k)) >= GEMINI_DAILY_LIMIT
        for k in keys)


def _call_gemini_json(system_prompt: str, user_prompt: str,
                      api_key: str | None = None,
                      model: str | None = None,
                      timeout: int | None = None) -> dict | None:
    """Chiamata REST a Google Gemini (Interactions API) con output JSON.
    Rotazione multi-chiave: 429 o budget esaurito su una chiave -> passa alla
    successiva. Il conteggio quota e' per chiave (la quota e' per progetto)."""
    global _LAST_GEMINI_CALL
    mdl = model or _RUNTIME_GEMINI_MODEL or GEMINI_MODEL
    url = GEMINI_API_URL.format(model=mdl)  # no-op se l'URL non contiene {model}
    payload = {
        "model": mdl,
        "input": f"{system_prompt}\n\n{user_prompt}",
        "generation_config": {
            "thinking_level": "minimal",  # scoring JSON: niente reasoning esteso
        },
    }

    for key in _gemini_keys(api_key):
        kid = _key_id(key)
        if kid in _GEMINI_KEYS_EXHAUSTED or db.llm_calls_today(kid) >= GEMINI_DAILY_LIMIT:
            continue
        # Pacing RPM: distanzia le chiamate per restare sotto il limite al minuto
        wait = GEMINI_MIN_INTERVAL - (time.time() - _LAST_GEMINI_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_GEMINI_CALL = time.time()
        db.llm_register_call(kid)  # ogni tentativo consuma quota giornaliera
        try:
            resp = requests.post(
                url,
                params={"key": key},
                headers={"x-goog-api-key": key},
                json=payload,
                timeout=timeout or GEMINI_TIMEOUT,
            )
            if resp.status_code == 429:
                _GEMINI_KEYS_EXHAUSTED.add(kid)
                print(f"[llm] Gemini 429 su chiave ...{key[-4:]}: switch alla successiva", flush=True)
                continue
            if resp.status_code != 200:
                print(f"[llm] Gemini HTTP {resp.status_code}: {resp.text[:300]}", flush=True)
                return None
            data = resp.json()
            texts = [
                part.get("text", "")
                for step in data.get("steps", [])
                if step.get("type") == "model_output"
                for part in step.get("content", [])
                if part.get("type") == "text"
            ]
            raw_text = texts[-1] if texts else ""
            if not raw_text:
                print(f"[llm] Gemini: risposta senza testo: {str(data)[:300]}", flush=True)
                return None
            m = _JSON_RE.search(raw_text)
            return json.loads(m.group(0)) if m else json.loads(raw_text)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
            print(f"[llm] Gemini errore: {type(e).__name__}: {e}", flush=True)
            return None
    return None


def _call_ollama_json(system_prompt: str, user_prompt: str,
                      model: str | None = None,
                      timeout: int | None = None) -> dict | None:
    """Chiamata REST a Ollama locale con formato JSON."""
    mdl = model or _RUNTIME_OLLAMA_MODEL or OLLAMA_MODEL
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": mdl,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=timeout or OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        m = _JSON_RE.search(content)
        return json.loads(m.group(0)) if m else json.loads(content)
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        print(f"[llm] Ollama errore: {type(e).__name__}: {e}", flush=True)
        return None


def generate_json_completion(
    system_prompt: str,
    user_prompt: str,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
) -> tuple[dict | None, str]:
    """Gateway unificato per chiamate LLM in formato JSON.
    
    Ritorna una tupla (dati_json, provider_effettivo).
    Se il provider preferito fallisce, tenta automaticamente l'altro prima di arrendersi.
    """
    p = (provider or get_active_provider()).lower()

    if p == "gemini":
        data = _call_gemini_json(system_prompt, user_prompt, api_key=api_key, model=model, timeout=timeout)
        if data is not None:
            return data, "gemini"
        # Fallback automatico a Ollama se disponibile e non disabilitato
        if not ollama_fallback_enabled():
            print("[llm] Gemini non riuscito; fallback Ollama disabilitato",
                  flush=True)
        elif ollama_available():
            print("[llm] Gemini non riuscito -> fallback su Ollama", flush=True)
            data = _call_ollama_json(system_prompt, user_prompt, model=model, timeout=timeout)
            if data is not None:
                return data, "ollama"
        return None, "failed"
    else:
        data = _call_ollama_json(system_prompt, user_prompt, model=model, timeout=timeout)
        if data is not None:
            return data, "ollama"
        # Fallback automatico a Gemini se configurato
        if gemini_available(api_key):
            print("[llm] Ollama non riuscito -> fallback su Gemini", flush=True)
            data = _call_gemini_json(system_prompt, user_prompt, api_key=api_key, model=model, timeout=timeout)
            if data is not None:
                return data, "gemini"
        return None, "failed"


def _score_llm(title: str, text: str, country_hint: str | None = None,
               provider: str | None = None) -> dict | None:
    prompt = f"TITOLO: {title}\nPAESE_SUGGERITO: {country_hint or 'sconosciuto'}\n\nTESTO:\n{text[:2500]}"
    data, scored_by = generate_json_completion(SYSTEM_PROMPT, prompt, provider=provider)
    if not data:
        return None

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
        "scored_by": scored_by,
    }


def _score_ollama(title: str, text: str, country_hint: str | None = None) -> dict | None:
    """Compatibilita' retroattiva con codice esistente."""
    return _score_llm(title, text, country_hint, provider="ollama")


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


def heuristic_prescore(title: str, text: str, country_hint: str | None = None) -> int:
    """Score euristico rapido (nessuna chiamata LLM) per ordinare la coda."""
    return _score_heuristic(title, text, country_hint).get("score", 0)


def score_opportunity(title: str, text: str, country_hint: str | None = None,
                      provider: str | None = None) -> dict:
    """Scoring con LLM (Ollama o Gemini) se disponibile, altrimenti euristico.

    Ottimizzazione CPU: se l'euristica identifica subito l'articolo come rumore
    (cronaca, polemiche, nessun intent commerciale - score 0), scarta direttamente
    senza interpellare l'LLM, risparmiando tempo e chiamate.
    """
    quick = _score_heuristic(title, text, country_hint)
    if quick.get("score", 0) == 0 and quick.get("scored_by") == "heuristic_filtered":
        return quick

    result = _score_llm(title, text, country_hint, provider=provider)
    return result if result else quick


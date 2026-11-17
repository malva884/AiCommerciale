"""Configurazione centrale dell'agente B2B per cavi speciali (Fibra & Rame).
Settori: Data Center, Telecom/Provider, Ferroviario, Navale, Avio/Aerospaziale.
Mercato: Europa (con suddivisione per Area Manager).
"""
import os


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path: str):
    """Loader .env minimale (no dipendenze): KEY=VALUE per riga, ignora # e vuote.
    Valori non vuoti sovrascrivono l'env: questo file contiene SOLO le
    impostazioni salvate esplicitamente dalla dashboard (chiavi, provider)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v:
                    os.environ[k] = v
    except OSError:
        pass


# .env legacy (sviluppo locale / Coolify env-file). Le impostazioni salvate
# dalla UI vivono nella tabella app_settings del DB, non qui.
_load_dotenv(os.path.join(_BASE_DIR, ".env"))

# --- Configurazione Provider LLM (Ollama locale o Gemini aziendale) ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()  # "ollama" | "gemini"

# --- LLM locale (Ollama) ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")  # alternativa piu' leggera: "mistral:7b"
OLLAMA_TIMEOUT = 120              # secondi per risposta
# Se "1", Ollama NON viene usato come fallback quando Gemini non funziona
DISABLE_OLLAMA_FALLBACK = os.environ.get(
    "DISABLE_OLLAMA_FALLBACK", "0").strip().lower() in ("1", "true", "yes")

# --- LLM cloud aziendale (Google Gemini) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Rotazione multi-chiave: elenco aggiuntivo separato da virgole (quota per progetto)
GEMINI_API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")  # es: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.6-flash
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "60"))       # secondi per risposta
# Interactions API (nuova API Gemini; l'endpoint generateContent e' legacy)
GEMINI_API_URL = os.environ.get(
    "GEMINI_API_URL",
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)
# Quota giornaliera Gemini (free tier ~500 RPD / ~15 RPM per modello)
GEMINI_DAILY_LIMIT = int(os.environ.get("GEMINI_DAILY_LIMIT", "450"))      # margine di sicurezza
GEMINI_MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL", "4.5"))  # sec tra chiamate

# --- Scoring a due stadi: Batch Triage + Deep-Dive ---
LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", "15"))                  # item per chiamata triage
BATCH_SCORE_THRESHOLD = int(os.environ.get("BATCH_SCORE_THRESHOLD", "80"))    # score min per accedere al deep-dive
BATCH_SNIPPET_MAX_CHARS = int(os.environ.get("BATCH_SNIPPET_MAX_CHARS", "250"))  # testo inviato al triage
BATCH_DEEP_DIVE_RESERVE = int(os.environ.get("BATCH_DEEP_DIVE_RESERVE", "30"))   # quota riservata al deep-dive
# Modello per il triage batch; vuoto = stesso GEMINI_MODEL dello scoring
GEMINI_BATCH_MODEL = os.environ.get("GEMINI_BATCH_MODEL", "")

# --- Profilo aziendale e settori target ---
AZIENDA = (
    "Produttore europeo di cavi speciali in fibra ottica e rame. "
    "Modello di vendita: FORNITORE B2B - il cliente potenziale e' l'azienda che "
    "vince o realizza commesse (prime contractor, OEM, EPC, system integrator), "
    "non l'ente pubblico appaltante. "
    "Settori core:\n"
    "1. Data Center: cavi alta densita' (MPO/MTP, OM4/OM5, Cat 8), CPR B2ca-s1a,d0.\n"
    "2. Telecom/Provider: cavi posa aerea, interrata, micro-cavi FTTH, backhauling 5G e cavi rame LAN Cat 6A/7/8 per reti dati.\n"
    "3. Ferroviario: standard EN 45545-2 (HL1/HL2/HL3), EN 50306/50355/50264, LSZH, cavi rame e fibra per materiale rotabile, segnalamento ed ERTMS.\n"
    "4. Navale & Offshore: certificazioni RINA, DNV, Bureau Veritas, Lloyd's Register.\n"
    "5. Avio & Difesa: standard MIL-DTL, norme EN aerospaziali, cavi leggeri PTFE/ETFE."
)

# --- Settori target canonici a 5 verticali (usati da LLM, euristica e dashboard) ---
SECTORS = ["Data Center", "Telecom/Provider", "Ferroviario",
           "Navale/Offshore", "Avio/Difesa", "Altro"]

# Etichette legacy presenti nel DB / prodotte da LLM -> nome canonico.
SECTOR_NORMALIZATION = {
    "Navale": "Navale/Offshore",
    "Navale & Offshore": "Navale/Offshore",
    "Navale e Offshore": "Navale/Offshore",
}

# Verticali ammessi nelle notifiche push ('Altro' escluso: anti-rumore).
NOTIFY_SECTORS = [s for s in SECTORS if s != "Altro"]


def normalize_sector(sector) -> str:
    """Riporta un'etichetta di settore al nome canonico (es. 'Navale' ->
    'Navale/Offshore'). None/ignoti -> 'Altro'."""
    if not sector:
        return "Altro"
    s = str(sector).strip()
    return SECTOR_NORMALIZATION.get(s, s if s in SECTORS else "Altro")

# --- Aree geografiche e Area Manager ---
AREA_MAPPING = {
    "DACH": ["DEU", "AUT", "CHE"],
    "IBERIA": ["ESP", "PRT"],
    "FRANCE": ["FRA", "BEL", "LUX"],
    "ITALY": ["ITA"],
    "NORDICS": ["SWE", "DNK", "FIN", "NOR"],
    "UK_IE": ["GBR", "IRL"],
    "CEE": ["POL", "CZE", "SVK", "HUN", "ROU", "BGR", "HRV", "SVN", "GRC", "LTU", "LVA", "EST"],
}

COUNTRY_TO_AREA = {}
for area, countries in AREA_MAPPING.items():
    for c in countries:
        COUNTRY_TO_AREA[c] = area

# --- Freschezza segnali: scarta notizie/bandi troppo vecchi alla fonte ---
NEWS_RECENCY_DAYS = int(os.environ.get("NEWS_RECENCY_DAYS", "14"))        # when:Nd nel feed Google News
MAX_SIGNAL_AGE_DAYS = int(os.environ.get("MAX_SIGNAL_AGE_DAYS", "45"))    # oltre -> record scartato pre-insert

# --- Google News RSS (fonti pubbliche scouting) ---
NEWS_EDITIONS = [
    {
        "lang": "it", "country": "IT",
        "queries": [
            "appalto cavi fibra ottica",
            "gara fornitura cavi fibra ottica",
            "bando cablaggio data center",
            "nuovo data center Italia",
            "RFI gara cavi segnalamento",
            "rete ferroviaria appalto cavi",
            "Fincantieri fornitura cavi navali",
            "rollout fibra ottica provider",
            "PNRR banda larga appalto",
            "aggiudicatario appalto cavi",
            "Leonardo commessa",
            "Fincantieri commessa",
            "Hitachi Rail contratto",
            "Alstom consegna treni",
            "vince commessa difesa",
            "gara fornitura cavi rame",
            "appalto cablaggio strutturato",
            "bando cavi dati rete LAN",
            "RFI appalto segnalamento",
            "gara ERTMS",
            "metropolitana appalto cavi",
            "Stadler ordine treni",
            "CAF commessa treni",
            "Trenitalia ordine materiale rotabile",
            "cavi resistenti al fuoco gara",
        ],
    },
    {
        "lang": "en", "country": "GB",
        "queries": [
            "fibre optic cable tender Europe",
            "data center construction Europe hyperscale",
            "FTTH rollout contract award Europe",
            "railway signalling cable tender EN 45545",
            "naval shipyard cable supply contract",
            "subsea power telecom cable contract",
            "data centre campus Frankfurt Milan Paris Dublin",
            "5G backhaul fibre network deployment",
            "aerospace defense wiring harness contract",
            "copper data cable tender",
            "contract awarded cable manufacturer",
            "Leonardo contract win",
            "Hitachi Rail wins contract",
            "Fincantieri awarded contract",
            "defence vehicle contract awarded Europe",
            "data center developer announces Europe",
            "copper cable supply contract",
            "copper cabling tender Europe",
            "LAN cable contract award",
            "structured cabling contract",
            "railway signalling contract award",
            "ERTMS contract Europe",
            "rolling stock contract awarded",
            "Stadler wins contract",
            "CAF wins contract",
            "metro line construction contract",
            "fire resistant cable tender",
            "railway cable supply",
        ],
    },
]
MAX_NEWS_PER_QUERY = 15

# --- TED - Tenders Electronic Daily (gare UE) ---
TED_API_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_COUNTRIES = list(COUNTRY_TO_AREA.keys())
# CPV Cavi Isolati, Reti, Cavi Telecomunicazione, Cablaggio
TED_CPV_CODES = [
    "31300000",  # Fili e cavi isolati
    "31310000",  # Cavi di comunicazione e accessori
    "31311000",  # Cavi telefonici
    "31320000",  # Cavi di distribuzione elettrica
    "31330000",  # Cavi coassiali
    "31340000",  # Cavi speciali
    "31350000",  # Cavi elettrici schermati
    "32562000",  # Cavi a fibre ottiche
    "34934000",  # Attrezzatura di comando, controllo, comunicazione e segnalamento
    "45314300",  # Installazione di infrastrutture di cablaggio
]
TED_KEYWORDS = [
    "fibre optic cable", "optical fibre", "data cable",
    "telecommunications cable", "cabling", "EN 45545",
    "CPR B2ca", "RINA", "DNV",
    "copper cable", "copper cabling", "LAN cable", "twisted pair",
    "coaxial cable", "railway cable", "rolling stock", "signalling",
    "ERTMS", "EN 50306", "EN 50264", "EN 50200",
    "fire resistant cable", "structured cabling", "EN 50173",
    "halogen-free cable",
]
TED_MAX_RESULTS = 100

# --- Scoring euristico (fallback quando Ollama non e' disponibile) ---
KEYWORD_SCORE = {
    # Tipologia
    "appalto": 25, "gara": 25, "bando": 20, "fornitura": 20, "tender": 25, "contract award": 30,
    # Aggiudicazioni / commesse -> vendita al vincitore
    "aggiudicat": 30, "wins contract": 35, "awarded": 25, "secures": 20,
    "signs contract": 35, "framework agreement": 30, "supply contract": 30,
    "commessa": 20, "subcontract": 25, "contract win": 35,
    # Prodotti
    "fibra ottica": 35, "fibre ottiche": 35, "fibre optic": 35, "optical fibre": 35, "optical-fibre": 35,
    "cavi": 20, "cable": 15, "cabling": 20, "cablaggio": 20, "copper cable": 20, "rame": 15,
    "copper": 20, "cavo dati": 20, "cavi dati": 20, "lan cable": 20, "lan cabling": 20,
    "twisted pair": 20, "cat 6": 15, "cat 7": 20, "cat 8": 25, "coassial": 20,
    "structured cabling": 20, "cablaggio strutturato": 20,
    "electrical cable": 15, "power cable": 15, "cavi elettrici": 15,
    # Normative / Specifiche chiave
    "en 45545": 40, "cpr": 30, "b2ca": 35, "lszh": 25, "rina": 30, "dnv": 30, "mil-dtl": 35,
    "en 50306": 40, "en 50355": 40, "en 50264": 40, "en 50200": 35,
    "en 60331": 30, "iec 60331": 30, "iec 60332": 30, "en 61034": 30, "en 50173": 35,
    "halogen-free": 25, "senza alogeni": 25, "fire resistant": 25,
    "resistenti al fuoco": 25, "resistente al fuoco": 25,
    # Settori
    "data center": 30, "datacenter": 30, "hyperscale": 30,
    "ferroviari": 25, "railway": 25, "rfi": 25, "alstom": 20, "siemens mobility": 20,
    "rolling stock": 30, "materiale rotabile": 30, "rotabili": 25, "segnalamento": 30,
    "signalling": 25, "ertms": 30, "etcs": 25, "catenaria": 20, "catenary": 20,
    "metropolitana": 20, "metro line": 15, "tram": 15, "tramway": 15,
    "trenitalia": 20, "sncf": 20, "deutsche bahn": 20, "renfe": 20, "network rail": 20,
    "navale": 25, "shipyard": 25, "fincantieri": 25,
    "telecom": 15, "provider": 10, "5g": 20, "ftth": 25, "backhaul": 20, "pnrr": 20,
    "aerospace": 25, "difesa": 20, "defense": 20, "subsea": 25,
    # Prime contractor / OEM (potenziali clienti)
    "leonardo": 25, "hitachi rail": 25, "fincantieri": 25, "stadler": 20,
    "thales": 20, "saab": 20, "rheinmetall": 20, "navantia": 20,
    "hensoldt": 20, "talgo": 15, "babcock": 15, "ansaldo": 15, "equinix": 15,
    "siemens": 15, "hitachi": 20, "webuild": 20, "pizzarotti": 15, "ghella": 15,
}

# --- Motore euristico anti-rumore a 4 livelli (pre-filtro triage) ---
# Il prescore decide l'ordine di invio al Triage Gemini e, sotto soglia,
# lo scarto deterministico senza consumare quota LLM.

# Livello 1: valore base per fonte (il segnale migliore e' chi deve comprare)
SOURCE_BASE_SCORE = {
    "ted_award": 35,   # aggiudicazione UE: vincitore certo che compra i cavi
    "crm": 30,         # segnale interno ERP (churn / cross-sell)
    "ted": 15,         # bando attivo UE
    "news": 5,         # Google News RSS: fonte rumorosa, si guadagna il punteggio
}

# Livello 2: dizionario pesato positivo (IT/EN/DE/FR/ES)
POSITIVE_KEYWORDS = {
    # +25: Specifiche cavi speciali & normative (alta marginalita')
    "fire resistant": 25, "resistente al fuoco": 25, "resistenti al fuoco": 25,
    "lszh": 25, "low smoke": 25, "armored": 25, "armato": 25,
    "sottomarino": 25, "submarine": 25, "subsea": 25, "umbilical": 25,
    "ibrido": 25, "hybrid cable": 25, "fibra ottica": 25, "fiber optic": 25,
    "optical fiber": 25, "instrumentation cable": 25, "cavi strumentazione": 25,
    "cavi controllo": 25, "control cable": 25, "rolling stock": 25,
    "materiale rotabile": 25,
    "en 45545": 25, "iec 60331": 25, "iec 60332": 25, "cpr b2ca": 25,
    "cpr c2": 25, "dnv": 25, "rina": 25, "bureau veritas": 25, "lloyd": 25,
    "atex": 25, "mil-dtl": 25,
    # +20: Trigger commerciali di commessa
    "aggiudica": 20, "aggiudicato": 20, "contract award": 20,
    "awarded contract": 20, "awarded": 20, "commessa": 20, "lotto": 20,
    "appalto integrato": 20, "epc": 20, "turnkey": 20, "chiavi in mano": 20,
    "revamping": 20, "ammodernamento": 20, "elettrificazione": 20,
    "segnalamento": 20, "ertms": 20, "etcs": 20, "ftth": 20,
    "backbone": 20, "hyperscale": 20, "data center": 20, "datacenter": 20,
    # +15: Prime contractor & target B2B
    "fincantieri": 15, "leonardo": 15, "alstom": 15, "hitachi rail": 15,
    "stadler": 15, "siemens mobility": 15, "caf": 15, "waberer": 15,
    "saipem": 15, "snam": 15, "terna": 15, "rfi": 15,
    "rete ferroviaria": 15, "chantiers de l'atlantique": 15, "navantia": 15,
    "thyssenkrupp": 15, "balfour beatty": 15, "vinci energies": 15,
    "bouygues": 15, "strabag": 15, "webuild": 15, "open fiber": 15,
    "fibercop": 15, "equinix": 15, "digital realty": 15,
}

# Livello 4: malus anti-rumore (possono portare il prescore sotto zero)
NEGATIVE_KEYWORDS = {
    # -50: Finanza, sindacati, cronaca
    "borsa": -50, "azioni": -50, "dividendo": -50, "trimestrale": -50,
    "semestrale": -50, "bilancio": -50, "ebitda": -50, "rating": -50,
    "sciopero": -50, "sindacati": -50, "cassa integrazione": -50,
    "inchiesta": -50, "procura": -50, "sequestro": -50, "incidente": -50,
    "guasto": -50, "ritardi treni": -50, "biglietti": -50,
    "orario estivo": -50, "assunzioni": -50, "concorso pubblico": -50,
    # -35: Cavi civili standard / bassa marginalita'
    "fs17": -35, "fg16": -35, "n07v-k": -35, "h07v-k": -35,
    "impianto elettrico civile": -35, "illuminazione pubblica": -35,
    "cavi bassa tensione standard": -35, "prolunga": -35,
    "cavo ricarica ev": -35, "colonnine ricarica": -35, "domotica": -35,
}

# -40 extra-UE: applicato solo se NON co-occorre un player europeo
EXTRA_EU_TERMS = ("usa", "stati uniti", "cina", "india", "australia",
                  "giappone", "brasile")
EXTRA_EU_PENALTY = -40
EU_PLAYER_GUARD = ("fincantieri", "leonardo", "alstom", "prysmian")

# Livello 3: bonus co-occorrenza Settore/Player x Evento di commessa
COMBO_ACTORS = ("ferrovi", "railway", "treno", "train", "metro", "navale",
                "shipbuilding", "fregata", "offshore", "data center", "fibra",
                "rfi", "fincantieri", "alstom", "hitachi", "stadler", "siemens")
COMBO_TRIGGERS = ("aggiudic", "award", "commess", "contratto", "contract",
                  "fornitura", "supply", "costruzione", "construction",
                  "posa", "installation")
COMBO_BONUS = 25

# Soglia di pre-scarto deterministico: prescore <= soglia -> DISCARDED
# senza invio al Triage Gemini (scored_by='heuristic_filter').
HEURISTIC_HARD_DISCARD = -10

# --- Notifiche email mattutine (digest commerciale Lun-Ven) ---
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip().lower() in ("1", "true", "yes")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_SENDER = os.environ.get("SMTP_SENDER", "noreply@metallurgicabresciana.it")

# URL pubblico della dashboard Streamlit (link diretto schede nelle email)
DASHBOARD_BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8501")

# Logo aziendale allegato CID nelle email digest (PNG/JPG; vuoto = nessun logo)
COMPANY_LOGO_PATH = os.environ.get(
    "COMPANY_LOGO_PATH",
    os.path.join(_BASE_DIR, "assets", "mb_logo.png"))

# Orario invio digest (formato HH:MM, lunedi-venerdi')
MORNING_REPORT_TIME = os.environ.get("MORNING_REPORT_TIME", "08:00")

# Regole di routing di fallback se app_settings.notification_routing_json
# non e' configurato: la UI le riscrive in app_settings al primo salvataggio.
DEFAULT_NOTIFICATION_ROUTING = [
    {
        "id": "rule_1",
        "active": True,
        "recipient_name": "Responsabile Ferroviario",
        "recipient_email": "ferroviario@metallurgicabresciana.it",
        "sectors": ["Ferroviario"],
        "areas": ["ITALY", "DACH", "FRANCE"],
        "min_score": 80,
        "max_items_per_sector": 3,
        "include_crm_alerts": True,
    },
    {
        "id": "rule_2",
        "active": True,
        "recipient_name": "Divisione Navale & Difesa",
        "recipient_email": "navale@metallurgicabresciana.it",
        "sectors": ["Navale/Offshore", "Avio/Difesa"],
        "areas": ["*"],
        "min_score": 80,
        "max_items_per_sector": 3,
        "include_crm_alerts": True,
    },
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "opportunita.db")

# --- Connessione SQL Server ERP (Sola Lettura) ---
# Ripresa dalla configurazione del progetto ARGUS
SQLSERVER_HOST = os.environ.get("SQLSERVER_HOST", "10.141.1.8")
SQLSERVER_PORT = int(os.environ.get("SQLSERVER_PORT", "1433"))
SQLSERVER_DB = os.environ.get("SQLSERVER_DB", "GP_NX_AGG")
SQLSERVER_USER = os.environ.get("SQLSERVER_USER", "GPSCH")
SQLSERVER_PWD = os.environ.get("SQLSERVER_PWD", "")
SQLSERVER_DRIVER = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server")
SQLSERVER_DB_URL = os.environ.get(
    "SQLSERVER_DB_URL",
    f"mssql+pyodbc://{SQLSERVER_USER}:{SQLSERVER_PWD}@{SQLSERVER_HOST}:{SQLSERVER_PORT}/{SQLSERVER_DB}?driver={SQLSERVER_DRIVER.replace(' ', '+')}&TrustServerCertificate=yes"
)

# Mappatura codici materiale ERP -> Categoria commerciale
MATERIAL_CATEGORY_MAP = {
    "20": "Fibra Ottica",
    "41": "Rame",
}

# --- Data Masking / Anonimizzazione per chiamate LLM cloud ---

# Fasce di fatturato per bucketing privacy (soglia inferiore inclusa, EUR).
# Ordinato dalla fascia piu' alta alla piu' bassa.
REVENUE_TIERS = [
    (250_000, "Tier A (> 250k EUR)"),
    (50_000, "Tier B (50k-250k EUR)"),
    (0, "Tier C (< 50k EUR)"),
]

# Transcodifica prefissi codici articolo interni (ERP GP_NX_AGG) ->
# macro-famiglia tecnica. I prefissi piu' lunghi hanno priorita' nel match.
SKU_FAMILY_MAP = {
    "FO-ARM": "Cavi in fibra ottica armati per posa interrata/galleria",
    "FO-MICRO": "Microcavi in fibra ottica 200um per soffiatura in minitubo",
    "FO-DROP": "Cavi di allacciamento FTTH (drop) CPR B2ca/Cca",
    "FO-ADSS": "Cavi ottici autoportanti per posa aerea (ADSS)",
    "FO-MP": "Dorsali e bretelle MPO/MTP ad alta densita' per Data Center",
    "FO": "Cavi in fibra ottica",
    "CU-DATA": "Cavi dati rame schermati Cat.6A/7/8",
    "CU-EN": "Cavi energia bassa tensione resistenti al fuoco",
    "CU": "Cavi in rame",
    "RAIL": "Cavi segnalamento e rotabili ferroviari EN 45545-2/EN 50306",
    "MAR": "Cavi navali omologati RINA/DNV mud-resistant",
    "AVIO": "Cavi speciali avio/difesa alta temperatura",
}
SKU_FAMILY_FALLBACK = "Famiglia cavi speciali"

# --- Company Intelligence 360 (Dossier on-demand + Contact Monitoring) ---

# Search API esterna (Tavily o Serper.dev) per news/progetti/dati societari.
# Chiavi: app_settings (UI) > env. Provider selezionabile da UI.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "tavily").lower()  # tavily | serper

# Crawler dossier aziendale
CI_MAX_PAGES = int(os.environ.get("CI_MAX_PAGES", "10"))           # pagine strategiche max
CI_MAX_CHARS = int(os.environ.get("CI_MAX_CHARS", "12000"))        # testo totale per LLM
CI_HTTP_TIMEOUT = int(os.environ.get("CI_HTTP_TIMEOUT", "12"))     # sec per richiesta
CI_TED_MONTHS = int(os.environ.get("CI_TED_MONTHS", "24"))         # storico aggiudicazioni

# Job Change Monitoring: cadenza verifica referenti (giorni)
CONTACT_MONITOR_DAYS_TOP = int(os.environ.get("CONTACT_MONITOR_DAYS_TOP", "15"))
CONTACT_MONITOR_DAYS_DEFAULT = int(os.environ.get("CONTACT_MONITOR_DAYS_DEFAULT", "30"))
# Match score prospect o flag ERP che promuove l'azienda a "top" (check 15 gg)
CONTACT_MONITOR_TOP_SCORE = int(os.environ.get("CONTACT_MONITOR_TOP_SCORE", "65"))

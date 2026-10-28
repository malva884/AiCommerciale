"""Configurazione centrale dell'agente B2B per cavi speciali (Fibra & Rame).
Settori: Data Center, Telecom/Provider, Ferroviario, Navale, Avio/Aerospaziale.
Mercato: Europa (con suddivisione per Area Manager).
"""
import os

# --- LLM locale (Ollama) ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")  # alternativa piu' leggera: "mistral:7b"
OLLAMA_TIMEOUT = 120              # secondi per risposta

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

# --- Settori target (usati da LLM, euristica e dashboard) ---
SECTORS = ["Data Center", "Telecom/Provider", "Ferroviario", "Navale", "Avio/Difesa", "Altro"]

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

DB_PATH = "data/opportunita.db"

# --- Connessione SQL Server ERP (Sola Lettura) ---
# Ripresa dalla configurazione del progetto ARGUS
SQLSERVER_HOST = os.environ.get("SQLSERVER_HOST", "10.141.1.8")
SQLSERVER_PORT = int(os.environ.get("SQLSERVER_PORT", "1433"))
SQLSERVER_DB = os.environ.get("SQLSERVER_DB", "GP_NX_AGG")
SQLSERVER_USER = os.environ.get("SQLSERVER_USER", "GPSCH")
SQLSERVER_PWD = os.environ.get("SQLSERVER_PWD", "GPSCH")
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

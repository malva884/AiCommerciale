# Agente Opportunita' Commerciali

Agente locale che raccoglie segnali pubblici (gare d'appalto UE, aggiudicazioni,
news su data center / ferroviario / fibra) e li valuta come opportunita' di
nuovi ordini per un produttore di cavi in fibra ottica e rame. Include
analisi CRM sullo storico ordini ERP, prospecting lookalike europeo e
generazione AI di materiale commerciale (dossier, outreach, analisi RFP).

## Logica operativa dell'agente

### Pipeline di scouting (`main.py`)

1. **Fetch** — raccolta da 3 fonti in sequenza:
   - Google News RSS (`fetchers/news.py`): query IT/EN su appalti, commesse e
     prime contractor (RFI, Fincantieri, Hitachi Rail, Stadler, ecc.).
   - Bandi TED attivi (`fetchers/ted.py`): gare UE filtrate per codici CPV
     cavi e keyword tecniche (richiede `TED_API_KEY`).
   - Aggiudicazioni TED (`fetchers/ted_awards.py`): contract award notices.
     Logica B2B: **il vincitore della commessa e' il cliente potenziale** —
     chi si aggiudica l'appalto dovra' comprare i cavi per realizzarlo.
2. **Dedup & persistenza** — inserimento in SQLite (`data/opportunita.db`),
   i duplicati vengono scartati.
3. **Scoring AI** — per ogni opportunita' il modello assegna score, settore,
   area manager, normative rilevate e una bozza email commerciale.

### Logiche decisionali di scoring (`llm.py`, `main.py`)

- **Provider a cascata**: Gemini (cloud) oppure Ollama (locale); se il
  provider attivo non risponde, si passa all'altro e infine al **fallback
  euristico** deterministico su parole chiave (`config.KEYWORD_SCORE`).
- **Budget Gemini**: con provider Gemini gli item sono ordinati per
  *prescore euristico* decrescente: la quota giornaliera va ai candidati
  piu' promettenti. Gli item gia' valutati solo con euristica
  (`include_heuristic`) vengono rimessi in coda per lo scoring LLM al run
  successivo.
- **Quota e pacing**: chiamate conteggiate in SQLite; stop a
  `GEMINI_DAILY_LIMIT` (default 450/giorno per chiave) e distanza minima
  `GEMINI_MIN_INTERVAL` (default 4.5s) tra chiamate. Piu' chiavi in
  rotazione (`GEMINI_API_KEYS`): switch automatico alla saturazione. NB: la
  quota e' per *progetto* Google Cloud.
- **Profilo commerciale** (`config.AZIENDA`): l'agente ragiona come fornitore
  B2B — il cliente e' il prime contractor/OEM/EPC/system integrator che
  realizza la commessa, non l'ente appaltante. Settori: Data Center,
  Telecom/Provider, Ferroviario, Navale, Avio/Difesa. Le opportunita' sono
  assegnate all'Area Manager tramite `AREA_MAPPING` (DACH, IBERIA, FRANCE,
  ITALY, NORDICS, UK_IE, CEE).

### Funzioni commerciali aggiuntive

- **CRM & Retention** (`crm_analyzer.py`, `sqlserver_orders.py`): lettura
  diretta SQL Server ERP (`GP_NX_AGG`, sola lettura) o CSV. Calcola MTBO
  (Mean Time Between Orders), stato churn (Regolare / In ritardo / Rischio
  churn / Dormiente / Unico ordine) e opportunita' di cross-sell
  fibra/rame/accessori.
- **Lookalike Prospecting** (`prospecting_engine.py`): database di prospect
  europei "clienti gemelli" (installatori FTTH, contractor ferroviari,
  cantieri navali, EPC data center) con cavi target, buyer roles e query
  LinkedIn; matching arricchito dai dati ordini.
- **Outreach AI multilingua** (`prospecting_engine.py`): bozze email,
  messaggi LinkedIn e script cold call in IT/EN/FR/DE via LLM con fallback
  template.
- **RFP Analyzer** (`rfp_analyzer.py`): estrae da un capitolato incollato
  normative richieste, specifiche cavi, livello di match produttivo e
  domande di chiarimento per il buyer.
- **Account Dossier** (`account_research.py`): dossier pre-meeting con
  posizionamento, sfide, buying signals e stakeholder raccomandati.
- **Enrichment aziende** (`company_enrich.py`): fatturato, dipendenti,
  crescita YoY da Wikidata (CC0, senza API key).
- **Ricerca referenti** (`contact_finder.py`): decision maker procurement/
  buyer via Apollo.io o Proxycurl (chiave API configurabile da UI; senza
  chiave resta il link di ricerca LinkedIn manuale).

### Scheduler notturno (`scheduler.py`)

Worker Docker dedicato (servizio `scheduler` in `docker-compose.yml`):
esegue la pipeline ogni notte all'ora `NIGHTLY_SCHEDULE_TIME` (default
01:00), rilegge le impostazioni Motore AI salvate dalla dashboard in
`app_settings` (priorita' DB > env > default) e, a DB vuoto, esegue un primo
popolamento all'avvio (`RUN_ON_STARTUP_IF_EMPTY`). Lock anti-sovrapposizione
e logging errori nello storico errori.

### Motore AI (LLM)

Supporto ibrido flessibile:
- **Locale (Ollama)**: 100% on-premise e privacy (`llama3.1:8b`, `mistral:7b`).
- **Cloud Aziendale (Google Gemini)**: massima accuratezza e velocita'
  (`gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`).
- **Fallback Euristico**: parole chiave e scoring deterministico se nessun
  LLM e' online.

La scelta del provider puo' essere effettuata:
1. Dalla sezione **AI & Agenti** della dashboard (**Motore AI**), inserendo
   una o piu' chiavi Gemini (rotazione con contatore d'uso per chiave) o
   selezionando Ollama. Le impostazioni sono persistite in `app_settings`
   nel DB e recepite anche dallo scheduler senza restart.
2. Tramite variabili d'ambiente (`LLM_PROVIDER=gemini` o `LLM_PROVIDER=ollama`,
   `GEMINI_API_KEY="chiave"`).

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Opzione A: LLM Locale (Ollama)

```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
```

### Opzione B: Gemini Aziendale (Google AI Studio / Vertex AI)

Impostare la chiave API nell'ambiente o direttamente nel pannello della
dashboard:

```powershell
setx GEMINI_API_KEY "la-tua-api-key"
setx LLM_PROVIDER "gemini"
```

Quota Gemini (free tier ~500 RPD / ~15 RPM per modello): le chiamate sono
conteggiate in SQLite e la pipeline si ferma a `GEMINI_DAILY_LIMIT` (default
450); gli scoring rimasti sono rinviati al run successivo. `GEMINI_MIN_INTERVAL`
(default 4.5s) distanzia le chiamate per restare sotto il limite al minuto.
Piu' chiavi in rotazione con `GEMINI_API_KEYS="k1,k2,k3"`: quando una satura,
lo switch alla successiva e' automatico. NB: la quota e' per *progetto* Google
Cloud — solo chiavi di progetti diversi aumentano il budget totale.

TED (opzionale, per gare e aggiudicazioni UE): API key gratuita su
<https://ted.europa.eu>, poi `setx TED_API_KEY "la-chiave"` e riaprire
il terminale.

SQL Server ERP (opzionale, per CRM/Retention): `SQLSERVER_HOST`,
`SQLSERVER_PORT`, `SQLSERVER_DB` (default `GP_NX_AGG`), `SQLSERVER_USER`,
`SQLSERVER_PWD`, `SQLSERVER_DRIVER`.

Ricerca referenti (opzionale): `CONTACT_PROVIDER` (`apollo`|`proxycurl`) con
`APOLLO_API_KEY` o `PROXYCURL_API_KEY` — configurabile anche dalla dashboard.

## Uso

```powershell
.\.venv\Scripts\python.exe main.py          # fetch + scoring (manuale)
.\.venv\Scripts\streamlit.exe run app.py    # dashboard
```

### Deploy Docker (app + scheduler notturno + Ollama)

```powershell
docker compose up -d --build
```

Il compose avvia 3 servizi: `app` (Streamlit su :8501), `scheduler`
(pipeline notturna) e `ollama` con pull automatico del modello
(`ollama-init`). Il DB SQLite e' sul volume condiviso `app_data`.

## Struttura

- `config.py` - profilo azienda, query news, CPV/keyword TED, soglie keyword,
  aree geografiche, parametri LLM e connessione SQL Server
- `main.py` - pipeline fetch -> dedup -> scoring
- `scheduler.py` - worker notturno della pipeline (Docker)
- `fetchers/news.py` - Google News RSS
- `fetchers/ted.py` - bandi TED attivi (richiede API key)
- `fetchers/ted_awards.py` - aggiudicazioni TED (winner = cliente potenziale)
- `llm.py` - provider Ollama/Gemini, rotazione chiavi, fallback euristico
- `db.py` - storage SQLite (`data/opportunita.db`), app_settings, error_log
- `app.py` - dashboard Streamlit (sezioni: Panoramica, Opportunita' & News,
  Documenti & Capitolati, Account Dossier, Processi & CRM, Analisi & New
  Business, AI & Agenti)
- `ui_style.py` - tema e componenti UI della dashboard
- `sqlserver_orders.py` - connettore read-only allo storico ordini ERP
- `crm_analyzer.py` - MTBO, churn e cross-selling
- `prospecting_engine.py` - prospect lookalike UE e outreach AI multilingua
- `rfp_analyzer.py` - analisi capitolati/RFP
- `account_research.py` - dossier pre-meeting
- `company_enrich.py` - enrichment dati aziendali da Wikidata
- `contact_finder.py` - ricerca decision maker (Apollo/Proxycurl)

## Roadmap fase 2

- Fonti extra: ANAC, portali RFI/Fincantieri diretti
- Export email report delle opportunita' top-score
- Notifiche proattive su clienti a rischio churn

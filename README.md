# Agente Opportunita' Commerciali

Agente locale che raccoglie segnali pubblici (gare d'appalto UE, news su
data center / ferroviario / fibra) e li valuta come opportunita' di nuovi
ordini per un produttore di cavi in fibra ottica e rame.

**Motore AI (LLM)**: Supporto ibrido flessibile:
- **Locale (Ollama)**: 100% on-premise e privacy (`llama3.1:8b`, `mistral:7b`).
- **Cloud Aziendale (Google Gemini)**: massima accuratezza e velocità (`gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`).
- **Fallback Euristico**: parole chiave e scoring deterministico se nessun LLM è online.

La scelta del provider può essere effettuata:
1. Direttamente dall'interfaccia Streamlit nella sidebar (**🧠 Motore AI**), inserendo la chiave Gemini o selezionando Ollama.
2. Tramite variabili d'ambiente (`LLM_PROVIDER=gemini` o `LLM_PROVIDER=ollama`, e `GEMINI_API_KEY="chiave"`).

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

Impostare la chiave API nell'ambiente o direttamente nel pannello della dashboard:

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

TED (opzionale, per le gare UE): API key gratuita su
<https://ted.europa.eu>, poi `setx TED_API_KEY "la-chiave"` e riaprire
il terminale.

## Uso

```powershell
.\.venv\Scripts\python.exe main.py          # fetch + scoring
.\.venv\Scripts\streamlit.exe run app.py    # dashboard
```

## Struttura

- `config.py` - query news, CPV TED, prompt, soglie
- `db.py` - storage SQLite (`data/opportunita.db`)
- `fetchers/news.py` - Google News RSS
- `fetchers/ted.py` - bandi TED (richiede API key)
- `llm.py` - scoring Ollama + fallback euristico
- `main.py` - pipeline fetch -> dedup -> scoring
- `app.py` - dashboard Streamlit

## Roadmap fase 2

- Storico ordini: riordini attesi, clienti dormienti, cross-sell rame/fibra
- Lookalike prospecting su clienti esistenti
- Fonti extra: ANAC, portali RFI/Fincantieri, export email report

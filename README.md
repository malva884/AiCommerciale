# Agente Opportunita' Commerciali

Agente locale che raccoglie segnali pubblici (gare d'appalto UE, news su
data center / ferroviario / fibra) e li valuta come opportunita' di nuovi
ordini per un produttore di cavi in fibra ottica e rame.

**Privacy**: nessun dato a servizi cloud. Il scoring usa un LLM locale
(Ollama); senza Ollama attivo c'e' un fallback euristico a parole chiave.
Le uniche chiamate verso l'esterno sono il download delle fonti pubbliche.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

LLM locale (opzionale ma consigliato):

```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
```

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

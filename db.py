"""Storage SQLite delle opportunita'. Nessun dato lascia la macchina."""
import json
import os
import sqlite3
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,              -- 'news' | 'ted' | 'crm'
    external_id     TEXT UNIQUE NOT NULL,       -- url o id gara (dedup)
    title           TEXT NOT NULL,
    url             TEXT,
    published       TEXT,
    text            TEXT,                       -- descrizione/sommario
    country         TEXT,                       -- es. ITA, DEU, FRA
    area_manager    TEXT,                       -- DACH, IBERIA, FRANCE, ITALY, NORDICS, UK_IE, CEE
    score           INTEGER,                    -- 0-100
    sector          TEXT,                       -- Data Center, Telco, Ferroviario, Navale, Avio
    target_company  TEXT,                       -- azienda potenziale cliente (vincitore commessa)
    norms           TEXT,                       -- es. EN 45545-2, CPR B2ca, RINA, MIL-DTL
    motivation      TEXT,
    action          TEXT,
    email_draft     TEXT,                       -- bozza email nel tono/lingua corretti per il paese
    scored_by       TEXT,                       -- 'ollama' | 'heuristic'
    created_at      TEXT NOT NULL
);

-- Cache dati pubblici delle aziende clienti (Wikidata)
CREATE TABLE IF NOT EXISTS company_info (
    company_name TEXT PRIMARY KEY,
    info_json    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);

-- Storico errori di raccolta dati (fonti non raggiungibili, API, parse)
CREATE TABLE IF NOT EXISTS fetch_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,              -- timestamp ISO dell'errore
    source      TEXT NOT NULL,              -- news | ted | ted_award | wikidata | erp | ollama | pipeline
    target      TEXT,                       -- query, nome azienda, contesto
    url         TEXT,                       -- indirizzo non raggiungibile
    error_type  TEXT,                       -- http_error | timeout | connection | parse | unexpected
    message     TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0, -- 1 = sistemato/riconosciuto
    resolved_at TEXT
);

-- Contatore giornaliero chiamate LLM cloud (quota Gemini RPD)
CREATE TABLE IF NOT EXISTS llm_usage (
    day    TEXT NOT NULL,              -- YYYY-MM-DD
    key_id TEXT NOT NULL DEFAULT '',   -- hash chiave Gemini ('' = legacy)
    calls  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key_id)
);

--- Prospect europei qualificati dal motore New Business / Lookalike
CREATE TABLE IF NOT EXISTS prospects_europa (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name    TEXT NOT NULL,          -- ragione sociale normalizzata
    country_code    TEXT NOT NULL DEFAULT '', -- codice ISO paese
    sector          TEXT,                   -- settore target
    website_url     TEXT,                   -- sito ufficiale verificato
    source_type     TEXT,                   -- DB_OPPORTUNITY | WIKIDATA_SEED | EXTERNAL_IMPORT
    is_erp_customer INTEGER NOT NULL DEFAULT 0, -- 1 = gia' cliente ERP (escluso)
    erp_match_name  TEXT,                   -- nome cliente ERP che ha matchato
    scraped_context TEXT,                   -- estratto testo dal sito ufficiale
    match_score     INTEGER NOT NULL DEFAULT 0, -- 0-100
    score_reasons   TEXT,                   -- JSON list: motivi del punteggio
    suggested_cables TEXT,                  -- JSON list cavi/certificazioni compatibili
    outreach_payload TEXT,                  -- JSON email/linkedin generato
    status          TEXT NOT NULL DEFAULT 'NEW', -- NEW | READY_FOR_REVIEW | APPROVED_SENT | DISCARDED | EXISTING_CUSTOMER
    last_analyzed_at TEXT,
    UNIQUE(company_name, country_code)
);

--- Impostazioni applicative salvate dalla UI (chiave/valore)
--- Esempi: LLM_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL, DISABLE_OLLAMA_FALLBACK
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)
        # Migrazione retrocompatibile per DB già esistente
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
        new_cols = [
            ("country", "TEXT"),
            ("area_manager", "TEXT"),
            ("norms", "TEXT"),
            ("email_draft", "TEXT"),
            ("target_company", "TEXT"),
        ]
        for name, ctype in new_cols:
            if name not in cols:
                conn.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {ctype}")
        # Migrazione llm_usage -> conteggio per chiave (rotazione multi-key)
        usage_cols = {r["name"] for r in conn.execute("PRAGMA table_info(llm_usage)").fetchall()}
        if "key_id" not in usage_cols:
            conn.executescript("""
                ALTER TABLE llm_usage RENAME TO llm_usage_old;
                CREATE TABLE llm_usage (
                    day    TEXT NOT NULL,
                    key_id TEXT NOT NULL DEFAULT '',
                    calls  INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, key_id)
                );
                INSERT INTO llm_usage (day, calls) SELECT day, calls FROM llm_usage_old;
                DROP TABLE llm_usage_old;
            """)


def insert_opportunity(item: dict) -> bool:
    """Inserisce se external_id non esiste. Ritorna True se inserito."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO opportunities
               (source, external_id, title, url, published, text, country,
                area_manager, target_company, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["source"], item["external_id"], item["title"],
             item.get("url"), item.get("published"), item.get("text"),
             item.get("country"), item.get("area_manager"),
             item.get("target_company"),
             datetime.now().isoformat(timespec="seconds")),
        )
        return cur.rowcount > 0


def unscored(limit: int = 200, include_heuristic: bool = False):
    """Righe da (ri)classificare: mai valutate oppure senza settore assegnato.

    Le correzioni manuali da dashboard (sector valorizzato) non vengono toccate.
    Con include_heuristic=True rivaluta anche le righe con solo scoring
    euristico (fallback senza LLM), promuovendole a valutazione LLM.
    """
    extra = " OR scored_by='heuristic'" if include_heuristic else ""
    with _connect() as conn:
        return conn.execute(
            f"""SELECT id, title, text, country, area_manager
               FROM opportunities
               WHERE score IS NULL OR sector IS NULL{extra}
               LIMIT ?""",
            (limit,),
        ).fetchall()


def update_score(opp_id: int, result: dict):
    with _connect() as conn:
        conn.execute(
            """UPDATE opportunities
               SET score=?, sector=?, norms=?, area_manager=COALESCE(?, area_manager),
                   country=COALESCE(?, country), motivation=?, action=?,
                   email_draft=?, scored_by=?,
                   target_company=COALESCE(?, target_company)
               WHERE id=?""",
            (result["score"], result.get("sector"), result.get("norms"),
             result.get("area_manager"), result.get("country"),
             result.get("motivation"), result.get("action"),
             result.get("email_draft"), result.get("scored_by"),
             result.get("target_company"), opp_id),
        )


def update_classification(opp_id: int, sector: str | None,
                          area_manager: str | None, score: int | None = None,
                          target_company: str | None = None):
    """Override manuale da dashboard: settore, area manager, score e cliente."""
    with _connect() as conn:
        conn.execute(
            """UPDATE opportunities
               SET sector=?, area_manager=?, target_company=?,
                   score=COALESCE(?, score), scored_by='manual'
               WHERE id=?""",
            (sector, area_manager, target_company, score, opp_id),
        )


def update_target(opp_id: int, target_company: str):
    """Valorizza il solo campo target_company (backfill euristico)."""
    with _connect() as conn:
        conn.execute("UPDATE opportunities SET target_company=? WHERE id=?",
                     (target_company, opp_id))


def targets_missing(limit: int = 1000):
    """Righe senza azienda cliente associata, candidati al backfill."""
    with _connect() as conn:
        return conn.execute(
            "SELECT id, title, text FROM opportunities "
            "WHERE target_company IS NULL LIMIT ?",
            (limit,),
        ).fetchall()


def stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE score IS NOT NULL"
        ).fetchone()[0]
    return {"total": total, "scored": scored}


def llm_calls_today(key_id: str | None = None) -> int:
    """Chiamate LLM cloud registrate oggi. key_id=None -> totale tutte le chiavi."""
    with _connect() as conn:
        if key_id is None:
            row = conn.execute(
                "SELECT SUM(calls) FROM llm_usage WHERE day=?",
                (datetime.now().strftime("%Y-%m-%d"),)).fetchone()
        else:
            row = conn.execute(
                "SELECT calls FROM llm_usage WHERE day=? AND key_id=?",
                (datetime.now().strftime("%Y-%m-%d"), key_id)).fetchone()
    return (row[0] or 0) if row else 0


def llm_register_call(key_id: str = ""):
    """Incrementa il contatore giornaliero delle chiamate LLM cloud per chiave."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO llm_usage (day, key_id, calls) VALUES (?, ?, 1)
               ON CONFLICT(day, key_id) DO UPDATE SET calls = calls + 1""",
            (datetime.now().strftime("%Y-%m-%d"), key_id))


def llm_usage_today() -> dict:
    """Mappa key_id -> chiamate odierne (vista quota multi-chiave)."""
    with _connect() as conn:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT key_id, calls FROM llm_usage WHERE day=?",
            (datetime.now().strftime("%Y-%m-%d"),)).fetchall()}


def get_company_info(company_name: str) -> dict | None:
    """Scheda azienda dalla cache locale (None se mai arricchita)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT info_json FROM company_info WHERE company_name=?",
            (company_name,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def upsert_company_info(company_name: str, info: dict):
    """Salva/aggiorna la scheda pubblica di un'azienda."""
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO company_info
               (company_name, info_json, fetched_at) VALUES (?, ?, ?)""",
            (company_name, json.dumps(info, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )


def companies_missing_info(limit: int = 50):
    """Aziende target presenti nelle opportunita' ma non ancora arricchite."""
    with _connect() as conn:
        return [r[0] for r in conn.execute(
            """SELECT DISTINCT target_company FROM opportunities
               WHERE target_company IS NOT NULL
                 AND target_company NOT IN
                     (SELECT company_name FROM company_info)
               LIMIT ?""",
            (limit,),
        ).fetchall()]


# ----------------------------------------------------------------------------
# STORICO ERRORI DI RACCOLTA
# ----------------------------------------------------------------------------

def log_error(source: str, target: str | None = None,
              url: str | None = None, error_type: str | None = None,
              message: str | None = None):
    """Storicizza un errore di fetch/enrichment.

    Dedup: se lo stesso errore (source+url+message) e' gia' presente e non
    ancora risolto non viene duplicato, aggiorna solo il timestamp.
    Non solleva mai eccezioni: il log non deve bloccare la pipeline.
    """
    try:
        now = datetime.now().isoformat(timespec="seconds")
        with _connect() as conn:
            dup = conn.execute(
                """SELECT id FROM fetch_errors
                   WHERE resolved=0 AND source IS ? AND url IS ?
                         AND message IS ?""",
                (source, url, message),
            ).fetchone()
            if dup:
                conn.execute("UPDATE fetch_errors SET ts=? WHERE id=?",
                             (now, dup["id"]))
                return
            conn.execute(
                """INSERT INTO fetch_errors
                   (ts, source, target, url, error_type, message)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (now, source, target, url, error_type,
                 (message or "")[:500]),
            )
    except Exception:
        pass


def get_error_log(include_resolved: bool = False,
                  limit: int = 500) -> list:
    """Errori di raccolta, dal piu' recente."""
    where = "" if include_resolved else "WHERE resolved=0"
    with _connect() as conn:
        return conn.execute(
            f"""SELECT id, ts, source, target, url, error_type, message,
                       resolved, resolved_at
                FROM fetch_errors {where}
                ORDER BY ts DESC, id DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def unresolved_error_count() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM fetch_errors WHERE resolved=0"
        ).fetchone()[0]


def mark_errors_resolved(ids: list[int]):
    """Segna errori come sistemati."""
    if not ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.executemany(
            "UPDATE fetch_errors SET resolved=1, resolved_at=? WHERE id=?",
            [(now, i) for i in ids],
        )


def delete_resolved_errors() -> int:
    """Elimina definitivamente gli errori segnati come risolti."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM fetch_errors WHERE resolved=1")
        return cur.rowcount


# ----------------------------------------------------------------------------
# PROSPECT EUROPA (New Business / Lookalike engine)
# ----------------------------------------------------------------------------

def upsert_prospect(p: dict) -> int:
    """Inserisce/aggiorna un prospect. Chiave naturale: (company_name, country_code)."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO prospects_europa
               (company_name, country_code, sector, website_url, source_type,
                is_erp_customer, erp_match_name, scraped_context, match_score,
                score_reasons, suggested_cables, outreach_payload, status,
                last_analyzed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(company_name, country_code) DO UPDATE SET
                sector          = COALESCE(excluded.sector, sector),
                website_url     = COALESCE(excluded.website_url, website_url),
                source_type     = COALESCE(excluded.source_type, source_type),
                is_erp_customer = excluded.is_erp_customer,
                erp_match_name  = COALESCE(excluded.erp_match_name, erp_match_name),
                scraped_context = COALESCE(excluded.scraped_context, scraped_context),
                match_score     = excluded.match_score,
                score_reasons   = COALESCE(excluded.score_reasons, score_reasons),
                suggested_cables = COALESCE(excluded.suggested_cables, suggested_cables),
                outreach_payload = COALESCE(excluded.outreach_payload, outreach_payload),
                status          = excluded.status,
                last_analyzed_at = excluded.last_analyzed_at""",
            (p["company_name"], p.get("country_code") or "",
             p.get("sector"), p.get("website_url"), p.get("source_type"),
             1 if p.get("is_erp_customer") else 0, p.get("erp_match_name"),
             p.get("scraped_context"), int(p.get("match_score") or 0),
             p.get("score_reasons"), p.get("suggested_cables"),
             p.get("outreach_payload"), p.get("status") or "NEW",
             p.get("last_analyzed_at")),
        )
        row = conn.execute(
            "SELECT id FROM prospects_europa "
            "WHERE company_name=? AND country_code=?",
            (p["company_name"], p.get("country_code") or "")).fetchone()
        return row["id"] if row else 0


def get_prospects(status: str | None = None, min_score: int = 0,
                  search: str = "", include_erp: bool = False,
                  limit: int = 300) -> list[dict]:
    """Prospect dal piu' qualificato; per default esclude i gia' clienti ERP."""
    clauses = ["match_score >= ?"]
    params: list = [min_score]
    if not include_erp:
        clauses.append("is_erp_customer = 0")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(company_name LIKE ? OR sector LIKE ? OR country_code LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    params.append(limit)
    with _connect() as conn:
        return conn.execute(
            f"""SELECT * FROM prospects_europa
                WHERE {' AND '.join(clauses)}
                ORDER BY match_score DESC, company_name LIMIT ?""",
            params).fetchall()


def update_prospect(prospect_id: int, fields: dict):
    """Update parziale whitelistato su un prospect."""
    allowed = {"status", "match_score", "scraped_context", "outreach_payload",
               "score_reasons", "suggested_cables", "website_url", "sector",
               "is_erp_customer", "erp_match_name", "last_analyzed_at"}
    sets = [(k, v) for k, v in fields.items() if k in allowed]
    if not sets:
        return
    sql = ", ".join(f"{k}=?" for k, _ in sets)
    with _connect() as conn:
        conn.execute(f"UPDATE prospects_europa SET {sql} WHERE id=?",
                     [v for _, v in sets] + [prospect_id])


def prospect_stats() -> dict:
    """Conteggi per la dashboard prospect."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c, SUM(is_erp_customer) erp "
            "FROM prospects_europa GROUP BY status").fetchall()
        total = conn.execute(
            "SELECT COUNT(*), COALESCE(AVG(match_score),0) "
            "FROM prospects_europa").fetchone()
    by_status = {r["status"]: r["c"] for r in rows}
    return {"total": total[0], "avg_score": round(total[1] or 0, 1),
            "by_status": by_status}


def opportunity_targets() -> list[dict]:
    """target_company reali rilevate da TED/News nel DB opportunita'."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT target_company,
                      MAX(country) AS country,
                      MAX(sector)  AS sector,
                      MAX(created_at) AS last_seen,
                      COUNT(*)     AS signals
               FROM opportunities
               WHERE target_company IS NOT NULL
                     AND TRIM(target_company) != ''
               GROUP BY target_company""").fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# IMPOSTAZIONI APPLICATIVE (salvate dalla dashboard, persistenti su volume DB)
# ----------------------------------------------------------------------------

def get_setting(key: str) -> str | None:
    """Valore di una impostazione UI. None se mai salvata."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key=?",
                (key,)).fetchone()
        return row["value"] if row else None
    except Exception:
        return None  # tabella non ancora creata / DB non raggiungibile


def set_setting(key: str, value: str):
    """Salva una impostazione UI (stringa vuota consentita = 'svuota')."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value or ""))

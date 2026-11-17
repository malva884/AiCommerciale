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
    scored_by       TEXT,                       -- 'ollama' | 'gemini' | 'heuristic' | 'gemini_batch'
    scoring_status  TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | BATCH_PASSED | DISCARDED | COMPLETED
    work_status     TEXT NOT NULL DEFAULT 'Da lavorare', -- Da lavorare | In trattativa | Scartata
    notified_at     TEXT,                       -- timestamp ISO invio digest email (mai reinviare)
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

--- Referenti/decision maker trovati via provider dati (Apollo, Proxycurl)
CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,             -- azienda target associata
    full_name    TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',  -- ruolo dichiarato (es. Category Buyer)
    linkedin_url TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    city         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',  -- apollo | proxycurl
    fetched_at   TEXT NOT NULL
);

--- Dossier 360° aziende profilate on-demand (Company Intelligence)
CREATE TABLE IF NOT EXISTS company_dossiers (
    company_id        TEXT PRIMARY KEY,        -- UUID
    erp_customer_code TEXT,                    -- codice cliente ERP se censita
    company_name      TEXT NOT NULL,
    domain            TEXT NOT NULL UNIQUE,    -- dominio web principale
    country_code      TEXT,                    -- ISO paese
    sector            TEXT,                    -- settore primario target
    flags             TEXT NOT NULL DEFAULT '',-- es. WARM_CHAMPION_LEAD (CSV)
    dossier_json      TEXT NOT NULL DEFAULT '{}', -- output strutturato LLM
    last_enriched_at  TEXT,
    created_at        TEXT NOT NULL
);

--- Decision maker verificati (enrichment B2B + monitoraggio job change)
CREATE TABLE IF NOT EXISTS company_contacts (
    contact_id       TEXT PRIMARY KEY,         -- UUID
    company_id       TEXT NOT NULL REFERENCES company_dossiers(company_id),
    full_name        TEXT NOT NULL,
    job_title        TEXT NOT NULL DEFAULT '',
    department       TEXT NOT NULL DEFAULT '', -- PROCUREMENT|ENGINEERING|MANAGEMENT|PROJECT
    email            TEXT NOT NULL DEFAULT '',
    email_status     TEXT NOT NULL DEFAULT 'UNKNOWN', -- VALID|INVALID|UNKNOWN
    linkedin_url     TEXT NOT NULL DEFAULT '',
    external_person_id TEXT NOT NULL DEFAULT '',  -- id provider per check futuri
    source_provider  TEXT NOT NULL DEFAULT '',
    verified_at      TEXT,
    confidence_score INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE|MOVED_COMPANY|LEFT_COMPANY|ARCHIVED
    previous_company_id TEXT,                  -- se proviene da altra azienda monitorata
    monitor_interval_days INTEGER NOT NULL DEFAULT 30,
    last_checked_at  TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE(company_id, email)
);

--- Log eventi commerciali: cambio azienda / promozione / bounce email
CREATE TABLE IF NOT EXISTS contact_change_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  TEXT NOT NULL REFERENCES company_contacts(contact_id),
    event_type  TEXT NOT NULL,            -- COMPANY_CHANGE|ROLE_PROMOTION|EMAIL_BOUNCED
    old_value   TEXT,
    new_value   TEXT,
    generated_action_payload TEXT,        -- JSON: bozza email + sostituto
    is_reviewed INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

--- Watchlist colossi OEM/Tier-0 (Doppio Binario, Binario 1)
CREATE TABLE IF NOT EXISTS oem_watchlist (
    oem_id          TEXT PRIMARY KEY,        -- UUID
    oem_name        TEXT NOT NULL,
    aliases_json    TEXT NOT NULL DEFAULT '[]', -- varianti/acronimi
    sector          TEXT NOT NULL,
    production_sites_json TEXT NOT NULL DEFAULT '[]',
    target_standards_json TEXT NOT NULL DEFAULT '[]',
    active          INTEGER NOT NULL DEFAULT 1,
    last_scanned_at TEXT
);

--- Alert 'Commesse Madre' intercettate sui colossi OEM
CREATE TABLE IF NOT EXISTS oem_contract_alerts (
    alert_id        TEXT PRIMARY KEY,        -- UUID
    oem_id          TEXT NOT NULL REFERENCES oem_watchlist(oem_id),
    contract_summary TEXT NOT NULL DEFAULT '',
    probable_site   TEXT,
    suggested_mb_cables TEXT NOT NULL DEFAULT '[]',
    source_url      TEXT NOT NULL DEFAULT '',
    source_title    TEXT NOT NULL DEFAULT '',
    detected_at     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'NEW'  -- NEW|ASSIGNED|DISMISSED
);

--- Segnali news (60-90 gg) per prospect/clienti: gancio outreach AI
CREATE TABLE IF NOT EXISTS company_news_signals (
    signal_id       TEXT PRIMARY KEY,        -- UUID
    company_key     TEXT NOT NULL,           -- company_id dossier O 'prospect:<nome>|<paese>'
    company_name    TEXT NOT NULL DEFAULT '',
    article_title   TEXT NOT NULL DEFAULT '',
    published_date  TEXT,
    signal_category TEXT NOT NULL DEFAULT '',-- NEW_CONTRACT|FACILITY_EXPANSION|TRADE_SHOW|SUPPLY_CHAIN_EVENT
    source_url      TEXT NOT NULL DEFAULT '',
    outreach_hook   TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT 'en',
    detected_at     TEXT NOT NULL,
    UNIQUE(company_key, source_url)
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
            ("scoring_status", "TEXT NOT NULL DEFAULT 'PENDING'"),
            ("work_status", "TEXT NOT NULL DEFAULT 'Da lavorare'"),
            ("notified_at", "TEXT"),
        ]
        for name, ctype in new_cols:
            if name not in cols:
                conn.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {ctype}")
        # Backfill stato scoring: righe gia' valutate da LLM o manualmente sono
        # COMPLETED; quelle con solo scoring euristico restano PENDING e
        # rientrano in coda per il triage batch al prossimo run.
        conn.execute("""
            UPDATE opportunities SET scoring_status='COMPLETED'
            WHERE scoring_status='PENDING' AND score IS NOT NULL
              AND COALESCE(scored_by,'') NOT IN
                  ('heuristic','heuristic_filtered','heuristic_batch','gemini_batch','ollama_batch')
        """)
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
    """Salva l'esito del deep-dive: stato COMPLETED, tranne quando l'LLM
    non ha risposto e si e' salvato solo il fallback euristico (il record
    resta nel suo stato, es. BATCH_PASSED, per essere rielaborato)."""
    with _connect() as conn:
        conn.execute(
            """UPDATE opportunities
               SET score=?, sector=?, norms=?, area_manager=COALESCE(?, area_manager),
                   country=COALESCE(?, country), motivation=?, action=?,
                   email_draft=?, scored_by=?,
                   scoring_status=CASE
                       WHEN ? IN ('heuristic','heuristic_filtered')
                       THEN scoring_status ELSE 'COMPLETED' END,
                   target_company=COALESCE(?, target_company)
               WHERE id=?""",
            (result["score"], result.get("sector"), result.get("norms"),
             result.get("area_manager"), result.get("country"),
             result.get("motivation"), result.get("action"),
             result.get("email_draft"), result.get("scored_by"),
             result.get("scored_by"),
             result.get("target_company"), opp_id),
        )


def pending_for_triage(limit: int = 500):
    """Righe PENDING da passare al batch triage (mai valutate o solo euristico)."""
    with _connect() as conn:
        return conn.execute(
            """SELECT id, source, title, text, country, target_company
               FROM opportunities
               WHERE scoring_status='PENDING' OR scoring_status IS NULL
               ORDER BY id LIMIT ?""",
            (limit,),
        ).fetchall()


def passed_for_deep_dive(limit: int = 1000):
    """Righe BATCH_PASSED in attesa di analisi completa (score decrescente)."""
    with _connect() as conn:
        return conn.execute(
            """SELECT id, source, title, text, country, area_manager, score,
                      target_company
               FROM opportunities
               WHERE scoring_status='BATCH_PASSED'
               ORDER BY score DESC, id LIMIT ?""",
            (limit,),
        ).fetchall()


# ----------------------------------------------------------------------------
# NOTIFICHE EMAIL MATTUTINE (digest commerciale)
# ----------------------------------------------------------------------------

ROUTING_SETTINGS_KEY = "notification_routing_json"


def get_notification_rules() -> list[dict]:
    """Regole di routing dei digest da app_settings; fallback su config.
    Ritorna sempre una lista di dict (mai None)."""
    raw = get_setting(ROUTING_SETTINGS_KEY)
    if raw:
        try:
            rules = json.loads(raw)
            if isinstance(rules, list):
                return rules
        except (ValueError, TypeError):
            pass
    from config import DEFAULT_NOTIFICATION_ROUTING
    return list(DEFAULT_NOTIFICATION_ROUTING)


def set_notification_rules(rules: list):
    """Persiste le regole di routing (JSON) salvate dall'editor UI."""
    set_setting(ROUTING_SETTINGS_KEY, json.dumps(rules, ensure_ascii=False))


def opportunities_to_notify(sectors: list, areas: list,
                            min_score: int = 80, limit: int = 500):
    """Opportunita' COMPLETED non ancora notificate per una regola di routing.

    - sector normalizzato via CASE (legacy 'Navale' -> 'Navale/Offshore');
    - '*' in sectors/areas = wildcard (nessun filtro su quell'asse);
    - ordinamento: priorita' fonte (ted_award > crm > ted > news), poi score.
    """
    where = ["scoring_status='COMPLETED'", "notified_at IS NULL",
             "score >= ?"]
    params: list = [min_score]
    if "*" not in (sectors or []):
        ph = ",".join("?" for _ in sectors)
        where.append(
            f"COALESCE(CASE WHEN sector IN ('Navale','Navale & Offshore',"
            f"'Navale e Offshore') THEN 'Navale/Offshore' ELSE sector END,''"
            f") IN ({ph})")
        params += list(sectors)
    if "*" not in (areas or []):
        ph = ",".join("?" for _ in areas)
        where.append(f"COALESCE(area_manager,'') IN ({ph})")
        params += list(areas)
    params.append(limit)
    with _connect() as conn:
        return conn.execute(
            f"""SELECT id, source, title, url, published, country, area_manager,
                       score, target_company, norms, motivation, action,
                       email_draft,
                       CASE WHEN sector IN ('Navale','Navale & Offshore',
                                            'Navale e Offshore')
                            THEN 'Navale/Offshore' ELSE sector END AS sector
                FROM opportunities
                WHERE {' AND '.join(where)}
                ORDER BY CASE source WHEN 'ted_award' THEN 1
                                     WHEN 'crm' THEN 2
                                     WHEN 'ted' THEN 3 ELSE 4 END,
                         score DESC
                LIMIT ?""",
            params,
        ).fetchall()


def mark_notified(opp_ids: list):
    """Valorizza notified_at (ISO8601) sugli id inclusi nel digest inviato."""
    if not opp_ids:
        return
    ph = ",".join("?" for _ in opp_ids)
    with _connect() as conn:
        conn.execute(
            f"UPDATE opportunities SET notified_at=? WHERE id IN ({ph})",
            [datetime.now().isoformat(timespec="seconds")] + list(opp_ids),
        )


def update_work_status(opp_id: int, work_status: str):
    """Stato di lavorazione commerciale impostato dai pulsanti feedback
    sulla scheda: 'Da lavorare' | 'In trattativa' | 'Scartata'."""
    with _connect() as conn:
        conn.execute(
            "UPDATE opportunities SET work_status=? WHERE id=?",
            (work_status, opp_id),
        )


def update_triage_result(opp_id: int, result: dict, status: str):
    """Esito del batch triage: status 'BATCH_PASSED' o 'DISCARDED'.
    Il motivo dello scarto viene salvato in motivation (visibile in UI)."""
    with _connect() as conn:
        conn.execute(
            """UPDATE opportunities
               SET score=?, sector=COALESCE(?, sector),
                   scored_by=?, scoring_status=?,
                   motivation=COALESCE(?, motivation)
               WHERE id=?""",
            (result["score"], result.get("sector"),
             result.get("scored_by"), status,
             result.get("discard_reason"), opp_id),
        )


def pending_scoring_count() -> int:
    """Elementi ancora in lavorazione (triage o deep-dive) per la dashboard."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM opportunities "
            "WHERE scoring_status IN ('PENDING','BATCH_PASSED')"
        ).fetchone()[0]


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


# ----------------------------------------------------------------------------
# CONTATTI / REFERENTI (Apollo.io, Proxycurl)
# ----------------------------------------------------------------------------

def get_contacts(company_name: str) -> list[dict]:
    """Referenti gia' recuperati per un'azienda (cache locale)."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM contacts WHERE company_name=? ORDER BY id",
            (company_name,)).fetchall()]


def save_contacts(company_name: str, contacts: list[dict]):
    """Sostituisce i referenti di un'azienda con l'ultimo set recuperato."""
    with _connect() as conn:
        conn.execute("DELETE FROM contacts WHERE company_name=?",
                     (company_name,))
        conn.executemany(
            """INSERT INTO contacts
               (company_name, full_name, title, linkedin_url, email,
                city, source, fetched_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(company_name, c.get("full_name", ""), c.get("title", ""),
              c.get("linkedin_url", ""), c.get("email", ""),
              c.get("city", ""), c.get("source", ""),
              datetime.now().isoformat(timespec="seconds"))
             for c in contacts])


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


# ==============================================================================
# Controllo & Manutenzione DB (pannello admin in AI & Agenti)
# ==============================================================================

def queue_stats() -> dict:
    """Conteggi delle opportunita' per stato della pipeline di scoring."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT scoring_status, COUNT(*) FROM opportunities "
            "GROUP BY scoring_status"
        ).fetchall()
    return {s or "NULL": n for s, n in rows}


def reset_heuristic_passed() -> int:
    """Riporta in PENDING i BATCH_PASSED promossi dal solo euristico
    (fallback dopo errori API): saranno rivalutati dal batch LLM."""
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE opportunities SET scoring_status='PENDING'
               WHERE scoring_status='BATCH_PASSED'
                 AND (scored_by LIKE 'heuristic%' OR scored_by IS NULL)"""
        )
        return cur.rowcount


def discard_pre_2026_passed() -> int:
    """Scarta i BATCH_PASSED pubblicati prima del 2026 (segnali obsoleti:
    notizie o bandi dell'anno scorso non valgono una chiamata deep-dive)."""
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE opportunities
               SET scoring_status='DISCARDED',
                   motivation='Scartato automaticamente: segnale precedente al 2026'
               WHERE scoring_status='BATCH_PASSED'
                 AND published NOT LIKE '%2026%'"""
        )
        return cur.rowcount


def reset_failed_records() -> int:
    """Riporta in PENDING i record bloccati: senza score o in stato ERROR
    (es. timeout di rete durante il deep-dive)."""
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE opportunities SET scoring_status='PENDING'
               WHERE scoring_status='ERROR'
                  OR (score IS NULL AND scoring_status <> 'PENDING')"""
        )
        return cur.rowcount


def purge_old_errors(days: int = 30) -> int:
    """Elimina i log errori piu' vecchi di `days` giorni (alleggerisce il DB)."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM fetch_errors WHERE ts < datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        return cur.rowcount


_RO_FORBIDDEN = ("DROP ", "DELETE ", "UPDATE ", "INSERT ", "ALTER ",
                 "REPLACE ", "ATTACH ", "DETACH ", "CREATE ", "VACUUM",
                 "REINDEX", "PRAGMA WRITABLE_SCHEMA")


def run_readonly_query(sql: str):
    """Esegue una query di sola lettura e ritorna un DataFrame.

    Guardrail obbligatorio: solo SELECT/PRAGMA, niente parole chiave di
    modifica, niente multi-statement, connessione SQLite aperta in
    modalita' URI read-only (?mode=ro).
    """
    import pandas as pd  # import lazy: db.py resta leggero per lo scheduler
    cleaned = (sql or "").strip().rstrip(";").strip()
    upper = " ".join(cleaned.upper().split())
    if not (upper.startswith("SELECT") or upper.startswith("PRAGMA")):
        raise ValueError("Sono consentite solo query di lettura (SELECT / PRAGMA).")
    if ";" in cleaned:
        raise ValueError("E' consentita una sola istruzione per query.")
    if any(w in upper for w in _RO_FORBIDDEN):
        raise ValueError("Comando non consentito in modalita' sola lettura.")
    uri = f"file:{DB_PATH}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        return pd.read_sql_query(cleaned, conn)


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


# ------------------------------------------------------------------------------
# COMPANY INTELLIGENCE: dossier 360, decision maker, job change monitoring
# ------------------------------------------------------------------------------

import uuid as _uuid


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_company_dossier(d: dict) -> str:
    """Inserisce/aggiorna un dossier azienda. Chiave naturale: domain.
    Ritorna company_id (creato se nuovo record)."""
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT company_id FROM company_dossiers WHERE domain=?",
            (d.get("domain") or "",)).fetchone()
        cid = row["company_id"] if row else (d.get("company_id") or _uuid.uuid4().hex)
        conn.execute(
            """INSERT INTO company_dossiers
               (company_id, erp_customer_code, company_name, domain,
                country_code, sector, flags, dossier_json,
                last_enriched_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(domain) DO UPDATE SET
                erp_customer_code = COALESCE(excluded.erp_customer_code, erp_customer_code),
                company_name      = COALESCE(excluded.company_name, company_name),
                country_code      = COALESCE(excluded.country_code, country_code),
                sector            = COALESCE(excluded.sector, sector),
                flags             = COALESCE(excluded.flags, flags),
                dossier_json      = CASE WHEN excluded.dossier_json <> '{}'
                                         THEN excluded.dossier_json
                                         ELSE dossier_json END,
                last_enriched_at  = COALESCE(excluded.last_enriched_at, last_enriched_at)""",
            (cid, d.get("erp_customer_code"), d.get("company_name") or "",
             d.get("domain") or "", d.get("country_code"), d.get("sector"),
             d.get("flags") or "",
             json.dumps(d.get("dossier_json") or {}, ensure_ascii=False)
             if isinstance(d.get("dossier_json"), dict)
             else (d.get("dossier_json") or "{}"),
             d.get("last_enriched_at") or now, now))
        return cid


def get_dossier_by_domain(domain: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM company_dossiers WHERE domain=?", (domain,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["dossier_json"] = json.loads(d.get("dossier_json") or "{}")
    except (ValueError, TypeError):
        d["dossier_json"] = {}
    return d


def get_dossier(company_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM company_dossiers WHERE company_id=?",
            (company_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["dossier_json"] = json.loads(d.get("dossier_json") or "{}")
    except (ValueError, TypeError):
        d["dossier_json"] = {}
    return d


def list_dossiers(limit: int = 300) -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT company_id, company_name, domain, country_code, sector,
                      flags, last_enriched_at
               FROM company_dossiers ORDER BY last_enriched_at DESC LIMIT ?""",
            (limit,)).fetchall()]


def add_company_flag(company_id: str, flag: str):
    """Aggiunge un flag CSV al dossier (deduplicato)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT flags FROM company_dossiers WHERE company_id=?",
            (company_id,)).fetchone()
        flags = [f for f in (row["flags"] or "").split(",") if f] if row else []
        if flag and flag not in flags:
            flags.append(flag)
            conn.execute(
                "UPDATE company_dossiers SET flags=? WHERE company_id=?",
                (",".join(flags), company_id))


def save_company_contacts(company_id: str, contacts: list[dict]) -> int:
    """Upsert referenti verificati di un'azienda. Chiave: (company_id, email).
    I contatti gia' presenti NON vengono resettati (preserva stato monitoraggio).
    Ritorna il numero di referenti inseriti nuovi."""
    now = _now_iso()
    inserted = 0
    with _connect() as conn:
        for c in contacts:
            exists = conn.execute(
                "SELECT 1 FROM company_contacts WHERE company_id=? AND email=?",
                (company_id, c.get("email") or "")).fetchone()
            if not exists:
                inserted += 1
            cid = _uuid.uuid4().hex
            conn.execute(
                """INSERT INTO company_contacts
                   (contact_id, company_id, full_name, job_title, department,
                    email, email_status, linkedin_url, external_person_id,
                    source_provider, verified_at, confidence_score, status,
                    previous_company_id, monitor_interval_days, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(company_id, email) DO UPDATE SET
                    full_name          = excluded.full_name,
                    job_title          = COALESCE(NULLIF(excluded.job_title,''), job_title),
                    department         = COALESCE(NULLIF(excluded.department,''), department),
                    email_status       = excluded.email_status,
                    linkedin_url       = COALESCE(NULLIF(excluded.linkedin_url,''), linkedin_url),
                    external_person_id = COALESCE(NULLIF(excluded.external_person_id,''), external_person_id),
                    verified_at        = excluded.verified_at,
                    confidence_score   = MAX(confidence_score, excluded.confidence_score)""",
                (cid, company_id, c.get("full_name") or "",
                 c.get("job_title") or c.get("title") or "",
                 c.get("department") or "", c.get("email") or "",
                 c.get("email_status") or "UNKNOWN",
                 c.get("linkedin_url") or "",
                 c.get("external_person_id") or "",
                 c.get("source_provider") or c.get("source") or "",
                 c.get("verified_at") or now,
                 int(c.get("confidence_score") or 0),
                 c.get("status") or "ACTIVE",
                 c.get("previous_company_id"),
                 int(c.get("monitor_interval_days") or 30), now))
    return inserted


def get_company_contacts(company_id: str,
                         status: str | None = None) -> list[dict]:
    where = "WHERE company_id=?"
    params: list = [company_id]
    if status:
        where += " AND status=?"
        params.append(status)
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM company_contacts {where} ORDER BY department, full_name",
            params).fetchall()]


def contacts_due_for_check(limit: int = 200) -> list[dict]:
    """Referenti ACTIVE da verificare: mai controllati o scaduto l'intervallo
    (15 gg top account / 30 gg standard, colonna monitor_interval_days).
    Include il dominio azienda salvato per il confronto job-change."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT cc.*, cd.domain AS company_domain,
                      cd.company_name, cd.sector AS company_sector,
                      cd.country_code AS company_country
               FROM company_contacts cc
               JOIN company_dossiers cd ON cd.company_id = cc.company_id
               WHERE cc.status='ACTIVE'
                 AND (cc.last_checked_at IS NULL
                      OR cc.last_checked_at <= datetime('now',
                          '-' || cc.monitor_interval_days || ' days'))
               ORDER BY cc.last_checked_at IS NULL DESC, cc.last_checked_at
               LIMIT ?""",
            (limit,)).fetchall()]


def update_contact_check(contact_id: str, email_status: str | None = None,
                         job_title: str | None = None,
                         status: str | None = None,
                         external_person_id: str | None = None):
    """Aggiorna esito verifica periodica sul referente."""
    sets, params = ["last_checked_at=?"], [_now_iso()]
    if email_status:
        sets.append("email_status=?")
        params.append(email_status)
    if job_title:
        sets.append("job_title=?")
        params.append(job_title)
    if status:
        sets.append("status=?")
        params.append(status)
    if external_person_id:
        sets.append("external_person_id=?")
        params.append(external_person_id)
    params.append(contact_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE company_contacts SET {', '.join(sets)} WHERE contact_id=?",
            params)


def insert_change_event(contact_id: str, event_type: str,
                        old_value: str | None = None,
                        new_value: str | None = None,
                        payload: dict | None = None) -> int:
    """Registra un alert commerciale (cambio azienda, promozione, bounce)."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO contact_change_events
               (contact_id, event_type, old_value, new_value,
                generated_action_payload, is_reviewed, created_at)
               VALUES (?,?,?,?,?,0,?)""",
            (contact_id, event_type, old_value, new_value,
             json.dumps(payload or {}, ensure_ascii=False), _now_iso()))
        return int(cur.lastrowid)


def pending_change_events(limit: int = 200,
                          include_reviewed: bool = False) -> list[dict]:
    """Eventi da rivedere, arricchiti con dati referente e azienda."""
    where = "" if include_reviewed else "WHERE e.is_reviewed=0"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            f"""SELECT e.*, cc.full_name, cc.job_title, cc.email,
                       cc.status AS contact_status,
                       cd.company_name, cd.domain AS company_domain
                FROM contact_change_events e
                JOIN company_contacts cc ON cc.contact_id = e.contact_id
                LEFT JOIN company_dossiers cd ON cd.company_id = cc.company_id
                {where} ORDER BY e.created_at DESC LIMIT ?""",
            (limit,)).fetchall()]


def mark_event_reviewed(event_ids: list[int]):
    if not event_ids:
        return
    ph = ",".join("?" for _ in event_ids)
    with _connect() as conn:
        conn.execute(
            f"UPDATE contact_change_events SET is_reviewed=1 "
            f"WHERE event_id IN ({ph})", list(event_ids))


def pending_events_count() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM contact_change_events WHERE is_reviewed=0"
        ).fetchone()[0]


# ------------------------------------------------------------------------------
# OEM RADAR (Doppio Binario) & NEWS INTELLIGENCE
# ------------------------------------------------------------------------------

def upsert_oem(d: dict) -> str:
    """Inserisce/aggiorna un colosso OEM in watchlist. Chiave: oem_name.
    Ritorna oem_id."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT oem_id FROM oem_watchlist WHERE oem_name=?",
            (d.get("oem_name") or "",)).fetchone()
        oid = row["oem_id"] if row else _uuid.uuid4().hex
        conn.execute(
            """INSERT INTO oem_watchlist
               (oem_id, oem_name, aliases_json, sector,
                production_sites_json, target_standards_json,
                active, last_scanned_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(oem_id) DO UPDATE SET
                aliases_json = COALESCE(NULLIF(excluded.aliases_json,'[]'), aliases_json),
                sector       = excluded.sector,
                production_sites_json = COALESCE(NULLIF(excluded.production_sites_json,'[]'), production_sites_json),
                target_standards_json = COALESCE(NULLIF(excluded.target_standards_json,'[]'), target_standards_json),
                active       = excluded.active""",
            (oid, d.get("oem_name") or "",
             json.dumps(d.get("aliases") or d.get("aliases_json") or [],
                        ensure_ascii=False)
             if not isinstance(d.get("aliases_json"), str)
             else d["aliases_json"],
             d.get("sector") or "",
             json.dumps(d.get("production_sites") or
                        d.get("production_sites_json") or [],
                        ensure_ascii=False)
             if not isinstance(d.get("production_sites_json"), str)
             else d["production_sites_json"],
             json.dumps(d.get("target_standards") or
                        d.get("target_standards_json") or [],
                        ensure_ascii=False)
             if not isinstance(d.get("target_standards_json"), str)
             else d["target_standards_json"],
             1 if d.get("active", True) else 0,
             d.get("last_scanned_at")))
        return oid


def list_oems(active_only: bool = True) -> list[dict]:
    where = "WHERE active=1" if active_only else ""
    with _connect() as conn:
        out = []
        for r in conn.execute(
                f"SELECT * FROM oem_watchlist {where} "
                "ORDER BY sector, oem_name").fetchall():
            d = dict(r)
            for k in ("aliases_json", "production_sites_json",
                      "target_standards_json"):
                try:
                    d[k[:-5]] = json.loads(d.get(k) or "[]")
                except (ValueError, TypeError):
                    d[k[:-5]] = []
            out.append(d)
        return out


def mark_oem_scanned(oem_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE oem_watchlist SET last_scanned_at=? WHERE oem_id=?",
            (_now_iso(), oem_id))


def oem_count() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM oem_watchlist WHERE active=1").fetchone()[0]


def insert_contract_alert(d: dict) -> str | None:
    """Registra un alert commessa madre. Dedup su source_url: ritorna None
    se l'URL era gia' segnalato."""
    url = d.get("source_url") or ""
    with _connect() as conn:
        if url and conn.execute(
                "SELECT 1 FROM oem_contract_alerts WHERE source_url=?",
                (url,)).fetchone():
            return None
        aid = _uuid.uuid4().hex
        conn.execute(
            """INSERT INTO oem_contract_alerts
               (alert_id, oem_id, contract_summary, probable_site,
                suggested_mb_cables, source_url, source_title,
                detected_at, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (aid, d.get("oem_id") or "",
             d.get("contract_summary") or "", d.get("probable_site"),
             json.dumps(d.get("suggested_mb_cables") or [],
                        ensure_ascii=False),
             url, d.get("source_title") or "", _now_iso(),
             d.get("status") or "NEW"))
        return aid


def list_contract_alerts(status: str | None = None,
                         limit: int = 100) -> list[dict]:
    where = "WHERE a.status=?" if status else ""
    params: list = []
    if status:
        params.append(status)
    params.append(limit)
    with _connect() as conn:
        out = []
        for r in conn.execute(
                f"""SELECT a.*, w.oem_name, w.sector
                    FROM oem_contract_alerts a
                    LEFT JOIN oem_watchlist w ON w.oem_id=a.oem_id
                    {where} ORDER BY a.detected_at DESC LIMIT ?""",
                params).fetchall():
            d = dict(r)
            try:
                d["suggested_mb_cables"] = json.loads(
                    d.get("suggested_mb_cables") or "[]")
            except (ValueError, TypeError):
                d["suggested_mb_cables"] = []
            out.append(d)
        return out


def set_alert_status(alert_id: str, status: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE oem_contract_alerts SET status=? WHERE alert_id=?",
            (status, alert_id))


def new_alerts_count() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM oem_contract_alerts WHERE status='NEW'"
        ).fetchone()[0]


def save_news_signal(d: dict) -> str | None:
    """Salva un segnale news classificato. Dedup (company_key, source_url):
    ritorna None se gia' presente."""
    url = d.get("source_url") or ""
    key = d.get("company_key") or ""
    with _connect() as conn:
        if url and conn.execute(
                "SELECT 1 FROM company_news_signals "
                "WHERE company_key=? AND source_url=?",
                (key, url)).fetchone():
            return None
        sid = _uuid.uuid4().hex
        conn.execute(
            """INSERT INTO company_news_signals
               (signal_id, company_key, company_name, article_title,
                published_date, signal_category, source_url,
                outreach_hook, language, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, key, d.get("company_name") or "",
             d.get("article_title") or "", d.get("published_date"),
             d.get("signal_category") or "", url,
             d.get("outreach_hook") or "", d.get("language") or "en",
             _now_iso()))
        return sid


def get_news_signals(company_key: str, days: int = 90,
                     limit: int = 20) -> list[dict]:
    """Segnali news recenti di un'azienda (default ultimi 90 gg)."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM company_news_signals
               WHERE company_key=?
                 AND detected_at >= datetime('now', ?)
               ORDER BY published_date DESC, detected_at DESC LIMIT ?""",
            (company_key, f"-{int(days)} days", limit)).fetchall()]


def latest_outreach_hook(company_key: str, days: int = 90) -> str:
    """Gancio outreach piu' recente per la company, '' se assente."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT outreach_hook FROM company_news_signals
               WHERE company_key=? AND outreach_hook<>''
                 AND detected_at >= datetime('now', ?)
               ORDER BY published_date DESC, detected_at DESC LIMIT 1""",
            (company_key, f"-{int(days)} days")).fetchone()
        return row["outreach_hook"] if row else ""


def latest_news_signal(company_key: str, days: int = 90) -> dict | None:
    """Ultimo segnale news (con URL) per mostrare fonte accanto alla bozza."""
    sigs = get_news_signals(company_key, days=days, limit=1)
    return sigs[0] if sigs else None

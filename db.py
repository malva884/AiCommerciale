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

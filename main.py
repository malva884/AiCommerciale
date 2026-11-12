"""Pipeline centrale di fetch, dedup e scoring delle opportunita' commerciali."""
import sys
import traceback
from datetime import datetime

import db
from config import GEMINI_DAILY_LIMIT
from fetchers import fetch_news, fetch_ted, fetch_ted_awards
from llm import (gemini_keys_count, gemini_quota_exhausted,
                 get_active_provider, heuristic_prescore, score_opportunity)


def _log(msg: str):
    """Log con timestamp: una riga per evento, flush immediato per il monitor live."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(use_llm: bool = True, provider: str | None = None):
    db.init_db()
    active_provider = (provider or get_active_provider()).lower()
    _log(f"AVVIO PIPELINE - Motore AI: {active_provider.upper()}")

    items = []
    steps = [
        ("Google News RSS", fetch_news),
        ("Bandi TED (attivi)", fetch_ted),
        ("Aggiudicazioni TED", fetch_ted_awards),
    ]
    for i, (label, fetch_fn) in enumerate(steps, 1):
        _log(f"[FASE {i}/3] Raccolta {label} in corso...")
        try:
            got = fetch_fn()
            items.extend(got)
            _log(f"[FASE {i}/3] {label}: {len(got)} segnali raccolti.")
        except Exception as exc:
            _log(f"[FASE {i}/3] ERRORE {label}: {exc}")

    _log(f"Salvataggio nel database: {len(items)} segnali totali...")
    inserted = 0
    for item in items:
        if db.insert_opportunity(item):
            inserted += 1
    _log(f"Database aggiornato: {inserted} nuove opportunita' inserite "
         f"({len(items) - inserted} duplicati scartati).")

    if use_llm:
        to_score = db.unscored(limit=250, include_heuristic=False)
        if active_provider == "gemini":
            # La quota giornaliera va ai candidati piu' promettenti: ordina per
            # score euristico decrescente (scoring rapido, zero chiamate API).
            to_score.sort(
                key=lambda r: heuristic_prescore(
                    r["title"], r["text"] or "", r["country"]),
                reverse=True)
        budget = max(0, GEMINI_DAILY_LIMIT * gemini_keys_count() - db.llm_calls_today())
        _log(f"Scoring AI in corso: {len(to_score)} opportunita' da valutare "
             f"(provider={active_provider.upper()}, budget Gemini residuo: {budget})")
        for i, row in enumerate(to_score, 1):
            if active_provider == "gemini" and gemini_quota_exhausted():
                _log(f"Quota Gemini esaurita ({GEMINI_DAILY_LIMIT * gemini_keys_count()}/giorno): "
                     f"{len(to_score) - i + 1} opportunita' rinviate al prossimo run.")
                break
            res = score_opportunity(
                title=row["title"],
                text=row["text"] or "",
                country_hint=row["country"],
                provider=active_provider,
            )
            db.update_score(row["id"], res)
            _log(f"  Scoring {i}/{len(to_score)} -> score={res.get('score')} "
                 f"({res.get('scored_by')}) | {(row['title'] or '')[:80]}")

    st = db.stats()
    _log(f"PIPELINE COMPLETATA. DB: {st['total']} opportunita' totali, "
         f"{st['scored']} valutate.")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        _log("ERRORE FATALE pipeline:")
        traceback.print_exc()
        sys.exit(1)

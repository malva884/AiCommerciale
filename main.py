"""Pipeline: fetch fonti pubbliche -> dedup SQLite -> scoring locale.

Uso:
    python main.py            # fetch + scoring (LLM se Ollama attivo)
    python main.py --no-llm   # forza scoring euristico
"""
import argparse
import sys

import db
from company_enrich import enrich_company
from fetchers import fetch_news, fetch_ted, fetch_ted_awards
from llm import (ollama_available, score_opportunity, _score_heuristic,
                 _extract_target)

# Evita caratteri '?' per accenti/simboli nella console PowerShell
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(use_llm: bool = True):
    db.init_db()

    print("== FETCH FONTI ==")
    items = fetch_news() + fetch_ted() + fetch_ted_awards()
    print(f"  trovate {len(items)} voci totali")

    new_count = sum(db.insert_opportunity(it) for it in items)
    print(f"  nuove (non gia' in DB): {new_count}")

    print("== SCORING ==")
    llm_on = use_llm and ollama_available()
    pending = db.unscored(include_heuristic=llm_on)
    if not pending:
        print("  niente da valutare")
    else:
        mode = "Ollama (LLM locale)" if llm_on else "euristico (fallback)"
        print(f"  {len(pending)} opportunita' da valutare - modalita': {mode}")
        for i, row in enumerate(pending, 1):
            country_hint = row["country"] if "country" in row.keys() else None
            if llm_on:
                result = score_opportunity(row["title"], row["text"] or "", country_hint)
            else:
                result = _score_heuristic(row["title"], row["text"] or "", country_hint)
            db.update_score(row["id"], result)
            print(f"  [{i}/{len(pending)}] score={result['score']:>3} "
                  f"[{result.get('sector') or 'Altro'}] "
                  f"{row['title'][:60]}")

    # Backfill: azienda cliente mancante su righe gia' classificate
    filled = 0
    for row in db.targets_missing():
        target = _extract_target(row["title"], row["text"] or "")
        if target:
            db.update_target(row["id"], target)
            filled += 1
    if filled:
        print(f"  cliente potenziale compilato su {filled} opportunita'")

    # Arricchimento dati pubblici delle aziende clienti (Wikidata)
    enriched = 0
    for name in db.companies_missing_info(limit=25):
        info = enrich_company(name)
        if info:
            db.upsert_company_info(name, info)
            enriched += 1
    if enriched:
        print(f"  scheda aziendale creata per {enriched} clienti")

    s = db.stats()
    print(f"== FINE == totale {s['total']}, valutate {s['scored']}")
    print("Apri la dashboard con: streamlit run app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true",
                        help="salta Ollama e usa solo lo scoring euristico")
    args = parser.parse_args()
    run(use_llm=not args.no_llm)

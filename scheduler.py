"""Worker di background per esecuzione automatica notturna della pipeline.

Gira come servizio Docker dedicato in docker-compose su Coolify.
- Condivide il volume SQLite con il servizio Streamlit (app_data -> /app/data).
- Schedula l'aggiornamento ogni notte all'orario specificato da NIGHTLY_SCHEDULE_TIME (default 01:00).
- Se al primo avvio il database e' completamente vuoto (0 opportunita'), esegue subito
  un primo ciclo di popolamento per non lasciare la dashboard vuota.
"""
import os
import sys
import time
from datetime import datetime

import schedule

import db
from main import run as run_pipeline

# Evita problemi di encoding su log console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEDULE_TIME = os.environ.get("NIGHTLY_SCHEDULE_TIME", "01:00")
RUN_ON_STARTUP_IF_EMPTY = os.environ.get("RUN_ON_STARTUP_IF_EMPTY", "1").lower() in ("1", "true", "yes")


def job():
    start = datetime.now()
    print(f"\n{'='*60}")
    print(f"[{start.strftime('%Y-%m-%d %H:%M:%S')}] AVVIO PIPELINE NOTTURNA BACKGROUND")
    print(f"{'='*60}")
    try:
        run_pipeline(use_llm=True)
    except Exception as exc:
        print(f"ERRORE durante la pipeline notturna: {exc}", file=sys.stderr)
        db.log_error("pipeline", target="scheduler notturno",
                     error_type=type(exc).__name__, message=str(exc))
    elapsed = (datetime.now() - start).total_seconds()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PIPELINE COMPLETATA in {elapsed/60:.1f} min")


def main():
    print(f"[Scheduler] Avviato worker background.")
    print(f"[Scheduler] Orario schedulato ogni notte: {SCHEDULE_TIME}")

    db.init_db()
    st = db.stats()
    print(f"[Scheduler] Stato DB all'avvio: {st['total']} opportunita' presenti.")

    if RUN_ON_STARTUP_IF_EMPTY and st["total"] == 0:
        print("[Scheduler] DB vuoto rilevato al bootstrap: avvio primo fetch immediato...")
        job()

    schedule.every().day.at(SCHEDULE_TIME).do(job)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

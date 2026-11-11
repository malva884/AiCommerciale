"""Worker di background per esecuzione automatica notturna della pipeline.

Gira come servizio Docker dedicato in docker-compose su Coolify.
- Condivide il volume SQLite con il servizio Streamlit (app_data -> /app/data).
- Schedula l'aggiornamento ogni notte all'orario specificato da NIGHTLY_SCHEDULE_TIME (default 01:00).
- Se al primo avvio il database e' completamente vuoto (0 opportunita'), esegue subito
  un primo ciclo di popolamento per non lasciare la dashboard vuota.
"""
import os
import sys
import threading
import time
from datetime import datetime

import schedule

import db
from llm import ollama_available
from main import run as run_pipeline

# Evita problemi di encoding su log console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEDULE_TIME = os.environ.get("NIGHTLY_SCHEDULE_TIME", "01:00")
RUN_ON_STARTUP_IF_EMPTY = os.environ.get("RUN_ON_STARTUP_IF_EMPTY", "1").lower() in ("1", "true", "yes")

_job_lock = threading.Lock()


def wait_for_ollama(timeout_sec: int = 120) -> bool:
    """Attende che Ollama sia online prima di partire (utile al primo boot)."""
    start = time.time()
    print("[Scheduler] Verifica disponibilita' Ollama...", flush=True)
    while time.time() - start < timeout_sec:
        if ollama_available():
            print("[Scheduler] Ollama e' online e pronto.", flush=True)
            return True
        time.sleep(3)
    print(f"[Scheduler] ATTENZIONE: Ollama non ha risposto entro {timeout_sec}s, si procede con fallback euristico.", flush=True)
    return False


def job():
    """Esecuzione protetta da lock contro sovrapposizioni."""
    if not _job_lock.acquire(blocking=False):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUN NOTTURNO SALTATO: pipeline gia' in corso.", flush=True)
        return

    start = datetime.now()
    try:
        print(f"\n{'='*60}", flush=True)
        print(f"[{start.strftime('%Y-%m-%d %H:%M:%S')}] AVVIO PIPELINE NOTTURNA BACKGROUND", flush=True)
        print(f"{'='*60}", flush=True)

        run_pipeline(use_llm=True)

        elapsed = (datetime.now() - start).total_seconds()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PIPELINE COMPLETATA in {elapsed/60:.1f} min", flush=True)
    except Exception as exc:
        print(f"ERRORE durante la pipeline notturna: {exc}", file=sys.stderr, flush=True)
        db.log_error("pipeline", target="scheduler notturno",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _job_lock.release()


def main():
    print(f"[Scheduler] Avviato worker background.", flush=True)
    print(f"[Scheduler] Orario schedulato ogni notte: {SCHEDULE_TIME}", flush=True)

    db.init_db()
    st = db.stats()
    print(f"[Scheduler] Stato DB all'avvio: {st['total']} opportunita' presenti.", flush=True)

    if RUN_ON_STARTUP_IF_EMPTY and st["total"] == 0:
        print("[Scheduler] DB vuoto rilevato al bootstrap: attesa Ollama e avvio primo fetch...", flush=True)
        wait_for_ollama(timeout_sec=120)
        job()

    schedule.every().day.at(SCHEDULE_TIME).do(job)

    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == "__main__":
    main()

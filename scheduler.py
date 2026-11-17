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

import config
import db
from llm import (ollama_available, set_active_provider, set_gemini_keys,
                 set_ollama_fallback)
from main import run as run_pipeline

# Evita problemi di encoding su log console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEDULE_TIME = os.environ.get("NIGHTLY_SCHEDULE_TIME", "01:00")
MORNING_DIGEST_TIME = os.environ.get("MORNING_REPORT_TIME",
                                     config.MORNING_REPORT_TIME)
RUN_ON_STARTUP_IF_EMPTY = os.environ.get("RUN_ON_STARTUP_IF_EMPTY", "1").lower() in ("1", "true", "yes")

_job_lock = threading.Lock()
_digest_lock = threading.Lock()
_monitor_lock = threading.Lock()
_radar_lock = threading.Lock()


def _load_llm_settings_from_db():
    """Applica allo scheduler le stesse impostazioni 'Motore AI' salvate
    dalla dashboard in app_settings (provider, chiavi, modelli, fallback).
    Priorita': DB > env var > default codice, come in app.py."""
    provider = (db.get_setting("LLM_PROVIDER") or config.LLM_PROVIDER
                or "ollama").lower()
    gemini_key = (db.get_setting("GEMINI_API_KEY") or "").strip()
    extra = [k.strip() for k in (db.get_setting("GEMINI_API_KEYS") or "").split(",")
             if k.strip()]
    db_keys = ([gemini_key] if gemini_key else []) + extra
    set_gemini_keys(db_keys)  # lista vuota -> fallback su chiavi da env

    set_active_provider(
        provider,
        api_key=gemini_key or None,
        gemini_model=db.get_setting("GEMINI_MODEL") or None,
        ollama_model=db.get_setting("OLLAMA_MODEL") or None,
    )

    fb = db.get_setting("DISABLE_OLLAMA_FALLBACK")
    if fb is not None:
        set_ollama_fallback(fb != "1")

    n_keys = len(db_keys) or len(config.GEMINI_API_KEYS) + bool(config.GEMINI_API_KEY)
    print(f"[Scheduler] Motore AI: provider={provider}, "
          f"chiavi Gemini configurate={n_keys}", flush=True)


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

        _load_llm_settings_from_db()  # recepisce cambi dalla UI senza restart
        run_pipeline(use_llm=True)

        elapsed = (datetime.now() - start).total_seconds()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PIPELINE COMPLETATA in {elapsed/60:.1f} min", flush=True)
    except Exception as exc:
        print(f"ERRORE durante la pipeline notturna: {exc}", file=sys.stderr, flush=True)
        db.log_error("pipeline", target="scheduler notturno",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _job_lock.release()


def morning_digest_job():
    """Digest email commerciale del mattino (lun-ven): protetto da lock
    dedicato per non interferire con la pipeline notturna. Errori SMTP
    e imprevisti finiscono in fetch_errors con source='notifier'."""
    if not _digest_lock.acquire(blocking=False):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "DIGEST SALTATO: invio precedente ancora in corso.", flush=True)
        return
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "AVVIO DIGEST EMAIL MATTUTINO", flush=True)
        import notifier
        report = notifier.run_morning_digest()
        sent = sum(1 for r in report if r["status"] == "SENT")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"DIGEST COMPLETATO: {sent} email inviate, "
              f"{len(report) - sent} regole senza invio.", flush=True)
    except Exception as exc:
        print(f"ERRORE durante il digest mattutino: {exc}",
              file=sys.stderr, flush=True)
        db.log_error("notifier", target="digest mattutino",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _digest_lock.release()


def contact_monitor_job():
    """Job Change Monitoring settimanale: verifica i referenti ACTIVE il cui
    intervallo e' scaduto (15 gg top account / 30 gg standard) e scatena le
    azioni a catena (champion tracking, backfill, alert eventi)."""
    if not _monitor_lock.acquire(blocking=False):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "CONTACT MONITOR SALTATO: run precedente in corso.", flush=True)
        return
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "AVVIO JOB CHANGE MONITORING", flush=True)
        import contact_monitor
        rep = contact_monitor.run_monitor_batch(limit=200)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"MONITOR COMPLETATO: {rep['checked']} verificati, "
              f"{len(rep['events'])} eventi, "
              f"{rep['skipped']} saltati.", flush=True)
    except Exception as exc:
        print(f"ERRORE durante il contact monitoring: {exc}",
              file=sys.stderr, flush=True)
        db.log_error("contact_monitor", target="scheduler settimanale",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _monitor_lock.release()


def oem_radar_job():
    """Radar Commesse Madre giornaliero: scansiona la watchlist OEM/Tier-0
    via Google News RSS + Search API, conferma LLM, alert al Key Account."""
    if not _radar_lock.acquire(blocking=False):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "OEM RADAR SALTATO: run precedente in corso.", flush=True)
        return
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "AVVIO OEM RADAR", flush=True)
        import oem_tier_radar
        rep = oem_tier_radar.run_radar(days=30)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"RADAR: {rep['scanned']} OEM, {rep['new_alerts']} nuovi "
              f"alert, {rep['errors']} errori.", flush=True)
    except Exception as exc:
        print(f"ERRORE OEM radar: {exc}", file=sys.stderr, flush=True)
        db.log_error("oem_radar", target="scheduler",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _radar_lock.release()


def news_intel_job():
    """News Intelligence settimanale: segnali 90gg + gancio outreach sui
    dossier Company Intelligence e i prospect qualificati. Include la
    Tier1/2 Discovery dei cablisti europei (richiede Search API)."""
    if not _radar_lock.acquire(blocking=False):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "NEWS INTEL SALTATO: run precedente in corso.", flush=True)
        return
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              "AVVIO NEWS INTELLIGENCE + TIER DISCOVERY", flush=True)
        import news_intelligence as ni
        import oem_tier_radar
        rep1 = ni.batch_update_companies(ni.collect_targets(limit=40))
        print(f"  [news_intel] {rep1['companies']} aziende, "
              f"{rep1['signals']} segnali salvati", flush=True)
        rep2 = oem_tier_radar.discover_tier_suppliers()
        print(f"  [tier_disc] {rep2['new_prospects']} nuovi prospect "
              f"({rep2['skipped_erp']} esclusi gia' clienti ERP)", flush=True)
    except Exception as exc:
        print(f"ERRORE news intelligence: {exc}", file=sys.stderr, flush=True)
        db.log_error("news_intel", target="scheduler",
                     error_type=type(exc).__name__, message=str(exc))
    finally:
        _radar_lock.release()


def main():
    print(f"[Scheduler] Avviato worker background.", flush=True)
    print(f"[Scheduler] Orario schedulato ogni notte: {SCHEDULE_TIME}", flush=True)

    db.init_db()
    _load_llm_settings_from_db()
    st = db.stats()
    print(f"[Scheduler] Stato DB all'avvio: {st['total']} opportunita' presenti.", flush=True)

    if RUN_ON_STARTUP_IF_EMPTY and st["total"] == 0:
        print("[Scheduler] DB vuoto rilevato al bootstrap: attesa Ollama e avvio primo fetch...", flush=True)
        wait_for_ollama(timeout_sec=120)
        job()

    schedule.every().day.at(SCHEDULE_TIME).do(job)

    # Digest email commerciale: lunedi-venerdi' al mattino
    print(f"[Scheduler] Digest email Lun-Ven ore {MORNING_DIGEST_TIME}",
          flush=True)
    for _wd in (schedule.every().monday, schedule.every().tuesday,
                schedule.every().wednesday, schedule.every().thursday,
                schedule.every().friday):
        _wd.at(MORNING_DIGEST_TIME).do(morning_digest_job)

    # Job Change Monitoring referenti: domenica mattina presto.
    # La cadenza 15/30 gg per contatto e' gestita da monitor_interval_days.
    print("[Scheduler] Job Change Monitoring: domenica ore 04:30", flush=True)
    schedule.every().sunday.at("04:30").do(contact_monitor_job)

    # OEM Radar Commesse Madre: ogni giorno alle 05:00.
    print("[Scheduler] OEM Radar Commesse Madre: ogni giorno ore 05:00",
          flush=True)
    schedule.every().day.at("05:00").do(oem_radar_job)

    # News Intelligence + Tier1/2 cablisti discovery: domenica 05:30.
    print("[Scheduler] News Intel + Tier1/2 Discovery: domenica ore 05:30",
          flush=True)
    schedule.every().sunday.at("05:30").do(news_intel_job)

    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == "__main__":
    main()

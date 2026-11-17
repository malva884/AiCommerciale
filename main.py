"""Pipeline centrale di fetch, dedup e scoring delle opportunita' commerciali."""
import sys
import traceback
from datetime import datetime

# Console Windows (cp1252): i titoli dei segnali possono contenere caratteri
# non codificabili (accenti, CJK, emoji) -> UnicodeEncodeError a meta' run.
# errors='replace' evita il crash sostituendoli con '?'.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

import db
from config import (BATCH_DEEP_DIVE_RESERVE, BATCH_SCORE_THRESHOLD,
                    GEMINI_DAILY_LIMIT, HEURISTIC_HARD_DISCARD,
                    LLM_BATCH_SIZE)
from fetchers import fetch_news, fetch_ted, fetch_ted_awards
from llm import (gemini_keys_count, gemini_quota_exhausted,
                 get_active_provider, heuristic_prescore,
                 score_opportunities_batch, score_opportunity)
from privacy_masker import PrivacyMasker


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
        is_gemini = active_provider == "gemini"
        total_quota = GEMINI_DAILY_LIMIT * gemini_keys_count() if is_gemini else 0

        def _quota_left() -> int:
            """Chiamate Gemini ancora disponibili oggi (illimitato se Ollama)."""
            if not is_gemini:
                return 10 ** 9
            return max(0, total_quota - db.llm_calls_today())

        _log(f"Scoring AI: provider={active_provider.upper()}, "
             f"chiamate Gemini oggi={db.llm_calls_today()}/{total_quota or 'n/a'}")

        # --- Data masking: vault effimero per la sessione di scoring ---
        # Le righe CRM hanno la ragione sociale in target_company: viene
        # tokenizzata ([CLIENTE_NN]) prima di qualsiasi payload LLM e i
        # risultati vengono re-idratati localmente prima del salvataggio.
        masker = PrivacyMasker()

        def _mask_for_llm(row) -> dict:
            """Copia della riga con entita' sensibili gia' tokenizzate."""
            r = dict(row)
            if (r.get("source") or "") == "crm" and r.get("target_company"):
                masker.mask_entity(r["target_company"], "CLIENTE")
                r["title"] = masker.mask_text(r.get("title") or "")
                r["text"] = masker.mask_text(r.get("text") or "")
            return r

        # ============ FASE 1: BATCH TRIAGE (scrematura massiva) ============
        if _quota_left() <= BATCH_DEEP_DIVE_RESERVE:
            _log(f"Quota residua <= {BATCH_DEEP_DIVE_RESERVE}: triage sospeso, "
                 "le chiamate restanti vanno solo al deep-dive dei BATCH_PASSED.")
        else:
            # La quota va ai candidati piu' promettenti: ordinamento per
            # prescore euristico decrescente (rapido, zero chiamate API).
            max_items = min(1000, max(250, _quota_left() * LLM_BATCH_SIZE))
            pending = db.pending_for_triage(limit=max_items)

            # Pre-scarto deterministico anti-rumore: prescore <= soglia ->
            # DISCARDED senza invio al Triage Gemini (costo zero quota).
            prescored = [(r, heuristic_prescore(dict(r))) for r in pending]
            hard_discards = [(r, s) for r, s in prescored
                             if s <= HEURISTIC_HARD_DISCARD]
            if hard_discards:
                for r, s in hard_discards:
                    db.update_triage_result(r["id"], {
                        "score": 0,
                        "sector": None,
                        "scored_by": "heuristic_filter",
                        "discard_reason": (
                            "Filtro euristico anti-rumore: "
                            f"prescore {s} <= {HEURISTIC_HARD_DISCARD}"),
                    }, "DISCARDED")
                _log(f"[TRIAGE] {len(hard_discards)} record scartati dal "
                     f"filtro euristico (prescore <= "
                     f"{HEURISTIC_HARD_DISCARD}): zero chiamate LLM.")
            prescored = [(r, s) for r, s in prescored
                         if s > HEURISTIC_HARD_DISCARD]
            prescored.sort(key=lambda t: t[1], reverse=True)
            pending = [r for r, _ in prescored]
            n_batches = (len(pending) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
            _log(f"[TRIAGE] {len(pending)} PENDING -> {n_batches} batch "
                 f"da {LLM_BATCH_SIZE} (soglia pass: {BATCH_SCORE_THRESHOLD})")
            done = passed_n = 0
            for b_start in range(0, len(pending), LLM_BATCH_SIZE):
                bnum = b_start // LLM_BATCH_SIZE + 1
                if is_gemini and (gemini_quota_exhausted()
                                  or _quota_left() <= BATCH_DEEP_DIVE_RESERVE):
                    _log("Quota Gemini quasi esaurita: triage interrotto, "
                         "i PENDING restano in coda per il prossimo run.")
                    break
                batch = pending[b_start:b_start + LLM_BATCH_SIZE]
                results = score_opportunities_batch(
                    [_mask_for_llm(r) for r in batch],
                    provider=active_provider)
                if results is None:
                    # Chiamata fallita (HTTP o parse): i record restano
                    # PENDING per il run successivo. L'euristica qui
                    # creerebbe falsi BATCH_PASSED e sprecherebbe quota
                    # nel deep-dive. Un errore di config si ripete su
                    # ogni batch: inutile continuare il ciclo.
                    db.log_error(
                        "triage_batch", target=f"batch {bnum}",
                        error_type="api_failure",
                        message="Risposta batch non valida: record "
                                "lasciati PENDING, triage interrotto")
                    _log(f"  Triage {bnum}/{n_batches}: batch LLM "
                         "fallito -> record restano PENDING, "
                         "triage interrotto.")
                    break
                returned = {res["id"] for res in results}
                for res in results:
                    status = ("BATCH_PASSED"
                              if res["score"] >= BATCH_SCORE_THRESHOLD
                              else "DISCARDED")
                    res = masker.unmask_result(res)  # token -> nomi reali
                    db.update_triage_result(res["id"], res, status)
                    done += 1
                    passed_n += status == "BATCH_PASSED"
                # Gli id mancanti nel JSON restano PENDING: riprocessati dopo
                missing = len(batch) - len(returned)
                _log(f"  Triage {bnum}/{n_batches}: {len(returned)}/{len(batch)} "
                     f"valutati ({passed_n} pass finora)"
                     + (f", {missing} id mancanti -> restano PENDING"
                        if missing else ""))
            _log(f"[TRIAGE] Fine: {done} classificati, "
                 f"{passed_n} promossi al deep-dive.")

        # ============ FASE 2: DEEP-DIVE (analisi completa 1-a-1) ============
        passed = db.passed_for_deep_dive(limit=1000)
        _log(f"[DEEP-DIVE] {len(passed)} opportunita' qualificate dal triage "
             f"(score >= {BATCH_SCORE_THRESHOLD}).")
        for i, row in enumerate(passed, 1):
            if is_gemini and gemini_quota_exhausted():
                _log(f"Quota Gemini esaurita ({total_quota}/giorno): "
                     f"{len(passed) - i + 1} deep-dive rinviati al prossimo run.")
                break
            row_m = _mask_for_llm(row)
            is_crm = (row_m.get("source") or "") == "crm"
            res = score_opportunity(
                title=row_m["title"],
                text=row_m["text"] or "",
                country_hint=row["country"],
                provider=active_provider,
                sensitive_guard=is_crm,  # guardrail su payload CRM
            )
            db.update_score(row["id"], masker.unmask_result(res))
            _log(f"  Deep-dive {i}/{len(passed)} -> score={res.get('score')} "
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

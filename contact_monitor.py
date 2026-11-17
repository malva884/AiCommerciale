"""Modulo C — Job Change Monitoring & automazioni a catena.

Batch job schedulato (scheduler.py, run settimanale): per ogni referente
ACTIVE scaduto il cui intervallo di monitoraggio e' trascorso
(15 gg top account / 30 gg standard, vedi contacts_due_for_check):

  C1. Verifica stato: people-match sul provider (Apollo) -> dominio e
      ruolo correnti + stato email (verified / unavailable / invalid).

  C2. Matrice decisionale:
      - dominio diverso dal salvato        -> MOVED_COMPANY
          * Champion Tracking: crea dossier stub sulla nuova azienda con
            flag WARM_CHAMPION_LEAD + bozza email di congratulazioni;
          * Backfill: cerca il sostituto sul vecchio dominio.
      - stesso dominio, ruolo diverso      -> PROMOTED_OR_CHANGED_ROLE
          * aggiorna job_title; evento ROLE_PROMOTION se ruolo decisionale.
      - email invalida, nessun nuovo posto -> LEFT_COMPANY
          * status LEFT_COMPANY + backfill sostituto.

Ogni evento e' persistito su contact_change_events con payload azione
(bozza email, nominativo sostituto) e flag is_reviewed per la UI.
"""
import json

import config
import contact_enrichment
import contact_finder
import db
from llm import generate_json_completion, is_llm_available

_EMAIL_INVALID_STATES = {"invalid", "unavailable", "bounced",
                         "hard_bounce", "not_found"}


# ---------------------------------------------------------------------------
# DRAFT EMAIL / NOTIFY
# ---------------------------------------------------------------------------

_CONGRATS_PROMPT = """Sei il copywriter commerciale di un produttore europeo di cavi speciali.
Scrivi una breve email (max 120 parole, tono professionale caldo) di
congratulazioni a un contatto che ha cambiato azienda, proponendo un
aggiornamento sulle forniture di cavi speciali (fibra ottica e rame:
EN 45545, RINA/DNV, CPR B2ca, data center). Rispondi SOLO con testo
plain dell'email, senza oggetto in JSON."""


def _draft_congrats_email(contact: dict, new_company: str) -> str:
    """Bozza email congratulazioni + proposta tecnica (LLM o template)."""
    name = (contact.get("full_name") or "").split()[0] or "Gentile"
    if is_llm_available(None):
        txt, _p = generate_json_completion(
            "Rispondi con un oggetto JSON {\"email\": \"<testo>\"}",
            f"Contatto: {contact.get('full_name')} ({contact.get('job_title')})"
            f" -> nuova azienda: {new_company or 'nuova realta'}\n"
            f"{_CONGRATS_PROMPT}", timeout=45)
        if isinstance(txt, dict) and txt.get("email"):
            return txt["email"]
    return (f"Gentile {name},\n\n"
            f"congratulazioni per il nuovo ruolo presso {new_company}. "
            "Da produttori di cavi speciali (fibra ottica e rame, "
            "certificazioni EN 45545 / RINA-DNV / CPR B2ca) saremo lieti "
            "di presentarle le soluzioni tecniche per i vostri progetti.\n\n"
            "Restiamo a disposizione per una call conoscitiva.\n\n"
            "Cordiali saluti,\nTeam Commerciale")


def _notify_event(subject: str, body_html: str):
    """Best-effort: invia alert email all'Area Manager della prima regola
    SMTP attiva. Silenzioso se SMTP non configurato."""
    try:
        import notifier
        cfg = notifier.smtp_config()
        if not cfg.get("host") or not cfg.get("sender"):
            return
        rules = [r for r in db.get_notification_rules()
                 if r.get("active") and r.get("recipient_email")]
        if not rules:
            return
        notifier._send_smtp(cfg, rules[0]["recipient_email"],
                            subject, body_html)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MATRICE DECISIONALE
# ---------------------------------------------------------------------------

def _norm_domain(d: str) -> str:
    d = (d or "").lower().strip()
    for p in ("https://", "http://", "www."):
        if d.startswith(p):
            d = d[len(p):]
    return d.split("/")[0]


def _handle_moved_company(contact: dict, res: dict) -> dict:
    """Champion tracking sulla nuova azienda + backfill sul vecchio dominio."""
    new_domain = _norm_domain(res.get("current_domain"))
    new_company = res.get("current_company") or new_domain
    old_domain = contact.get("company_domain") or ""
    old_company = contact.get("company_name") or old_domain

    # 1) Champion tracking: la nuova azienda entra nel radar
    new_dossier = db.get_dossier_by_domain(new_domain) if new_domain else None
    if not new_dossier and new_domain:
        cid = db.upsert_company_dossier({
            "company_name": new_company, "domain": new_domain,
            "flags": "WARM_CHAMPION_LEAD"})
        db.add_company_flag(cid, "WARM_CHAMPION_LEAD")
        new_sector = None
    else:
        cid = (new_dossier or {}).get("company_id") or ""
        if cid:
            db.add_company_flag(cid, "WARM_CHAMPION_LEAD")
        new_sector = (new_dossier or {}).get("sector")

    in_target = (new_sector in config.SECTORS
                 and new_sector != "Altro") if new_sector else True
    # sector sconosciuto -> trattiamo come potenzialmente target (flag lead)

    # 2) Backfill: sostituto sul vecchio dominio
    replacement = []
    if old_domain:
        try:
            replacement = contact_enrichment.find_replacement(
                old_domain, contact.get("job_title") or "",
                exclude_emails={(contact.get("email") or "").lower()})
        except Exception:
            replacement = []

    email_draft = _draft_congrats_email(contact, new_company)
    payload = {
        "action": "CHAMPION_TRACKING",
        "new_company": new_company, "new_domain": new_domain,
        "new_company_id": cid, "new_sector": new_sector,
        "in_target_sectors": in_target,
        "congrats_email_draft": email_draft,
        "replacement_candidates": replacement,
        "replacement_count": len(replacement),
    }
    db.insert_change_event(
        contact["contact_id"], "COMPANY_CHANGE",
        old_value=f"{contact.get('job_title')} @ {old_company}",
        new_value=f"{res.get('current_title')} @ {new_company}",
        payload=payload)

    # Aggiorna stato contatto: marcato MOVED; il referente viene "seguito"
    # anche sulla nuova azienda come nuovo contatto champion
    db.update_contact_check(contact["contact_id"],
                            status="MOVED_COMPANY")
    if cid and res.get("email"):
        db.save_company_contacts(cid, [{
            "full_name": res.get("full_name") or contact.get("full_name"),
            "job_title": res.get("current_title") or contact.get("job_title"),
            "department": contact_enrichment.classify_department(
                res.get("current_title")) or contact.get("department") or "MANAGEMENT",
            "email": res["email"].lower(),
            "email_status": "VALID",
            "linkedin_url": contact.get("linkedin_url") or "",
            "external_person_id": res.get("person_id") or "",
            "source_provider": contact.get("source_provider") or "apollo",
            "previous_company_id": contact.get("company_id"),
            "monitor_interval_days": contact.get("monitor_interval_days") or 30,
        }])
    return {"type": "COMPANY_CHANGE", "new_company": new_company,
            "in_target": in_target,
            "replacements": len(replacement)}


def _handle_role_change(contact: dict, res: dict) -> dict:
    new_title = res.get("current_title") or ""
    old_title = contact.get("job_title") or ""
    promoted = (contact_enrichment._is_decisional_title(new_title)
                and not contact_enrichment._is_decisional_title(old_title))
    db.update_contact_check(contact["contact_id"],
                            job_title=new_title,
                            email_status="VALID")
    db.insert_change_event(
        contact["contact_id"], "ROLE_PROMOTION",
        old_value=old_title, new_value=new_title,
        payload={"action": "ROLE_UPDATE", "promoted_to_decisional": promoted,
                 "company": contact.get("company_name")})
    if promoted:
        _notify_event(
            f"Promozione referente: {contact.get('full_name')} "
            f"({contact.get('company_name')})",
            f"<p><b>{contact.get('full_name')}</b> e' passato da "
            f"<i>{old_title}</i> a <i>{new_title}</i> presso "
            f"<b>{contact.get('company_name')}</b> — contatto ora "
            f"decisionale.</p>")
    return {"type": "ROLE_PROMOTION", "promoted": promoted}


def _handle_left_company(contact: dict, res: dict | None) -> dict:
    domain = contact.get("company_domain") or ""
    replacement = []
    if domain:
        try:
            replacement = contact_enrichment.find_replacement(
                domain, contact.get("job_title") or "",
                exclude_emails={(contact.get("email") or "").lower()})
        except Exception:
            replacement = []
    db.update_contact_check(contact["contact_id"], email_status="INVALID",
                            status="LEFT_COMPANY")
    db.insert_change_event(
        contact["contact_id"], "EMAIL_BOUNCED",
        old_value=contact.get("email"),
        new_value=None,
        payload={"action": "BACKFILL",
                 "company": contact.get("company_name"),
                 "replacement_candidates": replacement,
                 "replacement_count": len(replacement)})
    return {"type": "LEFT_COMPANY", "replacements": len(replacement)}


# ---------------------------------------------------------------------------
# JOB PRINCIPALE
# ---------------------------------------------------------------------------

def check_contact(contact: dict) -> dict:
    """Verifica puntuale di un referente. Ritorna esito azione."""
    res = contact_finder.verify_person(
        person_id=contact.get("external_person_id") or None,
        linkedin_url=contact.get("linkedin_url") or None,
        email=contact.get("email") or None,
        full_name=contact.get("full_name") or None,
        domain=contact.get("company_domain") or None)

    if res is None:
        # provider non configurato o lookup fallito: solo email check
        db.update_contact_check(contact["contact_id"])
        return {"type": "SKIPPED", "reason": "provider_unavailable"}

    saved_domain = _norm_domain(contact.get("company_domain"))
    current_domain = _norm_domain(res.get("current_domain"))
    new_title = res.get("current_title") or ""
    old_title = contact.get("job_title") or ""
    email_state = (res.get("email_status") or "").lower()

    # email_status 'verified' -> VALID; stati negativi -> INVALID
    email_status = ("VALID" if email_state in ("verified", "valid", "")
                    else "INVALID")

    if current_domain and saved_domain and current_domain != saved_domain:
        return _handle_moved_company(contact, res)

    if email_state in _EMAIL_INVALID_STATES:
        return _handle_left_company(contact, res)

    if new_title and old_title and new_title.lower() != old_title.lower():
        return _handle_role_change(contact, res)

    db.update_contact_check(contact["contact_id"],
                            email_status=email_status,
                            external_person_id=res.get("person_id") or None)
    return {"type": "OK", "email_status": email_status}


def run_monitor_batch(limit: int = 100, verbose: bool = True) -> dict:
    """Entry point scheduler/UI: verifica tutti i referenti dovuti.
    Ritorna riepilogo per tipo di evento."""
    due = db.contacts_due_for_check(limit=limit)
    summary = {"checked": 0, "events": [], "skipped": 0}
    for c in due:
        try:
            outcome = check_contact(c)
        except Exception as exc:
            db.log_error("contact_monitor",
                         target=c.get("full_name"),
                         error_type=type(exc).__name__, message=str(exc))
            outcome = {"type": "ERROR"}
        summary["checked"] += 1
        if outcome["type"] in ("SKIPPED", "ERROR"):
            summary["skipped"] += 1
        elif outcome["type"] != "OK":
            summary["events"].append(
                {"contact": c.get("full_name"), **outcome})
            if verbose:
                print(f"  [monitor] {c.get('full_name')}: "
                      f"{outcome['type']}", flush=True)
    return summary


if __name__ == "__main__":
    db.init_db()
    rep = run_monitor_batch()
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))

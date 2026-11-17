"""Digest email mattutino per i responsabili commerciali (Lun-Ven).

Instrada le opportunita' COMPLETED non ancora notificate incrociando
Settore Target (5 verticali canonici) e Area Geografica, secondo le regole
di routing salvate in app_settings (fallback: config.DEFAULT_NOTIFICATION_ROUTING).

Flusso send_daily_digests():
  1. legge config SMTP (app_settings > env) e le regole attive;
  2. per ogni regola estrae i record (priorita' fonte, poi score) e li
     raggruppa per categoria (max_items_per_sector) + sezione Clienti ERP;
  3. SKIPPED_EMPTY se nessuna opportunita' per il destinatario;
  4. invia email HTML via SMTP e marca notified_at SOLO al termine del
     ciclo su tutti i destinatari (la stessa commessa puo' andare a piu'
     regole senza che il primo invio la sottragga alle successive).
"""
import html
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import db
from config import (COMPANY_LOGO_PATH, DASHBOARD_BASE_URL,
                    MORNING_REPORT_TIME, NOTIFY_SECTORS, SMTP_HOST,
                    SMTP_PASSWORD, SMTP_PORT, SMTP_SENDER, SMTP_USE_TLS,
                    SMTP_USER, normalize_sector)

try:
    # Gamma cavi consigliata: stesso motore della dashboard (nessuna dip.
    # da Streamlit, importabile in modo sicuro dal worker scheduler).
    from crm_analyzer import get_suggested_cable_solution
except Exception:  # pragma: no cover - import difensivo
    def get_suggested_cable_solution(sector, norms, text):
        return {"family": "Cavi speciali", "products": "—",
                "certifications": norms or "—", "pitch": ""}

SOURCE_LABELS = {
    "ted_award": "AGGIUDICAZIONE TED",
    "ted": "BANDO TED",
    "news": "NEWS",
    "crm": "ERP / CLIENTE STORICO",
}

SECTION_ICONS = {
    "Ferroviario": "🚆",
    "Navale/Offshore": "🚢",
    "Data Center": "🖥️",
    "Telecom/Provider": "📡",
    "Avio/Difesa": "✈️",
    "_ERP": "🔁",
}
SECTION_ORDER = ["Data Center", "Telecom/Provider", "Ferroviario",
                 "Navale/Offshore", "Avio/Difesa", "_ERP"]

# Ordinamento sezioni ERP in coda
ERP_SECTION = "_ERP"


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [notifier] {msg}",
          flush=True)


def smtp_config() -> dict:
    """Config SMTP effettiva: impostazioni UI (app_settings) > env/config."""
    return {
        "host": (db.get_setting("SMTP_HOST") or SMTP_HOST or "").strip(),
        "port": int(db.get_setting("SMTP_PORT") or SMTP_PORT or 587),
        "use_tls": (db.get_setting("SMTP_USE_TLS") or
                    ("1" if SMTP_USE_TLS else "0")).strip() != "0",
        "user": (db.get_setting("SMTP_USER") or SMTP_USER or "").strip(),
        "password": (db.get_setting("SMTP_PASSWORD")
                     or SMTP_PASSWORD or ""),
        "sender": (db.get_setting("SMTP_SENDER") or SMTP_SENDER or "").strip(),
        # SSL implicito (porta 465): default auto on quando porta == 465
        "use_ssl": ((db.get_setting("SMTP_USE_SSL") or "").strip() == "1"
                    or int(db.get_setting("SMTP_PORT") or SMTP_PORT or 587)
                    == 465),
        "dash_url": (db.get_setting("DASHBOARD_BASE_URL")
                     or DASHBOARD_BASE_URL or "").rstrip("/"),
        "logo_path": (db.get_setting("COMPANY_LOGO_PATH")
                      or COMPANY_LOGO_PATH or "").strip(),
    }


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _score_color(score: int) -> str:
    if score >= 80:
        return "#1a7f37"   # verde
    if score >= 60:
        return "#b58500"   # ambra
    return "#8b8b8b"       # grigio


def _card_html(r: dict, dash_url: str) -> str:
    """Scheda HTML di una singola opportunita' nel digest."""
    score = int(r.get("score") or 0)
    color = _score_color(score)
    src = SOURCE_LABELS.get(r.get("source") or "", (r.get("source") or "").upper())
    country = _esc(r.get("country")) or "—"
    target = _esc(r.get("target_company")) or "Non identificato"
    title = _esc(r.get("title"))
    link = f"{dash_url}/?opp_id={r['id']}"

    cable = get_suggested_cable_solution(r.get("sector"), r.get("norms"), "")
    norms = _esc(r.get("norms")) or "—"
    motivation = _esc(r.get("motivation")) or "—"
    action = _esc(r.get("action")) or "—"

    draft = _esc(r.get("email_draft"))
    draft_block = (
        f'''<div style="margin-top:8px;background:#f8f9fb;border:1px dashed
             #c3c9d4;border-radius:6px;padding:10px;font-family:Consolas,
             monospace;font-size:12px;white-space:pre-wrap;color:#333">
             <b>✉️ Bozza email pronta:</b><br>{draft}</div>'''
        if draft else "")

    url_btn = ""
    if r.get("url"):
        url_btn = (f'<a href="{html.escape(r["url"])}" style="margin-left:10px;'
                   f'color:#0a5cc4;text-decoration:none;font-size:12px">'
                   f'🔗 Fonte originale</a>')

    return f"""
<div style="border:1px solid #dfe3ea;border-left:5px solid {color};
     border-radius:8px;padding:14px 16px;margin:0 0 14px 0;background:#fff">
  <div style="font-size:13px;color:#666;margin-bottom:4px">
    <span style="display:inline-block;background:{color};color:#fff;
          border-radius:10px;padding:1px 10px;font-weight:bold">{score}/100</span>
    &nbsp;<b>{_esc(src)}</b>&nbsp;·&nbsp;{country}&nbsp;·&nbsp;🏢 {target}
  </div>
  <div style="font-size:15px;font-weight:bold;color:#1c2733;margin-bottom:6px">
    {title}</div>
  <div style="font-size:13px;color:#333"><b>💡 Analisi:</b> {motivation}</div>
  <div style="font-size:13px;color:#333;margin-top:3px">
    <b>🎯 Azione:</b> {action}</div>
  <div style="font-size:12px;color:#555;margin-top:6px">
    🏷️ <b>Normative:</b> <code>{norms}</code><br>
    📦 <b>Gamma consigliata ({_esc(cable.get('family'))}):</b>
       {_esc(cable.get('products'))}</div>
  {draft_block}
  <div style="margin-top:10px;font-size:12px">
    <a href="{link}" style="color:#0a5cc4;text-decoration:none;font-weight:bold">
      ▶ Apri scheda in dashboard</a>{url_btn}
  </div>
</div>"""


def _digest_html(recipient_name: str, groups: dict,
                 dash_url: str, date_str: str,
                 has_logo: bool = False) -> str:
    """Email HTML responsive a blocchi per categoria."""
    total = sum(len(v) for v in groups.values())
    sections = []
    for sec in SECTION_ORDER:
        rows = groups.get(sec)
        if not rows:
            continue
        icon = SECTION_ICONS.get(sec, "📌")
        label = ("Allerte Clienti Storici (ERP)" if sec == ERP_SECTION
                 else sec)
        cards = "".join(_card_html(dict(r), dash_url) for r in rows)
        sections.append(f"""
<h2 style="font-size:16px;color:#12335e;border-bottom:2px solid #12335e;
   padding-bottom:4px;margin:24px 0 12px 0">{icon} {_esc(label)}
   <span style="font-weight:normal;color:#777">({len(rows)})</span></h2>
{cards}""")

    logo_html = (
        '<div style="background:#ffffff;border-radius:8px;padding:10px 14px;'
        'margin-bottom:14px">'
        '<img src="cid:mb_logo" alt="Metallurgica Bresciana" '
        'style="max-height:52px;max-width:280px;display:block"></div>'
        if has_logo else "")

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef1f5;
     font-family:Segoe UI,Arial,sans-serif">
<div style="max-width:720px;margin:0 auto;padding:18px">
  <div style="background:#12335e;color:#fff;border-radius:10px 10px 0 0;
       padding:20px 24px">
    {logo_html}
    <div style="font-size:20px;font-weight:bold">
      ⚡ MB Sales Metriks — Digest Commerciale</div>
    <div style="font-size:13px;opacity:.85;margin-top:4px">
      {date_str} · {total} nuove opportunità per <b>{_esc(recipient_name)}</b>
    </div>
  </div>
  <div style="background:#f5f7fa;border-radius:0 0 10px 10px;
       padding:18px 24px;border:1px solid #dfe3ea;border-top:none">
    {''.join(sections)}
    <div style="font-size:11px;color:#888;margin-top:20px;border-top:
         1px solid #dfe3ea;padding-top:10px">
      Digest automatico — opportunità con scoring_status COMPLETED e
      score ≥ soglia della regola. Invio giornaliero Lun–Ven
      {MORNING_REPORT_TIME}. Non reinoltrare fuori dall'organizzazione.
    </div>
  </div>
</div></body></html>"""


def _send_smtp(cfg: dict, to_addr: str, subject: str, html_body: str):
    """Invio SMTP: SSL implicito (465) o plain + STARTTLS (587/25).

    Se SMTP_SENDER non e' un indirizzo email (es. 'MB Sales Metriks')
    viene usato come display name e SMTP_USER diventa il vero MAIL FROM:
    i server (Gmail, O365) rifiutano buste senza @.
    Ritorna (ok, errore).
    """
    sender = cfg["sender"]
    if "@" in sender:
        envelope_from, header_from = sender, sender
    else:
        real = cfg["user"] or sender
        envelope_from = real
        header_from = f'"{sender}" <{real}>' if sender else real

    # multipart/related: la parte alternative (HTML) + eventuale logo
    # allegato inline referenziato dall'HTML con src="cid:mb_logo".
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = header_from
    msg["To"] = to_addr
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    logo_path = cfg.get("logo_path") or ""
    if logo_path and os.path.isfile(logo_path):
        try:
            with open(logo_path, "rb") as f:
                img = MIMEImage(f.read())
            img.add_header("Content-ID", "<mb_logo>")
            img.add_header("Content-Disposition", "inline",
                           filename=os.path.basename(logo_path))
            msg.attach(img)
        except OSError:
            pass  # logo non leggibile: email comunque inviata senza
    try:
        ctx = ssl.create_default_context()
        if cfg["use_ssl"]:
            smtp_cls, kwargs = smtplib.SMTP_SSL, {"context": ctx}
        else:
            smtp_cls, kwargs = smtplib.SMTP, {}
        with smtp_cls(cfg["host"], cfg["port"], timeout=30, **kwargs) as srv:
            srv.ehlo()
            if not cfg["use_ssl"] and cfg["use_tls"]:
                srv.starttls(context=ctx)
                srv.ehlo()
            if cfg["user"]:
                srv.login(cfg["user"], cfg["password"])
            srv.sendmail(envelope_from, [to_addr], msg.as_string())
        return True, None
    except Exception as exc:
        return False, exc


def _groups_for_rule(rule: dict) -> dict:
    """Estrae e raggruppa le opportunita' per una regola di routing.

    Ritorna {sezione: [rows]}: sezioni = settori canonici + '_ERP'.
    Le allerte ERP (source='crm') non applicano il filtro settori della
    regola quando include_crm_alerts e' attivo: un cliente storico e'
    sempre rilevante per chi lo segue.
    """
    sectors = rule.get("sectors") or ["*"]
    areas = rule.get("areas") or ["*"]
    min_score = int(rule.get("min_score", 80) or 80)
    max_per = int(rule.get("max_items_per_sector", 3) or 3)

    rows = [dict(r) for r in db.opportunities_to_notify(
        sectors=sectors, areas=areas, min_score=min_score)]

    crm_rows = []
    if rule.get("include_crm_alerts", True):
        # Allerte ERP svincolate dal filtro settori della regola
        seen = {r["id"] for r in rows}
        crm_rows = [dict(r) for r in db.opportunities_to_notify(
            sectors=["*"], areas=areas, min_score=min_score)
            if r["source"] == "crm" and r["id"] not in seen][:max_per]

    groups: dict[str, list] = {}
    for r in rows + crm_rows:
        r["sector"] = normalize_sector(r.get("sector"))
        if r["source"] == "crm" and rule.get("include_crm_alerts", True):
            groups.setdefault(ERP_SECTION, []).append(r)
            continue
        if r["sector"] not in NOTIFY_SECTORS:  # 'Altro' escluso: anti-rumore
            continue
        bucket = groups.setdefault(r["sector"], [])
        if len(bucket) < max_per:
            bucket.append(r)
    return groups


def send_daily_digests(dry_run: bool = False,
                       test_recipient: str | None = None) -> list[dict]:
    """Invia un digest per ogni regola attiva.

    dry_run=True: invia verso test_recipient (o la rule stessa se non
    specificato) SENZA marcare notified_at — serve al test grafico/SMTP.
    Ritorna un report per riga: {rule, recipient, status, items, error}.
    """
    cfg = smtp_config()
    report = []
    notified_ids: set[int] = set()

    if not cfg["host"]:
        _log("SMTP_HOST non configurato: invio annullato.")
        return [{"rule": "-", "recipient": "-", "status": "NO_SMTP",
                 "items": 0, "error": "SMTP_HOST mancante"}]

    rules = [r for r in db.get_notification_rules() if r.get("active")]
    if not rules:
        _log("Nessuna regola di routing attiva.")
        return [{"rule": "-", "recipient": "-", "status": "NO_RULES",
                 "items": 0, "error": None}]

    date_str = datetime.now().strftime("%d/%m/%Y")
    for rule in rules:
        rid = rule.get("id") or "rule"
        recipient = (test_recipient or rule.get("recipient_email") or "").strip()
        name = rule.get("recipient_name") or recipient
        if not recipient:
            report.append({"rule": rid, "recipient": "-",
                           "status": "NO_RECIPIENT", "items": 0,
                           "error": "recipient_email mancante"})
            continue

        groups = _groups_for_rule(rule)
        n_items = sum(len(v) for v in groups.values())
        if n_items == 0:
            _log(f"{rid} -> {recipient}: SKIPPED_EMPTY (0 opportunita')")
            report.append({"rule": rid, "recipient": recipient,
                           "status": "SKIPPED_EMPTY", "items": 0,
                           "error": None})
            continue

        body = _digest_html(name, groups, cfg["dash_url"], date_str,
                            has_logo=bool(cfg["logo_path"]
                                          and os.path.isfile(
                                              cfg["logo_path"])))
        secs = ", ".join(s for s in SECTION_ORDER if groups.get(s))
        subject = (f"[MB Sales] Digest {date_str} — {n_items} opportunità"
                   f" ({secs.replace('_ERP', 'Clienti ERP')})")

        ok, err = _send_smtp(cfg, recipient, subject, body)
        if ok:
            _log(f"{rid} -> {recipient}: SENT ({n_items} schede"
                 + (", DRY-RUN" if dry_run else "") + ")")
            if not dry_run:
                for rows in groups.values():
                    notified_ids.update(r["id"] for r in rows)
            report.append({"rule": rid, "recipient": recipient,
                           "status": "SENT", "items": n_items,
                           "error": None})
        else:
            _log(f"{rid} -> {recipient}: FAILED ({err})")
            db.log_error("notifier", target=f"{rid} -> {recipient}",
                         error_type=type(err).__name__,
                         message=str(err))
            report.append({"rule": rid, "recipient": recipient,
                           "status": "FAILED", "items": n_items,
                           "error": str(err)})

    # notified_at al termine del ciclo: la stessa opportunita' puo'
    # comparire nel digest di piu' destinatari nello stesso run.
    if notified_ids and not dry_run:
        db.mark_notified(sorted(notified_ids))
        _log(f"{len(notified_ids)} opportunita' marcate notified_at.")

    return report


def run_morning_digest() -> list[dict]:
    """Entry point per lo scheduler (Lun-Ven MORNING_REPORT_TIME)."""
    _log(f"Avvio digest mattutino (regole attive, soglia per regola).")
    return send_daily_digests(dry_run=False)


if __name__ == "__main__":
    import sys

    _dr = "--dry-run" in sys.argv
    _to = next((a.split("=", 1)[1] for a in sys.argv
                if a.startswith("--to=")), None)
    for line in send_daily_digests(dry_run=_dr, test_recipient=_to):
        print(line, flush=True)

"""Modulo B — Estrazione Decision Maker con filtro ruoli e compliance GDPR.

Quando un'azienda viene profilata (company_dossiers) o qualificata come
prospect (match_score >= CONTACT_MONITOR_TOP_SCORE), interroga il provider
di enrichment configurato (Apollo.io / Proxycurl via contact_finder) con la
tassonomia ruoli multilingua, poi applica la validazione GDPR:

- scarta record senza email aziendale sul dominio dell'azienda;
- scarta email su domini consumer (gmail, yahoo, libero...);
- salva metadati di tracciamento: source_provider, verified_at,
  confidence_score, external_person_id.

Uso:
    contacts, err = enrich_company_contacts(company_id)
"""
import re
from datetime import datetime

import contact_finder
import db

# ---------------------------------------------------------------------------
# TASSONOMIA RUOLI TARGET (EN / DE / FR / IT / ES)
# ---------------------------------------------------------------------------

ROLE_TAXONOMY = {
    "PROCUREMENT": {
        "priority": 1,
        "titles": [
            "Head of Procurement", "Procurement Manager",
            "Commodity Manager", "Category Manager Electrical",
            "Category Buyer", "Lead Buyer", "Strategic Buyer",
            "Purchasing Manager", "Supply Chain Manager",
            "Einkaufsleiter", "Strategischer Einkäufer",
            "Directeur des Achats", "Acheteur",
            "Responsabile Acquisti", "Chief Procurement Officer",
        ],
        "keywords": [
            "procurement", "purchas", "buyer", "commodity", "category",
            "supply chain", "acquisti", "achat", "einkauf", "compras",
            "approvvigionamento", "sourcing",
        ],
    },
    "ENGINEERING": {
        "priority": 2,
        "titles": [
            "Chief Electrical Engineer", "Electrical Engineering Lead",
            "Homologation Manager", "Quality Director", "Quality Manager",
            "Technical Director", "Chief Engineer", "R&D Manager",
            "Engineering Manager", "Technischer Leiter",
            "Directeur Technique", "Direttore Tecnico",
            "Responsabile Qualità", "CTO",
        ],
        "keywords": [
            "engineer", "engineering", "technical", "technique",
            "homologation", "quality", "qualit", "tecnico", "technisch",
            "cto", "r&d", "research", "progettazione", "omologazione",
        ],
    },
    "PROJECT": {
        "priority": 3,
        "titles": [
            "Project Manager Electrical", "Project Manager",
            "Program Manager", "Data Center Infrastructure Lead",
            "Rolling Stock Manager", "Shipbuilding Manager",
            "Site Manager", "Commissioning Manager",
            "Chef de Projet", "Projektleiter",
            "Direttore di Commessa", "Project Engineer",
        ],
        "keywords": [
            "project", "program", "commessa", "projet", "projekt",
            "site", "commissioning", "infrastructure", "cantiere",
            "rolling stock", "shipbuilding", "installation",
        ],
    },
    "MANAGEMENT": {
        "priority": 4,
        "titles": [
            "Managing Director", "General Manager", "CEO", "COO",
            "Business Director", "Direttore Generale",
            "Geschäftsführer", "Directeur Général",
        ],
        "keywords": [
            "managing", "general manager", "ceo", "coo", "direttore",
            "geschäftsführer", "directeur général", "amministratore",
        ],
    },
}

# Domini consumer: un'email su questi domini non e' mai aziendale
CONSUMER_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.it", "yahoo.fr",
    "yahoo.de", "yahoo.es", "hotmail.com", "hotmail.it", "hotmail.fr",
    "outlook.com", "outlook.it", "live.com", "live.it", "msn.com",
    "libero.it", "virgilio.it", "tiscali.it", "tin.it", "alice.it",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
    "protonmail.com", "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
    "web.de", "t-online.de", "freenet.de", "orange.fr", "wanadoo.fr",
    "free.fr", "laposte.net", "sfr.fr", "yahoo.co.uk", "btinternet.com",
    "virgilio.it", "fastwebnet.it", "email.it", "pec.it",
}

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")


# ---------------------------------------------------------------------------
# VALIDAZIONE GDPR / QUALITA'
# ---------------------------------------------------------------------------

def _email_domain(email: str) -> str:
    m = _EMAIL_RE.match((email or "").strip())
    return (m.group(1) or "").lower() if m else ""


def _is_consumer_domain(domain: str) -> bool:
    return domain in CONSUMER_DOMAINS


def _on_company_domain(email_domain: str, company_domain: str) -> bool:
    """Email sul dominio aziendale esatto o sottodominio diretto."""
    cd = (company_domain or "").lower().removeprefix("www.")
    if not cd or not email_domain:
        return False
    return email_domain == cd or email_domain.endswith("." + cd)


def classify_department(title: str) -> str:
    """PROCUREMENT | ENGINEERING | PROJECT | MANAGEMENT | '' dal titolo."""
    low = (title or "").lower()
    best, best_hits = "", 0
    for dept, spec in ROLE_TAXONOMY.items():
        hits = sum(1 for k in spec["keywords"] if k in low)
        # boost sul match esatto di un titolo noto
        if any(t.lower() in low for t in spec["titles"]):
            hits += 2
        if hits > best_hits:
            best, best_hits = dept, hits
    return best


def _confidence(c: dict, company_domain: str) -> int:
    """Score 0-100 di affidabilita' del record."""
    score = 40  # base: presente nel provider
    email_dom = _email_domain(c.get("email"))
    if email_dom and _on_company_domain(email_dom, company_domain):
        score += 30
    if c.get("linkedin_url"):
        score += 15
    if classify_department(c.get("title") or c.get("job_title")):
        score += 15
    return min(score, 100)


def _is_decisional_title(title: str) -> bool:
    """True se il titolo indica un ruolo decisionale/direzionale alto.
    Usato anche dal monitor per rilevare promozioni."""
    low = (title or "").lower()
    return len(low) > 3 and any(k in low for k in (
        "head", "director", "chief", "vp", "vice president", "c-level",
        "leiter", "direttore", "responsabile", "directeur",
        "geschäftsführer", "manager"))


def validate_contact(c: dict, company_domain: str) -> dict | None:
    """Record normalizzato o None se scartato dalla validazione GDPR."""
    email = (c.get("email") or "").strip()
    email_dom = _email_domain(email)
    # 1. email obbligatoria e aziendale
    if not email_dom or _is_consumer_domain(email_dom):
        return None
    if not _on_company_domain(email_dom, company_domain):
        return None
    title = c.get("title") or c.get("job_title") or ""
    return {
        "full_name": (c.get("full_name") or "").strip(),
        "job_title": title.strip(),
        "department": classify_department(title) or "MANAGEMENT",
        "email": email.lower(),
        "email_status": "VALID",
        "linkedin_url": c.get("linkedin_url") or "",
        "external_person_id": c.get("person_id") or "",
        "source_provider": c.get("source") or "",
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "confidence_score": _confidence(c, company_domain),
    }


# ---------------------------------------------------------------------------
# ENRICHMENT PRINCIPALE
# ---------------------------------------------------------------------------

def all_target_titles() -> list[str]:
    """Lista piatta dei job title da passare al provider."""
    out = []
    for spec in sorted(ROLE_TAXONOMY.values(), key=lambda s: s["priority"]):
        out.extend(spec["titles"])
    return out


def enrich_company_contacts(company_id: str,
                            limit: int = 12,
                            provider_titles: bool = True,
                            ) -> tuple[list[dict], str | None]:
    """Cerca e valida i decision maker dell'azienda `company_id`.

    Ritorna (contatti_validi_salvati, errore). Degrada pulito se il dossier
    manca o il provider non e' configurato."""
    dossier = db.get_dossier(company_id)
    if not dossier:
        return [], "dossier azienda non trovato"
    domain = dossier.get("domain") or ""
    company_name = dossier.get("company_name") or domain

    raw, err = contact_finder.find_buyers(
        company_name,
        roles=all_target_titles() if provider_titles else None,
        domain=domain,
        limit=limit)
    if err:
        return [], err

    valid = []
    for c in raw:
        v = validate_contact(c, domain)
        if v and v["full_name"]:
            valid.append(v)

    # dedup per email, poi ordina per priorita' dipartimento e confidence
    seen, unique = set(), []
    prio = {d: s["priority"] for d, s in ROLE_TAXONOMY.items()}
    for v in sorted(valid,
                    key=lambda x: (prio.get(x["department"], 9),
                                   -x["confidence_score"])):
        if v["email"] in seen:
            continue
        seen.add(v["email"])
        unique.append(v)

    if unique:
        _apply_monitor_cadence(company_id, unique)
        db.save_company_contacts(company_id, unique)
    return unique, None


def _apply_monitor_cadence(company_id: str, contacts: list[dict]):
    """Imposta monitor_interval_days=15 se l'azienda e' un top account
    (cliente ERP nel dossier o prospect qualificato >= soglia)."""
    dossier = db.get_dossier(company_id) or {}
    is_top = bool((dossier.get("dossier_json") or {}).get("_erp", {})
                  .get("is_customer"))
    if not is_top:
        # prospect qualificato?
        try:
            pros = db.get_prospects(search=dossier.get("company_name") or "",
                                    include_erp=True, limit=1)
            is_top = bool(pros and (pros[0].get("match_score") or 0)
                          >= 65)
        except Exception:
            is_top = False
    days = 15 if is_top else 30
    for c in contacts:
        c["monitor_interval_days"] = days


def find_replacement(domain: str, old_title: str,
                     exclude_emails: set[str] | None = None,
                     limit: int = 5) -> list[dict]:
    """Backfill: cerca un sostituto con ruolo simile sul dominio aziendale.
    Usato dal job-change monitor quando un referente lascia/cambia."""
    dept = classify_department(old_title)
    titles = (ROLE_TAXONOMY.get(dept, {}).get("titles")
              or contact_finder.DEFAULT_TITLES)
    raw, _err = contact_finder.find_buyers(
        domain, roles=titles, domain=domain, limit=limit * 2)
    exclude = exclude_emails or set()
    out = []
    for c in raw:
        v = validate_contact(c, domain)
        if v and v["email"] not in exclude:
            out.append(v)
        if len(out) >= limit:
            break
    return out

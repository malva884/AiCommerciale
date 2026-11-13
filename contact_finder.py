"""Ricerca referenti/decision maker aziendali via provider dati LinkedIn.

LinkedIn non espone API pubbliche di people-search: questo modulo interroga
provider terzi (Apollo.io o Proxycurl) selezionabili dalle Impostazioni.
Degrada in modo pulito: senza chiave API le funzioni restituiscono
([] / errore) e la UI conserva il link di ricerca LinkedIn classico.
"""
import os

import requests

import db

PROVIDERS = {
    "apollo": "Apollo.io (People Search — nome, ruolo, LinkedIn, email)",
    "proxycurl": "Proxycurl (profili LinkedIn dipendenti — pay-per-use)",
}

# Ruoli buyer tipici usati quando il prospect non ha target_buyer_roles
DEFAULT_TITLES = [
    "Procurement", "Purchasing", "Buyer", "Category Manager",
    "Supply Chain", "Head of Procurement",
]

_TIMEOUT = 30

# NB: /mixed_people/search e' deprecato (risponde 422) — il nuovo endpoint
# per chiamate API e' /mixed_people/api_search. Auth via header x-api-key.
_APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
_PROXYCURL_BASE = "https://nubela.co/proxycurl/api"


def _provider() -> str:
    """Provider attivo: impostazione salvata da UI > env > 'apollo'."""
    return (db.get_setting("CONTACT_PROVIDER")
            or os.environ.get("CONTACT_PROVIDER")
            or "apollo").strip().lower()


def _api_key(provider: str) -> str:
    """Chiave del provider: app_settings (UI) > variabile d'ambiente."""
    env_name = "APOLLO_API_KEY" if provider == "apollo" else "PROXYCURL_API_KEY"
    return (db.get_setting(env_name) or os.environ.get(env_name) or "").strip()


def is_configured() -> bool:
    """True se esiste una chiave API per il provider selezionato."""
    return bool(_api_key(_provider()))


def active_provider_label() -> str:
    return PROVIDERS.get(_provider(), _provider())


def find_buyers(company_name: str, roles: list[str] | None = None,
                domain: str | None = None,
                limit: int = 8) -> tuple[list[dict], str | None]:
    """Cerca decision maker di `company_name` con ruoli procurement/buyer.

    Ritorna (contatti, errore). Ogni contatto:
    {full_name, title, linkedin_url, email, city, source}.
    errore e' None in caso di successo; una stringa descrittiva altrimenti.
    """
    provider = _provider()
    key = _api_key(provider)
    if not key:
        return [], "missing_key"
    try:
        if provider == "apollo":
            return _apollo_search(company_name, roles, domain, limit, key)
        if provider == "proxycurl":
            return _proxycurl_search(company_name, roles, limit, key)
        return [], f"provider sconosciuto: {provider}"
    except requests.RequestException as exc:
        db.log_error("contacts", target=company_name,
                     error_type=type(exc).__name__, message=str(exc))
        return [], str(exc)


# ----------------------------------------------------------------------------
# APOLLO.IO — People Search API
# ----------------------------------------------------------------------------

def _apollo_search(company_name: str, roles: list[str] | None,
                   domain: str | None, limit: int,
                   key: str) -> tuple[list[dict], str | None]:
    payload = {
        "page": 1,
        "per_page": max(1, min(limit, 25)),
        "person_titles": roles or DEFAULT_TITLES,
    }
    if domain:
        payload["q_organization_domains_list"] = [domain]
    else:
        payload["q_organization_name"] = company_name
    resp = requests.post(
        _APOLLO_SEARCH_URL,
        headers={"Cache-Control": "no-cache",
                 "Content-Type": "application/json",
                 "x-api-key": key},
        json=payload,
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        return [], f"Apollo HTTP {resp.status_code}: {resp.text[:200]}"
    contacts = []
    for p in resp.json().get("people", [])[:limit]:
        name = p.get("name") or " ".join(filter(None, [
            p.get("first_name"), p.get("last_name")])).strip()
        if not name:
            continue
        contacts.append({
            "full_name": name,
            "title": p.get("title") or "",
            "linkedin_url": p.get("linkedin_url") or "",
            # il people-search NON ritorna email (serve Enrich, a crediti):
            # lascio il campo vuoto ma la struttura e' gia' predisposta
            "email": p.get("email") or "",
            "city": p.get("city") or "",
            "source": "apollo",
        })
    return contacts, None


# ----------------------------------------------------------------------------
# PROXYCURL — Company resolve + Employee Listing (profili LinkedIn)
# ----------------------------------------------------------------------------

def _proxycurl_get(url: str, params: dict, key: str) -> requests.Response:
    return requests.get(
        url, params=params,
        headers={"Authorization": f"Bearer {key}"},
        timeout=_TIMEOUT,
    )


def _resolve_company_url(company_name: str, key: str) -> str | None:
    """Nome azienda -> URL profilo LinkedIn aziendale (Company Lookup)."""
    resp = _proxycurl_get(
        f"{_PROXYCURL_BASE}/linkedin/company/resolve",
        {"company_name": company_name}, key)
    if resp.status_code != 200:
        return None
    return resp.json().get("url")


def _proxycurl_search(company_name: str, roles: list[str] | None,
                      limit: int, key: str) -> tuple[list[dict], str | None]:
    company_li = _resolve_company_url(company_name, key)
    if not company_li:
        return [], (f"profilo LinkedIn aziendale non trovato per "
                    f"'{company_name}'")
    role_re = "|".join(roles) if roles else (
        "Procurement|Purchas|Buyer|Buying|Supply Chain|Acquisti|Achats|Einkauf")
    resp = _proxycurl_get(
        f"{_PROXYCURL_BASE}/v2/linkedin/company/employees/",
        {"url": company_li, "role_search": role_re,
         "page_size": max(1, min(limit, 10))}, key)
    if resp.status_code >= 400:
        return [], f"Proxycurl HTTP {resp.status_code}"
    contacts = []
    for emp in resp.json().get("employees", [])[:limit]:
        name = emp.get("full_name")
        if not name:
            continue
        contacts.append({
            "full_name": name,
            "title": emp.get("title") or "",
            "linkedin_url": emp.get("profile_url") or "",
            "email": "",
            "city": "",
            "source": "proxycurl",
        })
    return contacts, None

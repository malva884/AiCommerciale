"""Company Intelligence 360° — Deep Company Profiling on-demand.

Pipeline asincrona (asyncio) per il dossier commerciale di un'azienda:

  A1. Discovery & Deep Web Scraping: homepage -> sitemap/link interni ->
      max CI_MAX_PAGES pagine strategiche (about/sectors/products/quality/
      certifications/news/projects), testo pulito con trafilatura
      (fallback regex) troncato a CI_MAX_CHARS.

  A2. Query parallele su fonti esterne e interne (asyncio.gather):
      - Search API (Tavily / Serper.dev): progetti, espansioni, dati societari
      - TED API v3 (Award Notices): gare vinte negli ultimi CI_TED_MONTHS
      - ERP SQL Server: match fuzzy >=85% su ragione sociale -> storico ordini,
        fatturato triennio, famiglie cavi acquistate, ultimo ordine

  A3. Sintesi LLM con schema JSON rigido -> persistenza su company_dossiers.

Uso (sync):
    result = profile_company_sync("Stadler Rail", "https://www.stadlerrail.com")
Uso (async):
    result = await profile_company("Stadler Rail", "https://www.stadlerrail.com")
"""
import asyncio
import difflib
import json
import re
import time
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

import requests

import config
import db
import sqlserver_orders as sso
from crm_analyzer import normalize_company_name
from llm import (generate_json_completion, gemini_available,
                 gemini_quota_exhausted, is_llm_available)

try:
    import trafilatura  # estrazione testo pulito di qualita' superiore
except ImportError:  # pragma: no cover - opzionale
    trafilatura = None

_UA = {"User-Agent": "Mozilla/5.0 (compatible; MB-SalesIntel/1.0; "
                     "company profiling)"}
_ERP_MIN_RATIO = 0.85

# Slug/anchor strategici per la selezione delle pagine interne
_STRATEGIC_KEYWORDS = (
    "about", "chi-siamo", "company", "azienda", "group", "gruppo",
    "sector", "settore", "market", "solution", "soluzion", "product",
    "prodott", "quality", "qualita", "certification", "certificaz",
    "news", "press", "media", "project", "progett", "reference",
    "case-stud", "innovation", "innovazion", "technology", "tecnolog",
)
# Sotto-path da escludere (rumore: privacy, cookie, login, caricate)
_EXCLUDE_KEYWORDS = (
    "privacy", "cookie", "legal", "imprint", "login", "sign-in", "cart",
    "search", "lang=", "facebook", "twitter", "linkedin", "instagram",
    "youtube", "mailto:", "javascript:", "#", "whatsapp",
)

# ---------------------------------------------------------------------------
# SEARCH API (Tavily / Serper.dev)
# ---------------------------------------------------------------------------

_TAVILY_URL = "https://api.tavily.com/search"
_SERPER_URL = "https://google.serper.dev/search"


def _search_provider() -> str:
    return (db.get_setting("SEARCH_PROVIDER")
            or config.SEARCH_PROVIDER or "tavily").strip().lower()


def _search_api_key(provider: str) -> str:
    env_name = "TAVILY_API_KEY" if provider == "tavily" else "SERPER_API_KEY"
    fallback = (config.TAVILY_API_KEY if provider == "tavily"
                else config.SERPER_API_KEY)
    return (db.get_setting(env_name) or fallback or "").strip()


def search_api_configured() -> bool:
    return bool(_search_api_key(_search_provider()))


def web_search(query: str, max_results: int = 8,
               days: int | None = None) -> list[dict]:
    """Query su Tavily o Serper. Ritorna [{title,url,content,published}].

    days: recency filter Tavily (es. 365). Degrada a [] senza chiave.
    """
    provider = _search_provider()
    key = _search_api_key(provider)
    if not key:
        return []
    try:
        if provider == "tavily":
            payload = {"api_key": key, "query": query,
                       "max_results": max_results,
                       "search_depth": "basic"}
            if days:
                payload["days"] = days
            r = requests.post(_TAVILY_URL, json=payload, timeout=20)
            r.raise_for_status()
            return [{"title": it.get("title") or "",
                     "url": it.get("url") or "",
                     "content": (it.get("content") or "")[:600],
                     "published": it.get("published_date") or ""}
                    for it in r.json().get("results", [])]
        # Serper.dev
        r = requests.post(_SERPER_URL, json={"q": query, "num": max_results},
                          headers={"X-API-KEY": key,
                                   "Content-Type": "application/json"},
                          timeout=20)
        r.raise_for_status()
        out = []
        for it in r.json().get("organic", [])[:max_results]:
            out.append({"title": it.get("title") or "",
                        "url": it.get("link") or "",
                        "content": (it.get("snippet") or "")[:600],
                        "published": it.get("date") or ""})
        return out
    except requests.RequestException as exc:
        db.log_error("search_api", target=query[:80],
                     error_type=type(exc).__name__, message=str(exc))
        return []


_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def _discover_domain_llm(company_name: str) -> str:
    """Fallback: chiede all'LLM il dominio web ufficiale dell'azienda.
    Utile quando la Search API non e' configurata. '' se incerto."""
    if not _any_llm_path(None):
        return ""
    data, _p = generate_json_completion(
        "Sei un assistente B2B. Rispondi SOLO con un oggetto JSON.",
        (f"Qual e' il dominio web ufficiale (es. azienda.com) di "
         f"'{company_name}'? Rispondi {{\"domain\": \"<dominio o null>\"}}. "
         "Usa null se non sei ragionevolmente sicuro. Nessun testo extra."),
        timeout=30)
    dom = ""
    if isinstance(data, dict):
        dom = str(data.get("domain") or "").strip().lower()
        dom = dom.removeprefix("https://").removeprefix("http://")
        dom = dom.removeprefix("www.").split("/")[0]
    return dom if _DOMAIN_RE.match(dom) else ""


def discover_domain(company_name: str) -> str:
    """Dominio aziendale stimato: Search API -> fallback LLM ('' se ignoto)."""
    results = web_search(f'"{company_name}" official website', max_results=5)
    skip = ("linkedin.", "facebook.", "twitter.", "instagram.", "youtube.",
            "wikipedia.", "bloomberg.", "crunchbase.", "glassdoor.",
            "dnb.com", "kompass.", "europages.", "youtube.", "tiktok.")
    for r in results:
        host = (urlparse(r.get("url") or "").netloc or "").lower()
        host = host.removeprefix("www.")
        if host and not any(s in host for s in skip):
            return host
    return _discover_domain_llm(company_name)


# ---------------------------------------------------------------------------
# A1 — DEEP WEB SCRAPING
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>",
                        re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r'href=["\']([^"\'#]+)["\']', re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _extract_text(html: str) -> str:
    """Testo leggibile: trafilatura se installata, altrimenti strip regex."""
    if trafilatura is not None:
        txt = trafilatura.extract(html, include_links=False,
                                  include_comments=False,
                                  favor_recall=True)
        if txt:
            return _WS_RE.sub(" ", txt).strip()
    txt = _SCRIPT_RE.sub(" ", html[:800_000])
    txt = _TAG_RE.sub(" ", txt)
    return _WS_RE.sub(" ", txt).strip()


def _fetch(url: str) -> str:
    """GET sincrono (HTML) -> '' su errore/non-HTML."""
    try:
        r = requests.get(url, headers=_UA, timeout=config.CI_HTTP_TIMEOUT,
                         allow_redirects=True)
        if r.status_code >= 400 or "html" not in r.headers.get(
                "Content-Type", ""):
            return ""
        return r.text
    except requests.RequestException:
        return ""


def _is_strategic(url: str) -> bool:
    low = url.lower()
    if any(bad in low for bad in _EXCLUDE_KEYWORDS):
        return False
    return any(k in low for k in _STRATEGIC_KEYWORDS)


def _discover_urls(base_url: str, homepage_html: str) -> list[str]:
    """URL candidati: sitemap.xml + link interni strategici della homepage."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    host = parsed.netloc.lower().removeprefix("www.")

    candidates: list[str] = []

    # 1) sitemap.xml (o quello dichiarato in robots.txt)
    sitemap_urls = [urljoin(root, "/sitemap.xml")]
    robots = ""
    try:
        rr = requests.get(urljoin(root, "/robots.txt"), headers=_UA,
                          timeout=8)
        if rr.status_code == 200:
            robots = rr.text
    except requests.RequestException:
        pass
    for m in re.finditer(r"(?im)^sitemap:\s*(\S+)", robots):
        sm = m.group(1).strip()
        if sm not in sitemap_urls:
            sitemap_urls.insert(0, sm)

    loc_re = re.compile(r"<loc>\s*([^<]+)\s*</loc>", re.IGNORECASE)
    for sm_url in sitemap_urls[:2]:
        try:
            r = requests.get(sm_url, headers=_UA, timeout=10)
            if r.status_code != 200 or "<loc>" not in r.text:
                continue
            for loc in loc_re.findall(r.text):
                loc = loc.strip()
                if loc.lower().endswith(".xml"):
                    continue  # sitemap index: ignora i sub-sitemap
                host_ok = (urlparse(loc).netloc.lower()
                           .removeprefix("www.") == host)
                if host_ok and _is_strategic(loc):
                    candidates.append(loc)
        except requests.RequestException:
            continue

    # 2) link interni dalla homepage
    for href in _HREF_RE.findall(homepage_html or ""):
        full = urljoin(base_url, href).split("#")[0]
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower().removeprefix("www.") != host:
            continue
        if _is_strategic(full):
            candidates.append(full)

    # dedup preservando l'ordine, cap a CI_MAX_PAGES
    seen, out = set(), []
    for u in candidates:
        clean = u.rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            out.append(u)
    return out[:config.CI_MAX_PAGES]


async def _fetch_extract(url: str) -> tuple[str, str]:
    html = await asyncio.to_thread(_fetch, url)
    if not html:
        return url, ""
    return url, _extract_text(html)


async def crawl_company_site(base_url: str,
                             max_pages: int | None = None,
                             max_chars: int | None = None) -> str:
    """Scarica homepage + pagine strategiche in parallelo, unisce il testo
    pulito troncato a `max_chars`. Ritorna blocco testo con marcatori URL."""
    max_pages = max_pages or config.CI_MAX_PAGES
    max_chars = max_chars or config.CI_MAX_CHARS

    homepage = await asyncio.to_thread(_fetch, base_url)
    if not homepage:
        return ""

    urls = _discover_urls(base_url, homepage)[:max_pages - 1]
    pages = await asyncio.gather(
        *[_fetch_extract(u) for u in urls],
        return_exceptions=False)

    blocks = [f"=== PAGINA: {base_url} ===\n{_extract_text(homepage)}"]
    for u, txt in pages:
        if txt:
            blocks.append(f"=== PAGINA: {u} ===\n{txt}")
    return "\n\n".join(blocks)[:max_chars]


# ---------------------------------------------------------------------------
# A2 — TED AWARD NOTICES (gare vinte, ultimi CI_TED_MONTHS)
# ---------------------------------------------------------------------------

def fetch_ted_awards_for_company(company_name: str,
                                 months: int | None = None) -> list[dict]:
    """Aggiudicazioni UE in cui `company_name` compare come vincitore.
    Filtra lato API per winner-name e lato client per fuzzy match >=80%."""
    import os
    api_key = os.environ.get("TED_API_KEY")
    if not api_key:
        return []
    months = months or config.CI_TED_MONTHS
    since = date.today().replace(day=1)
    # arretra di N mesi
    m = since.month - months
    y = since.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    since = date(y, m, 1)

    short = company_name.strip()
    payload = {
        "query": (f'form-type IN (result) AND winner-name ~ "{short}" '
                  f'AND PD >= "{since.isoformat()}"'),
        "fields": ["notice-title", "buyer-name", "publication-number",
                   "publication-date", "winner-name",
                   "description-proc",
                   "place-of-performance-country-lot"],
        "limit": 50,
        "scope": "ALL",
        "paginationMode": "PAGE_NUMBER",
        "onlyLatestVersions": True,
    }
    try:
        resp = requests.post(config.TED_API_URL,
                             params={"apiKey": api_key}, json=payload,
                             headers={"Accept": "application/json"},
                             timeout=30)
        if resp.status_code >= 400:
            db.log_error("ted_company", target=company_name,
                         url=config.TED_API_URL, error_type="http_error",
                         message=f"HTTP {resp.status_code}")
            return []
        notices = resp.json().get("notices", [])
    except (requests.RequestException, ValueError) as exc:
        db.log_error("ted_company", target=company_name,
                     url=config.TED_API_URL,
                     error_type=type(exc).__name__, message=str(exc))
        return []

    def _flat(v) -> str:
        if isinstance(v, list):
            return " | ".join(str(x) for x in v if x)
        return str(v or "")

    target_norm = normalize_company_name(company_name)
    out = []
    for n in notices:
        winners = _flat(n.get("winner-name"))
        # fuzzy check client-side: il match TED ~ e' approssimato
        winner_names = [w.strip() for w in winners.split("|") if w.strip()]
        matched = any(
            normalize_company_name(w) == target_norm
            or difflib.SequenceMatcher(
                None, normalize_company_name(w), target_norm).ratio() >= 0.80
            for w in winner_names)
        if not matched:
            continue
        pub_num = n.get("publication-number", "")
        out.append({
            "title": _flat(n.get("notice-title")),
            "buyer": _flat(n.get("buyer-name")),
            "winners": winners,
            "country": _flat(n.get("place-of-performance-country-lot")),
            "published": str(n.get("publication-date") or "")[:10],
            "url": f"https://ted.europa.eu/it/notice/-/detail/{pub_num}",
        })
    return out


# ---------------------------------------------------------------------------
# A2 — ERP SQL SERVER (storico cliente interno)
# ---------------------------------------------------------------------------

def _find_erp_client(company_name: str) -> tuple[str, str]:
    """(client_id, ragione sociale ERP) con fuzzy match >=85% su dsCliente.
    ('', '') se ERP non configurato o nessun match."""
    try:
        df = sso.fetch_clients_list()
    except Exception:
        return "", ""
    if df.empty:
        return "", ""
    target = normalize_company_name(company_name)
    if not target:
        return "", ""
    best_id, best_name, best_ratio = "", "", 0.0
    for _, row in df.iterrows():
        raw = str(row.get("client_name") or "").strip()
        norm = normalize_company_name(raw)
        if not norm:
            continue
        if norm == target or target in norm or norm in target:
            ratio = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, target, norm).ratio()
        if ratio >= _ERP_MIN_RATIO and ratio > best_ratio:
            best_id, best_name, best_ratio = (str(row["client_id"]).strip(),
                                              raw, ratio)
    return best_id, best_name


def erp_company_profile(company_name: str) -> dict:
    """Profilo storico ERP: fatturato ultimo triennio, famiglie cavi
    acquistate, data ultimo ordine, numero ordini. {} se non censita."""
    client_id, erp_name = _find_erp_client(company_name)
    if not client_id:
        return {}
    hist = sso.fetch_client_history(client_id)
    if hist.empty:
        return {"erp_customer_code": client_id, "erp_name": erp_name,
                "orders_count": 0}

    current_year = date.today().year
    years = [current_year, current_year - 1, current_year - 2]
    rev = {str(y): round(float(
        hist.loc[hist["order_date"].dt.year == y, "amount"].sum()), 2)
        for y in years}
    families = (hist["product_category"].value_counts()
                .head(5).index.tolist())
    last_order = hist["order_date"].max()
    return {
        "erp_customer_code": client_id,
        "erp_name": erp_name,
        "is_customer": True,
        "revenue_last_3y_eur": rev,
        "total_revenue_eur": round(float(hist["amount"].sum()), 2),
        "orders_count": int(len(hist)),
        "cable_families_bought": families,
        "last_order_date": last_order.strftime("%Y-%m-%d")
        if hasattr(last_order, "strftime") else str(last_order),
    }


# ---------------------------------------------------------------------------
# A3 — SINTESI LLM -> DOSSIER JSON RIGIDO
# ---------------------------------------------------------------------------

_DOSSIER_PROMPT = """Sei il Senior Sales Intelligence Analyst di un produttore europeo di cavi speciali in fibra ottica e rame (Metallurgica Bresciana).
Settori target: Data Center, Telecom/Provider, Ferroviario, Navale/Offshore, Avio/Difesa.

Analizza TUTTI i blocchi informativi raccolti sull'azienda e genera un dossier commerciale 360.
Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo extra, niente markdown):
{
 "legal_name": "<ragione sociale>",
 "hq": "<sede legale/citta'>",
 "plants": ["<stabilimenti/sedi operative note>"],
 "parent_group": "<gruppo controllante o null>",
 "size_estimate": "<dipendenti stimati>",
 "revenue_estimate": "<fatturato stimato con fonte>",
 "country_code": "<ISO3 paese, es. ITA, DEU, FRA>",
 "sector": "<Data Center|Telecom/Provider|Ferroviario|Navale/Offshore|Avio/Difesa|Altro>",
 "value_chain_role": {
   "classification": "<OEM|Tier_1_Supplier|EPC_Contractor|System_Integrator|Distributor>",
   "end_customers": ["<clienti finali citati>"]
 },
 "technical_fit": {
   "certifications": ["<norme/certificazioni citate: EN 45545, RINA, DNV, CPR B2ca, MIL-DTL, LSZH...>"],
   "recommended_mb_cables": ["<famiglie cavi MB consigliate per il fit tecnico>"]
 },
 "recent_signals": [
   {"date": "<YYYY-MM-DD o null>", "type": "<ted_award|news|erp>", "title": "<evento>", "source_url": "<url o null>"}
 ],
 "sales_angle": "<leva commerciale consigliata all'Area Manager in 2-3 frasi>"
}

REGOLE:
- Usa SOLO informazioni presenti nei blocchi; se un dato manca usa null o [].
- recent_signals: ordina dal piu' recente; includi le aggiudicazioni TED e le news.
- technical_fit.certifications: SOLO norme/certificazioni effettivamente citate nei testi.
- recommended_mb_cables: 2-4 famiglie coerenti col settore (es. cavi EN 45545-2 HL3, MPO/MTP OM4, Cat 6A/8, cavi navali RINA/DNV).
"""


def _render_source_block(title: str, content: str,
                         limit: int = 4000) -> str:
    if not content:
        return ""
    return f"--- {title} ---\n{content[:limit]}\n"


def _search_block(results: list[dict]) -> str:
    return "\n".join(
        f"- [{r.get('published') or 'n.d.'}] {r.get('title')} | "
        f"{r.get('url')}\n  {r.get('content', '')[:300]}"
        for r in results if r.get("title"))


def _ted_block(awards: list[dict]) -> str:
    return "\n".join(
        f"- [{a.get('published')}] {a.get('title')} | buyer: {a.get('buyer')} "
        f"| paese: {a.get('country')} | {a.get('url')}"
        for a in awards)


def _erp_block(erp: dict) -> str:
    if not erp:
        return ""
    return json.dumps(erp, ensure_ascii=False, default=str)


def _any_llm_path(provider: str | None) -> bool:
    """True se esiste ALMENO un percorso LLM tentabile: provider attivo
    raggiungibile OPPURE chiave Gemini configurata (fallback interno di
    generate_json_completion quando il primario fallisce)."""
    return is_llm_available(provider) or gemini_available()


def _llm_failure_reason(provider: str | None) -> str:
    """Diagnostica del fallimento LLM per la UI/log."""
    try:
        if gemini_quota_exhausted():
            return ("Quota Gemini giornaliera esaurita su tutte le "
                    "chiavi configurate")
    except Exception:
        pass
    if not is_llm_available(provider) and not gemini_available():
        p = (provider or "").lower() or "default"
        return (f"Nessun provider LLM utilizzabile: '{p}' non raggiungibile "
                "e nessuna chiave Gemini di fallback configurata")
    return ("LLM chiamato ma risposta non valida (JSON non parsabile, "
            "risposta vuota o errore HTTP): vedi console per dettagli")


def _heuristic_dossier(company_name: str, domain: str,
                       erp: dict, ted: list[dict],
                       llm_error: str | None = None) -> dict:
    """Dossier di emergenza quando l'LLM non e' disponibile."""
    return {
        "legal_name": erp.get("erp_name") or company_name,
        "hq": None, "plants": [], "parent_group": None,
        "size_estimate": None, "revenue_estimate": None,
        "country_code": None, "sector": "Altro",
        "value_chain_role": {"classification": None, "end_customers": []},
        "technical_fit": {"certifications": [],
                          "recommended_mb_cables": []},
        "recent_signals": [
            {"date": a.get("published"), "type": "ted_award",
             "title": a.get("title"), "source_url": a.get("url")}
            for a in ted],
        "sales_angle": ("Dossier parziale (LLM non disponibile): verificare "
                        "manualmente fit tecnico e referenti."),
        "_generated_by": "heuristic",
        "_llm_error": llm_error or "",
    }


def _dossier_user_prompt(company_name: str, domain: str, site_text: str,
                         search_results: list[dict],
                         corp_results: list[dict],
                         ted_awards: list[dict], erp: dict,
                         site_limit: int = 7000,
                         news_limit: int = 3500) -> str:
    return (
        f"AZIENDA: {company_name}\nDOMINIO: {domain or 'sconosciuto'}\n\n"
        + _render_source_block("SITO WEB AZIENDALE (pagine strategiche)",
                               site_text, site_limit)
        + _render_source_block("NEWS / PROGETTI / ESPANSIONI (12 mesi)",
                               _search_block(search_results), news_limit)
        + _render_source_block("DATI SOCIETARI (ricerca)",
                               _search_block(corp_results), 2000)
        + _render_source_block("APPALTI UE VINTI (TED, 24 mesi)",
                               _ted_block(ted_awards), 2500)
        + _render_source_block("STORICO ERP INTERNO (ordini MB)",
                               _erp_block(erp), 1500)
        + "\nGenera il dossier JSON."
    )


def synthesize_dossier(company_name: str, domain: str, site_text: str,
                       search_results: list[dict],
                       corp_results: list[dict],
                       ted_awards: list[dict], erp: dict,
                       provider: str | None = None) -> dict:
    """Step A3: sintesi LLM su schema rigido. Fallback euristico.
    Il gate usa _any_llm_path: generate_json_completion ha gia' un fallback
    interno Ollama<->Gemini, quindi basta che UN percorso esista."""
    if _any_llm_path(provider):
        # 1° tentativo: contesto pieno. 2° (se JSON non valido o errore):
        # contesto dimezzato — prompt troppo lunghi/troncati sono la
        # causa piu' comune di risposte non parsabili.
        for site_lim, news_lim in ((7000, 3500), (3000, 1500)):
            user = _dossier_user_prompt(
                company_name, domain, site_text, search_results,
                corp_results, ted_awards, erp,
                site_limit=site_lim, news_limit=news_lim)
            data, used = generate_json_completion(
                _DOSSIER_PROMPT, user, provider=provider, timeout=90)
            if isinstance(data, dict) and data:
                data["_generated_by"] = used
                return data
        reason = _llm_failure_reason(provider)
        db.log_error("company_intelligence", target=company_name,
                     error_type="llm_synthesis_failed", message=reason)
        return _heuristic_dossier(company_name, domain, erp, ted_awards,
                                  llm_error=reason)
    reason = _llm_failure_reason(provider)
    db.log_error("company_intelligence", target=company_name,
                 error_type="llm_unavailable", message=reason)
    return _heuristic_dossier(company_name, domain, erp, ted_awards,
                              llm_error=reason)


# ---------------------------------------------------------------------------
# PIPELINE ASINCRONA COMPLETA
# ---------------------------------------------------------------------------

def _site_candidates(domain_or_url: str) -> list[str]:
    if not domain_or_url:
        return []
    u = domain_or_url.strip()
    if u.startswith(("http://", "https://")):
        return [u]
    return [f"https://www.{u}", f"https://{u}"]


async def _crawl_best(domain_or_url: str) -> tuple[str, str]:
    """Prova le varianti https://www.dominio -> https://dominio.
    Ritorna (url_effettivo, testo)."""
    for cand in _site_candidates(domain_or_url):
        html = await asyncio.to_thread(_fetch, cand)
        if html:
            urls = _discover_urls(cand, html)[:config.CI_MAX_PAGES - 1]
            pages = await asyncio.gather(
                *[_fetch_extract(u) for u in urls])
            blocks = [f"=== PAGINA: {cand} ===\n{_extract_text(html)}"]
            blocks += [f"=== PAGINA: {u} ===\n{t}"
                       for u, t in pages if t]
            return cand, "\n\n".join(blocks)[:config.CI_MAX_CHARS]
    return "", ""


async def profile_company(company_name: str,
                          website_url: str | None = None,
                          provider: str | None = None) -> dict:
    """Dossier 360° completo. Esegue raccolta parallela multi-fonte,
    sintesi LLM e persistenza su company_dossiers. Non solleva eccezioni
    sulle singole fonti: ogni blocco degrada a vuoto."""
    started = time.time()
    company_name = (company_name or "").strip()
    domain = ""
    if website_url:
        domain = (urlparse(website_url).netloc
                  or urlparse("https://" + website_url).netloc)
        domain = domain.lower().removeprefix("www.")
    if not domain:
        domain = await asyncio.to_thread(discover_domain, company_name)

    base_url = f"https://{domain}" if domain else ""

    # --- A1 + A2 in parallelo: scraping, search x2, TED, ERP ---
    q_projects = (f'"{company_name}" AND ("contract" OR "project" OR '
                  f'"data center" OR "railway" OR "shipyard" OR "tender" '
                  f'OR "expansion")')
    q_corporate = f'"{company_name}" revenue employees headquarters group'

    site_task = _crawl_best(base_url) if base_url else asyncio.sleep(
        0, result=("", ""))
    projects_task = asyncio.to_thread(web_search, q_projects, 8, 365)
    corp_task = asyncio.to_thread(web_search, q_corporate, 5)
    ted_task = asyncio.to_thread(fetch_ted_awards_for_company, company_name)
    erp_task = asyncio.to_thread(erp_company_profile, company_name)

    (effective_url, site_text), search_results, corp_results, ted, erp = \
        await asyncio.gather(site_task, projects_task, corp_task,
                             ted_task, erp_task)

    if not domain and effective_url:
        domain = (urlparse(effective_url).netloc or "").lower(
        ).removeprefix("www.")

    # --- A3: sintesi LLM ---
    dossier = await asyncio.to_thread(
        synthesize_dossier, company_name, domain, site_text,
        search_results, corp_results, ted, erp, provider)

    # Arricchisci il dossier con i blocchi grezzi rilevanti per la UI
    dossier["_sources"] = {
        "domain": domain,
        "pages_scraped": bool(site_text),
        "search_results": len(search_results),
        "ted_awards": len(ted),
        "erp_customer": bool(erp.get("is_customer")),
        "elapsed_sec": round(time.time() - started, 1),
    }
    dossier["_ted_awards"] = ted
    dossier["_erp"] = erp
    if search_results:
        dossier["_search_results"] = search_results[:8]

    # --- Persistenza ---
    company_id = ""
    if domain:
        company_id = db.upsert_company_dossier({
            "company_name": dossier.get("legal_name") or company_name,
            "domain": domain,
            "country_code": dossier.get("country_code"),
            "sector": dossier.get("sector"),
            "erp_customer_code": erp.get("erp_customer_code"),
            "dossier_json": dossier,
        })
    return {"company_id": company_id, "company_name": company_name,
            "domain": domain, "dossier": dossier}


def profile_company_sync(company_name: str,
                         website_url: str | None = None,
                         provider: str | None = None) -> dict:
    """Wrapper sincrono per Streamlit / script."""
    return asyncio.run(profile_company(company_name, website_url, provider))

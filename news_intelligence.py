"""News & Media Intelligence — segnali commerciali recenti e gancio outreach.

Per ogni prospect/cliente monitorato raccoglie articoli degli ultimi
60-90 giorni da 3 fonti:

  1. Google News RSS localizzato (costo zero): hl/gl adattati al Paese
     del prospect, vincolo temporale when:Nd.
  2. Search API (Tavily/Serper via company_intelligence.web_search) con
     filtro temporale e keyword operative.
  3. Sezione /news|/press|/aktuelles|/actualites del sito aziendale:
     estratti titoli e date degli ultimi comunicati.

Gli articoli grezzi passano all'LLM che scarta il rumore (bilanci,
borsa, sponsor, nomine non operative) e classifica i segnali di acquisto
in: NEW_CONTRACT, FACILITY_EXPANSION, TRADE_SHOW, SUPPLY_CHAIN_EVENT.
Se almeno un segnale e' valido, genera `outreach_hook` (1-2 frasi nella
lingua del destinatario) da iniettare in generate_multilingual_outreach().

Uso:
    res = analyze_company_news("Stadler Rail", country_code="CHE",
                               domain="stadlerrail.com",
                               company_key="prospect:Stadler Rail|CHE")
"""
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser

import company_intelligence as ci
import db
from llm import generate_json_completion

NEWS_DAYS = 90           # finestra temporale segnali
_MAX_ARTICLES = 15       # per canale, poi il batch LLM
_GNEWS = ("https://news.google.com/rss/search"
          "?q={q}&hl={hl}&gl={gl}&ceid={ceid}")

# ISO3 -> (hl, gl, lingua out) per il feed Google News localizzato.
# Chiavi allineate a COUNTRY_TO_AREA (config.AREA_MAPPING).
_COUNTRY_LOCALE = {
    "ITA": ("it", "IT", "italiano"),
    "DEU": ("de", "DE", "tedesco"), "AUT": ("de", "AT", "tedesco"),
    "CHE": ("de", "CH", "tedesco"),
    "FRA": ("fr", "FR", "francese"), "BEL": ("fr", "BE", "francese"),
    "LUX": ("fr", "LU", "francese"),
    "ESP": ("es", "ES", "spagnolo"), "PRT": ("pt", "PT", "portoghese"),
    "NLD": ("nl", "NL", "olandese"),
    "POL": ("pl", "PL", "polacco"), "CZE": ("cs", "CZ", "ceco"),
    "SVK": ("sk", "SK", "slovacco"), "HUN": ("hu", "HU", "ungherese"),
    "ROU": ("ro", "RO", "rumeno"), "BGR": ("bg", "BG", "bulgaro"),
    "HRV": ("hr", "HR", "croato"), "SVN": ("sl", "SI", "sloveno"),
    "GRC": ("el", "GR", "greco"),
    "SWE": ("sv", "SE", "svedese"), "NOR": ("no", "NO", "norvegese"),
    "DNK": ("da", "DK", "danese"), "FIN": ("fi", "FI", "finlandese"),
    "LTU": ("lt", "LT", "lituano"), "LVA": ("lv", "LV", "lettone"),
    "EST": ("et", "EE", "estone"),
}
_DEFAULT_LOCALE = ("en", "GB", "inglese")


def locale_for_country(country_code: str | None) -> tuple[str, str, str]:
    """(hl, gl, nome lingua) per RSS localizzato e hook multilingua."""
    return _COUNTRY_LOCALE.get((country_code or "").upper(),
                               _DEFAULT_LOCALE)


def company_key_for(name: str, country_code: str | None = None,
                    company_id: str | None = None) -> str:
    """Chiave di collegamento alla anagrafica: company_id dossier se c'e',
    altrimenti 'prospect:<nome>|<paese>' come da convenzione DB."""
    if company_id:
        return company_id
    return f"prospect:{(name or '').strip()}|{(country_code or '').upper()}"


# ---------------------------------------------------------------------------
# FONTE 1 — Google News RSS localizzato
# ---------------------------------------------------------------------------

def _clean_summary(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", unescape(raw or ""))
    return re.sub(r"\s+", " ", txt).strip()


def google_news_rss(company_name: str, country_code: str | None,
                    days: int = NEWS_DAYS,
                    max_items: int = _MAX_ARTICLES) -> list[dict]:
    """Articoli Google News RSS localizzati sugli ultimi `days` giorni."""
    hl, gl, _lang = locale_for_country(country_code)
    q = urllib.parse.quote(f'"{company_name}" when:{days}d')
    url = _GNEWS.format(q=q, hl=hl, gl=gl, ceid=f"{gl}:{hl}")
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        db.log_error("news_intel", target=company_name, url=url,
                     error_type=type(exc).__name__, message=str(exc))
        return []
    status = getattr(feed, "status", None)
    if status is not None and status >= 400:
        db.log_error("news_intel", target=company_name, url=url,
                     error_type="http_error", message=f"HTTP {status}")
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for e in feed.entries[:max_items]:
        pub = e.get("published_parsed")
        pub_str = ""
        if pub is not None:
            pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
            pub_str = pub_dt.strftime("%Y-%m-%d")
        link = e.get("link") or ""
        if not link:
            continue
        out.append({"title": unescape(e.get("title", "")).strip(),
                    "url": link,
                    "published": pub_str,
                    "content": _clean_summary(e.get("summary", ""))[:300],
                    "source": "google_news"})
    return out


# ---------------------------------------------------------------------------
# FONTE 2 — Search API (Tavily/Serper, riuso company_intelligence)
# ---------------------------------------------------------------------------

def search_api_news(company_name: str,
                    days: int = NEWS_DAYS) -> list[dict]:
    """News operative via Search API con filtro recency."""
    if not ci.search_api_configured():
        return []
    query = (f'"{company_name}" ("contract" OR "expansion" OR '
             f'"new facility" OR "tender" OR "partnership" OR "exhibition")')
    out = ci.web_search(query, max_results=8,
                        days=days if days <= 365 else None)
    for r in out:
        r["source"] = "search_api"
    return out


# ---------------------------------------------------------------------------
# FONTE 3 — Sezione /news del sito aziendale
# ---------------------------------------------------------------------------

_NEWS_SLUGS = ("/news", "/press", "/aktuelles", "/actualites", "/media",
               "/notizie", "/presse", "/nouvelles", "/newsroom")
_HEADING_RE = re.compile(r"<(h[1-4]|time|article)[^>]*>(.*?)</\1>",
                         re.IGNORECASE | re.DOTALL)
_DATE_RE = re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]"
                      r"(0?[1-9]|[12]\d|3[01])\b")


def company_site_news(domain_or_url: str,
                      max_items: int = 5) -> list[dict]:
    """Titoli/date degli ultimi comunicati dalla sezione news del sito."""
    base = domain_or_url.strip()
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    out = []
    for slug in _NEWS_SLUGS:
        url = urllib.parse.urljoin(base, slug)
        html = ci._fetch(url)
        if not html or len(html) < 2000:
            continue
        items = []
        for m in _HEADING_RE.finditer(html):
            txt = re.sub(r"<[^>]+>", " ", m.group(2))
            txt = re.sub(r"\s+", " ", unescape(txt)).strip()
            if 15 < len(txt) < 220 and txt not in items:
                items.append(txt)
        if items:
            # Data pagina = ultima data ISO trovata nell'HTML (approssimata)
            d = _DATE_RE.search(html)
            pub = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}" \
                if d else ""
            for t in items[:max_items]:
                out.append({"title": t, "url": url,
                            "published": pub, "content": "",
                            "source": "site_news"})
            break  # prima sezione news trovata basta
    return out


# ---------------------------------------------------------------------------
# CLASSIFICAZIONE LLM + GANCIO OUTREACH
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """Sei il Sales Intelligence Analyst di un produttore europeo di cavi speciali (fibra ottica e rame: EN 45545, VG95218, RINA/DNV, CPR B2ca, data center).

Ricevi una lista di articoli recenti su un'azienda. CLASSIFICA solo i veri segnali di acquisto e SCARTA il rumore.

SCARTA: bilanci trimestrali, andamento azionario, sponsorizzazioni sportive, nomine dirigenziali non operative, articoli di opinione.
MANTIENI e classifica:
- NEW_CONTRACT: aggiudicazione di un appalto/ordine/fornitura
- FACILITY_EXPANSION: apertura/ampliamento stabilimento o linea produttiva
- TRADE_SHOW: partecipazione a fiere di settore (InnoTrans, SMM Hamburg, Data Centre World, Eurosatory, Paris Air Show...)
- SUPPLY_CHAIN_EVENT: partnership tecniche, joint venture, criticita' supply chain

Rispondi SOLO con JSON valido:
{
 "signals": [
   {"article_index": <int>, "category": "<NEW_CONTRACT|FACILITY_EXPANSION|TRADE_SHOW|SUPPLY_CHAIN_EVENT>",
    "summary": "<1 riga: cosa e' successo, volumi/mezzi/MW se citati>"}
 ],
 "outreach_hook": "<1-2 frasi NATURALI nella lingua richiesta: gancio di apertura per email commerciale che cita il segnale piu' recente senza inventare dati, o stringa vuota se nessun segnale>"
}"""


def classify_and_hook(company_name: str, articles: list[dict],
                      language: str = "italiano",
                      provider: str | None = None) -> dict:
    """Filtro LLM sugli articoli. Ritorna {signals:[...], outreach_hook}."""
    if not articles:
        return {"signals": [], "outreach_hook": ""}
    listing = "\n".join(
        f"[{i}] ({a.get('published') or 'n.d.'}) {a.get('title')} — "
        f"{(a.get('content') or '')[:160]}"
        for i, a in enumerate(articles[:25]))
    user = (f"AZIENDA: {company_name}\nLINGUA GANCIO: {language}\n\n"
            f"ARTICOLI:\n{listing}")
    data, _p = generate_json_completion(_CLASSIFY_PROMPT, user,
                                        provider=provider, timeout=60)
    if not isinstance(data, dict):
        return {"signals": [], "outreach_hook": "",
                "_llm_error": "classificazione fallita"}
    signals = []
    for s in data.get("signals") or []:
        try:
            idx = int(s.get("article_index"))
            art = articles[idx]
        except (TypeError, ValueError, IndexError):
            continue
        cat = str(s.get("category") or "").upper()
        if cat not in ("NEW_CONTRACT", "FACILITY_EXPANSION",
                       "TRADE_SHOW", "SUPPLY_CHAIN_EVENT"):
            continue
        signals.append({"category": cat,
                        "summary": str(s.get("summary") or "")[:300],
                        "article": art})
    return {"signals": signals,
            "outreach_hook": str(data.get("outreach_hook") or "").strip()}


# ---------------------------------------------------------------------------
# ORCHESTRATORE
# ---------------------------------------------------------------------------

def analyze_company_news(company_name: str,
                         country_code: str | None = None,
                         domain: str | None = None,
                         company_key: str | None = None,
                         company_id: str | None = None,
                         provider: str | None = None,
                         days: int = NEWS_DAYS) -> dict:
    """Raccoglie le 3 fonti, filtra con LLM, salva i segnali validi.
    Ritorna {signals, outreach_hook, articles_found, company_key}."""
    key = company_key or company_key_for(
        company_name, country_code, company_id=company_id)

    articles = google_news_rss(company_name, country_code, days=days)
    articles += search_api_news(company_name, days=days)
    if domain:
        articles += company_site_news(domain)

    # dedup per URL
    seen, uniq = set(), []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            uniq.append(a)

    _hl, _gl, lang = locale_for_country(country_code)
    result = classify_and_hook(company_name, uniq, language=lang,
                               provider=provider)

    hook = result.get("outreach_hook") or ""
    lang_code = _hl
    saved = 0
    for s in result.get("signals") or []:
        art = s["article"]
        if db.save_news_signal({
                "company_key": key, "company_name": company_name,
                "article_title": art.get("title"),
                "published_date": art.get("published") or None,
                "signal_category": s["category"],
                "source_url": art.get("url"),
                "outreach_hook": hook, "language": lang_code}):
            saved += 1

    return {"company_key": key, "articles_found": len(uniq),
            "signals": result.get("signals") or [],
            "signals_saved": saved, "outreach_hook": hook,
            "language": lang_code}


def batch_update_companies(targets: list[dict],
                           provider: str | None = None,
                           days: int = NEWS_DAYS,
                           verbose: bool = True) -> dict:
    """Aggiornamento periodico: targets = [{company_name, country_code,
    domain, company_id}...] da dossier + prospect qualificati."""
    rep = {"companies": 0, "articles": 0, "signals": 0, "errors": 0}
    for t in targets:
        try:
            r = analyze_company_news(
                t.get("company_name") or "",
                country_code=t.get("country_code"),
                domain=t.get("domain"),
                company_id=t.get("company_id"),
                provider=provider, days=days)
            rep["companies"] += 1
            rep["articles"] += r["articles_found"]
            rep["signals"] += r["signals_saved"]
            if verbose and r["signals_saved"]:
                print(f"  [news_intel] {t.get('company_name')}: "
                      f"{r['signals_saved']} segnali", flush=True)
        except Exception as exc:
            rep["errors"] += 1
            db.log_error("news_intel", target=t.get("company_name"),
                         error_type=type(exc).__name__, message=str(exc))
    return rep


def collect_targets(limit: int = 40) -> list[dict]:
    """Target per il batch: dossier Company Intelligence + prospect
    qualificati (match_score>=65) non ancora coperti dai dossier."""
    out, seen = [], set()
    for d in db.list_dossiers(limit=limit):
        out.append({"company_name": d["company_name"],
                    "country_code": d.get("country_code"),
                    "domain": d.get("domain"),
                    "company_id": d.get("company_id")})
        seen.add((d["company_name"] or "").lower())
    for p in db.get_prospects(min_score=65, limit=limit):
        name = (p.get("company_name") or "")
        if name.lower() in seen:
            continue
        dom = ""
        w = p.get("website_url") or ""
        if w:
            m = re.search(r"https?://(?:www\.)?([^/]+)", w)
            dom = m.group(1) if m else ""
        out.append({"company_name": name,
                    "country_code": p.get("country_code"),
                    "domain": dom, "company_id": None})
        seen.add(name.lower())
    return out

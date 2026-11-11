"""Fetch news da Google News RSS: fonte pubblica, nessuna chiave API."""
import urllib.parse
from html import unescape

import feedparser

import db
from config import NEWS_EDITIONS, MAX_NEWS_PER_QUERY

_RSS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


def _feed_url(query: str, lang: str, country: str) -> str:
    q = urllib.parse.quote(query)
    ceid = f"{country}:{lang}"
    return _RSS.format(q=q, hl=lang, gl=country, ceid=ceid)


def fetch_news(verbose: bool = True) -> list[dict]:
    items, seen = [], set()
    for edition in NEWS_EDITIONS:
        for query in edition["queries"]:
            items += _fetch_query(query, edition["lang"],
                                  edition["country"], seen, verbose)
    return items


def _fetch_query(query: str, lang: str, country: str,
                 seen: set, verbose: bool) -> list[dict]:
    results = []
    url = _feed_url(query, lang, country)
    try:
        feed = feedparser.parse(url)
    except Exception as exc:  # rete non disponibile, feed malformato, ecc.
        db.log_error("news", target=query, url=url,
                     error_type=type(exc).__name__, message=str(exc))
        if verbose:
            print(f"  [news] errore query '{query}': {exc}")
        return results
    # Indirizzo non raggiungibile o feed corrotto: feedparser non solleva
    # eccezioni, espone status HTTP e flag 'bozo'.
    status = getattr(feed, "status", None)
    if status is not None and status >= 400:
        db.log_error("news", target=query, url=url,
                     error_type="http_error",
                     message=f"HTTP {status}")
        if verbose:
            print(f"  [news] HTTP {status} su query '{query}'")
        return results
    if getattr(feed, "bozo", False) and not feed.entries:
        db.log_error("news", target=query, url=url,
                     error_type="parse",
                     message=str(feed.bozo_exception))
        if verbose:
            print(f"  [news] feed malformato su query '{query}': "
                  f"{feed.bozo_exception}")
        return results
    for entry in feed.entries[:MAX_NEWS_PER_QUERY]:
        link = entry.get("link", "")
        if not link or link in seen:
            continue
        seen.add(link)
        country_code = "ITA" if country == "IT" else None
        area_code = "ITALY" if country == "IT" else None
        results.append({
            "source": "news",
            "external_id": link,
            "title": unescape(entry.get("title", "")).strip(),
            "url": link,
            "published": entry.get("published"),
            "country": country_code,
            "area_manager": area_code,
            "text": unescape(entry.get("summary", "")).strip(),
        })
    return results

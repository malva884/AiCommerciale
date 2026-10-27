"""Fetch news da Google News RSS: fonte pubblica, nessuna chiave API."""
import urllib.parse
from html import unescape

import feedparser

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
    try:
        feed = feedparser.parse(_feed_url(query, lang, country))
    except Exception as exc:  # rete non disponibile, feed malformato, ecc.
        if verbose:
            print(f"  [news] errore query '{query}': {exc}")
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

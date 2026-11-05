"""Reiter Geopolitik: Meldungen zu Truppen, Angriffen, Eskalation und Rüstungsaufträgen, dazu der Rüstungssektor an der Börse.

Meldungen kommen aus Google-News-Suchen je Kategorie (deutsch und englisch), Kurse von Yahoo wie im Rest der App.
"""
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from briefings import _items as rss_items
from depot import to_eur
from markets import fetch_quote
from net import fetch

PARAMS = {"de": "hl=de&gl=DE&ceid=DE:de", "en": "hl=en-US&gl=US&ceid=US:en"}


def search(query, lang, days=2):
    """Google-News-Suche, Ergebnis im Aufbau einer Meldung der Startseite."""
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{query} when:{days}d") + "&" + PARAMS[lang]
    out = []
    for i in rss_items(fetch(url, 20)):
        m = re.match(r"(.*)\s+-\s+([^-]+)$", i["title"])
        title, source = (m.group(1), m.group(2).strip()) if m else (i["title"], "")
        out.append({"title": title, "summary": "", "url": i["url"], "lang": lang, "topic": "world", "time": i["time"].isoformat(),
                    "sources": [{"name": source or "Google News", "url": i["url"]}], "watch": [], "alert": False,
                    "election": False, "region": None, "score": 0})
    return out


def category(c):
    """Alle Suchen einer Kategorie, ohne doppelte Überschriften, neueste zuerst."""
    found, seen, must = [], set(), [w.lower() for w in c.get("must", [])]
    for q in c["queries"]:
        try:
            items = search(q["q"], q.get("lang", "de"))
        except Exception:
            continue
        for n in items:
            key = re.sub(r"\W+", "", n["title"].lower())[:50]
            if key not in seen and (not must or any(w in n["title"].lower() for w in must)):
                seen.add(key)
                found.append(n)
    found.sort(key=lambda n: n["time"], reverse=True)
    return {"key": c["key"], "label": c["label"], "news": found[:c.get("limit", 14)]}


def build(cfg, alerts):
    g = cfg.get("geopolitics") or {}
    cats, papers = g.get("categories", []), g.get("stocks", []) + g.get("etfs", [])

    def quote(p):
        q = to_eur(fetch_quote({"name": p["short"], "symbol": p["symbol"], "group": "stock"}, alerts), alerts, p.get("type") == "ETF")
        return {**q, "short": p["short"], "type": p.get("type", "Aktie"), "country": p.get("country", ""),
                "c": [round(x, 2 if x >= 10 else 4) for x in q.get("c") or []]}

    with ThreadPoolExecutor(max_workers=6) as ex:
        news = list(ex.map(category, cats))
        quotes = list(ex.map(quote, papers))
    stocks = [q for q in quotes if q.get("price") is not None]
    avg = lambda k: round(sum(q[k] for q in stocks if q.get(k) is not None) / max(1, sum(1 for q in stocks if q.get(k) is not None)), 2)
    return {"categories": news, "stocks": [q for q in stocks if q["type"] != "ETF"], "etfs": [q for q in stocks if q["type"] == "ETF"],
            "sector": {"day": avg("pct"), "week": avg("week"), "month": avg("month"), "n": len(stocks)}}

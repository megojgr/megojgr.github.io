"""Werteliste für eigene Depots auf dem Gerät der Nutzer: Kurs in Euro, Jahresverlauf und Meldungen je ETF oder Aktie.

Die Positionen der Nutzer kennt dieser Code nicht, sie bleiben im Browser. Öffentlich ist nur, welche Werte die App anbietet.
Meldungen werden höchstens alle paar Stunden neu gesucht (Zwischenspeicher im Repo), Kurse bei jedem Lauf.
"""
import datetime as dt
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from briefings import _items as rss_items
from depot import to_eur
from etfs import theme_of
from markets import fetch_quote
from net import fetch

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "universe.json"


def news_for(u, per_item=6):
    """Google-News-Suche nach den Begriffen des Werts; ein Titel muss einen der Begriffe enthalten."""
    terms = u["terms"]
    words = " OR ".join(f'"{t}"' for t in terms)
    extra = u.get("q_extra") or ("" if u["type"] == "ETF" else "(Aktie OR Börse OR Quartal OR Konzern)")
    query = f"({words}) {extra} when:3d".replace("  ", " ")
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=de&gl=DE&ceid=DE:de"
    title_re = re.compile(r"(?<![A-Za-zÄÖÜäöü-])(" + "|".join(re.escape(t) for t in terms) + ")", re.I)
    exclude = re.compile("|".join(re.escape(x) for x in u.get("exclude", [])), re.I) if u.get("exclude") else None
    out, seen = [], set()
    for i in sorted(rss_items(fetch(url, 20)), key=lambda i: i["time"], reverse=True):
        m = re.match(r"(.*)\s+-\s+([^-]+)$", i["title"])
        title, source = (m.group(1), m.group(2).strip()) if m else (i["title"], "")
        key = re.sub(r"\W+", "", title.lower())[:40]
        if key in seen or not title_re.search(title) or (exclude and exclude.search(title)):
            continue
        seen.add(key)
        # Aufbau wie eine Meldung der Startseite, damit die Seite sie gleich darstellen kann
        out.append({"title": title, "summary": "", "url": i["url"], "lang": "de", "topic": "markets", "time": i["time"].isoformat(),
                    "sources": [{"name": source or "Google News", "url": i["url"]}], "watch": [], "alert": False,
                    "election": False, "region": None, "score": 0})
        if len(out) >= per_item:
            break
    return out


def build(cfg, alerts):
    items = cfg.get("universe") or []
    if not items:
        return []
    def quote(u):
        q = to_eur(fetch_quote({"name": u["short"], "symbol": u["symbol"], "group": "depot"}, alerts), alerts, u["type"] == "ETF")
        if u.get("price_symbol") and q.get("price"):
            # Kurs von einer anderen Anteilsklasse (ohne Verlauf), Verlauf von "symbol" auf diesen Kurs umgerechnet
            p = to_eur(fetch_quote({"name": u["short"], "symbol": u["price_symbol"], "group": "depot"}, alerts), alerts, True)
            if p.get("price"):
                k = p["price"] / q["price"]
                q.update(price=p["price"], c=[x * k for x in q["c"]], hi52=q["hi52"] and q["hi52"] * k, lo52=q["lo52"] and q["lo52"] * k)
        return q

    with ThreadPoolExecutor(max_workers=8) as ex:
        quotes = list(ex.map(quote, items))

    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    news = cache.get("news", {})
    now = dt.datetime.now(dt.timezone.utc)
    fresh = cache.get("fetched") and (now - dt.datetime.fromisoformat(cache["fetched"])).total_seconds() < cfg.get("universe_news_hours", 3) * 3600
    # Meldungen je Aktie und je ETF-Thema (z. B. "theme:world"); ETFs zeigen dazu Meldungen ihrer größten Positionen
    themes = cfg.get("etf_themes", [])
    searches = [(u["symbol"], u) for u in items] + [("theme:" + t["key"], {"terms": t["terms"], "type": "ETF", "q_extra": t.get("q_extra")}) for t in themes]
    if not fresh or any(key not in news for key, _ in searches):
        def one(job):
            key, u = job
            try:
                return key, news_for(u)
            except Exception:
                return key, news.get(key, [])  # Suche gestört: alten Stand behalten
        with ThreadPoolExecutor(max_workers=4) as ex:
            news = dict(ex.map(one, searches))
        try:
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps({"fetched": now.isoformat(), "news": news}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def compact(c):  # Verlauf mit so vielen Stellen wie sinnvoll, hält die Seite fürs Handy klein
        return [round(x, 2 if x >= 10 else 4) for x in c]

    out = []
    for u, q in zip(items, quotes):
        q["c"] = compact(q.get("c") or [])
        out.append({"id": u["symbol"], "note": u.get("note"), "theme": theme_of(u["name"], themes) if u["type"] == "ETF" else None,
                    **{k: u[k] for k in ("name", "short", "type", "isin", "wkn", "symbol")},
                    **{k: q.get(k) for k in ("price", "pct", "week", "month", "t", "c", "currency", "hi52", "lo52", "alert", "error", "local", "fx_error")},
                    "news": news.get(u["symbol"], []), "context": []})
    theme_data = {t["key"]: {"label": t["label"], "holdings": t["holdings"], "news": news.get("theme:" + t["key"], [])} for t in themes}
    return out, theme_data

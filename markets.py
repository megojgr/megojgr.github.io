"""Kurse (Yahoo), Prediction Markets (Polymarket, Kalshi) und Termine. Alles kostenlos, ohne API-Key."""
import datetime as dt
import json
import urllib.parse

from net import fetch

NOW = dt.datetime.now(dt.timezone.utc)

PM_CATEGORIES = [
    ("Wahlen", {"elections", "global-elections", "world-elections", "main-election"}),
    ("Geopolitik", {"geopolitics", "world", "middle-east", "ukraine", "china", "russia"}),
    ("Politik", {"politics"}),
    ("Wirtschaft", {"economy", "finance", "business", "fed"}),
    ("Krypto", {"crypto"}),
    ("Tech", {"tech"}),
]
KALSHI_CATEGORIES = {
    "Elections": "Wahlen", "Politics": "Politik", "World": "Geopolitik", "Economics": "Wirtschaft",
    "Financials": "Wirtschaft", "Companies": "Wirtschaft", "Crypto": "Krypto",
}


def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def jlist(x):
    if isinstance(x, list):
        return x
    try:
        return json.loads(x)
    except Exception:
        return []


# ---------------------------------------------------------------- Kurse

def fetch_quote(q, alerts):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(q["symbol"])
           + "?interval=1d&range=1mo")
    base = {"name": q["name"], "symbol": q["symbol"], "group": q.get("group", "index"),
            "price": None, "pct": None, "week": None, "month": None, "series": [], "currency": "", "alert": None}
    try:
        res = json.loads(fetch(url, 15))["chart"]["result"][0]
        meta = res["meta"]
        closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
        price = meta["regularMarketPrice"]
        pct = meta.get("regularMarketChangePercent")
        if pct is None and len(closes) >= 2:
            pct = (closes[-1] / closes[-2] - 1) * 100
        week = (price / closes[-6] - 1) * 100 if len(closes) >= 6 else None
        month = (price / closes[0] - 1) * 100 if closes else None
        limit = q.get("alert_day_pct") or (alerts["stock_day_pct"] if base["group"] == "stock" else alerts["index_day_pct"])
        alert = None
        if q["symbol"] == "^VIX":
            if pct is not None and pct >= 10:
                alert = "day"
        elif pct is not None and abs(pct) >= limit:
            alert = "day"
        elif week is not None and week <= -alerts["week_pct"]:
            alert = "week"
        base.update(price=price, pct=pct, week=week, month=month, series=[round(c, 4) for c in closes][-22:],
                    currency=meta.get("currency", ""), alert=alert)
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {e}"[:160]
    return base


# ---------------------------------------------------------------- Polymarket

def pm_event(ev, include, exclude):
    tags = {t.get("slug", "") for t in ev.get("tags", [])}
    if tags & exclude or not tags & include:
        return None
    multi = len(ev.get("markets", [])) > 1
    rows = []
    for m in ev.get("markets", []):
        if m.get("closed") or not m.get("active", True):
            continue
        prices = jlist(m.get("outcomePrices"))
        if not prices:
            continue
        rows.append({"label": (m.get("groupItemTitle") or m.get("question")) if multi else "Ja",
                     "p": num(prices[0]), "d1": m.get("oneDayPriceChange")})
    if not rows:
        return None
    rows.sort(key=lambda r: r["p"], reverse=True)
    category = next((name for name, slugs in PM_CATEGORIES if tags & slugs), "Sonstiges")
    return {"source": "Polymarket", "unit": "usd", "title": ev.get("title", ""),
            "url": "https://polymarket.com/event/" + ev.get("slug", ""), "category": category,
            "vol24h": num(ev.get("volume24hr")), "vol": num(ev.get("volume")),
            "end": (ev.get("endDate") or "")[:10], "rows": rows[:5], "more": max(0, len(rows) - 5)}


def build_polymarket(cfg):
    """Liefert (Top nach 24h-Volumen, alle Kandidaten für Termine, Fehler)."""
    pm = cfg["polymarket"]
    include, exclude = set(pm["include_tags"]), set(pm["exclude_tags"])
    base = "https://gamma-api.polymarket.com/events?active=true&closed=false"
    try:
        events = json.loads(fetch(f"{base}&order=volume24hr&ascending=false&limit={pm['fetch_limit']}", 30))
    except Exception as e:
        return [], [], f"{type(e).__name__}: {e}"
    top = [x for x in (pm_event(ev, include, exclude) for ev in events) if x][: pm["max_events"]]
    window = []
    try:
        lo = NOW.date().isoformat()
        hi = (NOW + dt.timedelta(days=cfg["termine_days"])).date().isoformat()
        events = json.loads(fetch(f"{base}&end_date_min={lo}&end_date_max={hi}&order=volume&ascending=false&limit=100", 30))
        window = [x for x in (pm_event(ev, include, exclude) for ev in events) if x]
    except Exception:
        pass  # Termine sind ein Zusatz, die Hauptliste darf davon nicht abhängen
    return top, window, None


# ---------------------------------------------------------------- Kalshi

def build_kalshi(cfg):
    """Liefert (alle passenden Events, Fehler). Die Auswahl nach Volumen trifft der Aufrufer."""
    kc = cfg["kalshi"]
    include = set(kc["include_categories"])
    raw, cursor, err = [], None, None
    for _ in range(kc["max_pages"]):
        url = "https://api.elections.kalshi.com/trade-api/v2/events?status=open&with_nested_markets=true&limit=200"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor)
        try:
            page = json.loads(fetch(url, 60))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:160]
            break
        raw += [e for e in page.get("events", []) if e.get("category") in include]
        cursor = page.get("cursor")
        if not cursor:
            break
    events = []
    for e in raw:
        ms = [m for m in e.get("markets", []) if m.get("status") in ("active", "open")]
        rows = []
        for m in ms:
            p = num(m.get("last_price_dollars")) or num(m.get("yes_bid_dollars"))
            if p <= 0:
                continue
            prev = m.get("previous_price_dollars")
            d1 = (p - num(prev)) if prev not in (None, "") else None
            label = (m.get("yes_sub_title") or m.get("title") or "?") if len(ms) > 1 else "Ja"
            rows.append({"label": label, "p": p, "d1": d1})
        if not rows:
            continue
        rows.sort(key=lambda r: r["p"], reverse=True)
        closes = [m["close_time"][:10] for m in ms if m.get("close_time")]
        events.append({
            "source": "Kalshi", "unit": "contracts", "title": e.get("title", ""),
            "url": "https://kalshi.com/markets/" + (e.get("series_ticker") or "").lower(),
            "category": KALSHI_CATEGORIES.get(e.get("category"), "Sonstiges"),
            "vol24h": sum(num(m.get("volume_24h_fp")) for m in ms), "vol": sum(num(m.get("volume_fp")) for m in ms),
            "end": min(closes) if closes else "", "rows": rows[:5], "more": max(0, len(rows) - 5)})
    return events, err


# ---------------------------------------------------------------- Termine

def build_termine(candidates, days, limit=40):
    """Entscheidungen, die in den nächsten `days` Tagen enden: Wahlen, Zinsentscheide, Wirtschaftsdaten."""
    lo = NOW.date().isoformat()
    hi = (NOW + dt.timedelta(days=days)).date().isoformat()
    seen, out = set(), []
    for e in sorted(candidates, key=lambda e: (e["end"], -e["vol24h"])):
        if not (lo <= e["end"] <= hi) or (e["vol24h"] <= 0 and e["vol"] < 1000) or e["category"] == "Krypto":
            continue  # Krypto: nur Tages-Kursleitern ("Bitcoin above ...") ohne Terminwert
        lead = e["rows"][0]
        if not 0.03 <= lead["p"] <= 0.97:
            continue  # praktisch schon entschieden
        key = (e["source"], e["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": e["title"], "url": e["url"], "source": e["source"], "category": e["category"],
                    "end": e["end"], "lead": {"label": lead["label"], "p": lead["p"]},
                    "vol24h": e["vol24h"], "unit": e["unit"]})
    # Pro Tag nicht beliebig viele, damit ein einzelner Wahltag die Liste nicht füllt
    per_day, kept = {}, []
    for t in out:
        per_day[t["end"]] = per_day.get(t["end"], 0) + 1
        if per_day[t["end"]] <= 6:
            kept.append(t)
    return kept[:limit]

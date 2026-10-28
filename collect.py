"""Holt News, Marktdaten und Prediction Markets und baut docs/index.html.

Nur Standardbibliothek. Aufruf:  py collect.py
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "docs"
UA = "Mozilla/5.0 (private-news-reader)"
NOW = dt.datetime.now(dt.timezone.utc)

STOPWORDS = set(
    "der die das den dem des ein eine einen einem einer und oder aber mit von für auf aus bei nach über unter "
    "ist sind wird werden wurde wurden hat haben soll sollen will wollen kann nicht auch noch nur wie was wer "
    "the and for with from that this has have will are was were its their after over into about says say new"
    .split()
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def parse_feed(raw, feed):
    root = ET.fromstring(raw)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in el:
            f.setdefault(local(c.tag), c)

        def text(name):
            return (f[name].text or "") if name in f else ""

        title = clean(text("title"))
        link = ""
        if "link" in f:
            link = f["link"].get("href") or (f["link"].text or "").strip()
        when = next((parse_date(text(n)) for n in ("pubdate", "published", "updated", "date") if text(n)), None)
        source = feed["name"]
        if feed.get("google"):
            if text("source"):
                source = clean(text("source"))
                suffix = " - " + source
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
            summary = ""
        else:
            summary = clean(text("description") or text("summary") or text("encoded") or text("content"))
        if not (title and link and when):
            continue
        items.append({"title": title, "url": link, "time": when, "summary": summary[:320], "source": source,
                      "lang": feed.get("lang", "de"), "hint": feed.get("hint", "general"), "google": bool(feed.get("google"))})
    return items


def load_feed(feed):
    try:
        items = parse_feed(fetch(feed["url"]), feed)
        return feed["name"], items, None
    except Exception as e:
        return feed["name"], [], f"{type(e).__name__}: {e}"


def compile_keywords(words):
    pats = []
    for w in words:
        if w.endswith("$"):
            pats.append(re.compile(r"\b" + re.escape(w[:-1]) + r"\b", re.I))
        else:
            pats.append(re.compile(r"\b" + re.escape(w), re.I))
    return pats


def count_hits(pats, title, summary):
    return sum(2 for p in pats if p.search(title)) + sum(1 for p in pats if p.search(summary))


def tokens(title):
    return {w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", title.lower()) if w not in STOPWORDS}


def similar(a, b):
    inter = len(a & b)
    if inter < 3 and not (inter >= 2 and min(len(a), len(b)) <= 3):
        return False
    return inter / len(a | b) >= 0.4 or inter / min(len(a), len(b)) >= 0.6


def cluster(items):
    clusters = []
    for it in sorted(items, key=lambda x: x["time"], reverse=True):
        it["tok"] = tokens(it["title"])
        for c in clusters:
            if any(similar(it["tok"], m["tok"]) for m in c):
                c.append(it)
                break
        else:
            clusters.append([it])
    return clusters


def build_stories(cfg):
    results = list(ThreadPoolExecutor(max_workers=8).map(load_feed, cfg["feeds"]))
    feed_status = [{"name": n, "count": len(i), "error": e} for n, i, e in results]
    cutoff = NOW - dt.timedelta(hours=cfg["max_age_hours"])
    block = compile_keywords(cfg["blocklist"])
    topics = {k: compile_keywords(v) for k, v in cfg["topics"].items()}
    watch = [(w, re.compile(r"\b" + re.escape(w), re.I)) for w in cfg["watchlist"]]

    items = []
    for _, its, _ in results:
        for it in its:
            if it["time"] < cutoff or any(p.search(it["title"]) for p in block):
                continue
            items.append(it)

    stories = []
    for members in cluster(items):
        scores = {k: 0 for k in topics}
        for m in members:
            for k, pats in topics.items():
                scores[k] += count_hits(pats, m["title"], m["summary"])
            if m["hint"] in scores:
                scores[m["hint"]] += 2
        topic, top = max(scores.items(), key=lambda kv: kv[1])
        blob = " ".join(m["title"] + " " + m["summary"] for m in members)
        hits = [w for w, p in watch if p.search(blob)]
        if top < 3 and not hits:
            continue
        # Leitmeldung: bevorzugt Original-Feed mit Teaser, dann die neueste
        lead = max(members, key=lambda m: (bool(m["summary"]), not m["google"], m["time"]))
        sources, seen = [], set()
        for m in sorted(members, key=lambda m: m["time"], reverse=True):
            if m["source"] not in seen:
                seen.add(m["source"])
                sources.append({"name": m["source"], "url": m["url"]})
        newest = max(m["time"] for m in members)
        age_h = (NOW - newest).total_seconds() / 3600
        score = 3 * len(sources) + min(top, 6) + max(0, 3 - age_h / 8) + min(3 * len(hits), 6)
        stories.append({
            "title": lead["title"], "summary": lead["summary"], "url": lead["url"], "lang": lead["lang"],
            "topic": topic, "score": round(score, 2), "time": newest.isoformat(),
            "sources": sources, "watch": hits,
        })
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories, feed_status


def build_heute(stories, per_topic):
    picked = []
    for topic in ("markets", "world"):
        picked += [s for s in stories if s["topic"] == topic][:per_topic]
    picked.sort(key=lambda s: s["score"], reverse=True)
    return picked


def fetch_quote(q):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(q["symbol"]) + "?interval=1d&range=5d"
    try:
        meta = json.loads(fetch(url, 15))["chart"]["result"][0]["meta"]
        return {"name": q["name"], "symbol": q["symbol"], "price": meta["regularMarketPrice"],
                "pct": meta.get("regularMarketChangePercent"), "currency": meta.get("currency", "")}
    except Exception as e:
        return {"name": q["name"], "symbol": q["symbol"], "price": None, "pct": None, "currency": "", "error": str(e)}


PM_CATEGORIES = [
    ("Wahlen", {"elections", "global-elections", "world-elections", "main-election"}),
    ("Geopolitik", {"geopolitics", "world", "middle-east", "ukraine", "china", "russia"}),
    ("Politik", {"politics"}),
    ("Wirtschaft", {"economy", "finance", "business", "fed"}),
    ("Krypto", {"crypto"}),
    ("Tech", {"tech"}),
]


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


def build_polymarket(cfg):
    pm = cfg["polymarket"]
    url = ("https://gamma-api.polymarket.com/events?active=true&closed=false&order=volume24hr&ascending=false"
           f"&limit={pm['fetch_limit']}")
    try:
        events = json.loads(fetch(url, 30))
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    include, exclude = set(pm["include_tags"]), set(pm["exclude_tags"])
    out = []
    for ev in events:
        tags = {t.get("slug", "") for t in ev.get("tags", [])}
        if tags & exclude or not tags & include:
            continue
        rows = []
        for m in ev.get("markets", []):
            if m.get("closed") or not m.get("active", True):
                continue
            prices = jlist(m.get("outcomePrices"))
            if not prices:
                continue
            multi = len(ev.get("markets", [])) > 1
            rows.append({"label": (m.get("groupItemTitle") or m.get("question")) if multi else "Ja",
                         "p": num(prices[0]), "d1": m.get("oneDayPriceChange")})
        if not rows:
            continue
        rows.sort(key=lambda r: r["p"], reverse=True)
        category = next((name for name, slugs in PM_CATEGORIES if tags & slugs), "Sonstiges")
        out.append({"title": ev.get("title", ""), "url": "https://polymarket.com/event/" + ev.get("slug", ""),
                    "category": category, "vol24h": num(ev.get("volume24hr")), "vol": num(ev.get("volume")),
                    "end": (ev.get("endDate") or "")[:10], "rows": rows[:5], "more": max(0, len(rows) - 5)})
        if len(out) >= pm["max_events"]:
            break
    return out, None


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=8) as ex:
        quotes_f = [ex.submit(fetch_quote, q) for q in cfg["quotes"]]
        pm_f = ex.submit(build_polymarket, cfg)
        stories, feed_status = build_stories(cfg)
        quotes = [f.result() for f in quotes_f]
        polymarket, pm_error = pm_f.result()

    data = {
        "generated": NOW.isoformat(),
        "quotes": quotes,
        "stories": stories,
        "heute": build_heute(stories, cfg["heute_per_topic"]),
        "polymarket": polymarket,
        "status": {"feeds": feed_status, "polymarket_error": pm_error},
    }
    OUT.mkdir(exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    page = (ROOT / "template.html").read_text(encoding="utf-8").replace("__DATA__", blob)
    (OUT / "index.html").write_text(page, encoding="utf-8")

    for f in feed_status:
        print(("OK   " if not f["error"] else "FAIL ") + f"{f['name']:<28} {f['count']:>3}  {f['error'] or ''}")
    print(f"\n{len(stories)} Meldungen, {len(polymarket)} Prediction Markets, "
          f"{sum(1 for q in quotes if q['price'] is not None)}/{len(quotes)} Kurse -> {OUT / 'index.html'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

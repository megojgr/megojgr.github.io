"""Sendungen und Newsletter für den Deutschland-Tab: tagesschau 20 Uhr, tagesthemen, Handelsblatt Morning Briefing."""
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET

from net import fetch

try:
    from email.utils import parsedate_to_datetime
except ImportError:  # pragma: no cover
    parsedate_to_datetime = None


def _items(raw):
    root = ET.fromstring(raw)
    for it in root.iter("item"):
        f = {c.tag.split("}")[-1].lower(): (c.text or "").strip() for c in it}
        try:
            when = parsedate_to_datetime(f.get("pubdate", "")).astimezone(dt.timezone.utc)
        except Exception:
            continue
        if f.get("title") and f.get("link"):
            yield {"title": html.unescape(f["title"]), "url": f["link"], "time": when}


def _show_topics(page_html):
    text = re.sub(r"(?s)<(script|style).*?</\1>", " ", page_html)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    m = re.search(r"Themen der Sendung:\s*(.*?)(?:\sHinweis:|\stagesschau Weitere|\stagesthemen Weitere|$)", text)
    if not m:
        return []
    topics = [t.strip(" .") for t in re.split(r",\s+(?=[A-ZÄÖÜ„\"])", m.group(1)[:1500])]
    return [t for t in topics if t and t.lower() != "das wetter" and len(t) < 160][:12]


def youtube(feed, title_re):
    """Neuestes Video eines YouTube-Kanals (Atom-Feed, frei) mit passendem Titel, z. B. "tagesschau 20:00 Uhr, 28.10.2026"."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(fetch(feed, 20))
    best = None
    for e in root.findall("a:entry", ns):
        title = html.unescape(e.findtext("a:title", "", ns))
        link = e.find("a:link", ns)
        when = e.findtext("a:published", "", ns)
        if re.search(title_re, title) and link is not None and when and (best is None or when > best["time"]):
            best = {"title": title, "url": link.get("href"), "time": when}
    return best


def show(b):
    """Neueste Folge einer TV-Sendung samt Themenliste von ihrer Seite."""
    link_re = re.compile(b["link_re"])
    cands = [i for i in _items(fetch(b["feed"], 20)) if link_re.search(i["url"])]
    if not cands:
        return None
    latest = max(cands, key=lambda i: i["time"])
    topics = []
    try:
        topics = _show_topics(fetch(latest["url"], 25).decode("utf-8", "replace"))
    except Exception:
        pass  # ohne Themenliste bleibt der Link zur Sendung
    day = latest["time"].astimezone().strftime("%d.%m.%Y")
    yt = None
    if b.get("youtube_feed"):
        try:
            yt = youtube(b["youtube_feed"], b["youtube_re"])
        except Exception:
            pass  # ohne YouTube-Link bleibt der Link zur Sendung
    return {"name": b["name"], "title": f"{b['name']} vom {day}", "url": latest["url"],
            "time": latest["time"].isoformat(), "topics": topics, "youtube": yt}


def google(b):
    """Newsletter-Ausgaben über eine Google-News-Suche (z. B. "Morning Briefing"), neueste Ausgabe."""
    cands = [i for i in _items(fetch(b["url"], 20)) if i["title"].lower().startswith(b["prefix"].lower())]
    if not cands:
        return None
    latest = max(cands, key=lambda i: i["time"])
    title = re.sub(r"\s+-\s+[^-]+$", "", latest["title"])
    return {"name": b["name"], "title": title, "url": latest["url"], "time": latest["time"].isoformat(), "topics": []}


def build(cfg):
    out, errors = [], []
    for b in cfg["briefings"]:
        try:
            r = show(b) if b["kind"] == "show" else google(b)
            if r:
                out.append(r)
        except Exception as e:
            errors.append(f"{b['name']}: {type(e).__name__}")
    return out, errors

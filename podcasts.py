"""Neueste Folgen der Lieblings-Podcasts: Titel und Datum aus dem Feed, direkter Link zur Folge von der Spotify-Einbettungsseite."""
import datetime as dt
import html
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

from net import BROWSER_UA, fetch

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _key(title):
    return re.sub(r"\W+", "", title.lower())


def _minutes(text):
    """itunes:duration steht als Sekunden oder als hh:mm:ss im Feed."""
    try:
        parts = [int(x) for x in (text or "").strip().split(":")]
    except ValueError:
        return None
    seconds = 0
    for x in parts:
        seconds = seconds * 60 + x
    return round(seconds / 60) or None


def latest_in_feed(url, skip_re=None):
    """Neueste reguläre Folge; Hinweise auf andere Podcasts (skip_re) zählen nicht."""
    skip = re.compile(skip_re, re.I) if skip_re else None
    best = None
    for it in ET.fromstring(fetch(url, 25)).find("channel").findall("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            continue
        if title and not (skip and skip.search(title)) and (best is None or when > best["when"]):
            best = {"title": title, "when": when, "minutes": _minutes(it.findtext(ITUNES + "duration"))}
    return best


def latest_on_spotify(show):
    """Die Einbettungsseite einer Sendung nennt ihre neueste Folge samt Kennung und Cover."""
    page = fetch(f"https://open.spotify.com/embed/show/{show}", 25, ua=BROWSER_UA).decode("utf-8", "replace")
    entity = json.loads(NEXT_DATA.search(page).group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    art = entity.get("relatedEntityCoverArt") or []
    return {"id": entity["id"], "title": entity.get("title") or "", "image": art[0]["url"] if art else None}


def one(p):
    show_url = f"https://open.spotify.com/show/{p['spotify_show']}"
    out = {"name": p["name"], "by": p.get("by"), "show_url": show_url, "url": show_url, "exact": False,
           "title": None, "time": None, "minutes": None, "image": None, "error": None}
    try:
        ep = latest_in_feed(p["feed"], p.get("skip_re"))
        if ep:
            out.update(title=ep["title"], time=ep["when"].isoformat(), minutes=ep["minutes"])
    except Exception as e:
        out["error"] = f"Feed: {type(e).__name__}"
    try:
        sp = latest_on_spotify(p["spotify_show"])
        out["image"] = sp["image"]
        # Nur auf die Folge verlinken, wenn Spotify wirklich dieselbe hat; sonst führt der Knopf zur Sendung
        if not out["title"] or _key(sp["title"]) == _key(out["title"]):
            out.update(url=f"https://open.spotify.com/episode/{sp['id']}", exact=True, title=out["title"] or sp["title"])
    except Exception as e:
        out["error"] = f"Spotify: {type(e).__name__}"
    return out


def build(cfg):
    podcasts = cfg.get("podcasts") or []
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(one, podcasts))

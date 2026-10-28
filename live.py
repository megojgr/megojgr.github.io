"""Live-Radar: Welche Sender streamen gerade auf YouTube, was ist angekündigt (Pressekonferenzen, Reden, Sondersendungen)?

Liest die öffentliche /live-Seite jedes Kanals. Kein Schlüssel nötig. Fällt YouTube aus oder sperrt den Abruf,
bleibt der letzte gute Stand aus cache/live.json stehen; der Player lässt sich trotzdem öffnen.
"""
import datetime as dt
import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from net import BROWSER_UA, fetch

CACHE = Path(__file__).parent / "cache" / "live.json"
YT = {"Accept-Language": "de-DE,de;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI"}


def embeddable(video):
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video}&format=json",
            headers={"User-Agent": BROWSER_UA}), timeout=15)
        return True
    except Exception:
        return False


def check(ch):
    out = {"name": ch["name"], "group": ch["group"], "handle": ch.get("handle"), "state": "unbekannt",
           "video": None, "title": "", "start": None, "embed": False, "channel_id": None, "url": ch.get("url")}
    if not ch.get("handle"):
        out["state"] = "extern"  # nur ein Link zur offiziellen Seite des Senders
        return out
    try:
        page = fetch(f"https://www.youtube.com/@{ch['handle']}/live", 30, headers=YT, ua=BROWSER_UA).decode("utf-8", "replace")
    except Exception as e:
        out["error"] = f"{type(e).__name__}"
        return out
    chan = re.search(r'rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page)
    video = re.search(r'rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', page)
    status = re.search(r'"playabilityStatus":\{"status":"([A-Z_]+)"', page)
    sched = re.search(r'"scheduledStartTime":"(\d+)"', page)
    title = re.search(r'<meta name="title" content="([^"]*)"', page)
    if "consent.youtube.com" in page[:4000] or "<title>" not in page:
        out["error"] = "Abruf von YouTube blockiert"
        return out
    out["state"] = "aus"
    st = status.group(1) if status else None
    # Von Servern in Rechenzentren verlangt YouTube bei laufenden Streams oft eine Anmeldung (LOGIN_REQUIRED) und
    # lässt die canonical-Angabe weg. Die Video-Kennung steht dann trotzdem im Block "videoDetails".
    d = page.find('"videoDetails":{')
    details = page[d:d + 4000] if d >= 0 else ""
    vid = video.group(1) if video else None
    if not vid and details:
        m = re.search(r'"videoId":"([\w-]{11})"', details)
        vid = m.group(1) if m else None
    if chan:
        out["channel_id"] = chan.group(1)
    elif details:
        m = re.search(r'"channelId":"(UC[\w-]{22})"', details)
        out["channel_id"] = m.group(1) if m else None
    is_live = '"isLive":true' in (details or page)
    out["dbg"] = f"{st}|live={is_live}|video={bool(vid)}|{len(page) // 1000}k"
    out["title"] = html.unescape(title.group(1)) if title else ""
    if st == "LIVE_STREAM_OFFLINE" and sched and vid:
        start = int(sched.group(1))
        if start > dt.datetime.now(dt.timezone.utc).timestamp() - 3 * 3600:
            out["state"], out["start"] = "geplant", start
    elif is_live and st != "LIVE_STREAM_OFFLINE" and (vid or out["channel_id"]):
        out["state"] = "live"
    if out["state"] == "aus":
        out["title"] = ""
    else:
        out["video"] = vid
        out["embed"] = embeddable(vid) if vid else False
    return out


def build(cfg):
    channels = cfg["live"]["channels"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(check, channels))
    ok = sum(1 for r in results if r["state"] in ("live", "geplant", "aus"))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    youtube = [r for r in results if r["state"] != "extern"]
    if youtube and ok == 0:  # alles fehlgeschlagen: letzten guten Stand behalten
        try:
            old = json.loads(CACHE.read_text(encoding="utf-8"))
            old["stale"] = True
            return old
        except Exception:
            pass
    data = {"checked": now, "channels": results, "ok": ok, "failed": len(youtube) - ok, "stale": False}
    if ok:
        try:
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
    return data

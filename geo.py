"""Lagebild für den Globus: Konflikte (GDELT), Meerengen (IMF PortWatch), Wahlen, Flugzeugträger (USNI).

Alles kostenlos und ohne Schlüssel. Fällt eine Quelle aus, wird der letzte gute Stand aus cache/geo.json gezeigt.
"""
import collections
import datetime as dt
import html
import io
import json
import math
import os
import re
import sys
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from briefings import _items as rss_items
from elections import COUNTRY_DE
from net import fetch
from textutil import compile_keywords

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "geo.json"
WORLD = ROOT / "static" / "world.json"
PORTWATCH = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"

# Namen aus GDELT und Wikipedia -> Namen in der Weltkarte (Natural Earth)
ALIASES = {
    "United States": "United States of America", "USA": "United States of America", "Czech Republic": "Czechia",
    "Bosnia and Herzegovina": "Bosnia and Herz.", "Democratic Republic of the Congo": "Dem. Rep. Congo",
    "Congo (Kinshasa)": "Dem. Rep. Congo", "Republic of the Congo": "Congo", "Congo (Brazzaville)": "Congo",
    "Central African Republic": "Central African Rep.", "South Sudan": "S. Sudan", "Dominican Republic": "Dominican Rep.",
    "Western Sahara": "W. Sahara", "Ivory Coast": "Côte d'Ivoire", "Swaziland": "eSwatini", "Eswatini": "eSwatini",
    "North Macedonia": "Macedonia", "Burma": "Myanmar", "Equatorial Guinea": "Eq. Guinea",
    "Solomon Islands": "Solomon Is.", "Falkland Islands": "Falkland Is.", "West Bank": "Palestine",
    "Gaza Strip": "Palestine", "Palestinian Territories": "Palestine", "Timor Leste": "Timor-Leste",
    "East Timor": "Timor-Leste", "The Gambia": "Gambia", "Russian Federation": "Russia", "Korea, South": "South Korea",
    "Korea, North": "North Korea", "Syrian Arab Republic": "Syria", "Turkiye": "Turkey", "Türkiye": "Turkey",
    "Cabo Verde": "Cape Verde", "Hong Kong": "China",
}


def load_world():
    feats = json.loads(WORLD.read_text(encoding="utf-8"))["features"]
    return {f["properties"]["name"]: f["id"] for f in feats}


def find_country(name, world):
    name = (name or "").strip()
    name = ALIASES.get(name, name)
    return (name, world[name]) if name in world else (None, None)


def de_name(name):
    """Deutscher Landesname zu einem Namen der Weltkarte, z. B. "United States of America" -> "USA"."""
    if name in COUNTRY_DE:
        return COUNTRY_DE[name]
    for en, ne in ALIASES.items():
        if ne == name and en in COUNTRY_DE:
            return COUNTRY_DE[en]
    return name


# ---------------------------------------------------------------- Konflikte (GDELT)

def gdelt_day(day):
    """Ein Tag GDELT-Ereignisse: bewaffnete Gewalt (CAMEO 18-20 mit Militär- oder Rebellenbeteiligung)."""
    raw = fetch(f"https://data.gdeltproject.org/events/{day:%Y%m%d}.export.CSV.zip", 150, retries=1)
    z = zipfile.ZipFile(io.BytesIO(raw))
    cells, countries = {}, collections.Counter()
    with z.open(z.namelist()[0]) as f:
        for line in f:
            p = line.decode("utf-8", "replace").rstrip("\n").split("\t")
            if len(p) < 58:
                continue
            root, actors = p[28], p[5] + p[15]
            armed = any(x in actors for x in ("MIL", "REB", "SPY"))
            if not ((root in ("19", "20") and (armed or root == "20")) or (root == "18" and armed)):
                continue
            try:
                lat, lon, geo_type, w = float(p[53]), float(p[54]), p[49], max(1, int(p[31] or 1))
            except ValueError:
                continue
            full = p[50]
            if full.startswith(("White House", "Capitol")):
                continue  # Behörden-Treffer in Washington sind keine Kampfhandlungen
            country = full if geo_type == "1" else full.split(",")[-1].strip()
            if "Gaza" in full or "West Bank" in full:
                country = "Palestine"
            countries[country] += w
            if geo_type in ("3", "4", "5"):  # nur Orte, keine Länder-Mittelpunkte
                key = (round(lat), round(lon))
                c = cells.setdefault(key, {"w": 0, "n": 0, "best": (0, lat, lon, full)})
                c["w"] += w
                c["n"] += 1
                if w > c["best"][0]:
                    c["best"] = (w, lat, lon, full)
    return cells, countries


def conflicts(today, days, max_points, world, reason_countries=20):
    cells, countries, used = {}, collections.Counter(), []
    for back in range(1, days + 3):
        if len(used) >= days:
            break
        day = today - dt.timedelta(days=back)
        try:
            c, k = gdelt_day(day)
        except Exception:
            continue  # Tagesdatei noch nicht da: einen Tag weiter zurück
        used.append(day.isoformat())
        countries.update(k)
        for key, v in c.items():
            t = cells.setdefault(key, {"w": 0, "n": 0, "best": v["best"]})
            t["w"] += v["w"]
            t["n"] += v["n"]
            if v["best"][0] > t["best"][0]:
                t["best"] = v["best"]
    if not used:
        raise RuntimeError("keine GDELT-Tagesdatei erreichbar")
    points = []
    for v in sorted(cells.values(), key=lambda v: v["w"], reverse=True)[:max_points]:
        _, lat, lon, full = v["best"]
        parts = [x.strip() for x in full.split(",") if x.strip()]
        country = "Palestine" if ("Gaza" in full or "West Bank" in full) else (parts[-1] if parts else "")
        points.append({"lat": round(lat, 2), "lon": round(lon, 2), "w": v["w"], "n": v["n"],
                       "name": ", ".join(dict.fromkeys([parts[0], parts[-1]])) if parts else full,
                       "cid": find_country(country, world)[1]})
    merged = collections.Counter()
    for name, w in countries.items():
        ne, _ = find_country(name, world)
        if ne:
            merged[ne] += w
    top = [{"id": world[n], "name": n, "name_de": de_name(n), "w": w} for n, w in merged.most_common(40)]
    reasons(top, reason_countries)
    return {"days": used, "points": points, "countries": top}


REASON_NAMES = {"Palestine": "Gaza OR Westjordanland", "United States of America": "USA"}


def reasons(countries, how_many):
    """Zu den Ländern mit den meisten Konfliktmeldungen: aktuelle Schlagzeilen als Hinweis auf den Anlass."""
    def one(c):
        name = REASON_NAMES.get(c["name"]) or c["name_de"]
        q = f"({name}) (Krieg OR Angriff OR Kämpfe OR Beschuss OR Militär OR Anschlag OR Luftangriff OR Raketen) when:2d"
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=de&gl=DE&ceid=DE:de"
        try:
            items = sorted(rss_items(fetch(url, 20)), key=lambda i: i["time"], reverse=True)
        except Exception:
            return []
        out, seen = [], set()
        for i in items:
            m = re.match(r"(.*)\s+-\s+([^-]+)$", i["title"])
            title, source = (m.group(1), m.group(2).strip()) if m else (i["title"], "")
            key = re.sub(r"\W+", "", title.lower())[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "source": source, "url": i["url"], "time": i["time"].isoformat()})
            if len(out) == 4:
                break
        return out

    with ThreadPoolExecutor(max_workers=6) as ex:
        for c, news in zip(countries[:how_many], ex.map(one, countries[:how_many])):
            c["news"] = news


# ---------------------------------------------------------------- Meerengen (IMF PortWatch)

def portwatch_one(cp):
    where = urllib.parse.quote(f"portid='{cp['id']}'")
    url = (f"{PORTWATCH}/Daily_Chokepoints_Data/FeatureServer/0/query?where={where}&outFields=date,n_total"
           "&orderByFields=date%20DESC&resultRecordCount=420&returnGeometry=false&f=json")
    rows = [f["attributes"] for f in json.loads(fetch(url, 40))["features"]]
    return [(r["date"], r["n_total"]) for r in rows if r.get("date") and r.get("n_total") is not None]


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def chokepoints_data(cfg_cps):
    meta_url = (f"{PORTWATCH}/PortWatch_chokepoints_database/FeatureServer/0/query?where=1%3D1"
                "&outFields=portid,portname,lat,lon&returnGeometry=false&f=json&resultRecordCount=60")
    meta = {f["attributes"]["portid"]: f["attributes"] for f in json.loads(fetch(meta_url, 40))["features"]}
    with ThreadPoolExecutor(max_workers=6) as ex:
        series = list(ex.map(lambda cp: portwatch_one(cp) if cp["id"] in meta else [], cfg_cps))
    out = []
    for cp, rows in zip(cfg_cps, series):
        m = meta.get(cp["id"])
        if not m or len(rows) < 30:
            continue
        counts = [n for _, n in rows]
        last7 = mean(counts[:7])
        last_date = dt.date.fromisoformat(rows[0][0])
        year_ago = [n for d, n in rows if abs((dt.date.fromisoformat(d) - (last_date - dt.timedelta(days=365))).days) <= 10]
        if len(year_ago) >= 10:
            base, label = mean(year_ago), "Vorjahr"
        else:
            base, label = mean(counts[30:120]), "90-Tage-Schnitt"
        pct = (last7 / base - 1) * 100 if base and base >= 5 else None
        out.append({"id": cp["id"], "name": cp["name"], "lat": round(m["lat"], 3), "lon": round(m["lon"], 3),
                    "last7": round(last7, 1), "base": round(base, 1) if base else None, "base_label": label,
                    "pct": None if pct is None else round(pct, 1), "date": rows[0][0],
                    "history": list(reversed(counts[:60]))})
    return out


def attach_news(cps, cfg_cps, stories, closure_words):
    kw = {cp["id"]: compile_keywords(cp["keywords"]) for cp in cfg_cps}
    closure = compile_keywords(closure_words)
    for cp in cps:
        pats = kw[cp["id"]]
        hits = [s for s in stories if any(p.search(s["title"]) for p in pats)]
        hits.sort(key=lambda s: s["score"], reverse=True)
        cp["news"] = [{"title": s.get("title_de") or s["title"], "url": s["url"], "time": s["time"]} for s in hits[:3]]
        cp["news_count"] = len(hits)
        cp["alert_count"] = sum(1 for s in hits if any(p.search(s["title"]) for p in closure))
        level = 0
        if cp["pct"] is not None:
            level = 2 if cp["pct"] <= -50 else 1 if cp["pct"] <= -20 else 0
        if cp["alert_count"] >= 3:
            level = max(level, 1)
        cp["level"] = level
    return cps


# ---------------------------------------------------------------- Flugzeugträger (USNI Fleet Tracker)

PLACES = {
    "eastern mediterranean": (34.0, 31.0), "mediterranean": (35.0, 18.0), "arabian sea": (16.0, 63.0),
    "persian gulf": (27.0, 51.5), "gulf of oman": (24.5, 58.5), "red sea": (20.0, 38.0), "gulf of aden": (12.0, 48.0),
    "philippine sea": (20.0, 132.0), "south china sea": (14.0, 114.0), "east china sea": (28.0, 126.0),
    "sea of japan": (40.0, 134.0), "western pacific": (20.0, 140.0), "eastern pacific": (15.0, -120.0),
    "pacific ocean": (22.0, -155.0), "atlantic ocean": (30.0, -45.0), "caribbean": (15.0, -75.0),
    "baltic": (57.0, 19.0), "north sea": (56.0, 3.0), "norwegian sea": (68.0, 5.0), "indian ocean": (-5.0, 75.0),
    "gulf of mexico": (25.0, -90.0), "norfolk": (36.95, -76.3), "san diego": (32.7, -117.2), "bremerton": (47.57, -122.63),
    "everett": (47.98, -122.2), "yokosuka": (35.28, 139.67), "sasebo": (33.16, 129.72), "phuket": (7.9, 98.4),
    "japan": (35.0, 139.0), "guam": (13.4, 144.7), "pearl harbor": (21.35, -157.95), "hawaii": (21.35, -157.95),
    "newport news": (37.0, -76.4), "mayport": (30.4, -81.4), "bahrain": (26.2, 50.6), "rota": (36.6, -6.3),
    "naples": (40.85, 14.27), "souda bay": (35.5, 24.1), "singapore": (1.3, 103.8), "busan": (35.1, 129.0),
    "manila": (14.6, 120.9), "diego garcia": (-7.3, 72.4), "djibouti": (11.6, 43.1), "duqm": (19.7, 57.7),
    "thailand": (13.0, 101.0), "philippines": (13.0, 122.0), "australia": (-25.0, 134.0), "south korea": (36.0, 128.0),
}


def carriers_data():
    raw = fetch("https://news.usni.org/category/fleet-tracker/feed", 40).decode("utf-8", "replace")
    items = re.findall(r"<item>(.*?)</item>", raw, re.S)
    item = next((i for i in items if "Fleet and Marine Tracker" in i), None)
    if not item:
        raise RuntimeError("kein Fleet Tracker im Feed")
    title = re.search(r"<title>(.*?)</title>", item, re.S).group(1)
    link = re.search(r"<link>(.*?)</link>", item, re.S).group(1).strip()
    when = re.search(r"<pubDate>(.*?)</pubDate>", item).group(1)
    body = re.search(r"<content:encoded><!\[CDATA\[(.*?)\]\]>", item, re.S).group(1)
    text = re.sub(r"(?s)<(script|style).*?</\1>", " ", body)
    text = re.sub(r"</(p|li|h\d|div|figcaption)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]
    ships, heading, seen = [], None, set()
    keys = sorted(PLACES, key=len, reverse=True)
    for ln in lines:
        if re.match(r"^In (the )?[A-Z][^.]{2,50}\.?$", ln) and "CVN" not in ln and len(ln) < 60:
            heading = ln
            continue
        m = re.match(r"^USS ([A-Z][A-Za-z. ]+?)\s*\(CVN-(\d+)\)", ln)
        if m and heading and m.group(2) not in seen:
            seen.add(m.group(2))
            low = heading.lower()
            place = min((k for k in keys if k in low), key=lambda k: (low.index(k), -len(k)), default=None)
            ships.append({"name": "USS " + m.group(1).replace(" .", ".").strip(), "hull": "CVN-" + m.group(2),
                          "where": re.sub(r"^In (the )?", "", heading).rstrip("."),
                          "lat": PLACES[place][0] if place else None, "lon": PLACES[place][1] if place else None})
    # Schiffe an derselben Stelle (z. B. "Pazifik") leicht auseinanderziehen, damit sie sich nicht verdecken
    groups = collections.defaultdict(list)
    for s in ships:
        if s["lat"] is not None:
            groups[(s["lat"], s["lon"])].append(s)
    for members in groups.values():
        if len(members) > 1:
            for i, s in enumerate(members):
                a = 2 * math.pi * i / len(members)
                s["lat"] = round(s["lat"] + 3 * math.sin(a), 2)
                s["lon"] = round(s["lon"] + 3 * math.cos(a), 2)
    day = re.search(r"Tracker:\s*(.*)$", title)
    return {"ships": ships, "title": title, "url": link, "published": when, "as_of": day.group(1).strip() if day else ""}


def carrier_headlines():
    url = ("https://news.google.com/rss/search?q=Flugzeugtr%C3%A4ger+OR+%22aircraft+carrier%22+when:3d&hl=de&gl=DE&ceid=DE:de")
    items = sorted(rss_items(fetch(url, 20)), key=lambda i: i["time"], reverse=True)[:6]
    return [{"title": re.sub(r"\s+-\s+[^-]+$", "", i["title"]), "url": i["url"], "time": i["time"].isoformat()} for i in items]


# ---------------------------------------------------------------- Erdbeben (USGS)

def place_de(place):
    """"191 km ENE of Nagqu, China" -> "Nagqu, China (191 km ONO)"; Himmelsrichtungen auf Deutsch (E = Ost)."""
    m = re.match(r"^(\d+) km ([NSEW]{1,3}) of (.+)$", place)
    return f"{m.group(3)} ({m.group(1)} km {m.group(2).replace('E', 'O')})" if m else place


def quakes_data():
    """Beben ab Stärke 4,5 der letzten 7 Tage (USGS, frei, ohne Schlüssel)."""
    feed = json.loads(fetch("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson", 30))
    items = []
    for f in feed["features"]:
        p = f["properties"]
        if p.get("mag") is None:
            continue
        lon, lat, depth = f["geometry"]["coordinates"][:3]
        items.append({"lat": round(lat, 2), "lon": round(lon, 2), "mag": round(p["mag"], 1), "depth": round(depth or 0),
                      "t": int(p["time"] / 1000), "place": place_de(p.get("place") or ""), "url": p.get("url") or "",
                      "tsunami": int(p.get("tsunami") or 0), "felt": int(p.get("felt") or 0)})
    items.sort(key=lambda x: -x["t"])
    return {"items": items}


# ---------------------------------------------------------------- Wahlen

def elections_layer(election_list, world, horizon_days, today):
    out = []
    for e in election_list:
        name, cid = find_country(e.get("country_en"), world)
        if not name:
            continue
        days = (dt.date.fromisoformat(e["date"]) - today).days
        if days > horizon_days:
            continue
        out.append({"id": cid, "name": name, "name_de": e["country"], "date": e["date"], "end": e["end"],
                    "what": e["what"], "url": e["url"], "days": days, "important": e["important"]})
    return out


# ---------------------------------------------------------------- Zusammenbau

def build(cfg, stories, election_list, today):
    g = cfg["geo"]
    world = load_world()
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    notes, now = {}, dt.datetime.now(dt.timezone.utc).isoformat()

    force = bool(os.environ.get("GEO_FULL")) or "--full" in sys.argv

    def part(key, fn):
        """Langsame Quellen nur nach Ablauf ihrer Frist neu laden (stündliche Läufe bleiben schlank)."""
        cached = cache.get(key)
        if cached and not force and cached.get("fetched") and not cached.get("stale"):
            age_h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cached["fetched"])).total_seconds() / 3600
            if age_h < g["ttl_hours"].get(key, 6):
                return cached
        try:
            value = fn()
            value["fetched"] = now
            cache[key] = value
        except Exception as e:
            notes[key] = f"{type(e).__name__}: {str(e)[:90]}"
            value = cached
            if value:
                value["stale"] = True
        return value

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_conf = ex.submit(part, "conflict", lambda: conflicts(today, g["conflict_days"], g["conflict_max_points"], world, g["reason_countries"]))
        f_cp = ex.submit(part, "chokepoints", lambda: {"items": chokepoints_data(g["chokepoints"])})
        f_car = ex.submit(part, "carriers", carriers_data)
        f_eq = ex.submit(part, "quakes", quakes_data)
        conflict, cps, carriers, quakes = f_conf.result(), f_cp.result(), f_car.result(), f_eq.result()
    try:
        headlines = carrier_headlines()
    except Exception:
        headlines = []
    try:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
    items = attach_news(cps["items"] if cps else [], g["chokepoints"], stories, g["closure_words"])
    if carriers:
        carriers = dict(carriers, headlines=headlines)
    return {
        "names": {cid: de_name(name) for name, cid in world.items()},
        "conflict": conflict, "chokepoints": items, "carriers": carriers, "quakes": quakes,
        "elections": elections_layer(election_list, world, g["election_days"], today), "notes": notes,
    }

"""Frühwarn-Ebenen für den Globus: Aufklärungssatelliten, GPS-Störungen und Internet-Ausfälle.

Alles kostenlos und ohne Schlüssel:
- Satellitenbahnen: CelesTrak (öffentliche Bahndaten des US-Weltraumkommandos). Die Position berechnet der Browser
  selbst aus den Bahndaten, so bewegen sich die Satelliten live über den Globus.
- GPS-Störungen: gpsjam.org (aus den Positionsmeldungen von Flugzeugen, Datenbasis ADS-B Exchange), täglich.
- Internet-Ausfälle: IODA (Georgia Tech), automatisch erkannte Ausfälle ganzer Länder.
"""
import collections
import datetime as dt
import gzip
import math
import re
import time
import urllib.parse

from net import fetch

UA = "MegoNews/1.0 (privater News-Leser)"

# ---------------------------------------------------------------- Satelliten

# Gar nicht zeigen: Navigation, Kommunikation, Wetter, Vermessung (überwachen keine Gebiete)
SAT_SKIP = re.compile(r"GLONASS|NAVSTAR|\bGPS\b|BEIDOU|GALILEO|ETALON|RODNIK|STRELA|GEO-IK|PARUS|MOZHAETS|SKRL|"
                      r"\bWGS\b|AEHF|MUOS|MILSTAR|\bUFO\b|FLTSAT|DSCS|DMSP|SBSS|O/OREOS|FASTSAT|IGSO|SEAHAWK")

LAND = {"CN": "China", "RU": "Russland", "US": "USA", "DE": "Deutschland", "FR": "Frankreich", "IT": "Italien",
        "ES": "Spanien", "IL": "Israel", "IN": "Indien", "TR": "Türkei", "KP": "Nordkorea", "KR": "Südkorea",
        "IR": "Iran", "AE": "VAE", "JP": "Japan", "FI": "Finnland", "EU": "Europa"}

# (Muster, Land, Betreiber, Art, Beschreibung). Art: img Bild (optisch), sar Radar, elint Signale,
# warn Raketen-Frühwarnung, mil Militär mit unbekannter Aufgabe. Betreiber: mil Militär/Geheimdienst,
# dual staatlich (zivil und militärisch genutzt), com kommerziell.
SAT_RULES = [
    (r"^SBIRS", "US", "mil", "warn", "Frühwarnung vor Raketenstarts (SBIRS, Infrarot)"),
    (r"\(DSP \d+\)", "US", "mil", "warn", "Frühwarnung vor Raketenstarts (DSP, Infrarot)"),
    (r"^WFOV", "US", "mil", "warn", "Frühwarnung, Erprobungssatellit (Infrarot)"),
    (r"PRAETORIAN|^SDA[ _-]|^T1TL|^T1TR", "US", "mil", "mil", "US Space Development Agency: Datennetz und Raketenverfolgung"),
    (r"^USA \d+$", "US", "mil", "mil", "US-Militär, Aufgabe nicht öffentlich"),
    (r"^SAR-LUPE|^SARAH", "DE", "mil", "sar", "Bundeswehr, Radaraufklärung"),
    (r"^HELIOS|^CSO\b", "FR", "mil", "img", "Französisches Militär, Bildaufklärung"),
    (r"^CERES", "FR", "mil", "elint", "Französisches Militär, Signalaufklärung"),
    (r"^COSMO-SKYMED|^CSG-", "IT", "dual", "sar", "Italien, Radar (zivil und militärisch)"),
    (r"^PAZ$", "ES", "dual", "sar", "Spanien, Radar (zivil und militärisch)"),
    (r"^OFEQ|^OFEK", "IL", "mil", "img", "Israel, militärische Aufklärung"),
    (r"^EROS", "IL", "com", "img", "Israel, kommerzielle Bilder"),
    (r"^RISAT", "IN", "mil", "sar", "Indien, Radaraufklärung"),
    (r"^EMISAT", "IN", "mil", "elint", "Indien, Signalaufklärung"),
    (r"CARTOSAT", "IN", "dual", "img", "Indien, hochauflösende Bilder (zivil und militärisch)"),
    (r"^GOKTURK", "TR", "mil", "img", "Türkisches Militär, Bildaufklärung"),
    (r"^MALLIGYONG", "KP", "mil", "img", "Nordkorea, militärische Aufklärung"),
    (r"^NOOR\b", "IR", "mil", "img", "Iran (Revolutionsgarden), Aufklärung"),
    (r"^KHAYYAM|^PARS \d|^CHAMRAN", "IR", "dual", "img", "Iran, Erdbeobachtung"),
    (r"^FALCON EYE", "AE", "mil", "img", "VAE-Militär, Bildaufklärung"),
    (r"KOMPSAT-5|ARIRANG-5", "KR", "dual", "sar", "Südkorea, Radar"),
    (r"KOMPSAT-3|ARIRANG-3|^NEONSAT", "KR", "dual", "img", "Südkorea, Erdbeobachtung"),
    (r"^YAOGAN-\d+\s+0\d[A-C]\b", "CN", "mil", "elint", "Chinas Militär: Meeresüberwachung per Signalaufklärung (Dreiergruppe)"),
    (r"^YAOGAN", "CN", "mil", "img", "Chinas Militär: Bild- oder Radaraufklärung"),
    (r"^TJS-", "CN", "mil", "elint", "Chinas Militär, geostationär: vermutlich Signalaufklärung oder Frühwarnung"),
    (r"^SHIYAN", "CN", "mil", "mil", "China, Erprobungssatellit (teils militärisch)"),
    (r"^TIANHUI", "CN", "mil", "img", "Chinas Militär, Kartierung"),
    (r"^GAOFEN-3|^LUDI TANCE", "CN", "dual", "sar", "China, Radar (zivil und militärisch)"),
    (r"^GAOFEN", "CN", "dual", "img", "China, hochauflösende Bilder (zivil und militärisch)"),
    (r"^JILIN-1", "CN", "com", "img", "China, kommerzielle Bilder (Chang Guang)"),
    (r"^SUPERVIEW", "CN", "com", "img", "China, kommerzielle Bilder"),
    (r"^KONDOR|^OBZOR-R", "RU", "dual", "sar", "Russland, Radar (staatlich)"),
    (r"^RESURS|^KANOPUS", "RU", "dual", "img", "Russland, Erdbeobachtung (staatlich)"),
    (r"^WORLDVIEW|^LEGION|^GEOEYE", "US", "com", "img", "USA, kommerzielle Bilder (Maxar/Vantor)"),
    (r"^SKYSAT", "US", "com", "img", "USA, kommerzielle Bilder (Planet)"),
    (r"^CAPELLA", "US", "com", "sar", "USA, kommerzielles Radar (Capella)"),
    (r"^UMBRA", "US", "com", "sar", "USA, kommerzielles Radar (Umbra)"),
    (r"^HAWK-\d", "US", "com", "elint", "USA, kommerzielle Funkortung (HawkEye 360): findet Störsender und Schiffe ohne Signal"),
    (r"^PLEIADES|^SPOT [67]", "FR", "com", "img", "Frankreich, kommerzielle Bilder (Airbus)"),
    (r"^ICEYE", "FI", "com", "sar", "Finnland, kommerzielles Radar (ICEYE, liefert auch an die Ukraine)"),
    (r"^QPS-SAR|^STRIX", "JP", "com", "sar", "Japan, kommerzielles Radar"),
    (r"^SENTINEL-1", "EU", "dual", "sar", "EU Copernicus, Radar (frei verfügbar)"),
    (r"^SENTINEL-2", "EU", "dual", "img", "EU Copernicus, Bilder (frei verfügbar)"),
]
SAT_RULES = [(re.compile(p), *rest) for p, *rest in SAT_RULES]


def _orbit(l2):
    inc = float(l2[8:16])
    ecc = float("0." + l2[26:33].strip())
    mm = float(l2[52:63])  # Umläufe pro Tag
    a = (398600.4418 / (mm * 2 * math.pi / 86400) ** 2) ** (1 / 3)
    return inc, ecc, a - 6378.137


def _russian(name, l2):
    """Russische Militärsatelliten heißen alle „Kosmos“. Die Aufgabe lässt sich nur aus der Bahn schätzen."""
    inc, ecc, alt = _orbit(l2)
    if "(EKS" in name:
        return "warn", "Frühwarnung vor Raketenstarts (EKS „Kupol“)"
    if ecc > 0.5 and 60 < inc < 66:
        return "warn", "vermutlich Frühwarnung vor Raketenstarts (hochelliptische Bahn)"
    if alt > 30000:
        return "mil", "geostationär, vermutlich Kommunikation oder Signalaufklärung"
    if 1300 < alt < 1600 and 82 < inc < 83:
        return None  # Kommunikationssatelliten (Strela, Rodnik)
    if 900 < alt < 1100 and 82.5 < inc < 83.5:
        return None  # Parus (Navigation und Kommunikation)
    if 66.5 < inc < 67.5 and 400 < alt < 1000:
        return "elint", "vermutlich Signalaufklärung (Lotos-S oder Pion-NKS)"
    if 95 < inc < 99.5 and alt < 800:
        return "img", "vermutlich Bildaufklärung (z. B. Persona, Bars-M)"
    return "mil", "Militär, Aufgabe nicht öffentlich"


def classify_sat(name, l2):
    if SAT_SKIP.search(name):
        return None
    if name.startswith("COSMOS ") or name.startswith("KOSMOS "):
        r = _russian(name, l2)
        return r and (r[0], "mil", "RU", r[1])
    for pat, cc, owner, kind, label in SAT_RULES:
        if pat.search(name):
            return kind, owner, cc, label
    return None


# Ersatzweg, falls CelesTrak die Gesamtliste verweigert (sie sperrt eine zweite Abfrage derselben Liste
# innerhalb von 2 Stunden, und GitHub teilt sich Adressen mit anderen Nutzern): einzelne Namenssuchen
SAT_NAMES = ["YAOGAN", "TJS", "SHIYAN", "TIANHUI", "GAOFEN", "LUDI TANCE", "JILIN-1", "SUPERVIEW", "COSMOS", "KONDOR",
             "OBZOR", "RESURS", "KANOPUS", "SBIRS", "DSP", "WFOV", "PRAETORIAN", "USA", "SAR-LUPE", "SARAH", "HELIOS",
             "CSO", "CERES", "COSMO-SKYMED", "CSG", "PAZ", "OFEQ", "EROS", "RISAT", "EMISAT", "CARTOSAT", "GOKTURK",
             "MALLIGYONG", "NOOR", "KHAYYAM", "FALCON EYE", "KOMPSAT", "NEONSAT", "WORLDVIEW", "LEGION", "GEOEYE",
             "SKYSAT", "CAPELLA", "UMBRA", "HAWK", "PLEIADES", "SPOT", "ICEYE", "QPS-SAR", "STRIX", "SENTINEL"]
GP = "https://celestrak.org/NORAD/elements/gp.php"


def _tle_lines(raw):
    return [l.rstrip() for l in raw.decode("ascii", "replace").splitlines() if l.strip()]


def _fallback_lines():
    lines, ok = [], 0
    for name in SAT_NAMES:
        try:
            lines += _tle_lines(fetch(f"{GP}?NAME={urllib.parse.quote(name)}&FORMAT=tle", 40, ua=UA))
            ok += 1
        except Exception:
            pass
        time.sleep(0.3)
    print(f"Satelliten über Namenssuche: {ok} von {len(SAT_NAMES)} Abfragen erfolgreich")
    return lines


def satellites_data(previous=None):
    """Bahndaten aller aktiven Satelliten von CelesTrak, davon nur Aufklärung und Frühwarnung."""
    fallback = False
    try:
        lines = _tle_lines(fetch(f"{GP}?GROUP=active&FORMAT=tle", 90, retries=1, ua=UA))
    except Exception:
        fetched = (previous or {}).get("fetched")
        if fetched and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(fetched)).total_seconds() < 86400:
            raise  # der letzte Stand ist noch gut genug und wird weiter gezeigt
        lines, fallback = _fallback_lines(), True
    sats, newest, seen = [], None, set()
    for i in range(0, len(lines) - 2):
        name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if not (l1.startswith("1 ") and l2.startswith("2 ")) or name.startswith(("1 ", "2 ")):
            continue
        if " DEB" in name or "R/B" in name or l1[2:7] in seen:
            continue
        # Die Namenssuche liefert auch ausgediente Satelliten: alte russische Kosmos-Nummern weglassen
        if fallback and re.match(r"COSMOS (\d+)", name) and int(re.match(r"COSMOS (\d+)", name).group(1)) < 2480:
            continue
        try:
            c = classify_sat(name, l2)
        except ValueError:
            continue
        if not c:
            continue
        kind, owner, cc, label = c
        # Epoche der Bahndaten: Jahr (2 Stellen) und Tag des Jahres
        yy, doy = int(l1[18:20]), float(l1[20:32])
        epoch = dt.datetime(2000 + yy if yy < 57 else 1900 + yy, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=doy - 1)
        if (dt.datetime.now(dt.timezone.utc) - epoch).days > 30:
            continue  # veraltete Bahn, Position wäre falsch
        newest = max(newest or epoch, epoch)
        seen.add(l1[2:7])
        sats.append({"n": name, "a": l1, "b": l2, "k": kind, "o": owner, "c": cc, "r": label})
    if len(sats) < 50:
        raise RuntimeError(f"nur {len(sats)} Satelliten erkannt")
    counts = collections.Counter(s["c"] for s in sats)
    return {"sats": sats, "lands": LAND, "counts": dict(counts.most_common()),
            "epoch": newest.isoformat() if newest else None, "fallback": fallback}


# ---------------------------------------------------------------- GPS-Störungen

def _gunzip(b):
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


# Bezugsorte, damit mehrere Störgebiete im selben Land unterscheidbar sind ("Russland, bei Moskau")
CITIES = [("Moskau", 55.75, 37.62), ("St. Petersburg", 59.94, 30.31), ("Kaliningrad", 54.71, 20.51), ("Murmansk", 68.97, 33.08),
          ("Krasnodar", 45.04, 38.98), ("Rostow am Don", 47.24, 39.71), ("Wolgograd", 48.71, 44.51), ("Kasan", 55.79, 49.12),
          ("Samara", 53.2, 50.15), ("Jekaterinburg", 56.84, 60.6), ("Perm", 58.01, 56.25), ("Nowosibirsk", 55.03, 82.92),
          ("Omsk", 54.99, 73.37), ("Irkutsk", 52.29, 104.28), ("Wladiwostok", 43.12, 131.89), ("Belgorod", 50.6, 36.59),
          ("Kursk", 51.73, 36.19), ("Brjansk", 53.24, 34.36), ("Sewastopol", 44.62, 33.52), ("Kiew", 50.45, 30.52),
          ("Charkiw", 49.99, 36.23), ("Odessa", 46.48, 30.72), ("Lwiw", 49.84, 24.03), ("Dnipro", 48.46, 35.05),
          ("Minsk", 53.9, 27.56), ("Warschau", 52.23, 21.01), ("Danzig", 54.35, 18.65), ("Vilnius", 54.69, 25.28),
          ("Riga", 56.95, 24.11), ("Tallinn", 59.44, 24.75), ("Helsinki", 60.17, 24.94), ("Stockholm", 59.33, 18.07),
          ("Gotland", 57.5, 18.5), ("Kopenhagen", 55.68, 12.57), ("Berlin", 52.52, 13.4), ("Oslo", 59.91, 10.75),
          ("Bukarest", 44.43, 26.1), ("Istanbul", 41.01, 28.98), ("Ankara", 39.93, 32.86), ("Izmir", 38.42, 27.14),
          ("Antalya", 36.9, 30.7), ("Adana", 37.0, 35.32), ("Diyarbakır", 37.91, 40.24), ("Tiflis", 41.72, 44.78),
          ("Jerewan", 40.18, 44.51), ("Baku", 40.41, 49.87), ("Teheran", 35.69, 51.39), ("Täbris", 38.08, 46.29),
          ("Bandar Abbas", 27.18, 56.27), ("Isfahan", 32.65, 51.67), ("Bagdad", 33.31, 44.36), ("Basra", 30.51, 47.81),
          ("Erbil", 36.19, 44.01), ("Damaskus", 33.51, 36.28), ("Aleppo", 36.2, 37.13), ("Beirut", 33.89, 35.5),
          ("Tel Aviv", 32.09, 34.78), ("Gaza", 31.5, 34.47), ("Amman", 31.95, 35.93), ("Kairo", 30.04, 31.24),
          ("Zypern", 35.1, 33.4), ("Riad", 24.71, 46.68), ("Dschidda", 21.49, 39.19), ("Sanaa", 15.37, 44.19),
          ("Aden", 12.79, 45.02), ("Dubai", 25.2, 55.27), ("Maskat", 23.59, 58.41), ("Doha", 25.29, 51.53),
          ("Kuwait", 29.38, 47.99), ("Islamabad", 33.68, 73.05), ("Lahore", 31.55, 74.34), ("Karatschi", 24.86, 67.0),
          ("Neu-Delhi", 28.61, 77.21), ("Amritsar", 31.63, 74.87), ("Kaschmir", 34.08, 74.8), ("Kabul", 34.56, 69.21),
          ("Taschkent", 41.3, 69.24), ("Peking", 39.9, 116.4), ("Shanghai", 31.23, 121.47), ("Taipeh", 25.03, 121.57),
          ("Pjöngjang", 39.04, 125.76), ("Seoul", 37.57, 126.98), ("Tokio", 35.68, 139.69), ("Manila", 14.6, 120.98),
          ("Rangun", 16.87, 96.2), ("Khartum", 15.5, 32.56), ("Tripolis", 32.89, 13.19), ("Bengasi", 32.12, 20.09),
          ("Tunis", 36.81, 10.18), ("Algier", 36.75, 3.06), ("Caracas", 10.48, -66.9), ("Washington", 38.9, -77.04)]


def nearest_city(lat, lon, max_km=650):
    best, bd = None, max_km
    for name, la, lo in CITIES:
        d = 6371 * math.acos(min(1, math.sin(math.radians(lat)) * math.sin(math.radians(la))
                                 + math.cos(math.radians(lat)) * math.cos(math.radians(la)) * math.cos(math.radians(lon - lo))))
        if d < bd:
            best, bd = name, d
    return best


def gpsjam_data(locate):
    """Gebiete, in denen viele Flugzeuge eine ungenaue GPS-Position melden (Störsender oder Täuschung).
    Zellen (H3, etwa 40 km breit) mit mehr als 2 % (gelb) oder 10 % (rot) betroffenen Flugzeugen."""
    import h3  # nur hier gebraucht; fehlt das Paket, fällt nur diese Ebene aus

    man = _gunzip(fetch("https://gpsjam.org/data/manifest.csv", 30, retries=2, ua=UA)).decode("utf-8", "replace")
    rows = [r.split(",") for r in man.strip().splitlines()[1:] if r.strip()]
    rows = [r for r in rows if len(r) > 1 and r[1].strip().lower() != "true"] or rows  # "suspect"-Tage überspringen
    day = rows[-1][0].strip()
    raw = _gunzip(fetch(f"https://gpsjam.org/data/{day}-h3_4.csv", 90, retries=2, ua=UA)).decode("utf-8", "replace")
    cells = []
    for line in raw.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            good, bad = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        total = good + bad
        if total < 3 or bad * 100 / total <= 2:
            continue
        lat, lon = h3.cell_to_latlng(parts[0])
        cells.append([round(lat, 2), round(lon, 2), round(bad * 100 / total), total])
    # Zusammenfassen zu Gebieten (Raster von 3 Grad), nur Gebiete mit mehreren roten Zellen
    grid = collections.defaultdict(list)
    for c in cells:
        if c[2] > 10:
            grid[(math.floor(c[0] / 3), math.floor(c[1] / 3))].append(c)
    areas = []
    for group in grid.values():
        if len(group) < 3:
            continue
        lat = sum(c[0] for c in group) / len(group)
        lon = sum(c[1] for c in group) / len(group)
        country, sea = locate(lat, lon)
        areas.append({"lat": round(lat, 2), "lon": round(lon, 2), "cells": len(group), "country": country, "sea": sea,
                      "planes": sum(c[3] for c in group), "pct": round(sum(c[2] for c in group) / len(group))})
    # Benachbarte Rasterfelder im selben Land zu einem Eintrag zusammenlegen
    merged = []
    for a in sorted(areas, key=lambda a: -a["cells"]):
        twin = next((m for m in merged if m["country"] == a["country"] and m["sea"] == a["sea"]
                     and abs(m["lat"] - a["lat"]) < 7 and abs(m["lon"] - a["lon"]) < 9), None)
        if twin:
            twin["cells"] += a["cells"]
            twin["planes"] += a["planes"]
        else:
            merged.append(dict(a))
    merged.sort(key=lambda a: -a["cells"])
    for a in merged:
        a["near"] = nearest_city(a["lat"], a["lon"])
    return {"day": day, "cells": cells, "areas": merged[:25],
            "red": sum(1 for c in cells if c[2] > 10), "yellow": sum(1 for c in cells if c[2] <= 10)}


# ---------------------------------------------------------------- Internet-Ausfälle

SOURCE_DE = {"bgp": "Netz-Routen (BGP)", "ping-slash24": "Erreichbarkeit (Ping)", "gtr": "Google-Verkehr",
             "merit-nt": "Hintergrundverkehr", "gtr-norm": "Google-Verkehr"}


def outages_data(find):
    """Ausfälle des Internets in ganzen Ländern in den letzten 48 Stunden (IODA). Kurze oder schwache Ausschläge
    und dauerhafte Messlücken beim Google-Verkehr fallen weg, sie sind oft Fehlalarme."""
    until = int(time.time())
    url = (f"https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events?from={until - 2 * 86400}&until={until}"
           f"&entityType=country&limit=500&format=codf")
    import json
    data = json.loads(fetch(url, 60, retries=2, ua=UA)).get("data") or []
    by = {}
    for e in data:
        src, score, dur = e.get("datasource") or "", float(e.get("score") or 0), int(e.get("duration") or 0)
        if dur < 1800:
            continue
        code = (e.get("location") or "").split("/")[-1]
        if src.startswith("gtr"):
            # Google-Verkehr schwankt stark; in China ist Google gesperrt, dort sind die Werte bedeutungslos
            if score < 5000 or dur > 86400 or code == "CN":
                continue
        elif score < 100:
            continue
        name_en = e.get("location_name") or code
        world_name, cid, name_de = find(name_en)
        if not cid:
            continue  # kleine Inseln und Gebiete, die auf der Karte fehlen
        start = int(e.get("start") or 0)
        cur = by.setdefault(code, {"code": code, "name": name_de or name_en, "id": cid, "score": 0, "start": start,
                                    "end": start + dur, "sources": []})
        cur["score"] = max(cur["score"], round(score))
        cur["start"] = min(cur["start"], start)
        cur["end"] = max(cur["end"], start + dur)
        label = SOURCE_DE.get(src, src)
        if label not in cur["sources"]:
            cur["sources"].append(label)
    items = sorted(by.values(), key=lambda x: -x["score"])
    for x in items:
        x["ongoing"] = x["end"] >= until - 1800
    return {"items": items[:30], "until": until}

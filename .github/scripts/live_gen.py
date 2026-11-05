"""Gibt den Zeitstempel des Stands aus, den die echte Seite gerade ausliefert (leer, wenn nicht abrufbar)."""
import json, sys, time, urllib.request
url = sys.argv[1].rstrip("/") + f"/data.json?t={time.time_ns()}"
try:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "mego-news-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.loads(r.read())["generated"])
except Exception as e:
    print(f"Seite nicht abrufbar: {type(e).__name__}", file=sys.stderr)

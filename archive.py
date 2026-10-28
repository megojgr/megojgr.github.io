"""Tagesarchiv: pro Tag eine kleine JSON-Datei in archive/, daraus entsteht der Reiter „Verlauf“."""
import json
from pathlib import Path

DIR = Path(__file__).parent / "archive"


def snapshot(data, today):
    pm = sorted(data["prediction"], key=lambda e: e["vol24h"], reverse=True)[:6]
    return {
        "date": today,
        "generated": data["generated"],
        "quotes": [{"name": q["name"], "group": q["group"], "price": q["price"], "pct": q["pct"], "alert": q["alert"]}
                   for q in data["quotes"] if q["price"] is not None and q["group"] == "index"],
        "heute": [{"title": s["title"], "url": s["url"], "topic": s["topic"], "n": len(s["sources"]),
                   "alert": s.get("alert", False)} for s in data["heute"][:10]],
        "pm": [{"title": e["title"], "url": e["url"], "source": e["source"], "lead": e["rows"][0]["label"],
                "p": e["rows"][0]["p"], "d1": e["rows"][0]["d1"]} for e in pm],
    }


def write(data, today):
    DIR.mkdir(exist_ok=True)
    (DIR / f"{today}.json").write_text(json.dumps(snapshot(data, today), ensure_ascii=False, indent=1), encoding="utf-8")


def load(days):
    files = sorted(DIR.glob("*.json"), reverse=True)[:days] if DIR.exists() else []
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue  # eine kaputte Tagesdatei darf die Seite nicht stoppen
    return out

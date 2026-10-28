"""Depot: Positionen, Kurse und passende Meldungen. Das Ergebnis wird mit einem Passwort verschlüsselt.

Die Positionen stehen nie im Repo: lokal in depot.json (gitignored), im Workflow aus dem Secret DEPOT_JSON.
"""
import base64
import bisect
import json
import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from markets import fetch_quote
from textutil import compile_keywords

ROOT = Path(__file__).parent
ITERATIONS = 300_000


def load():
    """Liste der Positionen oder None, wenn kein Depot eingerichtet ist."""
    text = os.environ.get("DEPOT_JSON")
    if not text and (ROOT / "depot.json").exists():
        text = (ROOT / "depot.json").read_text(encoding="utf-8")
    if not text:
        return None
    try:
        positions = json.loads(text)["positions"]
        assert positions and all(p.get("symbol") and p.get("keywords") for p in positions)
        return positions
    except Exception:
        print("WARNUNG: depot.json ist unlesbar, Depot wird übersprungen")
        return None


def feeds(positions):
    """Google-News-Suchen pro Position, nur für das Depot (kommen nie in die öffentliche Liste)."""
    out = []
    for p in positions:
        query = "+OR+".join(urllib.parse.quote_plus('"' + k + '"') for k in p["keywords"][:3]) + "+when:2d"
        for lang, params in (("de", "hl=de&gl=DE&ceid=DE:de"), ("en", "hl=en-US&gl=US&ceid=US:en")):
            out.append({"name": f"{p['short']} ({lang})", "url": f"https://news.google.com/rss/search?q={query}&{params}",
                        "hint": "markets", "lang": lang, "google": True, "private": True})
    return out


def matcher(positions):
    """match(text) -> {Positionsnummer: "main" | "context"}"""
    compiled = [(compile_keywords(p["keywords"]), compile_keywords(p.get("context", []))) for p in positions]

    def match(text):
        out = {}
        for i, (main, ctx) in enumerate(compiled):
            if any(pt.search(text) for pt in main):
                out[i] = "main"
            elif any(pt.search(text) for pt in ctx):
                out[i] = "context"
        return out

    return match


def to_eur(q, alerts, is_etf):
    """Rechnet Kurs und Verlauf in Euro um (Tageskurs der jeweiligen Währung), z. B. HKD, USD, GBp.

    Der alte Kurs bleibt unter "local" erhalten. Klappt der Wechselkurs nicht, bleibt alles in der Börsenwährung."""
    cur = q.get("currency") or ""
    if cur in ("", "EUR") or not q.get("c") or q.get("price") is None:
        return q
    unit, code = (100.0, "GBP") if cur == "GBp" else (1.0, cur)
    fx = fetch_quote({"name": "fx", "symbol": f"EUR{code}=X", "group": "fx"}, alerts)
    if not fx.get("c") or not fx.get("price"):
        q["fx_error"] = f"Wechselkurs EUR/{code} nicht verfügbar"
        return q
    days = fx["t"]

    def rate_at(day):  # letzter bekannter Kurs bis zu diesem Tag (Börsen und Devisenmarkt haben verschiedene Handelstage)
        i = bisect.bisect_right(days, day) - 1
        return fx["c"][max(i, 0)]

    series = [round(c / unit / rate_at(t), 4) for t, c in zip(q["t"], q["c"])]
    price = q["price"] / unit / fx["price"]
    series[-1] = round(price, 4)
    q["local"] = {"price": q["price"], "currency": cur}
    q.update(price=price, currency="EUR", c=series,
             pct=(price / series[-2] - 1) * 100 if len(series) >= 2 else None,
             week=(price / series[-6] - 1) * 100 if len(series) >= 6 else None,
             month=(price / series[-22] - 1) * 100 if len(series) >= 22 else None,
             hi52=max(series), lo52=min(series))
    limit = alerts["index_day_pct"] if is_etf else alerts["stock_day_pct"]
    q["alert"] = "day" if q["pct"] is not None and abs(q["pct"]) >= limit else \
        "week" if q["week"] is not None and q["week"] <= -alerts["week_pct"] else None
    return q


def build(positions, private_news, alerts):
    """private_news: [(story, {Positionsnummer: Art})]. Liefert das Depot-Objekt, das verschlüsselt wird."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        quotes = list(ex.map(lambda p: to_eur(fetch_quote({"name": p["short"], "symbol": p["symbol"], "group": "depot"}, alerts),
                                              alerts, p.get("type") == "ETF"), positions))
    out = []
    for i, (p, q) in enumerate(zip(positions, quotes)):
        mine = {"main": [], "context": []}
        for story, dm in private_news:
            if i in dm:
                mine[dm[i]].append(story)
        for kind in mine:
            mine[kind].sort(key=lambda s: s["score"], reverse=True)
        out.append({**{k: p.get(k) for k in ("name", "short", "type", "wkn", "isin", "symbol")},
                    **{k: q.get(k) for k in ("price", "pct", "week", "month", "t", "c", "currency", "hi52", "lo52", "alert", "error", "local", "fx_error")},
                    "news": mine["main"][:8], "context": mine["context"][:6]})
    return {"positions": out}


def encrypt(obj, password):
    """AES-256-GCM mit PBKDF2-Schlüssel, passend zu crypto.subtle im Browser."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())
    blob = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(blob)}

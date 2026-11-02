"""Große ETF-Liste für die Suche im eigenen Depot: alle an Xetra handelbaren ETFs und ETCs.

Quelle der Liste ist die frei abrufbare Instrumentenliste der Deutschen Börse (ISIN, WKN, Xetra-Kürzel).
Kurse und Jahresverläufe kommen gesammelt von Yahoo (20 Werte je Abfrage), volle Namen einmalig je Wert
von Yahoo (Zwischenspeicher im Repo). Jeder ETF bekommt ein Thema (z. B. "world", "semis"), über das die
Seite Meldungen zum Thema und zu den größten Positionen (etwa Apple beim MSCI World) zeigt.

Ergebnis: docs/etfs.json (Suchliste) und docs/etf/<Kürzel>.json (Verlauf, erst beim Antippen geladen).
"""
import csv
import io
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from net import BROWSER_UA, fetch

ROOT = Path(__file__).parent
LIST_CACHE = ROOT / "cache" / "xetra_etfs.json"
NAME_CACHE = ROOT / "cache" / "etf_names.json"
XETRA_PAGE = "https://www.xetra.com/xetra-de/instrumente/alle-handelbaren-instrumente"


def xetra_list():
    """Aktive ETFs und ETCs an Xetra: [{isin, wkn, sym, xname, kind}]. Bei Ausfall die letzte gespeicherte Liste."""
    try:
        page = fetch(XETRA_PAGE, 30, ua=BROWSER_UA).decode("utf-8", "replace")
        href = re.search(r'href="([^"]*allTradableInstruments\.csv)"', page).group(1)
        url = href if href.startswith("http") else "https://www.xetra.com" + href
        text = fetch(url, 90, ua=BROWSER_UA).decode("utf-8", "replace").splitlines()
        rows = list(csv.reader(text[2:], delimiter=";"))
        head = rows[0]
        out = []
        for r in rows[1:]:
            d = dict(zip(head, r))
            if d.get("Instrument Type") in ("ETF", "ETC") and d.get("Instrument Status") == "Active" and d.get("Mnemonic"):
                out.append({"isin": d["ISIN"], "wkn": re.sub(r"^000", "", d.get("WKN", "")), "sym": d["Mnemonic"] + ".DE",
                            "xname": d["Instrument"].strip(), "kind": d["Instrument Type"],
                            "bond": "RENTEN" in d.get("Product Assignment Group Description", "")})
        if len(out) < 1000:
            raise RuntimeError(f"nur {len(out)} Einträge")
        text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
        if not LIST_CACHE.exists() or LIST_CACHE.read_text(encoding="utf-8") != text:
            LIST_CACHE.parent.mkdir(exist_ok=True)
            LIST_CACHE.write_text(text, encoding="utf-8")
        return out, None
    except Exception as e:
        try:
            return json.loads(LIST_CACHE.read_text(encoding="utf-8")), f"Xetra-Liste: {type(e).__name__}, alter Stand"
        except Exception:
            return [], f"Xetra-Liste: {type(e).__name__}"


def spark(symbols, rng="1y"):
    """Tagesschlusskurse vieler Werte, 20 je Abfrage: {Kürzel: (Tage seit 1970, Kurse)}."""
    def batch(chunk):
        url = ("https://query1.finance.yahoo.com/v8/finance/spark?symbols=" + ",".join(urllib.parse.quote(s) for s in chunk)
               + f"&range={rng}&interval=1d")
        try:
            data = json.loads(fetch(url, 30, ua=BROWSER_UA))
        except Exception:
            return {}
        out = {}
        for s in chunk:
            d = data.get(s) or {}
            pairs = [(t // 86400, c) for t, c in zip(d.get("timestamp") or [], d.get("close") or []) if c]
            if len(pairs) >= 2:
                out[s] = ([t for t, _ in pairs], [c for _, c in pairs])
        return out
    result = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for part in ex.map(batch, [symbols[i:i + 20] for i in range(0, len(symbols), 20)]):
            result.update(part)
    return result


def long_names(symbols, known, limit):
    """Volle Namen von Yahoo für noch unbekannte Kürzel, höchstens `limit` je Lauf."""
    todo = [s for s in symbols if s not in known][:limit]

    def one(s):
        try:
            meta = json.loads(fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?range=5d&interval=1d", 20,
                                    ua=BROWSER_UA))["chart"]["result"][0]["meta"]
            return s, meta.get("longName") or meta.get("shortName") or ""
        except Exception:
            return s, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for s, name in ex.map(one, todo):
            if name is not None:
                known[s] = name
    return len(todo)


def theme_of(name, themes, bond=False):
    """Thema eines ETFs anhand von Stichwörtern im Namen; die erste passende Regel gewinnt."""
    if bond:
        return "bonds"
    up = " " + re.sub(r"[()]", " ", name.upper()) + " "
    for t in themes:
        if t["match"] and any(w in up for w in t["match"]):
            return t["key"]
    return "markets"


def tidy(name):
    """Yahoo-Namen etwas aufräumen ("UCITS ETF" bleibt, doppelte Leerzeichen und Klammerreste nicht)."""
    name = re.sub(r"^[^-]*\b(PLC|ICAV|SICAV|Fund|Funds|Trust)\b[^-]*\s-\s+", "", name or "")  # "Vanguard Funds PLC - Vanguard ..." -> "Vanguard ..."
    return re.sub(r"\s+", " ", name).strip(" -")


def build(cfg, out_dir, names_per_run=600):
    """Schreibt etfs.json und etf/<Kürzel>.json in out_dir. Liefert eine Zusammenfassung für die Ausgabe."""
    themes = cfg.get("etf_themes", [])
    items, note = xetra_list()
    if not items:
        return {"count": 0, "note": note}
    series = spark([i["sym"] for i in items])
    try:
        names = json.loads(NAME_CACHE.read_text(encoding="utf-8"))
    except Exception:
        names = {}
    before = len(names)
    asked = long_names([i["sym"] for i in items if i["sym"] in series], names, names_per_run)
    if len(names) != before:
        NAME_CACHE.parent.mkdir(exist_ok=True)
        NAME_CACHE.write_text(json.dumps(names, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")

    sdir = Path(out_dir) / "etf"
    sdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in items:
        sym = i["sym"]
        if sym not in series:
            continue  # ohne Kurse nicht anbieten, sonst steht der Wert leer im Depot
        t, c = series[sym]
        name = tidy(names.get(sym)) or i["xname"]
        c = [round(x, 2 if x >= 10 else 4) for x in c]
        price = c[-1]
        back = lambda n: round((price / c[-1 - n] - 1) * 100, 2) if len(c) > n and c[-1 - n] else None
        rows.append([sym, name, i["isin"], i["wkn"], i["kind"], theme_of(name + " " + i["xname"], themes, i["bond"]),
                     price, back(1), back(5), back(21), t[-1], i["xname"]])
        (sdir / (sym + ".json")).write_text(json.dumps({"t": t, "c": c, "hi52": max(c), "lo52": min(c)}, separators=(",", ":")), encoding="utf-8")
    index = {"cols": ["id", "name", "isin", "wkn", "kind", "theme", "price", "pct", "week", "month", "day", "xname"], "rows": rows}
    (Path(out_dir) / "etfs.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"count": len(rows), "listed": len(items), "named": len(names), "asked": asked, "note": note}

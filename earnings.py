"""Quartalszahlen großer Unternehmen: Termine und Ergebnisse (Nasdaq), Kursreaktion (Yahoo), Schlagzeilen (Google News).

Alles frei und ohne Schlüssel. Verlinkt wird auf die Investor-Relations-Seite des Unternehmens als Originalquelle
und auf Berichte und Einordnungen als Analyse. Bei einem Ausfall der Quelle bleibt der letzte gute Stand sichtbar.
"""
import datetime as dt
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from briefings import _items as rss_items
from net import BROWSER_UA, fetch

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "earnings.json"

NASDAQ = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
TIMES = {"time-pre-market": "pre", "time-after-hours": "after"}
SUFFIX = re.compile(r"[,.]?\s+(Inc|Corp|Corporation|Incorporated|Company|Co|Ltd|Limited|plc|PLC|N\.V|NV|S\.A|SA|AG|SE|Holdings?|Group|"
                    r"Class [A-C]|Common Stock|Ordinary Shares?|ADS|American Depositary Shares?)\b\.?", re.I)
WORDS = re.compile(r"quartal|zahlen|earnings|results|umsatz|gewinn|revenue|profit|eps|q[1-4]\b|ausblick|guidance|forecast|prognose|bilanz", re.I)
PREFERRED = ("reuters", "cnbc", "bloomberg", "handelsblatt", "faz", "börse", "finanzen", "investopedia", "seeking alpha", "motley",
             "marketwatch", "barron", "yahoo", "manager magazin", "tagesschau", "aktion", "wirtschaftswoche", "tagesspiegel", "zeit", "spiegel", "wall street journal", "financial times")


def clean_name(name):
    out = SUFFIX.sub("", name or "").strip(" ,.")
    return out or name


def parse_cap(s):
    try:
        return int(re.sub(r"[^\d]", "", s or "") or 0)
    except ValueError:
        return 0


def number(s):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(s)))
    except ValueError:
        return None


def calendar_day(day):
    raw = fetch(f"https://api.nasdaq.com/api/calendar/earnings?date={day}", 25, headers=NASDAQ, ua=BROWSER_UA)
    return day, (json.loads(raw).get("data") or {}).get("rows") or []


def surprise(symbol):
    """Gemeldete Quartale mit Ergebnis je Aktie, Erwartung und Abweichung (neuestes zuerst)."""
    raw = fetch(f"https://api.nasdaq.com/api/company/{urllib.parse.quote(symbol)}/earnings-surprise", 25, headers=NASDAQ, ua=BROWSER_UA)
    table = (json.loads(raw).get("data") or {}).get("earningsSurpriseTable") or {}
    out = []
    for r in table.get("rows") or []:
        try:
            m, d, y = (int(x) for x in r["dateReported"].split("/"))
            out.append({"date": dt.date(y, m, d), "eps": r.get("eps"), "est": number(r.get("consensusForecast")),
                        "surprise": number(r.get("percentageSurprise")), "quarter": r.get("fiscalQtrEnd")})
        except (ValueError, KeyError, AttributeError):
            continue
    return out


EPOCH = dt.date(1970, 1, 1)


def bars(symbol):
    """Tagesschlusskurse der letzten drei Monate als Liste (Datum, Kurs)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol.replace('.', '-'))}?interval=1d&range=3mo"
    res = json.loads(fetch(url, 20))["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    return [(dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date(), c)
            for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c]


def series_of(rows):
    """Kursverlauf für die Seite: Tage seit 1970 (wie bei den Kursen) und Schlusskurse."""
    return {"t": [(d - EPOCH).days for d, _ in rows], "c": [round(c, 2) for _, c in rows]}


MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _nasdaq(path):
    return (json.loads(fetch("https://api.nasdaq.com/api/" + path, 25, headers=NASDAQ, ua=BROWSER_UA)).get("data") or {})


def parse_revenue(table):
    """Quartalsumsätze aus der Nasdaq-Tabelle: [(Quartalsende JJJJ-MM-TT, Umsatz in Mio. $)]. Das Datum steht in der EPS-Zeile."""
    out, rows = {}, (table or {}).get("rows") or []
    for k, r in enumerate(rows[:-1]):
        if r.get("value1") != "Revenue" or rows[k + 1].get("value1") != "EPS":
            continue
        for col in ("value2", "value3", "value4"):
            m = re.search(r"\((\d{2})/(\d{2})/(\d{4})\)", rows[k + 1].get(col) or "")
            v = re.search(r"([\d,]+(?:\.\d+)?)\(m\)", r.get(col) or "")
            if m and v:
                out[f"{m.group(3)}-{m.group(1)}-{m.group(2)}"] = float(v.group(1).replace(",", ""))
    return sorted(out.items())


def fundamentals(symbol):
    """Umsatz der letzten Quartale, Gewinnprognosen der Analysten und Kursziel; einzelne Teile dürfen fehlen."""
    f = {"fetched": _now(), "rev": [], "fq": [], "fy": [], "target": None}
    try:
        f["rev"] = parse_revenue(_nasdaq(f"company/{urllib.parse.quote(symbol)}/revenue?limit=1").get("revenueTable"))
    except Exception:
        pass
    try:
        d = _nasdaq(f"analyst/{urllib.parse.quote(symbol)}/earnings-forecast")
        keep = lambda r: {"end": r.get("fiscalEnd"), "est": number(r.get("consensusEPSForecast")), "hi": number(r.get("highEPSForecast")),
                          "lo": number(r.get("lowEPSForecast")), "n": number(r.get("noOfEstimates")), "up": number(r.get("up")), "down": number(r.get("down"))}
        f["fq"] = [keep(r) for r in ((d.get("quarterlyForecast") or {}).get("rows") or [])[:4]]
        f["fy"] = [keep(r) for r in ((d.get("yearlyForecast") or {}).get("rows") or [])[:2]]
    except Exception:
        pass
    try:
        c = _nasdaq(f"analyst/{urllib.parse.quote(symbol)}/targetprice").get("consensusOverview") or {}
        if c.get("priceTarget"):
            f["target"] = {k: c.get(k) for k in ("priceTarget", "lowPriceTarget", "highPriceTarget", "buy", "hold", "sell")}
    except Exception:
        pass
    return f


def quarter_ym(text):
    m = re.match(r"([A-Za-z]{3})\w*[ /]+(\d{4})", text or "")
    return (int(m.group(2)), MONTHS.get(m.group(1).title())) if m else (None, None)


def attach_fund(i, f):
    """Umsatz und Wachstum zum Vorjahresquartal, Prognosen und Kursziel an einen Termin hängen."""
    if not f:
        return
    rev = f.get("rev") or []
    find = lambda y, m: next((v for e, v in rev if int(e[:4]) == y and int(e[5:7]) == m), None)
    growth = lambda a, b: round((a / b - 1) * 100, 1) if a is not None and b else None
    y, m = quarter_ym((i.get("result") or {}).get("quarter") or i.get("quarter"))
    hist = [{"end": e, "rev": v, "yoy": growth(v, find(int(e[:4]) - 1, int(e[5:7])))} for e, v in rev][-8:]
    cur = find(y, m) if y else None
    i["revenue"] = {"value": cur, "prev": find(y - 1, m) if y else None, "yoy": growth(cur, find(y - 1, m)) if y else None,
                    "last_yoy": next((h["yoy"] for h in reversed(hist) if h["yoy"] is not None), None), "hist": hist} if rev else None
    i["forecast"] = {"q": f.get("fq") or [], "y": f.get("fy") or []} if f.get("fq") or f.get("fy") else None
    t = f.get("target")
    if t:
        last = (i.get("series") or {}).get("c") or [None]
        i["target"] = {**t, "last": last[-1], "upside": growth(t["priceTarget"], last[-1]) if last[-1] else None}


def reaction(rows, day, when):
    """Kursbewegung rund um die Zahlen: vor Börsenöffnung Berichtstag gegen Vortag, nach Börsenschluss Folgetag gegen Berichtstag."""
    if when not in ("pre", "after"):
        return None
    if when == "pre":
        before = [c for d, c in rows if d < day]
        after = [c for d, c in rows if d == day]
        label = "Kurs am Berichtstag"
    else:
        before = [c for d, c in rows if d == day]
        after = [c for d, c in rows if d > day]
        label = "Kurs am Tag danach"
    if not before or not after:
        return None
    return {"pct": round((after[0] / before[-1] - 1) * 100, 2), "label": label}


def change(i):
    """Veränderung des Gewinns je Aktie: bevorzugt zum Vorjahresquartal, sonst zum Vorquartal."""
    r = i["result"]
    eps, prev, label = r["eps"], None, None
    if i.get("prev_eps") is not None:
        prev, label = i["prev_eps"], "Vorjahresquartal"
    else:
        hist = [h for h in r.get("hist") or [] if h["quarter"] != r.get("quarter") and h["eps"] is not None]
        m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", r.get("quarter") or "")
        if m:
            year_ago = f"{m.group(1)} {int(m.group(2)) - 1}"
            hit = next((h for h in hist if h["quarter"] == year_ago), None)
            if hit:
                prev, label = hit["eps"], "Vorjahresquartal"
        if prev is None and hist:
            prev, label = hist[0]["eps"], "Vorquartal"
    if eps is None or prev is None:
        return None
    pct = None if prev == 0 else round((eps - prev) / abs(prev) * 100, 1)
    return {"vs": label, "prev": prev, "pct": pct}


def headlines(query, hours):
    """Aktuelle Berichte zu den Zahlen, deutsche und englische Quellen gemischt, mit einem Favoriten für den Analyse-Link.
    query: Suchbegriffe mit | getrennt, ein Titel muss mindestens einen davon enthalten."""
    terms = [t.strip() for t in query.split("|") if t.strip()]
    anyterm = "(" + " OR ".join(f'"{t}"' for t in terms) + ")"
    title_re = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(t) for t in terms) + ")", re.I)
    found = []
    for q, hl, gl, ceid in ((f"{anyterm} (Quartalszahlen OR Zahlen OR Bilanz) when:{max(1, round(hours / 24))}d", "de", "DE", "DE:de"),
                            (f"{anyterm} (earnings OR results) when:{max(1, round(hours / 24))}d", "en-US", "US", "US:en")):
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + f"&hl={hl}&gl={gl}&ceid={ceid}"
        try:
            items = rss_items(fetch(url, 20))
        except Exception:
            continue
        for i in items:
            m = re.match(r"(.*)\s+-\s+([^-]+)$", i["title"])
            title, source = (m.group(1), m.group(2).strip()) if m else (i["title"], "")
            if not title_re.search(title):
                continue
            found.append({"title": title, "source": source, "url": i["url"], "time": i["time"].isoformat(), "lang": "de" if hl == "de" else "en"})
    seen, out = set(), []
    for n in found:
        key = re.sub(r"\W+", "", n["title"].lower())[:40]
        if key not in seen:
            seen.add(key)
            n["score"] = (2 if WORDS.search(n["title"]) else 0) + (1 if any(p in n["source"].lower() for p in PREFERRED) else 0) + (0.5 if n["lang"] == "de" else 0) + (1.5 if title_re.match(n["title"]) else 0)
            out.append(n)
    out.sort(key=lambda n: (n["score"], n["time"]), reverse=True)
    return out[:4]


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(cfg, today):
    """today: datum.date. Liefert das Dict für die Seite; bei Ausfall der Terminquelle den letzten guten Stand."""
    ec = cfg.get("earnings")
    if not ec:
        return None
    cache = load_cache()
    times = cache.get("times", {})
    prev = {f"{i['symbol']}|{i['date']}": i for i in (cache.get("last") or {}).get("items", [])}
    companies, skip = ec.get("companies", {}), set(ec.get("skip", []))
    days = [today + dt.timedelta(days=n) for n in range(-ec.get("back_days", 7), ec.get("ahead_days", 14) + 1)]
    days = [d for d in days if d.weekday() < 5]
    errors, rows = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda d: _safe(calendar_day, str(d)), days):
            if isinstance(res, Exception):
                errors.append(type(res).__name__)
                continue
            day, day_rows = res
            for r in day_rows:
                sym = r.get("symbol", "").strip()
                if not sym or sym in skip:
                    continue
                if sym in companies or parse_cap(r.get("marketCap")) >= ec.get("min_cap_b", 60) * 1e9:
                    rows.append((dt.date.fromisoformat(day), r))
    if not rows:
        if cache.get("last"):
            last = cache["last"]
            last["stale"] = True
            return last
        return {"items": [], "error": "Terminkalender gerade nicht erreichbar", "checked": _now()}

    items = []
    for day, r in rows:
        sym = r["symbol"].strip()
        conf = companies.get(sym, {})
        when = TIMES.get(r.get("time"), "")
        key = f"{sym}|{day}"
        if when:
            times[key] = when
        else:
            when = times.get(key, "")
        name = conf.get("name") or clean_name(r.get("name"))
        query = conf.get("q") or name
        items.append({
            "symbol": sym, "watch": sym in companies, "name": name, "date": day.isoformat(), "when": when, "cap_b": round(parse_cap(r.get("marketCap")) / 1e9),
            "quarter": r.get("fiscalQuarterEnding") or "", "est": number(r.get("epsForecast")), "est_n": number(r.get("noOfEsts")),
            "prev_eps": number(r.get("lastYearEPS")), "cal_eps": number(r.get("eps")), "cal_surprise": number(r.get("surprise")), "status": "upcoming" if day > today else "pending", "result": None, "reaction": None,
            "news": [], "series": None, "query": query,
            "links": {"ir": conf.get("ir"),
                      "sec": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={urllib.parse.quote(sym)}&type=&dateb=&owner=include&count=10",
                      "search": "https://news.google.com/search?q=" + urllib.parse.quote(query.replace("|", " ") + " Quartalszahlen") + "&hl=de&gl=DE&ceid=DE:de"}})

    done = [i for i in items if i["date"] <= today.isoformat()]

    # Gewinn je Aktie des Vorjahresquartals: aus dem Kalender des Vorjahres (dort steht das Ergebnis je Firma)
    last_year = {}
    span = sorted({dt.date.fromisoformat(i["date"]) - dt.timedelta(days=364 + k) for i in done for k in range(-5, 6)})
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(lambda d: _safe(calendar_day, str(d)), [d for d in span if d.weekday() < 5]):
            if isinstance(res, Exception):
                continue
            for r in res[1]:
                e = number(r.get("eps"))
                if e is not None:
                    last_year.setdefault(r.get("symbol", "").strip(), []).append((dt.date.fromisoformat(res[0]), e))

    def year_ago(sym, day):
        target = day - dt.timedelta(days=364)
        best = min(last_year.get(sym, []), key=lambda x: abs((x[0] - target).days), default=None)
        return best[1] if best and abs((best[0] - target).days) <= 14 else None

    def attach_chart(i, day):
        try:
            rows = bars(i["symbol"])
            i["series"] = series_of(rows)
            i["reaction"] = reaction(rows, day, i["when"]) or i.get("reaction")
        except Exception:
            pass

    def enrich(i):
        day = dt.date.fromisoformat(i["date"])
        old = prev.get(f"{i['symbol']}|{i['date']}")
        reuse = old and old["status"] == "reported" and day < today - dt.timedelta(days=2)
        if reuse:  # Ergebnis steht fest, nur der Kursverlauf wird frisch geholt
            i.update(status="reported", result=old["result"], reaction=old["reaction"], when=i["when"] or old.get("when", ""))
        try:
            if reuse:
                raise StopIteration
            rows = surprise(i["symbol"])
            for r in rows:
                if abs((r["date"] - day).days) <= 1:
                    s = r["surprise"]
                    verdict = None if s is None else "übertroffen" if s >= 1 else "verfehlt" if s <= -1 else "im Rahmen"
                    i["result"] = {"eps": r["eps"], "est": r["est"], "surprise": s, "verdict": verdict, "quarter": r["quarter"],
                                   "hist": [{"quarter": h["quarter"], "date": h["date"].isoformat(), "eps": h["eps"], "est": h["est"],
                                             "surprise": h["surprise"]} for h in rows[:5]]}
                    i["status"] = "reported"
                    break
        except StopIteration:
            pass
        except Exception as e:
            i["error"] = type(e).__name__
        if i["status"] != "reported" and i["cal_eps"] is not None:
            sp = i["cal_surprise"]
            i["result"] = {"eps": i["cal_eps"], "est": i["est"], "surprise": sp, "quarter": i["quarter"].replace("/", " "), "hist": [],
                           "verdict": None if sp is None else "übertroffen" if sp >= 1 else "verfehlt" if sp <= -1 else "im Rahmen"}
            i["status"] = "reported"
        if old and i["prev_eps"] is None:
            i["prev_eps"] = old.get("prev_eps")   # vom Vortermin gemerkt, die Kalenderzeile verliert den Wert nach dem Termin
        if i["prev_eps"] is None and i["result"]:
            i["prev_eps"] = year_ago(i["symbol"], day)
        if i["result"]:
            i["change"] = change(i)
        attach_chart(i, day)
        if not reuse and (today - day).days <= ec.get("news_days", 3):
            i["news"] = headlines(i["query"], ec.get("news_hours", 96))
        return i

    coming = [i for i in items if i not in done and (i["watch"] or i["cap_b"] >= 200)]
    wanted = [i for i in items if i["watch"] or i["cap_b"] >= ec.get("fund_min_cap_b", 150)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(enrich, done))
        list(ex.map(lambda i: attach_chart(i, dt.date.fromisoformat(i["date"])), coming))
    for i in items:
        if i["status"] == "pending" and i["date"] < today.isoformat():
            i["status"] = "missing"      # Termin vorbei, aber noch kein Ergebnis in der Quelle
    # Umsatz, Prognosen und Kursziele: höchstens einmal am Tag je Firma, nach frischen Zahlen öfter, bis der Umsatz da ist
    fund = cache.get("fund", {})
    now = dt.datetime.now(dt.timezone.utc)

    def stale(i):
        f = fund.get(i["symbol"])
        if not f:
            return True
        age = (now - dt.datetime.fromisoformat(f["fetched"])).total_seconds() / 3600
        y, m = quarter_ym(i.get("quarter"))
        waiting = i["status"] != "upcoming" and y and not any(int(e[:4]) == y and int(e[5:7]) == m for e, _ in f.get("rev") or [])
        return age >= ec.get("fund_hours", 24) or (waiting and age >= 2)
    todo = list(dict.fromkeys(i["symbol"] for i in sorted(wanted, key=lambda i: abs((dt.date.fromisoformat(i["date"]) - today).days)) if stale(i)))
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, f in zip(todo[:ec.get("fund_per_run", 40)], ex.map(fundamentals, todo[:ec.get("fund_per_run", 40)])):
            fund[sym] = f
    for i in wanted:
        attach_fund(i, fund.get(i["symbol"]))
    fund = {s: f for s, f in fund.items() if s in {i["symbol"] for i in items}}
    for i in items:
        i.pop("cal_eps", None)
        i.pop("cal_surprise", None)
    items.sort(key=lambda i: (i["date"], -i["cap_b"]))

    out = {"items": items, "checked": _now(), "stale": False, "error": None if not errors else f"{len(errors)} Kalendertage fehlen"}
    keep = {k: v for k, v in times.items() if k.split("|")[1] >= str(today - dt.timedelta(days=60))}
    # Die Zwischenspeicherdatei landet im Repository: nur schreiben, wenn sich Inhalte (nicht nur der Zeitstempel) geändert haben
    snapshot = {"times": keep, "fund": fund, "last": {**out, "checked": None, "items": [{**i, "news": [], "series": None} for i in items]}}
    if json.dumps(snapshot, sort_keys=True) != json.dumps({"times": cache.get("times"), "fund": cache.get("fund"),
                                                           "last": {**(cache.get("last") or {}), "checked": None}}, sort_keys=True):
        try:
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return e


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

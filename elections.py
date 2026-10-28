"""Wahlkalender aus Wikipedia ("<Jahr> national electoral calendar"), mit Zwischenspeicher als Rückfall."""
import datetime as dt
import json
import re
import urllib.parse
from pathlib import Path

from net import fetch

CACHE = Path(__file__).parent / "cache" / "elections.json"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], 1)}

COUNTRY_DE = {
    "Germany": "Deutschland", "United States": "USA", "France": "Frankreich", "United Kingdom": "Großbritannien",
    "Italy": "Italien", "Spain": "Spanien", "Poland": "Polen", "Netherlands": "Niederlande", "Belgium": "Belgien",
    "Austria": "Österreich", "Switzerland": "Schweiz", "Sweden": "Schweden", "Norway": "Norwegen", "Denmark": "Dänemark",
    "Finland": "Finnland", "Greece": "Griechenland", "Hungary": "Ungarn", "Czech Republic": "Tschechien",
    "Slovakia": "Slowakei", "Slovenia": "Slowenien", "Croatia": "Kroatien", "Romania": "Rumänien", "Bulgaria": "Bulgarien",
    "Portugal": "Portugal", "Ireland": "Irland", "Latvia": "Lettland", "Lithuania": "Litauen", "Estonia": "Estland",
    "Russia": "Russland", "Ukraine": "Ukraine", "Belarus": "Belarus", "Turkey": "Türkei", "Israel": "Israel",
    "Iran": "Iran", "Iraq": "Irak", "Saudi Arabia": "Saudi-Arabien", "Egypt": "Ägypten", "South Africa": "Südafrika",
    "Nigeria": "Nigeria", "Kenya": "Kenia", "Ethiopia": "Äthiopien", "China": "China", "Japan": "Japan",
    "India": "Indien", "Pakistan": "Pakistan", "Bangladesh": "Bangladesch", "Indonesia": "Indonesien",
    "Philippines": "Philippinen", "Thailand": "Thailand", "Vietnam": "Vietnam", "South Korea": "Südkorea",
    "North Korea": "Nordkorea", "Taiwan": "Taiwan", "Australia": "Australien", "New Zealand": "Neuseeland",
    "Canada": "Kanada", "Mexico": "Mexiko", "Brazil": "Brasilien", "Argentina": "Argentinien", "Chile": "Chile",
    "Colombia": "Kolumbien", "Peru": "Peru", "Venezuela": "Venezuela", "Cuba": "Kuba", "Bolivia": "Bolivien",
    "Armenia": "Armenien", "Georgia": "Georgien", "Moldova": "Moldau", "Serbia": "Serbien", "Bosnia and Herzegovina": "Bosnien und Herzegowina",
    "Hong Kong": "Hongkong", "European Union": "Europäische Union", "Scotland": "Schottland", "Wales": "Wales",
}
COUNTRY_DE.update({
    "Yemen": "Jemen", "Syria": "Syrien", "Lebanon": "Libanon", "Jordan": "Jordanien", "Libya": "Libyen",
    "Sudan": "Sudan", "S. Sudan": "Südsudan", "Somalia": "Somalia", "Mali": "Mali", "Niger": "Niger",
    "Burkina Faso": "Burkina Faso", "Chad": "Tschad", "Cameroon": "Kamerun", "Dem. Rep. Congo": "DR Kongo",
    "Congo": "Kongo", "Angola": "Angola", "Mozambique": "Mosambik", "Zimbabwe": "Simbabwe", "Zambia": "Sambia",
    "Uganda": "Uganda", "Tanzania": "Tansania", "Algeria": "Algerien", "Morocco": "Marokko", "Tunisia": "Tunesien",
    "Afghanistan": "Afghanistan", "Myanmar": "Myanmar", "Sri Lanka": "Sri Lanka", "Nepal": "Nepal",
    "Kazakhstan": "Kasachstan", "Uzbekistan": "Usbekistan", "Azerbaijan": "Aserbaidschan", "Qatar": "Katar",
    "Kuwait": "Kuwait", "United Arab Emirates": "Vereinigte Arabische Emirate", "Oman": "Oman", "Palestine": "Palästina",
    "Cyprus": "Zypern", "Iceland": "Island", "Luxembourg": "Luxemburg", "Malta": "Malta", "Albania": "Albanien",
    "Kosovo": "Kosovo", "Montenegro": "Montenegro", "Macedonia": "Nordmazedonien", "Mongolia": "Mongolei",
    "Cambodia": "Kambodscha", "Laos": "Laos", "Malaysia": "Malaysia", "Haiti": "Haiti", "Ecuador": "Ecuador",
    "Paraguay": "Paraguay", "Uruguay": "Uruguay", "Panama": "Panama", "Costa Rica": "Costa Rica",
    "Guatemala": "Guatemala", "Honduras": "Honduras", "El Salvador": "El Salvador", "Nicaragua": "Nicaragua",
    "Jamaica": "Jamaika", "Ghana": "Ghana", "Senegal": "Senegal", "Côte d'Ivoire": "Elfenbeinküste",
    "Madagascar": "Madagaskar", "Namibia": "Namibia", "Botswana": "Botsuana", "Eritrea": "Eritrea",
    "Djibouti": "Dschibuti", "Rwanda": "Ruanda", "Burundi": "Burundi", "Gambia": "Gambia", "Fiji": "Fidschi",
    "Papua New Guinea": "Papua-Neuguinea", "Czechia": "Tschechien", "Bosnia and Herz.": "Bosnien und Herzegowina",
    "Central African Rep.": "Zentralafrikanische Republik", "Dominican Rep.": "Dominikanische Republik",
    "Eq. Guinea": "Äquatorialguinea", "Solomon Is.": "Salomonen", "W. Sahara": "Westsahara", "eSwatini": "Eswatini",
    "United States of America": "USA", "Kyrgyzstan": "Kirgisistan", "Tajikistan": "Tadschikistan",
    "Turkmenistan": "Turkmenistan", "Bhutan": "Bhutan", "Brunei": "Brunei", "Guyana": "Guyana", "Suriname": "Suriname",
    "Liberia": "Liberia", "Sierra Leone": "Sierra Leone", "Guinea": "Guinea", "Guinea-Bissau": "Guinea-Bissau",
    "Togo": "Togo", "Benin": "Benin", "Malawi": "Malawi", "Lesotho": "Lesotho", "Mauritania": "Mauretanien",
    "Gabon": "Gabun", "Timor-Leste": "Osttimor", "Vanuatu": "Vanuatu", "Belize": "Belize", "Bahamas": "Bahamas",
    "Trinidad and Tobago": "Trinidad und Tobago", "Cuba": "Kuba", "Greenland": "Grönland", "Antarctica": "Antarktis",
    "Somaliland": "Somaliland", "N. Cyprus": "Nordzypern", "New Caledonia": "Neukaledonien",
})
TYPE_DE = [
    (r"\bPresidential\b", "Präsidentschaftswahl"), (r"\bPresident\b", "Präsident"), (r"\bParliament\b", "Parlament"),
    (r"\bParliamentary\b", "Parlamentswahl"), (r"\bLegislative Assembly\b", "Parlament"), (r"\bLegislative\b", "Parlament"),
    (r"\bGeneral\b", "allgemeine Wahl"), (r"\bSenate\b", "Senat"), (r"\bHouse of Representatives\b", "Repräsentantenhaus"),
    (r"\bNational Assembly\b", "Nationalversammlung"), (r"\bReferendums?\b", "Referendum"), (r"\bMayor\b", "Bürgermeister"),
    (r"\bGovernor\b", "Gouverneur"), (r"\bLocal\b", "Kommunalwahl"), (r"\bRegional\b", "Regionalwahl"),
    (r"\b(\d)(?:st|nd|rd|th) round\b", r"\1. Runde"), (r"\b(\d)(?:st|nd|rd|th) phase\b", r"\1. Phase"),
    (r"\bCongress of Deputies\b", "Abgeordnetenhaus"), (r"\bLegislature\b", "Parlament"),
    (r"\bTBD\b", "Termin offen"), (r"\band\b", "und"),
]
WIKI = "https://en.wikipedia.org/wiki/"


def clean_text(wikitext):
    t = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    for _ in range(3):
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    return t


def parse_entry(rest):
    """Aus "[[Elections in X|X]], [[2026 X election|President]]" -> (Land, Art, Link)."""
    links = re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", rest)
    if not links:
        return None
    plain = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", rest)
    plain = re.sub(r"'''?", "", plain).strip(" ,;")
    country = re.sub(r"'+", "", links[0][1] or links[0][0]).strip(" ,;:")
    what = plain
    if what.startswith(country):
        what = what[len(country):].lstrip(" ,:;")
    target = links[1][0] if len(links) > 1 else links[0][0]
    return country, what, WIKI + urllib.parse.quote(target.strip().replace(" ", "_"), safe="_()%,-")


def parse(wikitext, year):
    out, cur = [], None
    for line in clean_text(wikitext).splitlines():
        m = re.match(r"^\*\s*(?:(\d{1,2})(?:\s*[–\-]\s*(\d{1,2}))?\s+)?([A-Z][a-z]+)\s*:\s*(.*)$", line)
        if m and m.group(3) in MONTHS:
            day, day2, mon, rest = m.groups()
            cur = (year, MONTHS[mon], int(day) if day else None, int(day2) if day2 else None)
            entries = [rest] if rest.strip() else []
        elif line.startswith("**") and cur:
            entries = [line.lstrip("*").strip()]
        else:
            continue
        for e in entries:
            parsed = parse_entry(e)
            if not parsed:
                continue
            y, mo, d, d2 = cur
            try:
                start = dt.date(y, mo, d or 1)
                end = dt.date(y, mo, d2) if d2 else start
            except ValueError:
                continue
            country, what, url = parsed
            out.append({"date": start.isoformat(), "end": end.isoformat(), "approx": d is None,
                        "country_en": country, "what_en": what, "url": url})
    return out


def fetch_all(pages):
    items = []
    for page in pages:
        url = ("https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext&format=json&redirects=1&page="
               + urllib.parse.quote(page))
        data = json.loads(fetch(url, 30))
        items += parse(data["parse"]["wikitext"]["*"], int(page[:4]))
    return items


def translate(item, important):
    what = item["what_en"]
    for pat, rep in TYPE_DE:
        what = re.sub(pat, rep, what)
    return {"date": item["date"], "end": item["end"], "approx": item["approx"], "country_en": item["country_en"],
            "country": COUNTRY_DE.get(item["country_en"], item["country_en"]), "what": what, "url": item["url"],
            "important": item["country_en"] in important}


def build(cfg, today):
    """Liefert (kommende Wahlen, Hinweistext oder None)."""
    ec = cfg["elections"]
    note = None
    try:
        items = fetch_all(ec["pages"])
        if len(items) < 5:
            raise ValueError(f"nur {len(items)} Einträge erkannt")
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        note = f"Wikipedia nicht lesbar ({type(e).__name__}), letzter gespeicherter Stand"
        try:
            items = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return [], f"Wahlkalender nicht verfügbar ({type(e).__name__})"
    items += [{"date": x["date"], "end": x.get("end", x["date"]), "approx": False, "country_en": x["country"],
               "what_en": x["what"], "url": x.get("url", "")} for x in ec.get("extra", [])]
    upcoming = [translate(i, set(ec["important"])) for i in items if i["end"] >= today]
    upcoming.sort(key=lambda i: (i["date"], not i["important"], i["country"]))
    return upcoming[: ec.get("max", 80)], note

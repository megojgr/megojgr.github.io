"""Wuppertal vor Ort: Wetter (Open-Meteo) und amtliche Warnungen (Deutscher Wetterdienst). Frei, ohne Schlüssel."""
import datetime as dt
import json
import re

from net import fetch

WMO = {
    0: "klar", 1: "überwiegend klar", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen", 56: "gefrierender Nieselregen", 57: "gefrierender Nieselregen",
    61: "leichter Regen", 63: "Regen", 65: "starker Regen", 66: "gefrierender Regen", 67: "gefrierender Regen",
    71: "leichter Schneefall", 73: "Schneefall", 75: "starker Schneefall", 77: "Schneegriesel",
    80: "leichte Schauer", 81: "Schauer", 82: "heftige Schauer", 85: "Schneeschauer", 86: "starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "schweres Gewitter mit Hagel",
}


def weather(lat, lon):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation,relative_humidity_2m,is_day"
           "&hourly=temperature_2m,precipitation_probability,weather_code,precipitation"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_gusts_10m_max,"
           "precipitation_probability_max,sunrise,sunset,uv_index_max"
           "&timezone=Europe%2FBerlin&forecast_days=7")
    d = json.loads(fetch(url, 20))
    cur, daily, hourly = d["current"], d["daily"], d["hourly"]
    days = [{"date": daily["time"][i], "tmax": round(daily["temperature_2m_max"][i]), "tmin": round(daily["temperature_2m_min"][i]),
             "rain": round(daily["precipitation_sum"][i], 1), "gust": round(daily["wind_gusts_10m_max"][i]),
             "pop": daily["precipitation_probability_max"][i], "code": daily["weather_code"][i],
             "sunrise": daily["sunrise"][i][11:16], "sunset": daily["sunset"][i][11:16],
             "uv": round(daily["uv_index_max"][i] or 0),
             "text": WMO.get(daily["weather_code"][i], "")} for i in range(len(daily["time"]))]
    # Stundenverlauf ab jetzt, alle zwei Stunden für die nächsten 24 Stunden (Ortszeit, wie von Open-Meteo geliefert)
    now_h = cur["time"][:13]
    start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= now_h), 0)
    hours = [{"time": hourly["time"][i][11:16], "temp": round(hourly["temperature_2m"][i]),
              "pop": hourly["precipitation_probability"][i], "rain": round(hourly["precipitation"][i], 1),
              "code": hourly["weather_code"][i], "text": WMO.get(hourly["weather_code"][i], "")}
             for i in range(start, min(start + 25, len(hourly["time"])), 2)]
    return {"now": {"temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
                    "text": WMO.get(cur["weather_code"], ""), "code": cur["weather_code"], "wind": round(cur["wind_speed_10m"]),
                    "rain": cur.get("precipitation", 0), "humidity": cur.get("relative_humidity_2m"), "night": cur.get("is_day") == 0},
            "hours": hours, "days": days}


def warnings(cells):
    """Aktuelle amtliche Wetterwarnungen des DWD für die angegebenen Warnzellen."""
    raw = fetch("https://www.dwd.de/DWD/warnungen/warnapp/json/warnings.json", 20).decode("utf-8", "replace")
    data = json.loads(re.sub(r"^[^(]*\(|\);?\s*$", "", raw))
    out = []
    for cell in cells:
        for w in data.get("warnings", {}).get(cell, []):
            out.append({"event": w.get("event", ""), "headline": w.get("headline", ""), "level": w.get("level", 0),
                        "start": int(w["start"] / 1000), "end": int(w["end"] / 1000) if w.get("end") else None,
                        "text": (w.get("description") or "")[:300]})
    return sorted(out, key=lambda w: (-w["level"], w["start"]))


def build(cfg):
    c = cfg["local"]
    out = {"name": c["name"], "links": c["links"], "weather": None, "warnings": [], "errors": [],
           "checked": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        out["weather"] = weather(c["lat"], c["lon"])
    except Exception as e:
        out["errors"].append(f"Wetter: {type(e).__name__}")
    try:
        out["warnings"] = warnings(c["warncells"])
    except Exception as e:
        out["errors"].append(f"Warnungen: {type(e).__name__}")
    return out

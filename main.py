from flask import Flask, render_template, jsonify, request
import requests
import json
import os
import datetime
import argparse

app = Flask(__name__, static_folder="static")

WEATHER_HISTORY_FILE = "weather_history.json"


MAX_HISTORY_SNAPSHOTS = 50
NWS_MAX_FORECAST_DAYS = 7
NWS_USER_AGENT = "(weather_trends, contact@example.com)"


def _is_within_nws_range(start_date_str, end_date_str):
    """Check if the entire date range falls within 7 days from today."""
    today = datetime.date.today()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    return (end_date - today).days < NWS_MAX_FORECAST_DAYS


def _fetch_nws_forecast(latitude, longitude, start_date_str, end_date_str):
    """Fetch forecast from the National Weather Service API.

    Returns a dict matching Open-Meteo's daily structure, or None on failure.
    NWS only covers US locations and ~7 days out.
    """
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}

    # Step 1: resolve grid point
    points_resp = requests.get(
        f"https://api.weather.gov/points/{round(latitude, 4)},{round(longitude, 4)}",
        headers=headers,
        timeout=10,
    )
    if points_resp.status_code != 200:
        return None

    forecast_url = points_resp.json().get("properties", {}).get("forecast")
    if not forecast_url:
        return None

    # Step 2: get the daily forecast
    fc_resp = requests.get(forecast_url, headers=headers, timeout=10)
    if fc_resp.status_code != 200:
        return None

    periods = fc_resp.json().get("properties", {}).get("periods", [])
    if not periods:
        return None

    # NWS returns separate day/night periods. Group by date.
    start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    day_data = {}  # date_str -> {temp_max, temp_min, precip_chance, weather_code}
    for p in periods:
        period_date = p["startTime"][:10]  # "YYYY-MM-DD"
        pdate = datetime.datetime.strptime(period_date, "%Y-%m-%d").date()
        if pdate < start_dt or pdate > end_dt:
            continue

        temp = p.get("temperature")
        is_day = p.get("isDaytime", True)
        precip = (p.get("probabilityOfPrecipitation") or {}).get("value")
        if precip is None:
            precip = 0

        if period_date not in day_data:
            day_data[period_date] = {
                "temp_max": None,
                "temp_min": None,
                "precip_chance": 0,
                "weather_code": 0,
            }

        entry = day_data[period_date]
        if is_day:
            entry["temp_max"] = temp
        else:
            entry["temp_min"] = temp
        entry["precip_chance"] = max(entry["precip_chance"], precip)

    if not day_data:
        return None

    # Fill in missing min/max with the other value as fallback
    for d in day_data.values():
        if d["temp_max"] is None:
            d["temp_max"] = d["temp_min"]
        if d["temp_min"] is None:
            d["temp_min"] = d["temp_max"]

    # Build the Open-Meteo-compatible daily structure
    dates_sorted = sorted(day_data.keys())
    return {
        "daily": {
            "time": dates_sorted,
            "temperature_2m_max": [day_data[d]["temp_max"] for d in dates_sorted],
            "temperature_2m_min": [day_data[d]["temp_min"] for d in dates_sorted],
            "precipitation_probability_max": [day_data[d]["precip_chance"] for d in dates_sorted],
            "weathercode": [day_data[d]["weather_code"] for d in dates_sorted],
        }
    }


def _fetch_open_meteo_forecast(latitude, longitude, start_date, end_date):
    """Fetch forecast from the Open-Meteo API. Returns parsed JSON or raises."""
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
            "timezone": "auto",
            "start_date": start_date,
            "end_date": end_date,
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "models": "best_match",
        },
        timeout=10,
    )
    return resp.json()


def load_weather_history():
    if os.path.exists(WEATHER_HISTORY_FILE):
        try:
            with open(WEATHER_HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_weather_history(history):
    if len(history) > MAX_HISTORY_SNAPSHOTS:
        history = history[-MAX_HISTORY_SNAPSHOTS:]
    with open(WEATHER_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    return history


weather_history = load_weather_history()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/geocode")
def geocode():
    """Search for locations using Open-Meteo geocoding API."""
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])

    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 5, "language": "en", "format": "json"},
            timeout=10,
        )
        data = resp.json()
        results = []
        for r in data.get("results", []):
            label_parts = [r.get("name", "")]
            if r.get("admin1"):
                label_parts.append(r["admin1"])
            if r.get("country"):
                label_parts.append(r["country"])
            results.append({
                "label": ", ".join(label_parts),
                "latitude": r["latitude"],
                "longitude": r["longitude"],
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route("/api/history", methods=["DELETE"])
def clear_history():
    """Delete all cached weather snapshots."""
    global weather_history
    weather_history = []
    save_weather_history(weather_history)
    return jsonify({"ok": True})


@app.route("/api/forecast")
def forecast():
    """Fetch weather forecast and compute trends."""
    global weather_history

    latitude = request.args.get("lat", type=float)
    longitude = request.args.get("lon", type=float)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    location_name = request.args.get("location_name", "Unknown")

    if latitude is None or longitude is None or not start_date or not end_date:
        return jsonify({"error": "Missing required parameters"}), 400

    # Use NWS for short-range forecasts (<=7 days), Open-Meteo otherwise
    data = None
    source = "open-meteo"
    try:
        if _is_within_nws_range(start_date, end_date):
            nws_data = _fetch_nws_forecast(latitude, longitude, start_date, end_date)
            if nws_data and "daily" in nws_data:
                data = nws_data
                source = "nws"

        if data is None:
            data = _fetch_open_meteo_forecast(latitude, longitude, start_date, end_date)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if "daily" not in data:
        return jsonify({"error": "No forecast data returned"}), 500

    daily = data["daily"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    forecast_days = []
    weather_snapshot = {}
    for i, date in enumerate(daily["time"]):
        day = {
            "date": date,
            "temp_max": daily["temperature_2m_max"][i],
            "temp_min": daily["temperature_2m_min"][i],
            "precip_chance": daily["precipitation_probability_max"][i],
            "weather_code": daily.get("weathercode", [0] * len(daily["time"]))[i],
        }
        forecast_days.append(day)
        weather_snapshot[date] = {
            "temp_max": day["temp_max"],
            "temp_min": day["temp_min"],
            "precip_chance": day["precip_chance"],
        }

    # Build location key for history filtering
    loc_key = f"{round(latitude, 2)},{round(longitude, 2)}"

    # Check if data actually changed from last snapshot
    loc_history = [
        h for h in weather_history
        if h.get("loc_key") == loc_key
        and h.get("start_date") == start_date
        and h.get("end_date") == end_date
    ]
    should_save = True
    if loc_history:
        last = loc_history[-1]
        if last.get("weather") == weather_snapshot:
            should_save = False

    if should_save:
        entry = {
            "timestamp": now,
            "loc_key": loc_key,
            "location_name": location_name,
            "start_date": start_date,
            "end_date": end_date,
            "weather": weather_snapshot,
        }
        weather_history.append(entry)
        weather_history = save_weather_history(weather_history)

    # Compute trends: compare current forecast to oldest snapshot for same query
    trends = {}
    if len(loc_history) > 0:
        oldest = loc_history[0]["weather"]
        for date in weather_snapshot:
            if date in oldest:
                temp_diff = round(weather_snapshot[date]["temp_max"] - oldest[date]["temp_max"], 1)
                precip_diff = round(
                    weather_snapshot[date]["precip_chance"] - oldest[date]["precip_chance"], 1
                )
                trends[date] = {
                    "temp_diff": temp_diff,
                    "precip_diff": precip_diff,
                    "temp_trend": "up" if temp_diff > 0 else ("down" if temp_diff < 0 else "same"),
                    "precip_trend": "up" if precip_diff > 0 else ("down" if precip_diff < 0 else "same"),
                }

    # Build chart series: historical snapshots for each date
    chart_series = {}
    for h in loc_history + ([{
        "timestamp": now,
        "weather": weather_snapshot,
    }] if should_save else []):
        ts = h["timestamp"]
        for date, w in h["weather"].items():
            if date not in chart_series:
                chart_series[date] = {"timestamps": [], "temps": [], "precips": []}
            chart_series[date]["timestamps"].append(ts)
            chart_series[date]["temps"].append(w["temp_max"])
            chart_series[date]["precips"].append(w["precip_chance"])

    return jsonify({
        "forecast": forecast_days,
        "trends": trends,
        "chart_series": chart_series,
        "snapshot_count": len(loc_history) + (1 if should_save else 0),
        "fetched_at": now,
        "source": source,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=False)

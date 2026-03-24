from flask import Flask, render_template, jsonify, request
import requests
import json
import os
import datetime
import argparse

app = Flask(__name__, static_folder="static")

WEATHER_HISTORY_FILE = "weather_history.json"


def select_model(end_date_str):
    return "best_match"
MAX_HISTORY_SNAPSHOTS = 50


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

    try:
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
                "models": select_model(end_date),
            },
            timeout=10,
        )
        data = resp.json()
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
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()
    app.run(host="0.0.0.0", port=args.port, debug=False)

from flask import Flask, render_template, jsonify, request
import requests
import json
import pandas as pd  # Add pandas for data manipulation
import os
import datetime  # Add import for datetime

app = Flask(__name__, static_folder="static")

# File to store weather history
WEATHER_HISTORY_FILE = "weather_history.json"
CHART_HISTORY_LENGTH = 20

# Load weather history from file
def load_weather_history():
    if os.path.exists(WEATHER_HISTORY_FILE):
        with open(WEATHER_HISTORY_FILE, "r") as file:
            return json.load(file)
    return []

# Save weather history to file
def save_weather_history():
    global weather_history
    if len(weather_history) > CHART_HISTORY_LENGTH:
        weather_history = weather_history[-CHART_HISTORY_LENGTH:]
    # Add a simplified timestamp to the latest entry
    if weather_history:
        weather_history[-1]["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(WEATHER_HISTORY_FILE, "w") as file:
        json.dump(weather_history, file, indent=4)

# List to store historical weather data and trends
weather_history = load_weather_history()

def scrape_weather(latitude, longitude, start_date, end_date):
    # Fetch weather data from Open-Meteo API
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "America/Chicago",
        "start_date": start_date,
        "end_date": end_date,
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch"
    }
    response = requests.get(url, params=params)
    data = response.json()

    # Extract relevant data
    daily_data = data["daily"]
    weather_data = {}
    for i, date in enumerate(daily_data["time"]):
        weather_data[date] = {
            "temp": daily_data["temperature_2m_max"][i],
            "condition": f"{daily_data['precipitation_probability_max'][i]}%"  # Use precipitation probability max
        }
    return weather_data

def calculate_trends(new_data):
    trends = {}
    #print(json.dumps(weather_history, indent=2))
    for date, new_weather in new_data.items():
        # Find the oldest weather for the date in weather_history
        oldest_weather = None
        for entry in weather_history:
            if date in entry["weather"]:
                oldest_weather = entry["weather"][date]
                break  # Stop after finding the first (oldest) entry

        if oldest_weather:
            temp_diff = round(new_weather["temp"] - oldest_weather["temp"])
            trends[date] = {
                "temp_diff": temp_diff,
                "trend": "up" if temp_diff > 0 else "down" if temp_diff < 0 else "same"
            }
    return trends

@app.route("/chart-data")
def chart_data():
    chart_data = {}
    for entry in weather_history:
        timestamp = entry.get("timestamp", "Unknown")  # Use timestamp if available
        for date, weather in entry["weather"].items():
            if date not in chart_data:
                chart_data[date] = {
                    "timestamps": [],
                    "previous_temps": [],
                    "previous_precipitation": [],
                }
            chart_data[date]["timestamps"].append(timestamp)
            chart_data[date]["previous_temps"].append(weather["temp"])
            chart_data[date]["previous_precipitation"].append(float(weather["condition"].strip('%')))

    formatted_chart_data = []
    for date, data in chart_data.items():
        timestamps = data["timestamps"][-CHART_HISTORY_LENGTH:]
        previous_temps = data["previous_temps"][-CHART_HISTORY_LENGTH:]
        previous_precipitation = data["previous_precipitation"][-CHART_HISTORY_LENGTH:]
        formatted_chart_data.append({
            "date": date,
            "timestamps": timestamps,
            "previous_temps": previous_temps,
            "previous_precipitation": previous_precipitation,
            "latest_temp": previous_temps[-1] if previous_temps else None,
            "latest_precipitation": previous_precipitation[-1] if previous_precipitation else None
        })

    return jsonify(formatted_chart_data)

@app.route("/")
def index():
    # Get location and date inputs from the form
    location = request.args.get("location", "42.9289,-88.8371")
    start_date = request.args.get("start_date", "2025-04-02")
    end_date = request.args.get("end_date", "2025-04-06")
    latitude, longitude = map(float, location.split(","))

    # Fetch weather data based on inputs
    new_data = scrape_weather(latitude, longitude, start_date, end_date)
    
    # Calculate trends
    trends = calculate_trends(new_data)

    # Check if new_data is different from the last cached data in weather_history
    if not weather_history or any(new_data[date] != weather_history[-1].get("weather", {}).get(date, {}) for date in new_data):
        weather_history.append({"weather": new_data})
        # Save the updated weather history
        save_weather_history()

    return render_template("index.html", weather=new_data, trends=trends, history=weather_history, 
                           location=location, start_date=start_date, end_date=end_date, chart_data_url="/chart-data", chart_history_length=CHART_HISTORY_LENGTH)

if __name__ == "__main__":
    # Correct the parameter for specifying the host
    app.run(host="0.0.0.0", debug=False)

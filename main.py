from flask import Flask, render_template, jsonify, request
import requests
import json
import pandas as pd  # Add pandas for data manipulation
import os
import datetime  # Add import for datetime

app = Flask(__name__, static_folder="static")
CHART_HISTORY_LENGTH = 20

# Add a function to load locations from a file
LOCATIONS_FILE = "locations.json"

def load_locations():
    if os.path.exists(LOCATIONS_FILE):
        with open(LOCATIONS_FILE, "r") as file:
            return json.load(file)
    return []

# Load locations at the start of the application
locations = load_locations()

# Update save_weather_history to save city-specific weather history
def save_weather_history(location, data):
    city_file = os.path.join("data", f"{location.replace(',', '_')}.json")
    os.makedirs("data", exist_ok=True)
    
    # Maintain CHART_HISTORY_LENGTH
    if len(data) > CHART_HISTORY_LENGTH:
        data = data[-CHART_HISTORY_LENGTH:]
    
    # Add a simplified timestamp to the latest entry
    if data:
        data[-1]["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    with open(city_file, "w") as file:
        json.dump(data, file, indent=4)

# Update load_weather_history to load city-specific weather history
def load_weather_history(location):
    city_file = os.path.join("data", f"{location.replace(',', '_')}.json")
    if os.path.exists(city_file):
        with open(city_file, "r") as file:
            return json.load(file)
    return []

# Define weather_history dynamically by loading all city-specific histories
def get_weather_history():
    weather_history = []
    data_dir = "data"
    if os.path.exists(data_dir):
        for file_name in os.listdir(data_dir):
            if file_name.endswith(".json"):
                location = file_name.replace("_", ",").replace(".json", "")
                weather_history.extend(load_weather_history(location))
    return weather_history

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
    weather_history = get_weather_history()  # Retrieve weather history dynamically
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
    weather_history = get_weather_history()  # Retrieve weather history dynamically
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

# Dynamically calculate the current date
current_date = datetime.datetime.now().strftime("%Y-%m-%d")

# Use current_date for default start_date and end_date

# Function to load city-specific weather history
def load_city_weather_history(city_coordinates):
    city_file = os.path.join("data", f"{city_coordinates.replace(',', '_')}.json")
    if os.path.exists(city_file):
        with open(city_file, "r") as file:
            return json.load(file)
    return []

# Function to save city-specific weather history
def save_city_weather_history(city_coordinates, data):
    city_file = os.path.join("data", f"{city_coordinates.replace(',', '_')}.json")
    os.makedirs("data", exist_ok=True)
    with open(city_file, "w") as file:
        json.dump(data, file, indent=4)

@app.route("/")
def index():
    location = request.args.get("location", "42.9289,-88.8371")
    start_date = request.args.get("start_date", current_date)
    end_date = request.args.get("end_date", current_date)
    latitude, longitude = map(float, location.split(","))

    # Load city-specific weather history
    city_weather_history = load_weather_history(location)

    # Fetch weather data based on inputs
    new_data = scrape_weather(latitude, longitude, start_date, end_date)
    
    # Calculate trends
    trends = calculate_trends(new_data)

    # Check if new_data is different from the last cached data in city_weather_history
    if not city_weather_history or any(new_data[date] != city_weather_history[-1].get("weather", {}).get(date, {}) for date in new_data):
        city_weather_history.append({"weather": new_data})
        save_weather_history(location, city_weather_history)

    # Adjust locations to be a list of dictionaries for template rendering
    locations_list = [{"coordinates": key, "name": value} for key, value in locations.items()]

    # Pass the adjusted locations list to the template
    return render_template("index.html", weather=new_data, trends=trends, history=city_weather_history, 
                           location=location, start_date=start_date, end_date=end_date, 
                           chart_data_url="/chart-data", chart_history_length=CHART_HISTORY_LENGTH, 
                           locations=locations_list)

if __name__ == "__main__":
    # Correct the parameter for specifying the host
    app.run(host="0.0.0.0", debug=False)

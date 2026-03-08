from fastmcp import FastMCP

mcp = FastMCP("WeatherTools")


WEATHER_DATA = {
    "new york": {
        "current": {
            "condition": "Cloudy",
            "temperature_f": 48,
            "feels_like_f": 44,
            "humidity_pct": 68,
            "wind_mph": 12,
        },
        "forecast": [
            {
                "day": "today",
                "condition": "Cloudy",
                "high_f": 51,
                "low_f": 42,
                "precip_pct": 20,
            },
            {
                "day": "tomorrow",
                "condition": "Rain",
                "high_f": 47,
                "low_f": 39,
                "precip_pct": 80,
            },
            {
                "day": "day_after_tomorrow",
                "condition": "Partly Sunny",
                "high_f": 55,
                "low_f": 41,
                "precip_pct": 10,
            },
        ],
        "alerts": [
            {
                "title": "Wind Advisory",
                "severity": "moderate",
                "window": "02:00 PM - 10:00 PM local",
                "guidance": "Secure loose outdoor items and use caution on bridges.",
            }
        ],
    },
    "mexico city": {
        "current": {
            "condition": "Sunny",
            "temperature_f": 73,
            "feels_like_f": 73,
            "humidity_pct": 35,
            "wind_mph": 9,
        },
        "forecast": [
            {
                "day": "today",
                "condition": "Sunny",
                "high_f": 76,
                "low_f": 51,
                "precip_pct": 5,
            },
            {
                "day": "tomorrow",
                "condition": "Partly Cloudy",
                "high_f": 74,
                "low_f": 50,
                "precip_pct": 10,
            },
            {
                "day": "day_after_tomorrow",
                "condition": "Isolated Showers",
                "high_f": 71,
                "low_f": 49,
                "precip_pct": 35,
            },
        ],
        "alerts": [],
    },
    "tokyo": {
        "current": {
            "condition": "Light Rain",
            "temperature_f": 59,
            "feels_like_f": 57,
            "humidity_pct": 84,
            "wind_mph": 7,
        },
        "forecast": [
            {
                "day": "today",
                "condition": "Light Rain",
                "high_f": 61,
                "low_f": 54,
                "precip_pct": 70,
            },
            {
                "day": "tomorrow",
                "condition": "Heavy Rain",
                "high_f": 58,
                "low_f": 52,
                "precip_pct": 90,
            },
            {
                "day": "day_after_tomorrow",
                "condition": "Cloudy",
                "high_f": 63,
                "low_f": 55,
                "precip_pct": 30,
            },
        ],
        "alerts": [
            {
                "title": "Flood Watch",
                "severity": "high",
                "window": "06:00 PM - 06:00 AM local",
                "guidance": "Avoid low-lying roads and monitor transit disruptions.",
            }
        ],
    },
    "miami": {
        "current": {
            "condition": "Thunderstorms",
            "temperature_f": 82,
            "feels_like_f": 88,
            "humidity_pct": 79,
            "wind_mph": 18,
        },
        "forecast": [
            {
                "day": "today",
                "condition": "Thunderstorms",
                "high_f": 85,
                "low_f": 75,
                "precip_pct": 85,
            },
            {
                "day": "tomorrow",
                "condition": "Scattered Storms",
                "high_f": 84,
                "low_f": 74,
                "precip_pct": 65,
            },
            {
                "day": "day_after_tomorrow",
                "condition": "Partly Sunny",
                "high_f": 86,
                "low_f": 76,
                "precip_pct": 25,
            },
        ],
        "alerts": [
            {
                "title": "Lightning Risk Statement",
                "severity": "moderate",
                "window": "03:00 PM - 09:00 PM local",
                "guidance": "Pause beach and field activities when thunder is heard.",
            }
        ],
    },
}


def normalize_city(city: str) -> str:
    return city.strip().lower()


def get_city_data(city: str):
    key = normalize_city(city)
    if key not in WEATHER_DATA:
        supported = ", ".join(sorted(WEATHER_DATA.keys()))
        return (
            None,
            f"City '{city}' not found in demo dataset. Supported cities: {supported}.",
        )
    return WEATHER_DATA[key], None


@mcp.tool()
async def get_current_weather(city: str) -> str:
    """Return the current hardcoded weather snapshot for a city."""
    data, error = get_city_data(city)
    if error:
        return error

    current = data["current"]
    return (
        f"{city.title()}: {current['condition']}, {current['temperature_f']}F "
        f"(feels like {current['feels_like_f']}F), humidity {current['humidity_pct']}%, "
        f"wind {current['wind_mph']} mph."
    )


@mcp.tool()
async def get_three_day_forecast(city: str) -> str:
    """Return a hardcoded 3-day forecast for a city."""
    data, error = get_city_data(city)
    if error:
        return error

    lines = [f"3-day forecast for {city.title()}:"]
    for item in data["forecast"]:
        lines.append(
            f"- {item['day']}: {item['condition']}, high {item['high_f']}F, "
            f"low {item['low_f']}F, precip chance {item['precip_pct']}%."
        )
    return "\n".join(lines)


@mcp.tool()
async def get_weather_alerts(city: str) -> str:
    """Return any hardcoded severe weather alerts for a city."""
    data, error = get_city_data(city)
    if error:
        return error

    alerts = data["alerts"]
    if not alerts:
        return f"No active weather alerts for {city.title()} in this demo dataset."

    lines = [f"Alerts for {city.title()}:"]
    for alert in alerts:
        lines.append(
            f"- {alert['title']} ({alert['severity']}): {alert['window']}. {alert['guidance']}"
        )
    return "\n".join(lines)


@mcp.tool()
async def compare_weather(city_a: str, city_b: str) -> str:
    """Compare current hardcoded weather between two cities."""
    data_a, error_a = get_city_data(city_a)
    data_b, error_b = get_city_data(city_b)
    if error_a:
        return error_a
    if error_b:
        return error_b

    a = data_a["current"]
    b = data_b["current"]
    warmer = (
        city_a.title()
        if a["temperature_f"] >= b["temperature_f"]
        else city_b.title()
    )
    windier = (
        city_a.title() if a["wind_mph"] >= b["wind_mph"] else city_b.title()
    )
    return (
        f"Comparison: {city_a.title()} is {a['condition']} at {a['temperature_f']}F, "
        f"{city_b.title()} is {b['condition']} at {b['temperature_f']}F. "
        f"Warmer city: {warmer}. Windier city: {windier}."
    )


@mcp.tool()
async def plan_outdoor_activity(city: str) -> str:
    """Suggest an activity plan based on hardcoded weather and alerts."""
    data, error = get_city_data(city)
    if error:
        return error

    current = data["current"]
    alerts = data["alerts"]
    condition = current["condition"].lower()

    if alerts:
        return (
            f"For {city.title()}, keep plans flexible. Active alerts exist and current condition "
            f"is {current['condition']}. Best option: indoor plan with short weather checks each hour."
        )
    if "rain" in condition or "storm" in condition:
        return (
            f"For {city.title()}, favor indoor activities. Current condition is {current['condition']} "
            f"with humidity {current['humidity_pct']}%."
        )
    if current["temperature_f"] >= 80:
        return (
            f"For {city.title()}, outdoor activity is okay in short blocks. Hydrate and avoid peak heat; "
            f"it currently feels like {current['feels_like_f']}F."
        )
    return (
        f"For {city.title()}, conditions are good for outdoor plans. Current weather is "
        f"{current['condition']} at {current['temperature_f']}F."
    )


if __name__ == "__main__":
    mcp.run()

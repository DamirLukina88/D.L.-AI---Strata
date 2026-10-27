#!/usr/bin/env python3
"""weather_mcp.py - Blazing fast local/global weather MCP server using Open-Meteo & OpenStreetMap geocoding."""
import sys
import json
import urllib.request
import urllib.parse

# WMO Weather interpretation codes (WW)
WMO_CODES = {
    0: "Clear sky ☀️",
    1: "Mainly clear 🌤️",
    2: "Partly cloudy ⛅",
    3: "Overcast ☁️",
    45: "Fog 🌫️",
    48: "Depositing rime fog 🌫️",
    51: "Light drizzle 🌧️",
    53: "Moderate drizzle 🌧️",
    55: "Dense drizzle 🌧️",
    61: "Slight rain 🌦️",
    63: "Moderate rain 🌧️",
    65: "Heavy rain 🌧️",
    71: "Slight snow fall 🌨️",
    73: "Moderate snow fall 🌨️",
    75: "Heavy snow fall ❄️",
    77: "Snow grains ❄️",
    80: "Slight rain showers 🌦️",
    81: "Moderate rain showers 🌧️",
    82: "Violent rain showers ⛈️",
    85: "Slight snow showers 🌨️",
    86: "Heavy snow showers ❄️",
    95: "Thunderstorm ⚡",
    96: "Thunderstorm with slight hail ⛈️",
    99: "Thunderstorm with heavy hail ⛈️"
}

def get_coordinates(city: str) -> tuple[float, float, str]:
    c = city.strip()
    if not c or c.lower() in ("zagreb", "zagreb, croatia", "zagreb hrvatska"):
        return 45.8150, 15.9819, "Zagreb, Croatia"
    
    encoded = urllib.parse.quote(c)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0 (+https://github.com/DamirLukina88/D.L.-AI---Strata)"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data:
        raise ValueError(f"Could not locate '{city}'.")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]

def fetch_weather(city: str = "Zagreb") -> str:
    try:
        lat, lon, location_name = get_coordinates(city)
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        curr = data.get("current", {})
        temp = curr.get("temperature_2m", "N/A")
        feels_like = curr.get("apparent_temperature", "N/A")
        humidity = curr.get("relative_humidity_2m", "N/A")
        wind = curr.get("wind_speed_10m", "N/A")
        precip = curr.get("precipitation", 0.0)
        code = curr.get("weather_code", 0)
        condition = WMO_CODES.get(code, "Clear/Cloudy")
        
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        daily_codes = daily.get("weather_code", [])
        
        lines = [
            f"## Weather for {location_name}",
            f"**Condition:** {condition}",
            f"- **Temperature:** {temp} °C (Feels like: {feels_like} °C)",
            f"- **Humidity:** {humidity}%",
            f"- **Wind Speed:** {wind} km/h",
            f"- **Precipitation:** {precip} mm\n",
            "### 3-Day Forecast:"
        ]
        for i in range(min(3, len(dates))):
            d_date = dates[i]
            d_max = max_temps[i] if i < len(max_temps) else "N/A"
            d_min = min_temps[i] if i < len(min_temps) else "N/A"
            d_cond = WMO_CODES.get(daily_codes[i], "Fair") if i < len(daily_codes) else ""
            lines.append(f"- **{d_date}:** {d_cond} | Min: {d_min} °C — Max: {d_max} °C")
            
        return "\n".join(lines)
    except Exception as e:
        return f"Weather lookup error: {e}"

def _reply(req, res):
    """Write one JSON-RPC reply: nothing for a notification, an empty result for ping, and isError on a tool
    result whose text is an error message ("... error: ...")."""
    if "id" not in req:
        return
    if req.get("method") == "ping":
        res = {"jsonrpc": "2.0", "id": req["id"], "result": {}}
    result = res.get("result")
    if req.get("method") == "tools/call" and isinstance(result, dict) and "isError" not in result:
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        head = text.lstrip().split(":", 1)
        result["isError"] = len(head) == 2 and len(head[0]) <= 45 and any(
            w in head[0].lower() for w in ("error", "failed"))
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        m, mid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "weather-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "get_weather",
                    "description": "Get current weather conditions and 3-day forecast for Zagreb or any city/location in the world (temperature, condition, humidity, wind).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City or location name, e.g. 'Zagreb', 'Split', 'Berlin', 'Tokyo' (defaults to Zagreb)", "default": "Zagreb"}
                        }
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "get_weather":
                text = fetch_weather(args.get("location", "Zagreb"))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()

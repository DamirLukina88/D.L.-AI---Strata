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


def _wind_dir(deg: float | int | None) -> str:
    if deg is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    try:
        ix = int((float(deg) + 11.25) / 22.5) % 16
        return dirs[ix]
    except (ValueError, TypeError):
        return ""


def fetch_weather(city: str = "Zagreb", hourly: bool = False, day: str = "today") -> str:
    try:
        lat, lon, location_name = get_coordinates(city)
        hourly_params = (
            "&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,wind_direction_10m"
            if hourly else ""
        )
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,sunrise,sunset"
            f"{hourly_params}&timezone=auto"
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
        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])
        precip_sums = daily.get("precipitation_sum", [])
        precip_probs = daily.get("precipitation_probability_max", [])
        wind_maxs = daily.get("wind_speed_10m_max", [])

        # Resolve target day for hourly or summary
        target_date = dates[0] if dates else ""
        day_str = str(day).strip().lower()
        if day_str in ("tomorrow", "sutra") and len(dates) > 1:
            target_date = dates[1]
        elif day_str in ("today", "danas", "") and dates:
            target_date = dates[0]
        elif day_str in dates:
            target_date = day_str

        lines = [
            f"## Weather for {location_name}",
            f"**Current Condition:** {condition}",
            f"- **Temperature:** {temp} °C (Feels like: {feels_like} °C)",
            f"- **Humidity:** {humidity}%",
            f"- **Wind Speed:** {wind} km/h",
            f"- **Precipitation:** {precip} mm\n",
        ]

        # Detailed Hourly Table if requested
        if hourly and "hourly" in data:
            h_data = data["hourly"]
            h_times = h_data.get("time", [])
            h_indices = [i for i, t in enumerate(h_times) if t.startswith(target_date)]
            
            # Day highlights
            d_idx = dates.index(target_date) if target_date in dates else -1
            sunrise_str = sunrises[d_idx].split("T")[-1] if (d_idx >= 0 and d_idx < len(sunrises)) else "N/A"
            sunset_str = sunsets[d_idx].split("T")[-1] if (d_idx >= 0 and d_idx < len(sunsets)) else "N/A"
            d_max = max_temps[d_idx] if (d_idx >= 0 and d_idx < len(max_temps)) else "N/A"
            d_min = min_temps[d_idx] if (d_idx >= 0 and d_idx < len(min_temps)) else "N/A"
            d_precip = precip_sums[d_idx] if (d_idx >= 0 and d_idx < len(precip_sums)) else 0.0
            d_prob = precip_probs[d_idx] if (d_idx >= 0 and d_idx < len(precip_probs)) else 0
            d_wind_max = wind_maxs[d_idx] if (d_idx >= 0 and d_idx < len(wind_maxs)) else "N/A"

            lines.append(f"### Hourly Forecast for {target_date}:")
            lines.append(f"- **Day Summary:** Min: {d_min} °C — Max: {d_max} °C | Rain: {d_precip} mm ({d_prob}% max chance) | Max wind: {d_wind_max} km/h")
            lines.append(f"- **Daylight:** Sunrise {sunrise_str} — Sunset {sunset_str}\n")
            lines.append("| Time | Sky | Temp | Rain % | Rain mm | Wind | Humidity |")
            lines.append("|:---:|:---|:---:|:---:|:---:|:---|:---:|")

            h_temps = h_data.get("temperature_2m", [])
            h_probs = h_data.get("precipitation_probability", [])
            h_precs = h_data.get("precipitation", [])
            h_codes = h_data.get("weather_code", [])
            h_winds = h_data.get("wind_speed_10m", [])
            h_dirs = h_data.get("wind_direction_10m", [])
            h_hums = h_data.get("relative_humidity_2m", [])

            for i in h_indices:
                t_str = h_times[i].split("T")[-1]
                t_temp = h_temps[i] if i < len(h_temps) else "N/A"
                t_prob = f"{h_probs[i]}%" if i < len(h_probs) else "N/A"
                t_prec = f"{h_precs[i]} mm" if i < len(h_precs) else "0 mm"
                t_cond = WMO_CODES.get(h_codes[i], "Fair") if i < len(h_codes) else ""
                t_wind_spd = h_winds[i] if i < len(h_winds) else "N/A"
                t_dir = _wind_dir(h_dirs[i]) if i < len(h_dirs) else ""
                t_wind = f"{t_wind_spd} km/h {t_dir}".strip()
                t_hum = f"{h_hums[i]}%" if i < len(h_hums) else "N/A"
                lines.append(f"| {t_str} | {t_cond} | {t_temp} °C | {t_prob} | {t_prec} | {t_wind} | {t_hum} |")
            lines.append("")

        lines.append("### 3-Day Forecast:")
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
                    "description": "Get current weather conditions, 3-day forecast, or detailed 24-hour table for Zagreb or any city/location in the world (temperature, condition, humidity, wind). Geocodes automatically.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City or location name, e.g. 'Zagreb', 'Split', 'Berlin', 'Tokyo' (defaults to Zagreb)", "default": "Zagreb"},
                            "hourly": {"type": "boolean", "description": "If true, return detailed 24-hour table (time, sky, temp, rain chance & mm, wind speed & compass direction, humidity, daylight/sunrise/sunset)", "default": False},
                            "day": {"type": "string", "description": "'today', 'tomorrow', or a date 'YYYY-MM-DD' (defaults to 'today')", "default": "today"}
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
                hourly_arg = args.get("hourly")
                if isinstance(hourly_arg, str):
                    hourly_arg = hourly_arg.lower() in ("true", "1", "yes")
                text = fetch_weather(
                    city=args.get("location", "Zagreb"),
                    hourly=bool(hourly_arg),
                    day=str(args.get("day") or "today")
                )
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()

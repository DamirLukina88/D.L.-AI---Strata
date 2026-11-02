"""tools/test_weather_mcp.py - unit tests for weather_mcp.py (hourly forecast, geocoding, formatting)."""
import json
import unittest
from pathlib import Path
from unittest import mock

import weather_mcp


class WeatherMcpTest(unittest.TestCase):
    def test_wind_dir_compass(self):
        self.assertEqual(weather_mcp._wind_dir(0), "N")
        self.assertEqual(weather_mcp._wind_dir(32), "NNE")
        self.assertEqual(weather_mcp._wind_dir(90), "E")
        self.assertEqual(weather_mcp._wind_dir(180), "S")
        self.assertEqual(weather_mcp._wind_dir(270), "W")
        self.assertEqual(weather_mcp._wind_dir(None), "")

    def test_zagreb_coordinates_cached(self):
        lat, lon, name = weather_mcp.get_coordinates("Zagreb")
        self.assertAlmostEqual(lat, 45.8150)
        self.assertAlmostEqual(lon, 15.9819)
        self.assertEqual(name, "Zagreb, Croatia")

    def test_fetch_weather_hourly_formatting(self):
        sample_api_response = {
            "current": {
                "temperature_2m": 8.5,
                "apparent_temperature": 5.0,
                "relative_humidity_2m": 80,
                "wind_speed_10m": 12.0,
                "precipitation": 0.0,
                "weather_code": 3,
            },
            "daily": {
                "time": ["2026-11-01", "2026-11-02", "2026-11-03"],
                "weather_code": [3, 2, 1],
                "temperature_2m_max": [10.0, 12.0, 14.0],
                "temperature_2m_min": [7.0, 8.0, 9.0],
                "precipitation_sum": [0.5, 0.0, 0.0],
                "precipitation_probability_max": [50, 10, 0],
                "wind_speed_10m_max": [15.0, 18.0, 10.0],
                "sunrise": ["2026-11-01T06:50", "2026-11-02T06:51", "2026-11-03T06:53"],
                "sunset": ["2026-11-01T16:58", "2026-11-02T16:57", "2026-11-03T16:55"],
            },
            "hourly": {
                "time": [
                    "2026-11-01T00:00", "2026-11-01T12:00",
                    "2026-11-02T00:00", "2026-11-02T06:00", "2026-11-02T12:00", "2026-11-02T18:00"
                ],
                "temperature_2m": [8.0, 10.0, 8.5, 8.2, 12.0, 10.5],
                "relative_humidity_2m": [80, 70, 75, 78, 60, 65],
                "apparent_temperature": [6.0, 9.0, 6.5, 6.0, 11.0, 9.0],
                "precipitation_probability": [20, 10, 5, 0, 0, 0],
                "precipitation": [0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
                "weather_code": [3, 3, 3, 2, 0, 1],
                "wind_speed_10m": [10.0, 12.0, 11.0, 9.0, 15.0, 8.0],
                "wind_direction_10m": [30, 45, 32, 20, 50, 40],
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps(sample_api_response).encode("utf-8")

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            res = weather_mcp.fetch_weather("Zagreb", hourly=True, day="tomorrow")
            self.assertIn("## Weather for Zagreb, Croatia", res)
            self.assertIn("### Hourly Forecast for 2026-11-02:", res)
            self.assertIn("Sunrise 06:51 — Sunset 16:57", res)
            self.assertIn("| Time | Sky | Temp | Rain % | Rain mm | Wind | Humidity |", res)
            self.assertIn("| 12:00 | Clear sky ☀️ | 12.0 °C | 0% | 0.0 mm | 15.0 km/h NE | 60% |", res)
            self.assertIn("### 3-Day Forecast:", res)


if __name__ == "__main__":
    unittest.main()

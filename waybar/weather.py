#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".config" / "hypr" / "lock"))
from lock_info import weather_data, weather_icon


def main():
    data = weather_data()
    if not data:
        print(json.dumps({"text": "", "class": "unavailable", "tooltip": "Weather unavailable"}))
        return
    current = data["current_condition"][0]
    print(json.dumps({
        "text": f"{weather_icon(current.get('weatherCode'))}  {current['temp_C']}°C",
        "tooltip": f"{current['weatherDesc'][0]['value']}, feels like {current['FeelsLikeC']}°  ·  Humidity {current['humidity']}%",
    }))


if __name__ == "__main__":
    main()

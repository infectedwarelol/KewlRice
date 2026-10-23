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
    tooltip = f"{current['weatherDesc'][0]['value']}, feels like {current['FeelsLikeC']}°  ·  Humidity {current['humidity']}%"
    if "icon" in sys.argv[1:]:
        text = weather_icon(current.get("weatherCode"))
    else:
        text = f"<span weight='bold' size='11pt'>{current['temp_C']}°C</span>\n<span size='7.5pt' fgalpha='60%'>feels {current['FeelsLikeC']}°</span>"
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()

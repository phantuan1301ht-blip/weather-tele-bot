import os
import requests
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

LOCATIONS = [
    {"name": "Dĩ An (Bình Dương)", "lat": 10.90682, "lon": 106.76940},
    {"name": "TP. Hồ Chí Minh", "lat": 10.82302, "lon": 106.62965},
    {"name": "Huyện Đức Thọ (Hà Tĩnh)", "lat": 18.5401307, "lon": 105.5855438},
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def icon(code):
    if code == 0: return "☀️"
    if code in (1,2): return "⛅"
    if code == 3: return "☁️"
    if code in (45,48): return "🌫️"
    if code in (51,53,55): return "🌦️"
    if code in (61,63,65,80,81,82): return "🌧️"
    if code in (95,96,99): return "⛈️"
    return "🌡️"

def fetch(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": TZ_NAME,
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
        "forecast_days": 1
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }, timeout=20)

def main():
    today = datetime.now(VN_TZ).date()
    header = f"🌤️ <b>Dự báo thời tiết hôm nay</b>\n⏰ 09:00–23:00\n\n"
    blocks = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        h = data["hourly"]
        rows = []
        for t, temp, pop, code, wind in zip(
            h["time"], h["temperature_2m"], h["precipitation_probability"],
            h["weather_code"], h["wind_speed_10m"]
        ):
            dt = datetime.fromisoformat(t)
            if dt.date() == today and 9 <= dt.hour <= 23:
                rows.append(f"{dt.hour:02d}:00 {icon(code)} {temp:.0f}°C ☔{int(pop)}% 💨{wind:.0f}km/h")

        blocks.append(f"📍 <b>{loc['name']}</b>\n" + "\n".join(rows))

    send(header + "\n\n".join(blocks))

if __name__ == "__main__":
    main()

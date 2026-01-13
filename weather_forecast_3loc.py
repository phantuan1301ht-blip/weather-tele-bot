import os
import requests
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

# =========================
# VỊ TRÍ (ĐÃ SỬA THEO YÊU CẦU)
# =========================
LOCATIONS = [
    # Nhà thờ Dĩ An – vẫn hiển thị tên là Dĩ An
    {"name": "Dĩ An (Bình Dương)", "lat": 10.9087, "lon": 106.7690},

    # Huyện Đức Thọ – Hà Tĩnh
    {"name": "Huyện Đức Thọ (Hà Tĩnh)", "lat": 18.5401307, "lon": 105.5855438},
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# =========================
# NGƯỠNG CẢNH BÁO
# =========================
RAIN_NOTICE = 30   # ≥30%: có khả năng mưa
RAIN_HIGH = 50     # ≥50%: mưa cao
RAIN_HEAVY = 70    # ≥70%: mưa lớn

HEAT_NOTICE = 30   # ≥30°C: nóng
HEAT_ALERT = 33    # ≥33°C: nắng nóng

COLD_NOTICE = 18   # ≤18°C: lạnh
COLD_ALERT = 15    # ≤15°C: rất lạnh
# =========================

def icon(code: int) -> str:
    if code == 0: return "☀️"
    if code in (1, 2): return "⛅"
    if code == 3: return "☁️"
    if code in (45, 48): return "🌫️"
    if code in (51, 53, 55): return "🌦️"
    if code in (61, 63, 65, 80, 81, 82): return "🌧️"
    if code in (95, 96, 99): return "⛈️"
    return "🌡️"

def fetch(lat: float, lon: float) -> dict:
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

def send(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }, timeout=20)
    r.raise_for_status()

def summarize_alerts(rows):
    rain_hours = [r["hour"] for r in rows if r["pop"] >= RAIN_NOTICE]
    rain_heavy = [r["hour"] for r in rows if r["pop"] >= RAIN_HEAVY]

    max_row = max(rows, key=lambda x: x["temp"])
    min_row = min(rows, key=lambda x: x["temp"])

    parts = []

    # Mưa
    if rain_heavy:
        parts.append(
            f"🌧️ <b>CẢNH BÁO MƯA LỚN</b>: {', '.join(f'{h:02d}:00' for h in rain_heavy)}"
        )
    elif rain_hours:
        parts.append(
            f"☔ <b>Có khả năng mưa</b>: {', '.join(f'{h:02d}:00' for h in rain_hours)}"
        )
    else:
        parts.append("🌧️ <b>Mưa</b>: Không có mưa đáng kể")

    # Nóng
    if max_row["temp"] >= HEAT_ALERT:
        parts.append(
            f"🔥 <b>CẢNH BÁO NẮNG NÓNG</b>: {max_row['temp']:.0f}°C lúc {max_row['hour']:02d}:00"
        )
    elif max_row["temp"] >= HEAT_NOTICE:
        parts.append(
            f"🔥 <b>Nóng nhẹ</b>: {max_row['temp']:.0f}°C lúc {max_row['hour']:02d}:00"
        )
    else:
        parts.append(
            f"🌡️ <b>Nhiệt độ cao nhất</b>: {max_row['temp']:.0f}°C"
        )

    # Lạnh
    if min_row["temp"] <= COLD_ALERT:
        parts.append(
            f"🥶 <b>CẢNH BÁO LẠNH</b>: {min_row['temp']:.0f}°C lúc {min_row['hour']:02d}:00"
        )
    elif min_row["temp"] <= COLD_NOTICE:
        parts.append(
            f"❄️ <b>Trời lạnh</b>: {min_row['temp']:.0f}°C lúc {min_row['hour']:02d}:00"
        )
    else:
        parts.append(
            f"🌙 <b>Nhiệt độ thấp nhất</b>: {min_row['temp']:.0f}°C"
        )

    return "\n".join(parts)

def main():
    now = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")
    today = datetime.now(VN_TZ).date()

    header = (
        f"🌦️ <b>DỰ BÁO THỜI TIẾT & CẢNH BÁO</b>\n"
        f"🕒 {now} (Giờ Việt Nam)\n"
        f"⏰ Khung giờ: 09:00 – 23:00\n"
    )

    blocks = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        h = data["hourly"]

        rows = []
        table = []

        for t, temp, pop, code, wind in zip(
            h["time"], h["temperature_2m"], h["precipitation_probability"],
            h["weather_code"], h["wind_speed_10m"]
        ):
            dt = datetime.fromisoformat(t)
            if dt.date() == today and 9 <= dt.hour <= 23:
                rows.append({
                    "hour": dt.hour,
                    "temp": float(temp),
                    "pop": int(pop),
                })
                table.append(
                    f"{dt.hour:02d}:00 {icon(int(code))} {temp:.0f}°C | ☔{int(pop)}% | 💨{wind:.0f}km/h"
                )

        alert = summarize_alerts(rows)

        blocks.append(
            f"\n\n📍 <b>{loc['name']}</b>\n"
            f"{alert}\n"
            f"──────────────\n"
            + "\n".join(table)
        )

    send(header + "".join(blocks))

if __name__ == "__main__":
    main()

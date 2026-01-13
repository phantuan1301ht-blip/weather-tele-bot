import os
import requests
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.getenv("MODE", "daily").strip().lower()  # "daily" hoặc "watch"

VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

LOCATIONS = [
    {"name": "Dĩ An (Bình Dương)", "lat": 10.9087, "lon": 106.7690},  # gần Nhà thờ Dĩ An
    {"name": "Huyện Đức Thọ (Hà Tĩnh)", "lat": 18.5401307, "lon": 105.5855438},
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Daily window
START_HOUR = 9
END_HOUR = 23

# Rain thresholds
RAIN_POP_NOTICE = 30
RAIN_POP_HIGH = 50
RAIN_POP_URGENT = 70  # watch mode: >70% in next hour

RAIN_MM_NOTICE = 0.2
RAIN_MM_MODERATE = 1.0
RAIN_MM_HEAVY = 5.0

# Temperature thresholds
COLD_NOTICE = 18
COLD_ALERT = 15

# Watch anti-spam (send at minute 00 or 30 only)
WATCH_SEND_MINUTES = {0, 30}

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

def send(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()

def fetch(lat: float, lon: float) -> dict:
    """
    Public API (no key). Adds current temperature for "nhiệt độ hiện tại".
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": TZ_NAME,
        "forecast_days": 1,
        "current": "temperature_2m",
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
        ]),
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_rows_today(data: dict, today_date):
    h = data.get("hourly", {})
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    pops = h.get("precipitation_probability", [])
    mms = h.get("precipitation", [])

    rows = []
    for t, temp, pop, mm in zip(times, temps, pops, mms):
        dt = datetime.fromisoformat(t)
        if dt.date() == today_date:
            rows.append({
                "dt": dt,
                "hour": dt.hour,
                "temp": float(temp) if temp is not None else 0.0,
                "pop": int(pop) if pop is not None else 0,
                "mm": float(mm) if mm is not None else 0.0,
            })
    return rows

def get_current_temp(data: dict):
    cur = data.get("current", {})
    # Open-Meteo returns "temperature_2m" and "time" under "current"
    if isinstance(cur, dict) and "temperature_2m" in cur:
        try:
            return float(cur["temperature_2m"])
        except Exception:
            return None
    return None

def compress_hour_ranges(hours):
    if not hours:
        return ""
    hours = sorted(set(hours))
    ranges = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
        else:
            ranges.append((start, prev))
            start = prev = h
    ranges.append((start, prev))

    out = []
    for s, e in ranges:
        if s == e:
            out.append(f"{s:02d}:00")
        else:
            out.append(f"{s:02d}:00–{e:02d}:00")
    return ", ".join(out)

def worst_rain(rows):
    max_mm = max((r["mm"] for r in rows), default=0.0)
    max_pop = max((r["pop"] for r in rows), default=0)

    if max_mm >= RAIN_MM_HEAVY:
        level = "MƯA TO"
    elif max_mm >= RAIN_MM_MODERATE:
        level = "MƯA ĐÁNG CHÚ Ý"
    elif max_mm >= RAIN_MM_NOTICE or max_pop >= RAIN_POP_HIGH:
        level = "MƯA KHẢ NĂNG CAO"
    elif max_pop >= RAIN_POP_NOTICE:
        level = "CÓ THỂ MƯA"
    else:
        level = "KHÔ RÁO"
    return level, max_pop, max_mm

def build_daily_block(name: str, current_temp, rows_window: list) -> str:
    max_row = max(rows_window, key=lambda x: x["temp"])
    min_row = min(rows_window, key=lambda x: x["temp"])
    tmax, hmax = max_row["temp"], max_row["hour"]
    tmin, hmin = min_row["temp"], min_row["hour"]

    rain_hours = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_NOTICE) or (r["mm"] >= RAIN_MM_NOTICE)]
    rain_hours_high = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_HIGH) or (r["mm"] >= RAIN_MM_MODERATE)]

    level, max_pop, max_mm = worst_rain(rows_window)

    # --- Pretty layout ---
    lines = []
    lines.append(f"📍 <b>{name}</b>")

    # Current temp
    if current_temp is not None:
        lines.append(f"🌡️ <b>Hiện tại</b>: {current_temp:.0f}°C")
    else:
        lines.append("🌡️ <b>Hiện tại</b>: (không lấy được)")

    # Rain summary
    if rain_hours_high:
        lines.append(f"🌧️ <b>Mưa (khả năng cao)</b>: {compress_hour_ranges(rain_hours_high)}")
        lines.append(f"📌 <b>Mưa tối đa</b>: ☔{max_pop}% | 🌧️{max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc</b>: Mang áo mưa/ô khi ra ngoài.")
    elif rain_hours:
        lines.append(f"☔ <b>Có thể mưa</b>: {compress_hour_ranges(rain_hours)}")
        lines.append(f"📌 <b>Mưa tối đa</b>: ☔{max_pop}% | 🌧️{max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc</b>: Nên mang áo mưa/ô dự phòng.")
    else:
        lines.append("🌤️ <b>Mưa</b>: Không có khung giờ mưa đáng kể.")
        lines.append("🧥 <b>Nhắc</b>: Khô ráo, nên mang áo khoác nhẹ.")

    # Max/Min
    lines.append(f"🔥 <b>Cao nhất</b>: {tmax:.0f}°C • {hmax:02d}:00")
    lines.append(f"❄️ <b>Thấp nhất</b>: {tmin:.0f}°C • {hmin:02d}:00")

    # Cold advice
    if tmin <= COLD_ALERT:
        lines.append("🧣 <b>Nhắc</b>: Trời lạnh, nhớ mặc ấm (tối/đêm).")
    elif tmin <= COLD_NOTICE:
        lines.append("🧣 <b>Nhắc</b>: Buổi tối se lạnh, nên mang thêm áo khoác.")

    # Rain level
    lines.append(f"✅ <b>Đánh giá</b>: {level}")

    return "\n".join(lines)

def next_hour_row(rows_today, now_vn):
    target_hour = (now_vn.hour + 1) % 24
    candidates = [r for r in rows_today if r["hour"] == target_hour]
    if not candidates:
        return None
    candidates.sort(key=lambda x: abs((x["dt"] - now_vn).total_seconds()))
    return candidates[0]

def build_quick_alert(now_vn, loc_name, current_temp, fc):
    cur_text = f"{current_temp:.0f}°C" if current_temp is not None else "N/A"
    return (
        f"⛈️ <b>CẢNH BÁO MƯA TRONG 1 GIỜ TỚI</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (VN)\n"
        f"{DIVIDER}\n"
        f"📍 <b>{loc_name}</b>\n"
        f"🌡️ <b>Hiện tại</b>: {cur_text}\n"
        f"⏰ <b>Dự kiến</b>: khoảng {fc['hour']:02d}:00\n"
        f"☔ <b>Khả năng mưa</b>: <b>{fc['pop']}%</b>\n"
        f"🌧️ <b>Lượng mưa</b>: <b>{fc['mm']:.1f}mm/h</b>\n"
        f"{DIVIDER}\n"
        f"🧥 <b>Nhắc</b>: Ra ngoài nhớ mang áo mưa/ô."
    )

def run_watch(now_vn):
    # Limit spam
    if now_vn.minute not in WATCH_SEND_MINUTES:
        return

    today = now_vn.date()
    alerts = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        current_temp = get_current_temp(data)
        rows_today = parse_rows_today(data, today)

        fc = next_hour_row(rows_today, now_vn)
        if not fc:
            continue

        # If next hour rain probability > 70%
        if fc["pop"] > RAIN_POP_URGENT:
            alerts.append(build_quick_alert(now_vn, loc["name"], current_temp, fc))

    if alerts:
        send("\n\n".join(alerts))

def run_daily(now_vn):
    today = now_vn.date()
    header = (
        f"🌦️ <b>DỰ BÁO & CẢNH BÁO THỜI TIẾT</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (Giờ Việt Nam)\n"
        f"⏰ Khung giờ: {START_HOUR:02d}:00–{END_HOUR:02d}:00\n"
        f"{DIVIDER}\n"
    )

    blocks = []
    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        current_temp = get_current_temp(data)
        rows_today = parse_rows_today(data, today)
        rows_window = [r for r in rows_today if START_HOUR <= r["hour"] <= END_HOUR]

        if not rows_window:
            blocks.append(f"📍 <b>{loc['name']}</b>\n⚠️ Không lấy được dữ liệu trong khung giờ yêu cầu.")
            continue

        blocks.append(build_daily_block(loc["name"], current_temp, rows_window))

    send(header + f"\n\n{DIVIDER}\n\n".join(blocks))

def main():
    now_vn = datetime.now(VN_TZ)
    if MODE == "watch":
        run_watch(now_vn)
    else:
        run_daily(now_vn)

if __name__ == "__main__":
    main()

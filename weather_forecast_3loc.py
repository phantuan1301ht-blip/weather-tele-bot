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

# Khung giờ bản tổng hợp
START_HOUR = 9
END_HOUR = 23

# Ngưỡng mưa
RAIN_POP_NOTICE = 30     # có thể mưa
RAIN_POP_HIGH = 50       # mưa cao
RAIN_POP_URGENT = 70     # mưa rất cao (cảnh báo nhanh)

RAIN_MM_NOTICE = 0.2     # mm/h: có mưa đo được
RAIN_MM_MODERATE = 1.0   # mm/h: mưa đáng chú ý
RAIN_MM_HEAVY = 5.0      # mm/h: mưa to

# Nhiệt độ
COLD_NOTICE = 18
COLD_ALERT = 15

# Chống spam trong chế độ watch:
# chỉ gửi lại tối đa mỗi 30 phút (phút 00 hoặc 30)
WATCH_SEND_MINUTES = {0, 30}

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
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": TZ_NAME,
        "forecast_days": 1,
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "precipitation",  # mm/h
        ]),
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def parse_rows_today(data: dict, today_date):
    h = data.get("hourly", {})
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    pops  = h.get("precipitation_probability", [])
    mms   = h.get("precipitation", [])

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

def build_daily_block(name: str, rows_window: list) -> str:
    max_row = max(rows_window, key=lambda x: x["temp"])
    min_row = min(rows_window, key=lambda x: x["temp"])
    tmax, hmax = max_row["temp"], max_row["hour"]
    tmin, hmin = min_row["temp"], min_row["hour"]

    rain_hours = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_NOTICE) or (r["mm"] >= RAIN_MM_NOTICE)]
    rain_hours_high = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_HIGH) or (r["mm"] >= RAIN_MM_MODERATE)]

    level, max_pop, max_mm = worst_rain(rows_window)

    lines = [f"📍 <b>{name}</b>"]

    if rain_hours_high:
        lines.append(f"🌧️ <b>Mưa (khả năng cao)</b>: {compress_hour_ranges(rain_hours_high)}")
        lines.append(f"☔ <b>Khả năng mưa tối đa</b>: {max_pop}% | 🌧️ <b>Max</b>: {max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc:</b> Mang áo mưa/ô khi ra ngoài.")
    elif rain_hours:
        lines.append(f"☔ <b>Có thể mưa</b>: {compress_hour_ranges(rain_hours)}")
        lines.append(f"☔ <b>Khả năng mưa tối đa</b>: {max_pop}% | 🌧️ <b>Max</b>: {max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc:</b> Nên mang áo mưa/ô dự phòng.")
    else:
        lines.append("🌤️ <b>Mưa</b>: Không có khung giờ mưa đáng kể.")
        lines.append("🧥 <b>Nhắc:</b> Khô ráo, nên mang áo khoác nhẹ.")

    lines.append(f"🔥 <b>Cao nhất</b>: {tmax:.0f}°C lúc {hmax:02d}:00")
    lines.append(f"❄️ <b>Thấp nhất</b>: {tmin:.0f}°C lúc {hmin:02d}:00")

    if tmin <= COLD_ALERT:
        lines.append("🧣 <b>Nhắc:</b> Trời lạnh, nhớ mặc ấm (tối/đêm).")
    elif tmin <= COLD_NOTICE:
        lines.append("🧣 <b>Nhắc:</b> Buổi tối se lạnh, nên mang thêm áo khoác.")

    lines.append(f"📌 <i>Mức dự báo mưa:</i> {level}")
    return "\n".join(lines)

def next_hour_row(rows_today, now_vn):
    # 1 giờ tới: lấy giờ kế tiếp
    target_hour = (now_vn.hour + 1) % 24
    candidates = [r for r in rows_today if r["hour"] == target_hour]
    if not candidates:
        return None
    # lấy cái gần nhất
    candidates.sort(key=lambda x: abs((x["dt"] - now_vn).total_seconds()))
    return candidates[0]

def build_quick_alert(now_vn, loc_name, fc):
    return (
        f"⛈️ <b>CẢNH BÁO MƯA SẮP XẢY RA</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (VN)\n\n"
        f"📍 <b>{loc_name}</b>\n"
        f"⏰ Trong 1 giờ tới (khoảng <b>{fc['hour']:02d}:00</b>)\n"
        f"☔ <b>Khả năng mưa</b>: <b>{fc['pop']}%</b>\n"
        f"🌧️ <b>Lượng mưa dự báo</b>: <b>{fc['mm']:.1f} mm/h</b>\n\n"
        f"🧥 <b>Nhắc:</b> Ra ngoài nhớ mang áo mưa/ô."
    )

def run_watch(now_vn):
    # chống spam: chỉ gửi ở phút 00 hoặc 30
    if now_vn.minute not in WATCH_SEND_MINUTES:
        return

    today = now_vn.date()
    alerts = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        rows_today = parse_rows_today(data, today)
        fc = next_hour_row(rows_today, now_vn)
        if not fc:
            continue

        # cảnh báo khi pop > 70%
        if fc["pop"] > RAIN_POP_URGENT:
            alerts.append(build_quick_alert(now_vn, loc["name"], fc))

    if alerts:
        send("\n\n──────────────\n\n".join(alerts))

def run_daily(now_vn):
    today = now_vn.date()
    header = (
        f"🌦️ <b>DỰ BÁO & CẢNH BÁO THỜI TIẾT</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (Giờ Việt Nam)\n"
        f"⏰ Áp dụng khung giờ: {START_HOUR:02d}:00–{END_HOUR:02d}:00\n"
    )

    blocks = []
    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        rows_today = parse_rows_today(data, today)
        rows_window = [r for r in rows_today if START_HOUR <= r["hour"] <= END_HOUR]

        if not rows_window:
            blocks.append(f"📍 <b>{loc['name']}</b>\n⚠️ Không lấy được dữ liệu trong khung giờ yêu cầu.")
            continue

        blocks.append(build_daily_block(loc["name"], rows_window))

    send(header + "\n\n" + "\n\n".join(blocks))

def main():
    now_vn = datetime.now(VN_TZ)

    if MODE == "watch":
        run_watch(now_vn)
    else:
        run_daily(now_vn)

if __name__ == "__main__":
    main()

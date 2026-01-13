import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.getenv("MODE", "daily").strip().lower()  # "daily" hoặc "watch"

VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

LOCATIONS = [
    {"name": "Dĩ An (Bình Dương)", "lat": 10.9087, "lon": 106.7690},
    {"name": "Huyện Đức Thọ (Hà Tĩnh)", "lat": 18.5401307, "lon": 105.5855438},
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

START_HOUR = 9
END_HOUR = 23

RAIN_POP_NOTICE = 30
RAIN_POP_HIGH = 50
RAIN_POP_URGENT = 70

RAIN_MM_NOTICE = 0.2
RAIN_MM_MODERATE = 1.0
RAIN_MM_HEAVY = 5.0

COLD_NOTICE = 18
COLD_ALERT = 15

ALERT_COOLDOWN_SECONDS = 3 * 60 * 60  # 3 giờ / MỖI địa điểm

QUIET_START_HOUR = 21
QUIET_END_HOUR = 7
QUIET_END_MINUTE = 30

POST_DAILY_ALERT_DELAY_SECONDS = 10
WATCH_BLOCK_AFTER_DAILY_SECONDS = 180  # chặn watch trùng sau daily

# Ban đêm: 18:00 -> 05:59
NIGHT_START_HOUR = 18
NIGHT_END_HOUR = 6

STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "last_alert.json"

DIVIDER = "──────────────"


# ========= Helpers: Rain intensity language =========
def rain_intensity(mm_per_hour: float) -> str:
    # Phân loại "chuẩn thời tiết" theo mm/giờ
    if mm_per_hour < 0.2:
        return "không mưa"
    if mm_per_hour < 0.5:
        return "mưa phùn"
    if mm_per_hour < 2.0:
        return "mưa nhỏ"
    if mm_per_hour < 5.0:
        return "mưa vừa"
    if mm_per_hour < 10.0:
        return "mưa to"
    return "mưa rất to"


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
        "current": "temperature_2m",
        "hourly": "temperature_2m,precipitation_probability,precipitation",
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_current_temp(data: dict):
    cur = data.get("current", {})
    try:
        return float(cur.get("temperature_2m"))
    except Exception:
        return None


def parse_rows_today(data: dict, today_date):
    h = data.get("hourly", {})
    rows = []
    for t, temp, pop, mm in zip(
        h.get("time", []),
        h.get("temperature_2m", []),
        h.get("precipitation_probability", []),
        h.get("precipitation", []),
    ):
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
    s = p = hours[0]
    for h in hours[1:]:
        if h == p + 1:
            p = h
        else:
            ranges.append((s, p))
            s = p = h
    ranges.append((s, p))
    out = []
    for a, b in ranges:
        out.append(f"{a:02d}:00" if a == b else f"{a:02d}:00–{b:02d}:00")
    return ", ".join(out)


def worst_rain(rows):
    max_mm = max((r["mm"] for r in rows), default=0.0)
    max_pop = max((r["pop"] for r in rows), default=0)
    intensity = rain_intensity(max_mm)

    if max_mm >= 10:
        level = "MƯA RẤT TO"
    elif max_mm >= RAIN_MM_HEAVY:
        level = "MƯA TO"
    elif max_mm >= RAIN_MM_MODERATE:
        level = "MƯA VỪA"
    elif max_mm >= RAIN_MM_NOTICE or max_pop >= RAIN_POP_HIGH:
        level = "MƯA KHẢ NĂNG CAO"
    elif max_pop >= RAIN_POP_NOTICE:
        level = "CÓ THỂ MƯA"
    else:
        level = "KHÔ RÁO"
    return level, max_pop, max_mm, intensity


def build_daily_block(name: str, current_temp, rows_window: list) -> str:
    max_row = max(rows_window, key=lambda x: x["temp"])
    min_row = min(rows_window, key=lambda x: x["temp"])
    tmax, hmax = max_row["temp"], max_row["hour"]
    tmin, hmin = min_row["temp"], min_row["hour"]

    # giờ có khả năng mưa
    rain_hours = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_NOTICE) or (r["mm"] >= RAIN_MM_NOTICE)]
    rain_hours_high = [r["hour"] for r in rows_window if (r["pop"] >= RAIN_POP_HIGH) or (r["mm"] >= RAIN_MM_MODERATE)]

    level, max_pop, max_mm, intensity = worst_rain(rows_window)
    cur_text = f"{current_temp:.0f}°C" if current_temp is not None else "N/A"

    lines = []
    lines.append(f"📍 <b>{name}</b>")
    lines.append(f"🌡️ <b>Hiện tại</b>: {cur_text}")

    # Dòng MƯA chuẩn + rõ + có mô tả
    if rain_hours_high:
        lines.append(f"🔴 <b>MƯA</b>: Khả năng cao ({compress_hour_ranges(rain_hours_high)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h • <i>{intensity}</i>")
        lines.append("🧥 <b>Nhắc</b>: Nên mang áo mưa/ô dự phòng.")
    elif rain_hours:
        lines.append(f"🔴 <b>MƯA</b>: Có thể mưa ({compress_hour_ranges(rain_hours)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h • <i>{intensity}</i>")
        lines.append("🧥 <b>Nhắc</b>: Mang áo mưa/ô khi ra ngoài.")
    else:
        lines.append("🟢 <b>MƯA</b>: Không có mưa đáng kể.")
        lines.append("🧥 <b>Nhắc</b>: Khô ráo, mang áo khoác nhẹ.")

    lines.append(f"🔥 <b>Cao nhất</b>: {tmax:.0f}°C • {hmax:02d}:00")
    lines.append(f"❄️ <b>Thấp nhất</b>: {tmin:.0f}°C • {hmin:02d}:00")

    if tmin <= COLD_ALERT:
        lines.append("🧣 <b>Nhắc</b>: Trời lạnh, nhớ mặc ấm.")
    elif tmin <= COLD_NOTICE:
        lines.append("🧣 <b>Nhắc</b>: Tối se lạnh, mang thêm áo khoác.")

    lines.append(f"✅ <b>Đánh giá</b>: {level}")
    return "\n".join(lines)


def is_quiet_time(now_vn: datetime) -> bool:
    h, m = now_vn.hour, now_vn.minute
    if h > QUIET_START_HOUR:
        return True
    if h == QUIET_START_HOUR:
        return True
    if h < QUIET_END_HOUR:
        return True
    if h == QUIET_END_HOUR and m < QUIET_END_MINUTE:
        return True
    return False


def is_night_hour(hour: int) -> bool:
    return (hour >= NIGHT_START_HOUR) or (hour < NIGHT_END_HOUR)


def alert_prefix_for_hour(hour: int) -> str:
    return "🔴🌙🌧️" if is_night_hour(hour) else "🔴🌧️"


def alert_hint_for_hour(hour: int, intensity: str) -> str:
    # Nhắc theo cường độ + ban ngày/đêm
    if intensity in ("mưa to", "mưa rất to"):
        base = "⚠️ <b>Lưu ý</b>: Có thể mưa lớn — hạn chế di chuyển, chú ý ngập/trơn trượt."
    elif intensity in ("mưa vừa", "mưa nhỏ", "mưa phùn"):
        base = "🚦 <b>Lưu ý</b>: Đường có thể trơn — chạy chậm, an toàn."
    else:
        base = "🚦 <b>Lưu ý</b>: Di chuyển an toàn."

    if is_night_hour(hour):
        return "🌙 " + base
    return base


# ---------- STATE: cooldown theo từng địa điểm ----------
def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"alerts": {}, "last_daily_ts": 0}


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def can_send_alert(state: dict, loc_key: str, now_ts: int) -> bool:
    # loc_key tách riêng từng địa điểm => không ảnh hưởng nhau
    alerts = state.setdefault("alerts", {})
    last_ts = alerts.get(loc_key)
    if last_ts is None:
        return True
    try:
        last_ts = int(last_ts)
    except Exception:
        return True
    return (now_ts - last_ts) >= ALERT_COOLDOWN_SECONDS


def mark_sent(state: dict, loc_key: str, now_ts: int):
    state.setdefault("alerts", {})[loc_key] = int(now_ts)


def get_row_by_hour(rows_today, hour: int):
    for r in rows_today:
        if r["hour"] == hour:
            return r
    return None


def detect_rain_now_and_next_hour(rows_today, now_vn):
    # NOW
    now_row = get_row_by_hour(rows_today, now_vn.hour)
    raining_now = False
    now_mm = 0.0
    if now_row:
        now_mm = now_row["mm"]
        if now_mm >= RAIN_MM_NOTICE:
            raining_now = True

    # NEXT HOUR
    next_hour = (now_vn.hour + 1) % 24
    next_row = get_row_by_hour(rows_today, next_hour)
    likely_next_hour = False
    next_pop = 0
    next_mm = 0.0
    if next_row:
        next_pop = next_row["pop"]
        next_mm = next_row["mm"]
        if (next_pop > RAIN_POP_URGENT) or (next_mm >= RAIN_MM_MODERATE):
            likely_next_hour = True

    return {
        "raining_now": raining_now,
        "now_mm": now_mm,
        "likely_next_hour": likely_next_hour,
        "next_hour": next_hour,
        "next_pop": next_pop,
        "next_mm": next_mm,
    }


# ---------- ALERT messages (chuẩn ngôn ngữ thời tiết + cường độ) ----------
def build_alert_raining_now(loc_name: str, now_hour: int, now_mm: float) -> str:
    prefix = alert_prefix_for_hour(now_hour)
    intensity = rain_intensity(now_mm)
    hint = alert_hint_for_hour(now_hour, intensity)
    return (
        f"{prefix} <b>CẢNH BÁO TRỜI ĐANG MƯA</b>\n"
        f"🚨 <b>HÃY CHUẨN BỊ ÁO MƯA TRƯỚC KHI RA ĐƯỜNG</b>\n"
        f"{DIVIDER}\n"
        f"📍 <b>{loc_name}</b>\n"
        f"⏰ <b>Thời điểm</b>: <b>{now_hour:02d}:00</b>\n"
        f"🌧️ <b>Tình trạng</b>: <b>ĐANG MƯA</b> • <i>{intensity}</i>\n"
        f"💧 <b>Lượng mưa</b>: <b>{now_mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def build_alert_next_hour(loc_name: str, next_hour: int, pop: int, mm: float) -> str:
    prefix = alert_prefix_for_hour(next_hour)
    intensity = rain_intensity(mm)
    hint = alert_hint_for_hour(next_hour, intensity)
    return (
        f"{prefix} <b>CẢNH BÁO CÓ MƯA VÀO 1 GIỜ TỚI</b>\n"
        f"⚠️ <b>NÊN CHUẨN BỊ ÁO MƯA / Ô DÙ</b>\n"
        f"{DIVIDER}\n"
        f"📍 <b>{loc_name}</b>\n"
        f"⏰ <b>Dự kiến</b>: <b>{next_hour:02d}:00</b>\n"
        f"☔ <b>Khả năng mưa</b>: <b>{pop}%</b>\n"
        f"🌧️ <b>Dạng mưa</b>: <i>{intensity}</i> • <b>{mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def run_watch(now_vn):
    if is_quiet_time(now_vn):
        return

    state = load_state()
    now_ts = int(now_vn.timestamp())

    # chặn watch trùng sau daily (nhưng không khóa theo địa điểm)
    last_daily_ts = int(state.get("last_daily_ts", 0) or 0)
    if last_daily_ts and (now_ts - last_daily_ts) < WATCH_BLOCK_AFTER_DAILY_SECONDS:
        return

    today = now_vn.date()
    alerts = []

    # Mỗi địa điểm tự quyết định gửi hay không (cooldown riêng)
    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        rows_today = parse_rows_today(data, today)
        cond = detect_rain_now_and_next_hour(rows_today, now_vn)

        if not (cond["raining_now"] or cond["likely_next_hour"]):
            continue

        loc_key = loc["name"]
        if not can_send_alert(state, loc_key, now_ts):
            continue

        if cond["raining_now"]:
            alerts.append(build_alert_raining_now(loc["name"], now_vn.hour, cond["now_mm"]))
        else:
            alerts.append(build_alert_next_hour(loc["name"], cond["next_hour"], cond["next_pop"], cond["next_mm"]))

        mark_sent(state, loc_key, now_ts)

    if alerts:
        send(f"\n\n{DIVIDER}\n\n".join(alerts))
        save_state(state)


def run_daily(now_vn):
    today = now_vn.date()

    header = (
        f"🌦️ <b>DỰ BÁO & CẢNH BÁO THỜI TIẾT</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (Giờ Việt Nam)\n"
        f"⏰ <b>Khung giờ</b>: {START_HOUR:02d}:00–{END_HOUR:02d}:00\n"
        f"{DIVIDER}\n"
    )

    blocks = []
    daily_data = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        current_temp = get_current_temp(data)
        rows_today = parse_rows_today(data, today)
        rows_window = [r for r in rows_today if START_HOUR <= r["hour"] <= END_HOUR]

        if rows_window:
            blocks.append(build_daily_block(loc["name"], current_temp, rows_window))
        else:
            blocks.append(f"📍 <b>{loc['name']}</b>\n⚠️ Không lấy được dữ liệu.")

        daily_data.append((loc, rows_today))

    send(header + f"\n{DIVIDER}\n".join(blocks))

    # ghi dấu daily vừa chạy
    state = load_state()
    state["last_daily_ts"] = int(datetime.now(VN_TZ).timestamp())
    save_state(state)

    # Sau daily 10s: nếu đang mưa / sắp mưa thì gửi alert (cooldown riêng theo địa điểm)
    time.sleep(POST_DAILY_ALERT_DELAY_SECONDS)
    now2 = datetime.now(VN_TZ)
    if is_quiet_time(now2):
        return

    state = load_state()
    now_ts = int(now2.timestamp())
    alerts = []

    for loc, rows_today in daily_data:
        cond = detect_rain_now_and_next_hour(rows_today, now2)
        if not (cond["raining_now"] or cond["likely_next_hour"]):
            continue

        loc_key = loc["name"]
        if not can_send_alert(state, loc_key, now_ts):
            continue

        if cond["raining_now"]:
            alerts.append(build_alert_raining_now(loc["name"], now2.hour, cond["now_mm"]))
        else:
            alerts.append(build_alert_next_hour(loc["name"], cond["next_hour"], cond["next_pop"], cond["next_mm"]))

        mark_sent(state, loc_key, now_ts)

    if alerts:
        send(f"\n\n{DIVIDER}\n\n".join(alerts))
        save_state(state)


def main():
    now_vn = datetime.now(VN_TZ)
    if MODE == "watch":
        run_watch(now_vn)
    else:
        run_daily(now_vn)


if __name__ == "__main__":
    main()

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =========================
# TELEGRAM (GitHub Secrets)
# =========================
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.getenv("MODE", "daily").strip().lower()  # "daily" hoặc "watch"

# =========================
# TIMEZONE
# =========================
VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

# =========================
# LOCATIONS
# =========================
LOCATIONS = [
    {"name": "Dĩ An (Bình Dương)", "lat": 10.9087, "lon": 106.7690},
    {"name": "Huyện Đức Thọ (Hà Tĩnh)", "lat": 18.5401307, "lon": 105.5855438},
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# =========================
# DAILY WINDOW
# =========================
START_HOUR = 9
END_HOUR = 23

# =========================
# THRESHOLDS
# =========================
RAIN_POP_NOTICE = 30
RAIN_POP_HIGH = 50
RAIN_POP_URGENT = 70   # sắp mưa 1h tới (watch): >70%

RAIN_MM_NOTICE = 0.2   # coi như có mưa
RAIN_MM_MODERATE = 1.0
RAIN_MM_HEAVY = 5.0

COLD_NOTICE = 18
COLD_ALERT = 15

# =========================
# COOLDOWN & QUIET HOURS
# =========================
ALERT_COOLDOWN_SECONDS = 3 * 60 * 60  # 3 giờ

# Không gửi cảnh báo trong 21:00 -> 07:30
QUIET_START_HOUR = 21
QUIET_END_HOUR = 7
QUIET_END_MINUTE = 30

# Sau daily nếu có mưa/ sắp mưa thì gửi alert sau 10s
POST_DAILY_ALERT_DELAY_SECONDS = 10

# =========================
# NIGHT ICON RULE
# =========================
# Ban đêm: 18:00 -> 05:59 dùng 🌙
NIGHT_START_HOUR = 18
NIGHT_END_HOUR = 6  # đến trước 06:00

# =========================
# STATE (cooldown memory)
# =========================
STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "last_alert.json"

DIVIDER = "──────────────"


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
    # Public API, no key
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


def get_current_temp(data: dict):
    cur = data.get("current", {})
    if isinstance(cur, dict) and "temperature_2m" in cur:
        try:
            return float(cur["temperature_2m"])
        except Exception:
            return None
    return None


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
    cur_text = f"{current_temp:.0f}°C" if current_temp is not None else "N/A"

    lines = []
    lines.append(f"📍 <b>{name}</b>")
    lines.append(f"🌡️ <b>Hiện tại</b>: {cur_text}")

    # 🔴 chỉ khi có khả năng mưa
    if rain_hours_high:
        lines.append(f"🔴 <b>MƯA</b>: Khả năng cao ({compress_hour_ranges(rain_hours_high)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc</b>: Mang áo mưa/ô.")
    elif rain_hours:
        lines.append(f"🔴 <b>MƯA</b>: Có thể mưa ({compress_hour_ranges(rain_hours)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h")
        lines.append("🧥 <b>Nhắc</b>: Nên mang áo mưa/ô dự phòng.")
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


# ---------- quiet hours ----------
def is_quiet_time(now_vn: datetime) -> bool:
    h, m = now_vn.hour, now_vn.minute
    # Quiet: 21:00 -> trước 07:30
    if h > QUIET_START_HOUR:
        return True
    if h == QUIET_START_HOUR:
        return True
    if h < QUIET_END_HOUR:
        return True
    if h == QUIET_END_HOUR and m < QUIET_END_MINUTE:
        return True
    return False


# ---------- night icon ----------
def is_night_hour(hour: int) -> bool:
    # Ban đêm: 18:00 -> 23:59 OR 00:00 -> 05:59
    return (hour >= NIGHT_START_HOUR) or (hour < NIGHT_END_HOUR)


def alert_prefix_for_hour(hour: int) -> str:
    # Chỉ đổi icon cho “ban đêm”
    return "🔴🌙🌧️" if is_night_hour(hour) else "🔴🌧️"


def alert_hint_for_hour(hour: int) -> str:
    # Nhắc nhẹ nhàng theo thời điểm
    return "🌙 <b>Lưu ý</b>: Trời tối, đường dễ trơn — đi chậm, an toàn." if is_night_hour(hour) else "🚦 <b>Lưu ý</b>: Đường có thể trơn — chạy chậm, an toàn."


# ---------- state (cooldown) ----------
def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def can_send_alert(state: dict, loc_key: str, now_ts: int) -> bool:
    last_ts = state.get(loc_key)
    if last_ts is None:
        return True
    try:
        last_ts = int(last_ts)
    except Exception:
        return True
    return (now_ts - last_ts) >= ALERT_COOLDOWN_SECONDS


def mark_sent(state: dict, loc_key: str, now_ts: int):
    state[loc_key] = int(now_ts)


# ---------- alert conditions ----------
def get_row_by_hour(rows_today, hour: int):
    for r in rows_today:
        if r["hour"] == hour:
            return r
    return None


def detect_rain_now_and_next_hour(rows_today, now_vn):
    # NOW: dùng lượng mưa của giờ hiện tại
    now_row = get_row_by_hour(rows_today, now_vn.hour)
    raining_now = False
    now_mm = 0.0
    now_pop = 0
    if now_row:
        now_mm = now_row["mm"]
        now_pop = now_row["pop"]
        if now_mm >= RAIN_MM_NOTICE:
            raining_now = True

    # NEXT HOUR: pop > 70% (hoặc mm next hour >= 1.0 để chắc hơn)
    next_hour = (now_vn.hour + 1) % 24
    next_row = get_row_by_hour(rows_today, next_hour)
    next_pop = 0
    next_mm = 0.0
    likely_next_hour = False
    if next_row:
        next_pop = next_row["pop"]
        next_mm = next_row["mm"]
        if (next_pop > RAIN_POP_URGENT) or (next_mm >= RAIN_MM_MODERATE):
            likely_next_hour = True

    return {
        "raining_now": raining_now,
        "now_mm": now_mm,
        "now_pop": now_pop,
        "likely_next_hour": likely_next_hour,
        "next_hour": next_hour,
        "next_pop": next_pop,
        "next_mm": next_mm,
    }


# ---------- alert message formats (UPDATED: night icons) ----------
def build_alert_raining_now(loc_name: str, now_hour: int, now_mm: float) -> str:
    prefix = alert_prefix_for_hour(now_hour)
    hint = alert_hint_for_hour(now_hour)
    return (
        f"{prefix} <b>CẢNH BÁO TRỜI ĐANG MƯA</b>\n"
        f"🚨 <b>HÃY CHUẨN BỊ ÁO MƯA TRƯỚC KHI RA ĐƯỜNG</b>\n"
        f"{DIVIDER}\n"
        f"📍 <b>{loc_name}</b>\n"
        f"⏰ <b>Thời điểm</b>: <b>{now_hour:02d}:00</b>\n"
        f"🌧️ <b>Tình trạng</b>: <b>ĐANG MƯA</b>\n"
        f"💧 <b>Lượng mưa</b>: <b>{now_mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def build_alert_next_hour(loc_name: str, next_hour: int, pop: int, mm: float) -> str:
    prefix = alert_prefix_for_hour(next_hour)
    hint = alert_hint_for_hour(next_hour)
    return (
        f"{prefix} <b>CẢNH BÁO CÓ MƯA VÀO 1 GIỜ TỚI</b>\n"
        f"⚠️ <b>NÊN CHUẨN BỊ ÁO MƯA / Ô DÙ</b>\n"
        f"{DIVIDER}\n"
        f"📍 <b>{loc_name}</b>\n"
        f"⏰ <b>Dự kiến</b>: <b>{next_hour:02d}:00</b>\n"
        f"☔ <b>Khả năng mưa</b>: <b>{pop}%</b>\n"
        f"🌧️ <b>Lượng mưa</b>: <b>{mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def run_watch(now_vn):
    # Watch chạy liên tục, nhưng không gửi trong giờ ngủ
    if is_quiet_time(now_vn):
        return

    today = now_vn.date()
    now_ts = int(now_vn.timestamp())

    state = load_state()
    alerts = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        rows_today = parse_rows_today(data, today)
        cond = detect_rain_now_and_next_hour(rows_today, now_vn)

        loc_key = loc["name"]

        # ưu tiên: đang mưa -> cảnh báo đang mưa
        should_alert = cond["raining_now"] or cond["likely_next_hour"]
        if not should_alert:
            continue

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
    daily_data = []  # giữ lại rows để check alert sau 10s

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

    # 1) gửi daily
    send(header + f"\n{DIVIDER}\n".join(blocks))

    # 2) Sau daily 10 giây, nếu đang mưa / sắp mưa thì gửi cảnh báo
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

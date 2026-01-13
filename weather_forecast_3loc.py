import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =========================
# ENV
# =========================
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.getenv("MODE", "daily").strip().lower()  # daily | watch

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
RAIN_POP_URGENT = 70

RAIN_MM_NOTICE = 0.2
RAIN_MM_MODERATE = 1.0

COLD_NOTICE = 18
COLD_ALERT = 15

# ✅ 3h cooldown per location
ALERT_COOLDOWN_SECONDS = 3 * 60 * 60  # 3 hours

# Quiet time for watch
QUIET_START_HOUR = 21
QUIET_END_HOUR = 7
QUIET_END_MINUTE = 30

POST_DAILY_ALERT_DELAY_SECONDS = 10

# ✅ After DAILY, WATCH must wait >= 3 hours before any first alert
WATCH_BLOCK_AFTER_DAILY_SECONDS = 3 * 60 * 60  # 3 hours

NIGHT_START_HOUR = 18
NIGHT_END_HOUR = 6

STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "last_alert.json"

DIVIDER = "──────────────"
BIG_DIV = "━━━━━━━━━━━━━━━━━━━━"


def rain_intensity(mm_per_hour: float) -> str:
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


def is_night_hour(hour: int) -> bool:
    return (hour >= NIGHT_START_HOUR) or (hour < NIGHT_END_HOUR)


def alert_prefix_for_hour(hour: int) -> str:
    return "🔴🌙🌧️" if is_night_hour(hour) else "🔴🌧️"


def alert_hint_for_hour(hour: int, intensity: str) -> str:
    if intensity in ("mưa to", "mưa rất to"):
        base = "⚠️ <b>Lưu ý</b>: Có thể mưa lớn — hạn chế di chuyển, chú ý ngập/trơn."
    else:
        base = "🚦 <b>Lưu ý</b>: Đường có thể trơn — chạy chậm, an toàn."
    return ("🌙 " if is_night_hour(hour) else "") + base


def fmt_location_title(name: str) -> str:
    return f"📍 <b>📌 {name.upper()}</b>"


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


def get_row_by_hour(rows_today, hour: int):
    for r in rows_today:
        if r["hour"] == hour:
            return r
    return None


def compress_hour_ranges(hours):
    """e.g. [11,12,13,16,17] -> '11:00–13:00, 16:00–17:00' """
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


def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"alerts_ts": {}, "last_event_key": {}, "last_daily_ts": 0}


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def can_send_by_cooldown(state: dict, loc_key: str, now_ts: int) -> bool:
    last_ts = state.setdefault("alerts_ts", {}).get(loc_key)
    if last_ts is None:
        return True
    try:
        last_ts = int(last_ts)
    except Exception:
        return True
    return (now_ts - last_ts) >= ALERT_COOLDOWN_SECONDS


def mark_sent(state: dict, loc_key: str, now_ts: int, event_key: str):
    state.setdefault("alerts_ts", {})[loc_key] = int(now_ts)
    state.setdefault("last_event_key", {})[loc_key] = event_key


def is_duplicate_event(state: dict, loc_key: str, event_key: str) -> bool:
    return state.setdefault("last_event_key", {}).get(loc_key) == event_key


def detect_rain_now_and_next_hour(rows_today, now_vn):
    now_row = get_row_by_hour(rows_today, now_vn.hour)
    raining_now = False
    now_mm = 0.0
    if now_row:
        now_mm = now_row["mm"]
        if now_mm >= RAIN_MM_NOTICE:
            raining_now = True

    next_hour = (now_vn.hour + 1) % 24
    next_row = get_row_by_hour(rows_today, next_hour)
    likely_next_hour = False
    next_pop = 0
    next_mm = 0.0
    if next_row:
        next_pop = next_row["pop"]
        next_mm = next_row["mm"]
        if (next_pop >= RAIN_POP_URGENT) or (next_mm >= RAIN_MM_MODERATE):
            likely_next_hour = True

    return {
        "raining_now": raining_now,
        "now_mm": now_mm,
        "data_hour_now": (now_row["hour"] if now_row else now_vn.hour),
        "likely_next_hour": likely_next_hour,
        "next_hour": next_hour,
        "next_pop": next_pop,
        "next_mm": next_mm,
        "data_hour_next": (next_row["hour"] if next_row else next_hour),
    }


def build_alert_raining_now(loc_name: str, now_vn: datetime, now_mm: float, data_hour: int) -> str:
    send_time = now_vn.strftime("%Y-%m-%d %H:%M")
    prefix = alert_prefix_for_hour(now_vn.hour)
    intensity = rain_intensity(now_mm)
    hint = alert_hint_for_hour(now_vn.hour, intensity)

    return (
        f"{prefix} <b>CẢNH BÁO TRỜI ĐANG MƯA</b>\n"
        f"🚨 <b>HÃY CHUẨN BỊ ÁO MƯA TRƯỚC KHI RA ĐƯỜNG</b>\n"
        f"🕒 <b>Gửi lúc</b>: {send_time}\n"
        f"{DIVIDER}\n"
        f"{fmt_location_title(loc_name)}\n"
        f"⏰ <b>Dữ liệu</b>: <b>{data_hour:02d}:00</b>\n"
        f"🌧️ <b>Tình trạng</b>: <b>ĐANG MƯA</b> • <i>{intensity}</i>\n"
        f"💧 <b>Lượng mưa</b>: <b>{now_mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def build_alert_next_hour(loc_name: str, now_vn: datetime, next_hour: int, pop: int, mm: float, data_hour: int) -> str:
    send_time = now_vn.strftime("%Y-%m-%d %H:%M")
    prefix = alert_prefix_for_hour(next_hour)
    intensity = rain_intensity(mm)
    hint = alert_hint_for_hour(next_hour, intensity)

    return (
        f"{prefix} <b>CẢNH BÁO CÓ MƯA VÀO 1 GIỜ TỚI</b>\n"
        f"⚠️ <b>NÊN CHUẨN BỊ ÁO MƯA / Ô DÙ</b>\n"
        f"🕒 <b>Gửi lúc</b>: {send_time}\n"
        f"{DIVIDER}\n"
        f"{fmt_location_title(loc_name)}\n"
        f"⏰ <b>Dự kiến</b>: <b>{next_hour:02d}:00</b>\n"
        f"⏰ <b>Dữ liệu</b>: <b>{data_hour:02d}:00</b>\n"
        f"☔ <b>Khả năng mưa</b>: <b>{pop}%</b>\n"
        f"🌧️ <b>Dạng mưa</b>: <i>{intensity}</i> • <b>{mm:.1f} mm/giờ</b>\n"
        f"{hint}"
    )


def build_daily_block(name: str, current_temp, rows_window: list, now_status_line: str) -> str:
    max_row = max(rows_window, key=lambda x: x["temp"])
    min_row = min(rows_window, key=lambda x: x["temp"])
    tmax, hmax = max_row["temp"], max_row["hour"]
    tmin, hmin = min_row["temp"], min_row["hour"]

    # ✅ FIX: gom nhiều khung giờ mưa rõ ràng (không chỉ 1 giờ)
    rain_hours = []
    rain_hours_high = []
    for r in rows_window:
        if (r["mm"] >= RAIN_MM_MODERATE) or (r["pop"] >= RAIN_POP_HIGH):
            rain_hours_high.append(r["hour"])
        elif (r["mm"] >= RAIN_MM_NOTICE) or (r["pop"] >= RAIN_POP_NOTICE):
            rain_hours.append(r["hour"])

    max_mm = max((r["mm"] for r in rows_window), default=0.0)
    max_pop = max((r["pop"] for r in rows_window), default=0)
    intensity = rain_intensity(max_mm)

    if max_mm >= 10:
        level = "MƯA RẤT TO"
    elif max_mm >= 5:
        level = "MƯA TO"
    elif max_mm >= 1:
        level = "MƯA VỪA"
    elif max_mm >= RAIN_MM_NOTICE or max_pop >= RAIN_POP_HIGH:
        level = "MƯA KHẢ NĂNG CAO"
    elif max_pop >= RAIN_POP_NOTICE:
        level = "CÓ THỂ MƯA"
    else:
        level = "KHÔ RÁO"

    cur_text = f"{current_temp:.0f}°C" if current_temp is not None else "N/A"

    lines = []
    lines.append(fmt_location_title(name))
    lines.append(f"🌡️ <b>Hiện tại</b>: {cur_text}")
    lines.append(now_status_line)

    if rain_hours_high:
        lines.append(f"🔴 <b>MƯA</b>: Khả năng cao ({compress_hour_ranges(rain_hours_high)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h • <i>{intensity}</i>")
        lines.append("🧥 <b>Nhắc</b>: Mang áo mưa/ô khi ra ngoài.")
    elif rain_hours:
        lines.append(f"🟠 <b>MƯA</b>: Có thể mưa ({compress_hour_ranges(rain_hours)})")
        lines.append(f"☔ <b>Tối đa</b>: {max_pop}% | 🌧️ {max_mm:.1f}mm/h • <i>{intensity}</i>")
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


def run_watch(now_vn):
    if is_quiet_time(now_vn):
        return

    state = load_state()
    now_ts = int(now_vn.timestamp())

    # ✅ block watch for 3h after daily
    last_daily_ts = int(state.get("last_daily_ts", 0) or 0)
    if last_daily_ts and (now_ts - last_daily_ts) < WATCH_BLOCK_AFTER_DAILY_SECONDS:
        return

    today = now_vn.date()
    alerts = []

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        rows_today = parse_rows_today(data, today)
        cond = detect_rain_now_and_next_hour(rows_today, now_vn)

        if not (cond["raining_now"] or cond["likely_next_hour"]):
            continue

        loc_key = loc["name"]

        # ✅ per-location cooldown 3h
        if not can_send_by_cooldown(state, loc_key, now_ts):
            continue

        if cond["raining_now"]:
            event_key = f"{today.isoformat()}|{loc_key}|RAINING|{now_vn.hour:02d}"
            if is_duplicate_event(state, loc_key, event_key):
                continue
            alerts.append(build_alert_raining_now(loc["name"], now_vn, cond["now_mm"], cond["data_hour_now"]))
            mark_sent(state, loc_key, now_ts, event_key)
        else:
            event_key = f"{today.isoformat()}|{loc_key}|NEXT1H|{cond['next_hour']:02d}"
            if is_duplicate_event(state, loc_key, event_key):
                continue
            alerts.append(build_alert_next_hour(loc["name"], now_vn, cond["next_hour"], cond["next_pop"], cond["next_mm"], cond["data_hour_next"]))
            mark_sent(state, loc_key, now_ts, event_key)

    if alerts:
        send(f"\n\n{BIG_DIV}\n\n".join(alerts))
        save_state(state)


def run_daily(now_vn):
    today = now_vn.date()
    header = (
        f"🌦️ <b>DỰ BÁO & CẢNH BÁO THỜI TIẾT</b>\n"
        f"🕒 {now_vn.strftime('%Y-%m-%d %H:%M')} (Giờ Việt Nam)\n"
        f"⏰ <b>Khung giờ</b>: {START_HOUR:02d}:00–{END_HOUR:02d}:00\n"
        f"{BIG_DIV}\n"
    )

    blocks = []
    state = load_state()
    now_ts_daily = int(now_vn.timestamp())

    for loc in LOCATIONS:
        data = fetch(loc["lat"], loc["lon"])
        current_temp = get_current_temp(data)
        rows_today = parse_rows_today(data, today)
        rows_window = [r for r in rows_today if START_HOUR <= r["hour"] <= END_HOUR]

        now_row = get_row_by_hour(rows_today, now_vn.hour)
        now_mm = float(now_row["mm"]) if now_row else 0.0
        now_intensity = rain_intensity(now_mm)
        if now_mm >= RAIN_MM_NOTICE:
            now_status_line = f"🔴 <b>TRẠNG THÁI</b>: <b>ĐANG MƯA</b> • <i>{now_intensity}</i> • <b>{now_mm:.1f} mm/giờ</b>"
        else:
            now_status_line = "🟢 <b>TRẠNG THÁI</b>: <b>KHÔ RÁO</b>"

        if rows_window:
            blocks.append(build_daily_block(loc["name"], current_temp, rows_window, now_status_line))
        else:
            blocks.append(f"{fmt_location_title(loc['name'])}\n⚠️ Không lấy được dữ liệu.")

        # ✅ daily counts as an alert for cooldown per location (if raining/likely soon)
        cond = detect_rain_now_and_next_hour(rows_today, now_vn)
        loc_key = loc["name"]
        if cond["raining_now"]:
            event_key = f"{today.isoformat()}|{loc_key}|RAINING|{now_vn.hour:02d}"
            mark_sent(state, loc_key, now_ts_daily, event_key)
        elif cond["likely_next_hour"]:
            event_key = f"{today.isoformat()}|{loc_key}|NEXT1H|{cond['next_hour']:02d}"
            mark_sent(state, loc_key, now_ts_daily, event_key)

    send(header + f"\n{BIG_DIV}\n".join(blocks))

    # ✅ stamp daily time so watch is blocked for 3h
    state["last_daily_ts"] = int(now_vn.timestamp())
    save_state(state)

    time.sleep(POST_DAILY_ALERT_DELAY_SECONDS)


def main():
    now_vn = datetime.now(VN_TZ)
    if MODE == "watch":
        run_watch(now_vn)
    else:
        run_daily(now_vn)


if __name__ == "__main__":
    main()

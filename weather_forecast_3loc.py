import os
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =========================
# ENV
# =========================
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

WORKER_BASE_URL = os.getenv("WORKER_BASE_URL", "").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "phone1").strip()

# =========================
# TIMEZONE (VN)
# =========================
VN_TZ = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Ho_Chi_Minh"

# =========================
# RUN WINDOW (VN)
# =========================
START_HOUR = 7
START_MIN = 30
END_HOUR = 21
END_MIN = 0

# =========================
# WEATHER
# =========================
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# =========================
# THRESHOLDS (tùy bạn chỉnh)
# =========================
RAIN_POP_URGENT = 70      # % mưa cao
RAIN_MM_NOTICE = 0.2      # mm/h coi là mưa
RAIN_MM_MODERATE = 1.0    # mm/h coi là mưa đáng kể

# =========================
# COOLDOWN (3 giờ)
# =========================
ALERT_COOLDOWN_SECONDS = 3 * 60 * 60

STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "state.json"


def in_run_window(now_vn: datetime) -> bool:
    """Chỉ chạy trong 07:30 -> 21:00 (VN)"""
    h, m = now_vn.hour, now_vn.minute

    after_start = (h > START_HOUR) or (h == START_HOUR and m >= START_MIN)
    before_end = (h < END_HOUR) or (h == END_HOUR and m <= END_MIN)
    return after_start and before_end


def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "last_alert_ts": 0,
        "last_event_key": ""
    }


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def send_telegram(text: str) -> None:
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


def fetch_gps_from_worker() -> dict:
    if not WORKER_BASE_URL:
        raise RuntimeError("WORKER_BASE_URL chưa set")

    url = f"{WORKER_BASE_URL}/get"
    r = requests.get(url, params={"device_id": DEVICE_ID}, timeout=20)
    r.raise_for_status()
    data = r.json()

    # Expected: {"lat":..., "lon":..., "acc":..., "ts":...}
    if "lat" not in data or "lon" not in data:
        raise RuntimeError(f"Worker trả dữ liệu không đúng: {data}")

    return data


def fetch_open_meteo(lat: float, lon: float) -> dict:
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


def pick_hour_row(data: dict, target_hour: int, today_date):
    h = data.get("hourly", {})
    times = h.get("time", [])
    pops = h.get("precipitation_probability", [])
    mms = h.get("precipitation", [])
    temps = h.get("temperature_2m", [])

    best = None
    for t, pop, mm, temp in zip(times, pops, mms, temps):
        dt = datetime.fromisoformat(t)
        if dt.date() != today_date:
            continue
        if dt.hour == target_hour:
            best = {
                "dt": dt,
                "hour": dt.hour,
                "pop": int(pop) if pop is not None else 0,
                "mm": float(mm) if mm is not None else 0.0,
                "temp": float(temp) if temp is not None else None,
            }
            break
    return best


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


def should_alert(now_row: dict, next_row: dict) -> (bool, str):
    """
    Quy tắc:
    - Nếu giờ hiện tại mưa (mm >= 0.2) => alert
    - Hoặc 1 giờ tới mưa mạnh: pop >= 70 hoặc mm >= 1.0 => alert
    """
    if now_row and now_row["mm"] >= RAIN_MM_NOTICE:
        return True, "NOW"

    if next_row and (next_row["pop"] >= RAIN_POP_URGENT or next_row["mm"] >= RAIN_MM_MODERATE):
        return True, "NEXT1H"

    return False, ""


def build_message(now_vn: datetime, gps: dict, now_row: dict, next_row: dict, reason: str) -> str:
    lat = gps["lat"]
    lon = gps["lon"]
    acc = gps.get("acc")

    time_str = now_vn.strftime("%Y-%m-%d %H:%M")
    map_link = f"https://www.google.com/maps?q={lat},{lon}"

    if reason == "NOW":
        intensity = rain_intensity(now_row["mm"])
        return (
            f"🔴🌧️ <b>CẢNH BÁO: ĐANG MƯA</b>\n"
            f"🕒 {time_str} (VN)\n"
            f"📍 GPS: <a href=\"{map_link}\">{lat:.6f},{lon:.6f}</a>\n"
            f"{'🎯 Sai số: ~%.1fm' % float(acc) if acc is not None else ''}\n"
            f"⏰ Dữ liệu: <b>{now_row['hour']:02d}:00</b>\n"
            f"☔ Lượng mưa: <b>{now_row['mm']:.1f} mm/h</b> • <i>{intensity}</i>\n"
            f"🧥 Nhắc: Mang áo mưa/ô nếu ra ngoài."
        )

    # NEXT1H
    intensity = rain_intensity(next_row["mm"])
    return (
        f"🟠🌧️ <b>CẢNH BÁO: 1 GIỜ TỚI CÓ MƯA</b>\n"
        f"🕒 {time_str} (VN)\n"
        f"📍 GPS: <a href=\"{map_link}\">{lat:.6f},{lon:.6f}</a>\n"
        f"{'🎯 Sai số: ~%.1fm' % float(acc) if acc is not None else ''}\n"
        f"⏰ Dự kiến: <b>{next_row['hour']:02d}:00</b>\n"
        f"☔ Khả năng mưa: <b>{next_row['pop']}%</b>\n"
        f"🌧️ Lượng mưa: <b>{next_row['mm']:.1f} mm/h</b> • <i>{intensity}</i>\n"
        f"🧥 Nhắc: Nên chuẩn bị áo mưa/ô."
    )


def main():
    now_vn = datetime.now(VN_TZ)

    # Ngoài khung giờ: không gửi gì hết
    if not in_run_window(now_vn):
        return

    # 1) Lấy GPS 1 lần
    gps = fetch_gps_from_worker()
    lat = float(gps["lat"])
    lon = float(gps["lon"])

    # 2) Lấy thời tiết theo GPS
    weather = fetch_open_meteo(lat, lon)

    today = now_vn.date()
    now_row = pick_hour_row(weather, now_vn.hour, today)
    next_hour = (now_vn.hour + 1) % 24
    next_row = pick_hour_row(weather, next_hour, today)

    ok, reason = should_alert(now_row, next_row)
    if not ok:
        return  # không mưa => im lặng

    # 3) Cooldown 3 giờ: tối thiểu 3 tiếng mới gửi lại
    state = load_state()
    now_ts = int(now_vn.timestamp())
    last_ts = int(state.get("last_alert_ts", 0) or 0)

    if last_ts and (now_ts - last_ts) < ALERT_COOLDOWN_SECONDS:
        return

    # Chống spam theo event (cùng giờ + cùng lý do)
    event_key = f"{today.isoformat()}|{DEVICE_ID}|{reason}|{now_vn.hour:02d}"
    if state.get("last_event_key") == event_key:
        return

    msg = build_message(now_vn, gps, now_row, next_row, reason)
    send_telegram(msg)

    state["last_alert_ts"] = now_ts
    state["last_event_key"] = event_key
    save_state(state)


if __name__ == "__main__":
    main()

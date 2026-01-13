import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =========================
# TELEGRAM
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
# CLOUDFLARE WORKER (GPS)
# =========================
WORKER_BASE_URL = "https://wispy-recipe-e63f.bbgaming4-vn.workers.dev"

DEVICES = [
    {"id": "phone1", "name": "📱 ĐIỆN THOẠI CHÍNH"},
    # thêm thiết bị khác ở đây
    # {"id": "phone2", "name": "📱 ĐIỆN THOẠI PHỤ"},
]

# =========================
# WEATHER
# =========================
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

START_HOUR = 9
END_HOUR = 23

RAIN_POP_NOTICE = 30
RAIN_POP_HIGH = 50
RAIN_POP_URGENT = 70

RAIN_MM_NOTICE = 0.2
RAIN_MM_MODERATE = 1.0

# =========================
# ALERT CONTROL
# =========================
ALERT_COOLDOWN_SECONDS = 3 * 60 * 60  # 3h
WATCH_BLOCK_AFTER_DAILY_SECONDS = 3 * 60 * 60

QUIET_START_HOUR = 21
QUIET_END_HOUR = 7
QUIET_END_MINUTE = 30

STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "last_alert.json"

DIVIDER = "──────────────"
BIG_DIV = "━━━━━━━━━━━━━━━━━━━━"


# ======================================================
# UTIL
# ======================================================
def send(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    ).raise_for_status()


def rain_intensity(mm):
    if mm < 0.2:
        return "không mưa"
    if mm < 0.5:
        return "mưa phùn"
    if mm < 2:
        return "mưa nhỏ"
    if mm < 5:
        return "mưa vừa"
    if mm < 10:
        return "mưa to"
    return "mưa rất to"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text("utf-8"))
    return {"alerts_ts": {}, "last_event_key": {}, "last_daily_ts": 0}


def save_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ======================================================
# GPS
# ======================================================
def fetch_gps(device_id: str):
    r = requests.get(
        f"{WORKER_BASE_URL}/get",
        params={"device_id": device_id},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    return float(d["lat"]), float(d["lon"]), int(d.get("ts", 0))


def build_locations():
    locations = []
    for d in DEVICES:
        try:
            lat, lon, ts = fetch_gps(d["id"])
            locations.append({
                "key": d["id"],
                "name": d["name"],
                "lat": lat,
                "lon": lon,
                "ts": ts,
            })
        except Exception as e:
            print(f"[WARN] GPS error {d['id']}: {e}")
    return locations


# ======================================================
# WEATHER
# ======================================================
def fetch_weather(lat, lon):
    r = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "timezone": TZ_NAME,
            "forecast_days": 1,
            "current": "temperature_2m",
            "hourly": "precipitation_probability,precipitation",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def parse_today(data, today):
    h = data["hourly"]
    rows = []
    for t, pop, mm in zip(
        h["time"], h["precipitation_probability"], h["precipitation"]
    ):
        dt = datetime.fromisoformat(t)
        if dt.date() == today:
            rows.append({
                "hour": dt.hour,
                "pop": int(pop),
                "mm": float(mm),
            })
    return rows


# ======================================================
# WATCH MODE
# ======================================================
def run_watch(now):
    if (
        now.hour > QUIET_START_HOUR
        or now.hour < QUIET_END_HOUR
        or (now.hour == QUIET_END_HOUR and now.minute < QUIET_END_MINUTE)
    ):
        return

    state = load_state()
    now_ts = int(now.timestamp())

    if now_ts - state.get("last_daily_ts", 0) < WATCH_BLOCK_AFTER_DAILY_SECONDS:
        return

    alerts = []
    for loc in build_locations():
        data = fetch_weather(loc["lat"], loc["lon"])
        rows = parse_today(data, now.date())

        now_row = next((r for r in rows if r["hour"] == now.hour), None)
        next_row = next((r for r in rows if r["hour"] == (now.hour + 1) % 24), None)

        if not now_row and not next_row:
            continue

        if now_row and now_row["mm"] >= RAIN_MM_NOTICE:
            alerts.append(
                f"🔴🌧️ <b>ĐANG MƯA</b>\n"
                f"{loc['name']}\n"
                f"💧 {now_row['mm']:.1f} mm/h ({rain_intensity(now_row['mm'])})"
            )

        elif next_row and (
            next_row["pop"] >= RAIN_POP_URGENT
            or next_row["mm"] >= RAIN_MM_MODERATE
        ):
            alerts.append(
                f"⚠️🌧️ <b>SẮP MƯA</b>\n"
                f"{loc['name']}\n"
                f"⏰ {next_row['hour']:02d}:00 • {next_row['pop']}%"
            )

    if alerts:
        send("\n\n".join(alerts))
        state["alerts_ts"]["global"] = now_ts
        save_state(state)


# ======================================================
# DAILY MODE
# ======================================================
def run_daily(now):
    blocks = []
    for loc in build_locations():
        data = fetch_weather(loc["lat"], loc["lon"])
        rows = parse_today(data, now.date())

        rain_hours = [r["hour"] for r in rows if r["mm"] >= RAIN_MM_NOTICE]
        max_mm = max((r["mm"] for r in rows), default=0)

        gps_age = int((now.timestamp() - loc["ts"]) / 60)

        blocks.append(
            f"{loc['name']}\n"
            f"📡 GPS: {gps_age} phút trước\n"
            f"🌧️ Max: {max_mm:.1f} mm/h ({rain_intensity(max_mm)})\n"
            f"⏰ Mưa: {', '.join(f'{h:02d}:00' for h in rain_hours) or 'Không'}\n"
            f"🗺️ https://maps.google.com/?q={loc['lat']},{loc['lon']}"
        )

    send(
        f"🌦️ <b>DỰ BÁO THỜI TIẾT</b>\n"
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        + f"\n{DIVIDER}\n".join(blocks)
    )

    state = load_state()
    state["last_daily_ts"] = int(now.timestamp())
    save_state(state)


# ======================================================
# MAIN
# ======================================================
def main():
    now = datetime.now(VN_TZ)
    if MODE == "watch":
        run_watch(now)
    else:
        run_daily(now)


if __name__ == "__main__":
    main()

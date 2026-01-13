🌦️ Weather Alert Telegram Bot (Vietnam)

A fully automated weather forecast & rain alert bot for Vietnam, powered by public weather APIs and GitHub Actions — no server, no PC required.

📬 Sends daily weather summaries and real-time rain alerts directly to Telegram.

✨ Features
✅ Daily Weather Report (07:30 AM Vietnam Time)

Current temperature

Rain status (raining or dry)

Highest & lowest temperature of the day

Cold / hot reminders

Clean, iPhone-friendly message layout

🔴 Real-Time Rain Alerts (Every 5 Minutes)

Alerts when:

🌧️ It is currently raining

⏰ Rain is likely within the next 1 hour

Shows:

Rain intensity (drizzle, light, moderate, heavy)

Rain amount (mm/hour)

Safety reminders (slippery roads, drive carefully)

Per-location cooldown (3 hours) → no spam

🌙 Smart Quiet Hours

❌ No alerts between 21:00 – 07:30

🌙 Night alerts use different icons

🧠 Anti-Spam System

Uses GitHub Actions Cache

Remembers:

Last alert per location

Last alert type (raining / next hour)

Even if GitHub Actions runs every 5 minutes → only sends when needed

📍 Supported Locations (Customizable)

Dĩ An (Bình Dương)

Huyện Đức Thọ (Hà Tĩnh)

👉 You can add/remove locations easily by editing coordinates in the Python file.

🛠️ How It Works
Architecture
GitHub Actions (Server)
│
├─ Daily Workflow (07:30 VN)
│   └─ Send daily weather summary
│
├─ Watch Workflow (Every 5 minutes)
│   └─ Check rain conditions
│       ├─ Is it raining now?
│       └─ Will it rain in 1 hour?
│
└─ Telegram Bot
    └─ Sends messages to your chat


✅ Runs 100% on GitHub servers
✅ Works even if:

Your PC is off

You are logged out of GitHub

You have no internet on your device

🚀 Installation Guide
1️⃣ Create a Telegram Bot

Talk to @BotFather

Create a bot

Copy your BOT TOKEN

2️⃣ Get Your Telegram Chat ID

Send a message to your bot

Use tools like @userinfobot to get your chat_id

Group chats usually start with -100...

3️⃣ Add Secrets to GitHub

Go to:

Repository → Settings → Secrets and variables → Actions


Add 2 secrets:

Name	Value
TELEGRAM_BOT_TOKEN	Your bot token
TELEGRAM_CHAT_ID	Your chat ID
4️⃣ Enable GitHub Actions

This repository includes 2 workflows:

🟢 Daily Weather

File: .github/workflows/daily.yml

Runs at 07:30 AM (VN)

🔴 Rain Watch

File: .github/workflows/rain_watch.yml

Runs every 5 minutes

Sends alerts only when necessary

➡️ GitHub Actions are enabled by default for public repos.

📂 Project Structure
weather-tele-bot/
├─ weather_forecast_3loc.py   # Main bot logic
├─ .github/
│  └─ workflows/
│     ├─ daily.yml            # Daily forecast
│     └─ rain_watch.yml       # Rain alert watcher
├─ .state/                    # Cached alert state (auto-created)
└─ README.md

🔐 Why This Bot Does NOT Spam

Each location has its own cooldown

Same alert cannot be sent twice

Daily alerts automatically block rain alerts for 3 hours

Cached state persists across workflow runs

💸 Cost & Limits

✅ FREE

Uses public weather API (Open-Meteo)

GitHub Actions:

~2000 minutes/month (public repo)

This bot uses < 5% of the limit

🌐 Weather Data Source

Open-Meteo API

No API key required

High accuracy, updated hourly

📱 Optimized for iPhone & Telegram

Short lines

Clear emoji hierarchy

Bold important information

No screen overflow

🧩 Customization Ideas

Add more cities

Send alerts to multiple chats

Add flood or heatwave alerts

Integrate Zalo / SMS / Email

Display rain radar images

✅ Conclusion

A set-and-forget weather alert system
No servers. No maintenance. No spam.

If you’re looking for a reliable Telegram weather alert bot — this is it.

⭐ If you find this project useful, feel free to star the repositor

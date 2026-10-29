# Video Tool Bot

Professional Telegram bot for **splitting**, **merging**, **timeline cutting** and **downloading** videos.  
Supports large files (2 GB normal / ~4 GB with premium bot account) via **Pyrogram MTProto**.

Optimized for **Render Free** (and other free Docker hosts).

---

## Features

| Feature | Description |
|---------|-------------|
| **Split** | Split any video into fixed-duration parts (upload **or** direct link) |
| **Merge** | Merge multiple clips in exact order |
| **Timeline** | Cut multiple precise time ranges from one video |
| **Download** | Download any direct video link → convert to MP4 → upload back |
| **Large files** | Up to 2 GB (normal) / ~4 GB (premium) via MTProto |
| **Multi-admin** | Multiple Telegram user IDs can use the bot |
| **Progress** | Live progress bars with speed & ETA |
| **Cleanup** | Automatic temp-file cleanup after every job |
| **Render Free** | Health-check endpoint + low-resource design |

---

## Commands

| Command | Usage |
|---------|-------|
| `/start` | Welcome + feature overview |
| `/help` | Detailed help |
| `/split` | 1. Duration (seconds) → 2. Video **or** direct link |
| `/merge` | Send clips one by one → `/done` |
| `/timeline` | Upload video → enter ranges (`00:07-00:15`, `7-15` …) |
| `/download` | Send a direct video URL → get MP4 back |
| `/cancel` | Cancel current job & clean temp files |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `ADMIN_IDS` | Yes | Comma-separated Telegram user IDs (e.g. `123456789,987654321`) |
| `API_ID` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `TEMP_DIR` | No | Default: `/tmp/video_bot` |
| `PORT` | Auto | Set by Render for health checks |

> You can still use the old name `OWNER_ID` – it is accepted as a fallback for a single admin.

---

## Deploy on Render (Free)

1. Push this repository to GitHub.
2. Create a **new Web Service** on [Render](https://render.com) → connect the repo.
3. Runtime: **Docker**.
4. Add the environment variables above.
5. Health Check Path: `/`
6. Deploy.

The bot starts a tiny HTTP server on `$PORT` so Render’s free plan health-check succeeds.

---

## Local Run

```bash
# 1. Clone & enter
git clone <your-repo>
cd tg-video-splitter

# 2. Create .env from example
cp .env.example .env
# Edit .env with your values

# 3. Install
pip install -r requirements.txt

# System dependency
# Ubuntu/Debian: sudo apt install ffmpeg
# macOS: brew install ffmpeg

# 4. Run
python main.py
```

---

## Docker (local)

```bash
docker build -t video-tool-bot .
docker run --env-file .env -e PORT=10000 -p 10000:10000 video-tool-bot
```

---

## How large files work

Telegram Bot API has low download limits.  
This bot uses **Pyrogram** (MTProto) so the bot can download & upload files up to the full Telegram limit (2 GB / 4 GB with premium).

External links are downloaded with streaming (low memory) so the bot stays stable on free plans.

---

## Notes for Render Free

- Free instances sleep after ~15 min of inactivity – the bot wakes on the next message.
- Disk is ephemeral – every job cleans its own temp files.
- FFmpeg uses `veryfast` preset + limited threads to stay within memory limits.
- Prefer direct `.mp4` / `.mkv` links for fastest results.

---

## License

MIT – free to use and modify.

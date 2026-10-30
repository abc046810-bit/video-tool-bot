# Video Tool Bot — Premium

Professional Telegram bot for **splitting**, **merging**, **timeline cutting** and **downloading** videos.  
Large files (2 GB / ~4 GB premium) via **Pyrogram MTProto**.

Optimized for **Render Free**.

---

## Features

| Feature | Description |
|---------|-------------|
| **Split** | Duration + video/link (any order) → equal parts |
| **Merge** | Merge clips in order |
| **Timeline** | Cut precise time ranges |
| **Download** | Any direct link → MP4 upload |
| **Buttons** | Persistent reply keyboard + sidebar commands |
| **Admins** | Owners from env; extra admins via `/addadmin` (no DB) |
| **Thumbnails** | Correct duration + preview thumbnail on every upload |
| **Progress** | Live speed & ETA |
| **Render Free** | Health check + low-resource design |

---

## Commands / Buttons

| Action | How |
|--------|-----|
| Main menu | `/start` or buttons |
| Split | ✂️ Split or `/split` |
| Merge | 🔗 Merge or `/merge` → clips → `/done` |
| Timeline | 🎞 Timeline or `/timeline` |
| Download | ⬇️ Download or `/download` |
| Cancel | ❌ Cancel or `/cancel` |
| List admins | `/admins` |
| Add admin | `/addadmin 123456789` (owner only) |
| Remove admin | `/removeadmin 123456789` (owner only) |

---

## Environment (Render)

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | From @BotFather |
| `ADMIN_IDS` | Yes | Bootstrap owner IDs (comma-separated) |
| `API_ID` | Yes | my.telegram.org |
| `API_HASH` | Yes | my.telegram.org |

Extra admins added via the bot are stored in a local JSON file.  
They **reset on redeploy** — re-add with `/addadmin` after deploy if needed.  
Owners from `ADMIN_IDS` never reset.

---

## Deploy (Render Free)

1. Push repo to GitHub  
2. New Web Service → Docker  
3. Set env vars above  
4. Health Check Path: `/`  
5. Deploy  

**Keep awake:** UptimeRobot → HTTP monitor every 5 min on `https://your-app.onrender.com/`

---

## Local

```bash
cp .env.example .env   # edit values
pip install -r requirements.txt
# need ffmpeg on system
python main.py
```

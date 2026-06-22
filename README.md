# 🦊 GoMine Bot

GoMine Telegram Mini App automation — multi-account, daily checkin, ads claiming via Firefox.

## Features

- **Multi-account** — `auth.txt` (1 initData per line)
- **Per-account proxy** — `proxy.txt` (1 proxy per line, fallback `socks5://127.0.0.1:1080`)
- **Daily checkin** — auto claim daily rewards
- **Ads claiming** — Firefox + Playwright bypasses Monetag fingerprint (10 ads/day)
- **Balance & profile** — shows points, sparks, streak, tier, balance
- **Tasks listing** — see available campaigns and tasks
- **Loop mode** — run forever with configurable interval

## Requirements

- Python 3.12+
- Playwright Firefox
- SOCKS5 proxy (local or remote)

```bash
pip install playwright
playwright install firefox
```

## Setup

1. Copy example files:
   ```bash
   cp auth.txt.example auth.txt
   cp proxy.txt.example proxy.txt
   ```

2. Edit `auth.txt` — add your Telegram initData (1 per line):
   ```
   query_id=AAHxxx&user=%7B%22id%22%3A123456789%7D&auth_date=1719000000&hash=abc123
   ```

3. Edit `proxy.txt` — add your proxies (1 per line):
   ```
   socks5://127.0.0.1:1080
   socks5://proxy2.example.com:1080
   ```

4. Run:
   ```bash
   python3 gomine.py
   ```

## Usage

```bash
# Full flow (login + checkin + ads)
python3 gomine.py

# Skip ads
python3 gomine.py --no-ads

# Max 5 ads per account
python3 gomine.py --max-ads 5

# List tasks only
python3 gomine.py --tasks

# Show status only
python3 gomine.py --status

# Loop forever (default 6h interval)
python3 gomine.py --loop

# Loop with custom interval (1 hour)
python3 gomine.py --loop --interval 3600
```

## Getting initData

Use Telethon to get fresh initData:

```python
from telethon import TelegramClient
from telethon.tl.functions.messages import RequestWebViewRequest

async def get_init_data():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start()
    bot = await client.get_entity("GoMineAppBot")
    result = await client(RequestWebViewRequest(
        peer=bot, bot=bot,
        url="https://app.gomine.social/",
        platform="android"
    ))
    await client.disconnect()
    url = result.url
    fragment = url.split("#")[1]
    params = dict(p.split("=") for p in fragment.split("&"))
    return params["tgWebAppData"]
```

## Proxy Format

```
socks5://127.0.0.1:1080
socks5://user:pass@host:port
http://host:port
http://user:pass@host:port
```

If `proxy.txt` is missing or has fewer lines than accounts, remaining accounts use `socks5://127.0.0.1:1080`.

## License

MIT

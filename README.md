# 🦊 GoMine Bot v2 — Fixed & Optimized

GoMine Telegram Mini App automation — multi-account, daily checkin, ads claiming via Firefox.

## 🔧 Fixes Applied (vs original)

| ID | Fix | Detail |
|---|---|---|
| P1 | ✅ File path bug | `auth.txt`/`proxy.txt` now in same dir as script (was `../`) |
| P2 | ✅ `subprocess(curl)` → `httpx` | Async HTTP with connection pooling, 10-50× faster, retry built-in |
| P3 | ✅ Fully async | No nested event loop. Multi-account API calls run in parallel |
| P4 | ✅ Retry + error handling | `tenacity` retry decorator (3 attempts, exponential backoff) |
| P5 | ✅ Anti-detection | Random delays, UA rotation pool, varied viewport |
| P6 | ✅ Session cache | Persists cookies between runs so you're not "new browser" every time |
| P7 | ✅ Smart ad interaction | Dynamic element detection instead of hardcoded selectors |
| P8 | ✅ Parallel ads | Each account runs ads in its own Playwright context — multi-account concurrent |

## Requirements

```bash
pip install httpx playwright tenacity
playwright install firefox
```

## Setup

```bash
cp auth.txt.example auth.txt
cp proxy.txt.example proxy.txt
```

Edit `auth.txt` — add your Telegram initData (1 per line):

```
query_id=AAHxxx&user=%7B%22id%22%3A123456789%7D&auth_date=1719000000&hash=abc123
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

# Loop forever (default 6h)
python3 gomine.py --loop

# Verbose debug
python3 gomine.py --verbose
```

## Proxy Format

```bash
socks5://127.0.0.1:1080
socks5://user:pass@host:port
http://host:port
http://user:pass@host:port
```

If `proxy.txt` has fewer lines than accounts, remaining accounts use `socks5://127.0.0.1:1080`.

## License

MIT

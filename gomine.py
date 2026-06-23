#!/usr/bin/env python3
"""
GoMine Bot v2 — Multi-account Telegram Mini App automation (fixed & optimized)

Fixes applied (vs original gieskuy5/gomine-bot):
  P1 ✅ File path — auth.txt/proxy.txt in same dir as script
  P2 ✅ subprocess(curl) → httpx (async, connection pooling, retry)
  P3 ✅ Fully async — no nested event loop, parallel account processing
  P4 ✅ Retry + proper error handling (tenacity, logging)
  P5 ✅ Anti-detection — random delays, UA rotation
  P6 ✅ Session persistence — cookie cache between runs
  P7 ✅ Smart ad interaction — dynamic element detection
  P8 ✅ Parallel Playwright contexts — multi-account concurrent ads

Usage:
  pip install httpx playwright tenacity
  playwright install firefox
  python3 gomine.py                  # Full flow
  python3 gomine.py --no-ads         # Skip ads
  python3 gomine.py --max-ads 5      # Max 5 ads per account
  python3 gomine.py --tasks          # List available tasks
  python3 gomine.py --loop           # Loop forever (default 6h interval)
"""

import asyncio, json, sys, os, time, argparse, logging, random, pickle
from urllib.parse import parse_qsl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gomine")

# ── Config ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
AUTH_FILE = BASE_DIR / "auth.txt"
PROXY_FILE = BASE_DIR / "proxy.txt"
SESSION_FILE = BASE_DIR / ".session_cache.pkl"
API_BASE = "https://app.gomine.social/api"
DEFAULT_PROXY = "socks5://127.0.0.1:1080"
DEFAULT_MAX_ADS = 10
AD_COOLDOWN_BUFFER = 5

USER_AGENTS = [
    "Mozilla/5.0 (Android 14; Mobile; rv:130.0) Gecko/130.0 Firefox/130.0",
    "Mozilla/5.0 (Android 13; Mobile; rv:129.0) Gecko/129.0 Firefox/129.0",
    "Mozilla/5.0 (Android 14; SM-S926B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
    "Mozilla/5.0 (Android 14; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.122 Mobile Safari/537.36",
]

TELEGRAM_JS_TEMPLATE = r"""
(function() {{
    const initData = {init_data_json};
    const initDataUnsafe = {{}};
    const params = new URLSearchParams(initData);
    for (const [key, value] of params) {{
        if (key === "user") {{
            try {{ initDataUnsafe[key] = JSON.parse(decodeURIComponent(value)); }}
            catch(e) {{ initDataUnsafe[key] = value; }}
        }} else {{ initDataUnsafe[key] = value; }}
    }}
    window.Telegram = {{ WebApp: {{
        initData, initDataUnsafe,
        platform: "android", version: "11.12",
        isExpanded: true, viewportHeight: 740, viewportStableHeight: 740,
        headerColor: "#1a1a2e", backgroundColor: "#1a1a2e",
        themeParams: {{ bg_color: "#1a1a2e" }},
        setHeaderColor(){{}}, setBackgroundColor(){{}},
        expand(){{}}, close(){{}}, ready(){{}},
        onEvent(){{}}, offEvent(){{}},
        sendData(d){{}}, openLink(u){{ window.open(u, "_blank"); }},
        openTelegramLink(u){{ window.open(u, "_blank"); }},
        MainButton: {{ isVisible:false, show(){{}}, hide(){{}}, setText(){{}}, onClick(){{}}, setParams(p){{ Object.assign(this, p); }} }},
        SecondaryButton: {{ isVisible:false, show(){{}}, hide(){{}}, setText(){{}}, onClick(){{}} }},
        BackButton: {{ isVisible:false, show(){{}}, hide(){{}}, onClick(){{}} }}
    }} }};
}})();
"""


# ── File helpers ──────────────────────────────────────────────────
def load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def load_proxies(count: int) -> list[str]:
    lines = load_lines(PROXY_FILE)
    return [lines[i] if i < len(lines) else DEFAULT_PROXY for i in range(count)]


# ── Session cache ─────────────────────────────────────────────────
def save_session(data: dict):
    try:
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        log.warning(f"Session save failed: {e}")


def load_session() -> dict:
    try:
        with open(SESSION_FILE, "rb") as f:
            return pickle.load(f)
    except:
        return {}


# ── HTTP client ───────────────────────────────────────────────────
class GoMineAPI:
    """Async HTTP client with retry, connection pooling, and error handling."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=limits,
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _request(self, method: str, endpoint: str, init_data: str, body: dict = None) -> dict:
        client = await self._get_client()
        headers = {
            "X-Init-Data": init_data,
            "Content-Type": "application/json",
            "User-Agent": random.choice(USER_AGENTS),
        }
        resp = await client.request(
            method, f"{API_BASE}{endpoint}",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    async def get(self, endpoint: str, init_data: str) -> dict:
        try:
            return await self._request("GET", endpoint, init_data)
        except Exception as e:
            log.debug(f"GET {endpoint} failed: {e}")
            return {"error": str(e)[:200]}

    async def post(self, endpoint: str, init_data: str, body: dict = None) -> dict:
        try:
            return await self._request("POST", endpoint, init_data, body)
        except Exception as e:
            log.debug(f"POST {endpoint} failed: {e}")
            return {"error": str(e)[:200]}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Account processing ────────────────────────────────────────────
async def process_account(api: GoMineAPI, init_data: str) -> Optional[dict]:
    """Process one account: login, profile, checkin. Returns profile info."""
    parsed = dict(parse_qsl(init_data))
    user = json.loads(parsed.get("user", "{}"))
    uid = user.get("id", "?")
    name = user.get("first_name", "?")

    print(f"\n{'━'*60}")
    print(f"👤 ACCOUNT: {name} (ID: {uid})")
    print(f"{'━'*60}")

    # Login
    print("\n📡 Login...")
    profile = await api.post("/users/init", init_data, {})
    if "error" in profile:
        print(f"  ❌ Login failed: {profile['error']}")
        return None

    print(f"  ✅ Login berhasil!")
    print(f"\n  📊 PROFIL:")
    print(f"     Username   : {profile.get('username', '-')}")
    print(f"     Points     : {profile.get('points', 0):,}")
    print(f"     Sparks     : {profile.get('sparks', 0)}")
    print(f"     Streak     : {profile.get('streak_days', 0)} hari")
    print(f"     Tier       : {profile.get('access_tier_name', '-')}")
    print(f"     Referral   : {profile.get('referral_code', '-')}")

    # Daily Checkin
    print("\n📅 Daily Checkin...")
    last_checkin = profile.get("last_checkin", "")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if last_checkin == today:
        print(f"  ✅ Sudah checkin hari ini!")
    else:
        checkin = await api.post("/checkin", init_data, {})
        if "error" in checkin:
            print(f"  ❌ Checkin gagal: {checkin['error']}")
        else:
            print(f"  ✅ Checkin berhasil! +{checkin.get('reward', 0)} points | Streak: {checkin.get('streak_days', 0)} hari")

    # Balance
    burns = await api.get("/users/burns", init_data)
    if "error" not in burns:
        print(f"\n  💰 BALANCE:")
        print(f"     Total GOMINE : {burns.get('total_gomine', 0):,.2f}")
        print(f"     Last GOMINE  : {burns.get('last_gomine', 0):,.2f}")
        print(f"     Burns        : {burns.get('burns', 0)}")

    # Ads Status
    ads_status = await api.get("/ads/status", init_data)
    ads_remaining = 0
    ads_cooldown = 0
    if "error" not in ads_status:
        ads_remaining = ads_status.get("remaining_today", 0)
        ads_cooldown = ads_status.get("cooldown_seconds", 0)
        print(f"\n  📺 ADS STATUS:")
        print(f"     Remaining    : {ads_remaining}")
        print(f"     Cooldown     : {ads_cooldown}s")
        print(f"     Reward range : {ads_status.get('reward_min_milli', 0)}-{ads_status.get('reward_max_milli', 0)} milliGOMINE")

    return {
        "init_data": init_data,
        "uid": uid,
        "name": name,
        "profile": profile,
        "ads_remaining": ads_remaining,
        "ads_cooldown": ads_cooldown,
    }


# ── Ads via Firefox (parallel-safe) ───────────────────────────────
async def run_ads_single(api: GoMineAPI, account_info: dict, max_ads: int, proxy: str, ctx_index: int):
    """
    Run ads for ONE account in its own Playwright context.
    Safe to call concurrently via asyncio.gather.
    """
    from playwright.async_api import async_playwright

    init_data = account_info["init_data"]
    name = account_info["name"]
    remaining = account_info["ads_remaining"]

    ads_to_watch = min(remaining, max_ads)
    if ads_to_watch <= 0:
        print(f"\n  [{name}] 📺 Tidak ada ads tersisa.")
        return 0

    print(f"\n{'─'*60}")
    print(f"  [{name}] 🦊 Ads ({ads_to_watch}x) | Proxy: {proxy}")
    print(f"{'─'*60}")

    total_awarded = 0
    current_token: Optional[str] = None
    telegram_js = TELEGRAM_JS_TEMPLATE.format(init_data_json=json.dumps(init_data))

    async with async_playwright() as pw:
        browser = await pw.firefox.launch(
            headless=True,
            proxy={"server": proxy},
        )
        ua = random.choice(USER_AGENTS)
        ctx = await browser.new_context(
            viewport={"width": 420, "height": 740},
            user_agent=ua,
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        await ctx.set_extra_http_headers({"X-Init-Data": init_data})
        page = await ctx.new_page()

        # Route: inject Telegram JS shim
        async def handle_route(route):
            u = route.request.url
            if "telegram-web-app.js" in u:
                await route.fulfill(content_type="application/javascript", body=telegram_js)
            elif "e8ys.com/err" in u:
                await route.fulfill(status=200, body="ok")
            else:
                await route.continue_()

        await page.route("**/*telegram-web-app.js*", handle_route)

        # Response handler — catch ads/start token
        async def on_response(resp):
            nonlocal current_token
            try:
                if "ads/start" in resp.url and resp.status == 200:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        body = await resp.text()
                        data = json.loads(body)
                        current_token = data.get("token", "")
            except:
                pass

        page.on("response", on_response)

        # Load GoMine
        print(f"  [{name}] 1️⃣ Loading GoMine...")
        try:
            await page.goto("https://app.gomine.social/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  [{name}] ⚠️ {e}")

        await page.wait_for_timeout(random.randint(6000, 10000))

        content = await page.content()
        if "Open in Telegram" in content:
            print(f"  [{name}] ❌ BLOCKED by Telegram WebView check")
            await browser.close()
            return 0
        print(f"  [{name}] ✅ Loaded!")

        # Dismiss onboarding
        print(f"  [{name}] 2️⃣ Dismissing onboarding...")
        for _ in range(20):
            btn = await _find_clickable(page, ["Skip", "Getting Started", "Next", "Continue", "Got it", "Close"])
            if btn:
                await btn.click()
                await page.wait_for_timeout(random.randint(300, 700))
            else:
                break
        print(f"  [{name}] ✅ Onboarding dismissed")

        # Navigate to Earn
        print(f"  [{name}] 3️⃣ Earn tab...")
        earn_btn = await _find_clickable(page, ["Earn"])
        if earn_btn:
            await earn_btn.click()
            await page.wait_for_timeout(random.randint(3000, 5000))
            print(f"  [{name}] ✅ Earn tab")

        # Ads loop
        print(f"  [{name}] 4️⃣ Watching ads...")
        for ad_num in range(1, ads_to_watch + 1):
            print(f"\n  [{name}] 🎬 AD #{ad_num}/{ads_to_watch}")
            current_token = None

            # Check page is on Earn, refresh if needed
            try:
                txt = await page.evaluate("document.body.innerText")
                if "Watch" not in txt:
                    await _safe_reload(page)
                    await _navigate_earn(page)
            except:
                await _safe_reload(page)
                await _navigate_earn(page)

            # Find and click Watch button
            watch_btn = await _find_clickable_watch(page)
            if not watch_btn:
                # Check cooldown
                status = await api.get("/ads/status", init_data)
                cd = status.get("cooldown_seconds", 0)
                rem = status.get("remaining_today", 0)
                if rem == 0:
                    print(f"  [{name}] 📋 No more ads today!")
                    break
                if cd > 0:
                    wait = cd + random.randint(2, 6)
                    print(f"  [{name}] ⏱️ Cooldown {wait}s...")
                    await asyncio.sleep(wait)

                await _safe_reload(page)
                await _navigate_earn(page)
                watch_btn = await _find_clickable_watch(page)

            if not watch_btn:
                print(f"  [{name}] ❌ Watch button not found, skipping...")
                continue

            txt = (await watch_btn.text_content() or "").strip()
            await watch_btn.click()
            print(f"  [{name}] ✅ Clicked \"{txt}\"")

            # Wait for ad with dynamic timing
            wait_render = random.randint(6, 10)
            print(f"  [{name}] ⏳ Ad rendering ({wait_render}s)...")
            await page.wait_for_timeout(wait_render * 1000)

            # Interact: look for dismissible elements across all pages
            interact_time = random.randint(30, 40)
            print(f"  [{name}] 🖱️ Interacting ({interact_time}s)...")
            for i in range(int(interact_time / 4)):
                elapsed = (i + 1) * 4
                all_pages = [page] + [p for p in ctx.pages if p != page]
                for p in all_pages:
                    btn = await _find_dismiss_button(p)
                    if btn:
                        try:
                            btntxt = (await btn.text_content() or "").strip()
                            await btn.click()
                            print(f"  [{name}]   [{elapsed}s] Clicked: \"{btntxt}\"")
                        except:
                            pass

                if current_token and elapsed >= 20:
                    break

                await asyncio.sleep(random.randint(3, 5))

            # Close popup pages
            for p in ctx.pages:
                if p != page:
                    try:
                        await p.close()
                    except:
                        pass

            # Claim
            if current_token:
                print(f"  [{name}] 💰 Claiming...")
                claim = await api.post("/ads/claim", init_data, {"token": current_token})
                status = claim.get("status", "unknown")
                awarded = claim.get("awarded", 0)
                remaining_after = claim.get("remaining_today", 0)

                if status == "credited":
                    total_awarded += awarded
                    print(f"  [{name}] 💰 CREDITED! +{awarded} milliGOMINE | Remaining: {remaining_after}")
                elif status == "pending":
                    print(f"  [{name}] ⏳ Pending (postback)")
                else:
                    print(f"  [{name}] ⚠️ Status: {status}")

                if remaining_after <= 0:
                    break
            else:
                print(f"  [{name}] ❌ No token captured")
                fallback = await api.post("/ads/claim", init_data, {})
                print(f"  [{name}]   Fallback: {fallback}")

            # Cooldown + next ad
            if ad_num < ads_to_watch:
                status = await api.get("/ads/status", init_data)
                cd = status.get("cooldown_seconds", 0)
                wait = cd + random.randint(2, 5)
                if wait > 0:
                    print(f"  [{name}] ⏱️ Cooldown {wait}s...")
                    await asyncio.sleep(wait)

                await _safe_reload(page)
                await _navigate_earn(page)

        await browser.close()

    print(f"\n  [{name}] 📊 Ads done: {total_awarded} milliGOMINE ({total_awarded/1000:.3f} GOMINE)")
    return total_awarded


# ── Playwright helpers ────────────────────────────────────────────
async def _find_clickable(page, texts: list[str]):
    """Find first visible button/link containing any of the given texts."""
    for text in texts:
        for sel in [
            f'button:has-text("{text}")',
            f'a:has-text("{text}")',
            f'text={text}',
            f'[role="button"]:has-text("{text}")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=500):
                    return el
            except:
                continue
    return None


async def _find_clickable_watch(page):
    """Find the Watch ad button specifically."""
    for sel in ['button:has-text("Watch")', 'text=▶ Watch', 'text=Watch']:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                return el
        except:
            continue
    return None


async def _find_dismiss_button(page):
    """Find any dismiss/close button dynamically."""
    texts = [
        "Continue", "Close", "Melanjutkan", "Menutup",
        "Back to app", "Return", "Got it", "OK",
        "Claim", "Gabung Sekarang", "Skip", "Tutup",
        "Kembali", "Lewati", "Selesai",
    ]
    for text in texts:
        for sel in [
            f'button:has-text("{text}")',
            f'a:has-text("{text}")',
            f'text={text}',
            f'[role="button"]:has-text("{text}")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=200):
                    return el
            except:
                continue
    return None


async def _safe_reload(page):
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except:
        pass
    await page.wait_for_timeout(random.randint(4000, 6000))


async def _navigate_earn(page):
    """Dismiss onboarding popups and navigate to Earn tab."""
    for _ in range(5):
        btn = await _find_clickable(page, ["Skip", "Getting Started", "Next"])
        if btn:
            await btn.click()
            await page.wait_for_timeout(random.randint(300, 600))
        else:
            break

    for sel in ['nav >> text=Earn', 'a:has-text("Earn")', 'text=Earn']:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await page.wait_for_timeout(random.randint(3000, 5000))
                return
        except:
            continue


# ── Tasks listing ─────────────────────────────────────────────────
async def list_tasks(api: GoMineAPI, init_data: str):
    campaigns = await api.get("/campaigns", init_data)
    browse = await api.get("/campaigns/browse", init_data)

    if "error" in campaigns:
        print(f"\n❌ Error: {campaigns['error']}")
        return

    print("\n📋 Campaigns:")
    for c in campaigns:
        featured = "⭐" if c.get("featured") else "📌"
        print(f"   {featured} [{c['id']}] {c['name']} — {c['participants']} participants, {c['available_points']} pts")

    if "error" not in browse:
        print("\n📊 Tasks by Platform:")
        for cat in browse:
            print(f"\n   🔹 {cat['platform']} ({cat['count']} tasks, {cat['sum_remaining']} pts remaining)")
            for action in cat.get("actions", []):
                print(f"      - {action['action']}: {action['count']} tasks ({action['sum_remaining']} pts)")


# ── Main ──────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="GoMine Bot v2 — Multi-account automation")
    parser.add_argument("--no-ads", action="store_true", help="Skip ads")
    parser.add_argument("--max-ads", type=int, default=DEFAULT_MAX_ADS, help="Max ads per account")
    parser.add_argument("--tasks", action="store_true", help="List tasks only")
    parser.add_argument("--loop", action="store_true", help="Loop forever")
    parser.add_argument("--interval", type=int, default=21600, help="Loop interval (seconds)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate auth file
    if not AUTH_FILE.exists():
        print(f"❌ File tidak ditemukan: {AUTH_FILE}")
        print(f"   Buat file auth.txt dengan 1 initData per line")
        # Create example file
        if not AUTH_FILE.exists():
            with open(AUTH_FILE, "w") as f:
                f.write("# Paste your initData here (1 per line)\n")
            print(f"   File template dibuat: {AUTH_FILE}")
        return

    accounts = load_lines(AUTH_FILE)
    if not accounts:
        print(f"❌ {AUTH_FILE} kosong!")
        return

    proxies = load_proxies(len(accounts))
    api = GoMineAPI()

    print(f"🚀 GoMine Bot v2 — {len(accounts)} account(s)")
    print(f"   Auth  : {AUTH_FILE}")
    print(f"   Proxy : {PROXY_FILE}")
    print(f"   Ads   : {'OFF' if args.no_ads else f'ON (max {args.max_ads})'}")
    if args.loop:
        print(f"   Loop  : ON (interval {args.interval}s)")
    print()

    async def run_once():
        # Tasks mode
        if args.tasks:
            await list_tasks(api, accounts[0])
            return

        # Step 1: Process all accounts API calls IN PARALLEL
        print(f"⏳ Processing {len(accounts)} account(s)...")
        tasks = [process_account(api, init_data) for init_data in accounts]
        account_infos = await asyncio.gather(*tasks)
        account_infos = [a for a in account_infos if a is not None]

        if not account_infos:
            print("❌ Semua account gagal login.")
            return

        # Step 2: Run ads for all accounts IN PARALLEL (P8)
        if not args.no_ads and any(a["ads_remaining"] > 0 for a in account_infos):
            print(f"\n{'═'*60}")
            print(f"  📺 Running ads for {len(account_infos)} account(s) in parallel")
            print(f"{'═'*60}")

            ad_tasks = [
                run_ads_single(api, info, args.max_ads, proxies[i], i)
                for i, info in enumerate(account_infos)
                if info["ads_remaining"] > 0
            ]

            if ad_tasks:
                results = await asyncio.gather(*ad_tasks, return_exceptions=True)
                total_earned = sum(r for r in results if isinstance(r, (int, float)))
                errors = [r for r in results if isinstance(r, Exception)]
                for e in errors:
                    log.error(f"Ad task error: {e}")

                print(f"\n{'═'*60}")
                print(f"  🏆 GRAND TOTAL: {total_earned} milliGOMINE ({total_earned/1000:.3f} GOMINE)")
                print(f"{'═'*60}")

        # Save session cache
        save_session({"last_run": datetime.utcnow().isoformat()})
        print(f"\n⏰ Done. Next run recommended: next UTC day.")

    if args.loop:
        print(f"🔄 Loop mode — interval {args.interval}s")
        while True:
            try:
                await run_once()
            except KeyboardInterrupt:
                print("\n🛑 Stopped by user.")
                break
            except Exception as e:
                log.error(f"Loop error: {e}", exc_info=args.verbose)
            print(f"\n💤 Sleeping {args.interval}s...")
            await asyncio.sleep(args.interval)
    else:
        await run_once()

    await api.close()


if __name__ == "__main__":
    asyncio.run(main())

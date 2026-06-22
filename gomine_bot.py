#!/usr/bin/env python3
"""
gomine_bot.py — GoMine multi-account automation

Flow per account:
  1. Login (API) → tampilkan profil lengkap
  2. Cek daily checkin → lakukan checkin
  3. Cek task ads → selesaikan 10 task ads (open ads > tunggu cooldown > repeat)
  4. Info next daily checkin

Auth: auth.txt (1 line = 1 initData)
Proxy: SOCKS5 localhost:1080 (Indonesian IP via SSH tunnel)
Browser: Playwright Firefox (bypasses Monetag fingerprint)

Usage:
  python3 gomine_bot.py
  python3 gomine_bot.py --no-ads       # Skip ads
  python3 gomine_bot.py --max-ads 5    # Max 5 ads per account
"""
import asyncio, json, subprocess, sys, os, time
from urllib.parse import parse_qsl
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────
AUTH_FILE = os.path.join(os.path.dirname(__file__), "..", "auth.txt")
API_BASE = "https://app.gomine.social/api"
SOCKS_PROXY = "socks5://localhost:1080"
DEFAULT_MAX_ADS = 10
AD_COOLDOWN_WAIT = 5  # extra seconds after API cooldown
AD_RENDER_WAIT = 8    # seconds to wait for ad to render
AD_INTERACT_WAIT = 35 # seconds to interact with ad before claim

TELEGRAM_JS_TEMPLATE = """
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


# ── HTTP API helpers ──────────────────────────────────────────────
def api_get(endpoint, init_data):
    """GET request to GoMine API."""
    r = subprocess.run(
        ["curl", "-s", "-X", "GET", f"{API_BASE}{endpoint}",
         "-H", f"X-Init-Data: {init_data}"],
        capture_output=True, text=True, timeout=15
    )
    try:
        return json.loads(r.stdout)
    except:
        return {"error": r.stdout[:200]}


def api_post(endpoint, init_data, body=None):
    """POST request to GoMine API."""
    cmd = ["curl", "-s", "-X", "POST", f"{API_BASE}{endpoint}",
           "-H", f"X-Init-Data: {init_data}",
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try:
        return json.loads(r.stdout)
    except:
        return {"error": r.stdout[:200]}


# ── Account processing ───────────────────────────────────────────
def process_account_http(init_data, max_ads, no_ads):
    """Process one account: login, profile, checkin. Returns profile info."""
    # Parse user info from initData
    parsed = dict(parse_qsl(init_data))
    user = json.loads(parsed.get("user", "{}"))
    uid = user.get("id", "?")
    name = user.get("first_name", "?")

    print(f"\n{'━'*60}")
    print(f"👤 ACCOUNT: {name} (ID: {uid})")
    print(f"{'━'*60}")

    # 1. Login / Init
    print("\n📡 Login...")
    profile = api_post("/users/init", init_data, {})
    if "error" in profile:
        print(f"  ❌ Login failed: {profile['error']}")
        return None

    # Display profile
    print(f"  ✅ Login berhasil!")
    print(f"\n  📊 PROFIL:")
    print(f"     Username   : {profile.get('username', '-')}")
    print(f"     Nama       : {profile.get('first_name', '-')}")
    print(f"     Points     : {profile.get('points', 0):,}")
    print(f"     Sparks     : {profile.get('sparks', 0)}")
    print(f"     Streak     : {profile.get('streak_days', 0)} hari")
    print(f"     Tier       : {profile.get('access_tier_name', '-')}")
    print(f"     Referral   : {profile.get('referral_code', '-')}")
    print(f"     Twitter    : {profile.get('twitter_username') or '❌ Belum'}")

    # 2. Daily Checkin
    print("\n📅 Daily Checkin...")
    last_checkin = profile.get("last_checkin", "")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if last_checkin == today:
        print(f"  ✅ Sudah checkin hari ini!")
    else:
        checkin = api_post("/checkin", init_data)
        if "error" in checkin:
            print(f"  ❌ Checkin gagal: {checkin['error']}")
        else:
            reward = checkin.get("reward", 0)
            streak = checkin.get("streak_days", 0)
            print(f"  ✅ Checkin berhasil! +{reward} points | Streak: {streak} hari")

    # 3. Burns / Balance
    burns = api_get("/users/burns", init_data)
    if "error" not in burns:
        print(f"\n  💰 BALANCE:")
        print(f"     Total GOMINE : {burns.get('total_gomine', 0):,.2f}")
        print(f"     Last GOMINE  : {burns.get('last_gomine', 0):,.2f}")
        print(f"     Burns        : {burns.get('burns', 0)}")
        print(f"     Last TX      : {burns.get('last_tx', '-')[:30]}...")

    # 4. Ads Status
    ads_status = api_get("/ads/status", init_data)
    if "error" not in ads_status:
        remaining = ads_status.get("remaining_today", 0)
        daily_cap = ads_status.get("daily_cap", 0)
        cooldown = ads_status.get("cooldown_seconds", 0)
        reward_min = ads_status.get("reward_min_milli", 0)
        reward_max = ads_status.get("reward_max_milli", 0)
        print(f"\n  📺 ADS STATUS:")
        print(f"     Daily cap    : {daily_cap}")
        print(f"     Remaining    : {remaining}")
        print(f"     Cooldown     : {cooldown}s")
        print(f"     Reward range : {reward_min}-{reward_max} milliGOMINE")

    # Next daily
    if last_checkin:
        try:
            last_dt = datetime.strptime(last_checkin, "%Y-%m-%d")
            next_dt = last_dt + timedelta(days=1)
            print(f"\n  ⏰ Next daily checkin: {next_dt.strftime('%Y-%m-%d')} (UTC)")
        except:
            pass

    return {
        "init_data": init_data,
        "uid": uid,
        "name": name,
        "profile": profile,
        "ads_remaining": ads_status.get("remaining_today", 0) if "error" not in ads_status else 0,
        "ads_cooldown": ads_status.get("cooldown_seconds", 0) if "error" not in ads_status else 0,
    }


async def run_ads_firefox(account_info, max_ads):
    """Run ads via Playwright Firefox with SOCKS5 proxy."""
    init_data = account_info["init_data"]
    uid = account_info["uid"]
    name = account_info["name"]
    remaining = account_info["ads_remaining"]

    ads_to_watch = min(remaining, max_ads)
    if ads_to_watch <= 0:
        print(f"\n  📺 Tidak ada ads tersisa hari ini.")
        return 0

    print(f"\n{'─'*60}")
    print(f"  🦊 ADS MODE: Firefox + SOCKS5 proxy")
    print(f"  📺 Watching {ads_to_watch} ads...")
    print(f"{'─'*60}")

    from playwright.async_api import async_playwright

    total_awarded = 0
    total_claims = 0
    current_token = None

    telegram_js = TELEGRAM_JS_TEMPLATE.format(init_data_json=json.dumps(init_data))

    async with async_playwright() as pw:
        browser = await pw.firefox.launch(
            headless=True,
            proxy={"server": SOCKS_PROXY},
        )
        ctx = await browser.new_context(
            viewport={"width": 420, "height": 740},
            user_agent="Mozilla/5.0 (Android 13; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        await ctx.set_extra_http_headers({"X-Init-Data": init_data})
        page = await ctx.new_page()

        # Route: inject Telegram JS
        async def handle_route(route):
            u = route.request.url
            if "telegram-web-app.js" in u:
                await route.fulfill(content_type="application/javascript", body=telegram_js)
            elif "e8ys.com/err" in u:
                await route.fulfill(status=200, body="ok")
            else:
                await route.continue_()
        await page.route("**/*telegram-web-app.js*", handle_route)

        # Response handler for token tracking
        async def on_response(resp):
            nonlocal current_token
            u = resp.url
            try:
                if "ads/start" in u and resp.status == 200:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        body = await resp.text()
                        data = json.loads(body)
                        current_token = data.get("token", "")
            except: pass
        page.on("response", on_response)

        # Load GoMine
        print(f"\n  1️⃣ Loading GoMine...")
        try:
            await page.goto("https://app.gomine.social/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"     ⚠️ {e}")
        await page.wait_for_timeout(8000)

        content = await page.content()
        if "Open in Telegram" in content:
            print(f"     ❌ BLOCKED by Telegram WebView check")
            await browser.close()
            return 0
        print(f"     ✅ Loaded!")

        # Dismiss onboarding
        print(f"  2️⃣ Dismissing onboarding...")
        for _ in range(15):
            dismissed = False
            for sel in ['text=Skip', 'text=Getting Started', 'text=Next', 'text=Continue', 'text=Got it']:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=400):
                        await el.click()
                        dismissed = True
                        await page.wait_for_timeout(400)
                except: pass
            if not dismissed:
                break
        await page.wait_for_timeout(1000)
        print(f"     ✅ Done")

        # Navigate to Earn
        print(f"  3️⃣ Earn tab...")
        for sel in ['nav >> text=Earn', 'a:has-text("Earn")', 'text=Earn']:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    await page.wait_for_timeout(4000)
                    print(f"     ✅ Earn tab")
                    break
            except: continue

        # Ads loop
        print(f"\n  4️⃣ Watching ads...")
        for ad_num in range(1, ads_to_watch + 1):
            print(f"\n  {'─'*50}")
            print(f"  🎬 AD #{ad_num}/{ads_to_watch}")
            print(f"  {'─'*50}")

            current_token = None

            # Make sure we're on Earn page
            try:
                txt = await page.evaluate("document.body.innerText")
                if "Watch" not in txt:
                    print(f"     🔄 Refreshing Earn page...")
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                    except: pass
                    await page.wait_for_timeout(5000)

                    # Re-dismiss onboarding
                    for _ in range(5):
                        dismissed = False
                        for sel in ['text=Skip', 'text=Getting Started']:
                            try:
                                el = page.locator(sel).first
                                if await el.is_visible(timeout=400):
                                    await el.click()
                                    dismissed = True
                                    await page.wait_for_timeout(400)
                            except: pass
                        if not dismissed:
                            break

                    # Navigate to Earn
                    for sel in ['nav >> text=Earn', 'a:has-text("Earn")']:
                        try:
                            el = page.locator(sel).first
                            if await el.is_visible(timeout=3000):
                                await el.click()
                                await page.wait_for_timeout(4000)
                                break
                        except: continue
            except: pass

            # Find and click Watch button
            watch_clicked = False
            for sel in ['button:has-text("Watch")', 'text=▶ Watch']:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        txt = await el.text_content()
                        await el.click()
                        print(f"     ✅ Clicked \"{txt.strip()}\"")
                        watch_clicked = True
                        break
                except: continue

            if not watch_clicked:
                # Check if cooldown
                status = api_get("/ads/status", init_data)
                cd = status.get("cooldown_seconds", 0)
                rem = status.get("remaining_today", 0)
                if rem == 0:
                    print(f"     📋 No more ads today!")
                    break
                if cd > 0:
                    print(f"     ⏱️ Cooldown {cd}s, waiting...")
                    await asyncio.sleep(cd + AD_COOLDOWN_WAIT)
                # Refresh and retry
                print(f"     🔄 Refreshing...")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                except: pass
                await page.wait_for_timeout(5000)

                for _ in range(5):
                    dismissed = False
                    for sel in ['text=Skip', 'text=Getting Started']:
                        try:
                            el = page.locator(sel).first
                            if await el.is_visible(timeout=400):
                                await el.click()
                                dismissed = True
                                await page.wait_for_timeout(400)
                        except: pass
                    if not dismissed:
                        break

                for sel in ['nav >> text=Earn', 'a:has-text("Earn")']:
                    try:
                        el = page.locator(sel).first
                        if await el.is_visible(timeout=3000):
                            await el.click()
                            await page.wait_for_timeout(4000)
                            break
                    except: continue

                for sel in ['button:has-text("Watch")', 'text=▶ Watch']:
                    try:
                        el = page.locator(sel).first
                        if await el.is_visible(timeout=3000):
                            txt = await el.text_content()
                            await el.click()
                            print(f"     ✅ Retry: \"{txt.strip()}\"")
                            watch_clicked = True
                            break
                    except: continue

                if not watch_clicked:
                    print(f"     ❌ Watch button not found, skipping...")
                    continue

            # Wait for ad to render
            print(f"     ⏳ Waiting for ad ({AD_RENDER_WAIT}s)...")
            await page.wait_for_timeout(AD_RENDER_WAIT * 1000)

            # Interact with ad (click buttons that appear)
            print(f"     🖱️ Interacting with ad ({AD_INTERACT_WAIT}s)...")
            for i in range(int(AD_INTERACT_WAIT / 5)):
                elapsed = (i + 1) * 5
                all_pages = [page] + [p for p in ctx.pages if p != page]
                for p in all_pages:
                    for sel in ['text=Continue', 'text=Close', 'text=Melanjutkan', 'text=Menutup',
                                'text=Back to app', 'text=Return', 'text=Got it', 'text=OK',
                                'text=Claim', 'text=Gabung Sekarang',
                                'button:has-text("Close")', 'button:has-text("Continue")',
                                'button:has-text("Got it")', 'button:has-text("OK")',
                                'button:has-text("Return")']:
                        try:
                            el = p.locator(sel).first
                            if await el.is_visible(timeout=300):
                                txt = (await el.text_content() or "").strip()
                                await el.click()
                                print(f"        [{elapsed}s] Clicked: \"{txt}\"")
                        except: pass

                # Early claim if token available
                if current_token and elapsed >= 25:
                    break

                await page.wait_for_timeout(5000)

            # Close extra pages
            for p in ctx.pages:
                if p != page:
                    try: await p.close()
                    except: pass

            # Claim reward
            if current_token:
                print(f"     💰 Claiming...")
                claim = api_post("/ads/claim", init_data, {"token": current_token})
                status = claim.get("status", "unknown")
                awarded = claim.get("awarded", 0)
                remaining = claim.get("remaining_today", 0)

                if status == "credited":
                    total_awarded += awarded
                    total_claims += 1
                    print(f"     💰 CREDITED! +{awarded} milliGOMINE | Total: {total_awarded} | Remaining: {remaining}")
                elif status == "pending":
                    print(f"     ⏳ Pending (postback belum diterima)")
                else:
                    print(f"     ⚠️ Status: {status}")

                if remaining <= 0:
                    print(f"     📋 Selesai! Semua ads habis.")
                    break
            else:
                print(f"     ❌ Token tidak tertangkap")
                # Try direct claim
                claim = api_post("/ads/claim", init_data, {})
                print(f"     Direct claim: {claim}")

            # Wait for cooldown before next ad
            if ad_num < ads_to_watch:
                status = api_get("/ads/status", init_data)
                cd = status.get("cooldown_seconds", 0)
                wait_time = cd + AD_COOLDOWN_WAIT
                if wait_time > 0:
                    print(f"     ⏱️ Cooldown {cd}s + buffer {AD_COOLDOWN_WAIT}s = {wait_time}s...")
                    await asyncio.sleep(wait_time)

                # Refresh page for next ad
                print(f"     🔄 Refreshing for next ad...")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                except: pass
                await page.wait_for_timeout(5000)

                # Re-dismiss onboarding
                for _ in range(5):
                    dismissed = False
                    for sel in ['text=Skip', 'text=Getting Started']:
                        try:
                            el = page.locator(sel).first
                            if await el.is_visible(timeout=400):
                                await el.click()
                                dismissed = True
                                await page.wait_for_timeout(400)
                        except: pass
                    if not dismissed:
                        break

                # Re-navigate to Earn
                for sel in ['nav >> text=Earn', 'a:has-text("Earn")']:
                    try:
                        el = page.locator(sel).first
                        if await el.is_visible(timeout=3000):
                            await el.click()
                            await page.wait_for_timeout(4000)
                            break
                    except: continue

        # Final summary
        await browser.close()

    print(f"\n  {'─'*50}")
    print(f"  📊 ADS SUMMARY for {name}:")
    print(f"     Claimed : {total_claims}/{ads_to_watch}")
    print(f"     Earned  : {total_awarded} milliGOMINE ({total_awarded/1000:.3f} GOMINE)")
    print(f"  {'─'*50}")

    return total_awarded


async def main():
    # Parse args
    args = sys.argv[1:]
    no_ads = "--no-ads" in args
    max_ads = DEFAULT_MAX_ADS
    for i, a in enumerate(args):
        if a == "--max-ads" and i + 1 < len(args):
            max_ads = int(args[i + 1])

    # Read auth.txt
    auth_path = os.path.abspath(AUTH_FILE)
    if not os.path.exists(auth_path):
        print(f"❌ File tidak ditemukan: {auth_path}")
        print(f"   Buat file auth.txt dengan 1 initData per line")
        return

    with open(auth_path) as f:
        accounts = [line.strip() for line in f if line.strip()]

    if not accounts:
        print(f"❌ auth.txt kosong!")
        return

    print(f"🚀 GoMine Bot — {len(accounts)} account(s)")
    print(f"   Auth file : {auth_path}")
    print(f"   Ads       : {'OFF' if no_ads else f'ON (max {max_ads})'}")
    print(f"   Proxy     : {SOCKS_PROXY}")

    # Process each account (HTTP part)
    account_infos = []
    for i, init_data in enumerate(accounts):
        print(f"\n{'═'*60}")
        print(f"  ACCOUNT {i+1}/{len(accounts)}")
        print(f"{'═'*60}")

        info = process_account_http(init_data, max_ads, no_ads)
        if info:
            account_infos.append(info)

    # Ads via Firefox (shared browser for all accounts)
    if not no_ads and account_infos:
        total_earned = 0
        for info in account_infos:
            if info["ads_remaining"] > 0:
                earned = await run_ads_firefox(info, max_ads)
                total_earned += earned

        print(f"\n{'═'*60}")
        print(f"  🏆 GRAND TOTAL: {total_earned} milliGOMINE ({total_earned/1000:.3f} GOMINE)")
        print(f"{'═'*60}")

    # Next daily info
    print(f"\n⏰ Next daily checkin: esok hari (UTC)")
    print(f"   Jalankan script ini lagi setiap hari untuk auto-checkin + ads")


if __name__ == "__main__":
    asyncio.run(main())

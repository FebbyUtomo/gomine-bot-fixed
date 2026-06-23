#!/usr/bin/env python3
"""
get_initdata.py — Dapatkan initData dari GoMineAppBot

Cara pakai:
  1. Buka https://my.telegram.org/apps → ambil API_ID & API_HASH
  2. python3 get_initdata.py
  3. Masukin API_ID, API_HASH, nomor telepon
  4. Masukin kode OTP yang dikirim Telegram
  5. InitData otomatis tersimpan ke auth.txt
"""

import asyncio, json, os
from urllib.parse import parse_qs

from telethon import TelegramClient
from telethon.tl.functions.messages import RequestWebViewRequest

API_ID_INPUT = input("Masukkan API ID: ").strip()
API_HASH_INPUT = input("Masukkan API Hash: ").strip()

if not API_ID_INPUT or not API_HASH_INPUT:
    print("❌ API ID dan API Hash wajib diisi!")
    exit(1)

API_ID = int(API_ID_INPUT)
API_HASH = API_HASH_INPUT

SESSION_FILE = "gomine_session"
AUTH_OUTPUT = os.path.join(os.path.dirname(__file__) or ".", "auth.txt")

async def main():
    print("\n📡 Menyambung ke Telegram...")
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

    await client.start()
    print("✅ Berhasil login!\n")

    bot = await client.get_entity("GoMineAppBot")
    print(f"✅ Bot GoMineAppBot ditemukan!\n")

    result = await client(RequestWebViewRequest(
        peer=bot,
        bot=bot,
        url="https://app.gomine.social/",
        platform="android"
    ))

    url = result.url
    fragment = url.split("#")[1]
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    init_data = params["tgWebAppData"]

    # Baca auth.txt lama kalo ada
    existing = []
    if os.path.exists(AUTH_OUTPUT):
        with open(AUTH_OUTPUT) as f:
            existing = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    # Tambah initData baru (kalo belum ada)
    if init_data in existing:
        print("⚡ InitData ini sudah ada di auth.txt, skip duplikat.")
    else:
        with open(AUTH_OUTPUT, "a") as f:
            f.write(init_data + "\n")
        print(f"✅ InitData berhasil ditambahkan ke {AUTH_OUTPUT}!")

    print(f"\n📋 Preview InitData (20 karakter pertama): {init_data[:20]}...")
    print(f"\n📊 Total akun di auth.txt: {len(existing) + (0 if init_data in existing else 1)}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

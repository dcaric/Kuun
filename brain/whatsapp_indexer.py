#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "kuun.config")


def bridge_send_api() -> str:
    wa_port = os.getenv("WA_API_PORT", "8101")
    return os.getenv("WA_SEND_API_URL", f"http://localhost:{wa_port}")


def main():
    parser = argparse.ArgumentParser(description="Index locally stored WhatsApp messages into Kuun memory.")
    parser.add_argument("--sync", action="store_true", help="Ask the bridge to request more WhatsApp history first.")
    args = parser.parse_args()

    send_api = bridge_send_api()
    print(f"🔍 WhatsApp bridge API: {send_api}")

    if args.sync:
        try:
            resp = requests.get(f"{send_api}/sync-all", timeout=120)
            print(f"📜 Sync trigger: HTTP {resp.status_code} {resp.text[:300]}")
        except Exception as exc:
            print(f"⚠️ Could not trigger sync: {exc}")

    try:
        resp = requests.get(f"{send_api}/sync-status", timeout=10)
        if resp.status_code == 200:
            stats = resp.json()
            print(f"📦 Store: {stats.get('totalStored', 0)} messages across {stats.get('storeChats', 0)} chats")
    except Exception as exc:
        print(f"⚠️ Could not read sync status: {exc}")

    try:
        resp = requests.get(f"{send_api}/index-all", timeout=180)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Indexed {result.get('totalSent', 0)} messages from {result.get('chats', 0)} chats")
            print(f"📦 Total stored: {result.get('totalStored', 0)}")
        else:
            print(f"❌ Index failed: HTTP {resp.status_code} {resp.text[:300]}")
    except requests.exceptions.Timeout:
        print("⏱️ Index request timed out; it may still be running.")
    except Exception as exc:
        print(f"❌ Index error: {exc}")

    try:
        from brain.whatsapp_memory import WhatsAppMemory

        wm = WhatsAppMemory(silent=True)
        print(f"🧠 WhatsApp memory total: {wm.get_count()} messages")
    except Exception as exc:
        print(f"⚠️ Could not read WhatsApp memory count: {exc}")


if __name__ == "__main__":
    main()

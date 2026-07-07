from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
from typing import Any

from tglol.config import Config


ANDROID_DEVICES = [
    "Google Pixel 10 Pro XL",
    "Google Pixel 10 Pro",
    "Google Pixel 10",
    "Google Pixel 9 Pro XL",
    "Google Pixel 9 Pro",
    "Google Pixel 9",
    "Samsung Galaxy S25 Ultra",
    "Samsung Galaxy S25+",
    "Samsung Galaxy S25",
    "Samsung Galaxy S24 Ultra",
    "Samsung Galaxy S24+",
    "Samsung Galaxy S24",
]

ANDROID_VERSIONS = [
    "Android 16",
    "Android 15",
]

APP_VERSIONS = [
    "12.8.1",
    "12.8",
]


def random_android_runtime() -> dict[str, str]:
    return {
        "device": random.choice(ANDROID_DEVICES),
        "sdk": random.choice(ANDROID_VERSIONS),
        "app_version": random.choice(APP_VERSIONS),
        "lang_code": "en",
        "system_lang_code": "en-US",
        "lang_pack": "android",
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def random_created_at_iso() -> str:
    offset = timedelta(
        days=random.randint(0, 45),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    return (datetime.now(timezone.utc) - offset).isoformat(timespec="seconds")


def generated_account_json(
    config: Config,
    *,
    runtime: dict[str, str] | None = None,
    twofa: str | None = None,
    session_file: str | None = None,
    phone: str | None = None,
    user_id: int | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict[str, Any]:
    runtime = runtime or random_android_runtime()
    return {
        "app_id": config.telegram_api_id,
        "app_hash": config.telegram_api_hash,
        "device": runtime["device"],
        "sdk": runtime["sdk"],
        "app_version": runtime["app_version"],
        "lang_code": runtime.get("lang_code", config.default_lang_code),
        "system_lang_code": runtime.get("system_lang_code", config.default_system_lang_code),
        "lang_pack": runtime.get("lang_pack", config.default_lang_pack),
        "twoFA": twofa,
        "phone": phone,
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "session_file": session_file,
        "created_at": random_created_at_iso(),
    }

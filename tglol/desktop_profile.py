from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
from typing import Any

from tglol.config import Config


IPHONE_DEVICES = [
    "iPhone 16 Pro Max",
    "iPhone 16 Pro",
    "iPhone 16 Plus",
    "iPhone 16",
    "iPhone 15 Pro Max",
    "iPhone 15 Pro",
    "iPhone 15 Plus",
    "iPhone 15",
    "iPhone 14 Pro Max",
    "iPhone 14 Pro",
    "iPhone 14 Plus",
    "iPhone 14",
]

IOS_VERSIONS = [
    "iOS 18.6",
    "iOS 18.5",
]

APP_VERSIONS = [
    "12.8.1",
    "12.8",
]


def random_iphone_runtime() -> dict[str, str]:
    return {
        "device": random.choice(IPHONE_DEVICES),
        "sdk": random.choice(IOS_VERSIONS),
        "app_version": random.choice(APP_VERSIONS),
        "lang_code": "en",
        "system_lang_code": "en-US",
        "lang_pack": "ios",
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
    runtime = runtime or random_iphone_runtime()
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

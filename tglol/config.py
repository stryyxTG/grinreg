from dataclasses import dataclass
from pathlib import Path
import os
import re

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    telegram_api_id: int
    telegram_api_hash: str
    bot_parse_mode: str
    data_dir: Path
    sessions_dir: Path
    json_dir: Path
    temp_dir: Path
    db_path: Path
    default_lang_code: str
    default_system_lang_code: str
    default_lang_pack: str
    captcha_api_key: str | None = None
    captcha_service: str | None = None
    captcha_timeout: int = 120
    webapp_url: str | None = None


def _get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("PUT_"):
        raise RuntimeError(f"Set {name} in .env")
    return value


def _parse_admin_ids(raw: str, *, source: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in re.split(r"[\s,;]+", raw):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise RuntimeError(f"{source} must contain only numeric Telegram IDs")
        ids.add(int(item))
    if not ids:
        raise RuntimeError(f"Set {source} in .env")
    return frozenset(ids)


def _get_owner_ids() -> frozenset[int]:
    raw = os.getenv("OWNER_IDS", "").strip()
    if raw and not raw.startswith("PUT_"):
        return _parse_admin_ids(raw, source="OWNER_IDS")
    return _parse_admin_ids(_get_required("ADMIN_IDS"), source="ADMIN_IDS")


def load_config() -> Config:
    # Загружаем .env из корня проекта
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    data_dir = Path(os.getenv("DATA_DIR", "storage"))
    
    # Загружаем ключ капчи
    captcha_api_key = os.getenv("CAPTCHA_API_KEY", "").strip()
    if not captcha_api_key or captcha_api_key.startswith("PUT_") or captcha_api_key == "ваш_ключ_от_2captcha_или_capsolver":
        captcha_api_key = None
    
    captcha_service = os.getenv("CAPTCHA_SERVICE", "").strip().lower()
    if captcha_service not in ("2captcha", "rucaptcha", "capsolver"):
        captcha_service = None
    
    return Config(
        bot_token=_get_required("BOT_TOKEN"),
        admin_ids=_get_owner_ids(),
        telegram_api_id=int(_get_required("TELEGRAM_API_ID")),
        telegram_api_hash=_get_required("TELEGRAM_API_HASH"),
        bot_parse_mode=os.getenv("BOT_PARSE_MODE", "HTML"),
        data_dir=data_dir,
        sessions_dir=Path(os.getenv("SESSIONS_DIR", data_dir / "sessions")),
        json_dir=Path(os.getenv("JSON_DIR", data_dir / "json")),
        temp_dir=Path(os.getenv("TEMP_DIR", data_dir / "tmp")),
        db_path=Path(os.getenv("DB_PATH", data_dir / "bot.sqlite3")),
        default_lang_code=os.getenv("DEFAULT_LANG_CODE", "en"),
        default_system_lang_code=os.getenv("DEFAULT_SYSTEM_LANG_CODE", "en-US"),
        default_lang_pack=os.getenv("DEFAULT_LANG_PACK", "android"),
        captcha_api_key=captcha_api_key,
        captcha_service=captcha_service,
        captcha_timeout=int(os.getenv("CAPTCHA_TIMEOUT", "120")),
        webapp_url=os.getenv("WEBAPP_URL", "").strip() or None,
    )

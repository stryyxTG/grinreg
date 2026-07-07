from __future__ import annotations

from html import escape
from math import ceil
from pathlib import Path
import logging
import re
import secrets
import shutil
import zipfile

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message, TelegramObject
from telethon.errors import SessionPasswordNeededError

from tglol.captcha_solver import CaptchaSolver
from tglol.config import Config
from tglol.db import (
    add_account,
    add_captcha_request,
    clear_captcha_cooldown,
    count_accounts,
    delete_account_row,
    delete_all_accounts,
    get_account,
    get_captcha_stats,
    is_phone_on_captcha_cooldown,
    list_accounts,
    list_accounts_by_scope,
    set_captcha_cooldown,
    update_account_status,
)
from tglol.desktop_profile import generated_account_json, random_android_runtime, utc_now_iso
from tglol.json_utils import load_json, pick_api, runtime_from_json, write_json
from tglol.keyboards import (
    ACCOUNTS_PER_PAGE,
    account_detail_menu,
    accounts_menu,
    accounts_page_keyboard,
    confirm_check_account_menu,
    confirm_delete_account_menu,
    confirm_delete_all_accounts_menu,
    digit_code_keyboard,
)
from tglol.paths import unique_path
from tglol.states import AddByCode
from tglol.telegram_service import (
    TelegramCaptchaRequired,
    inspect_session,
    resend_code,
    send_code,
    send_login_email_code,
    sign_in_or_sign_up,
    sign_in_password,
    user_fields,
    verify_login_email_code,
)


router = Router()
logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        config: Config = data["config"]
        user = data.get("event_from_user")
        if not user:
            return None
        if user.id in config.admin_ids:
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or "").strip() == "/start":
            await event.answer("Нет доступа.")
        return None


router.message.outer_middleware(AccessMiddleware())
router.callback_query.outer_middleware(AccessMiddleware())


def _pages(total: int) -> int:
    return max(1, ceil(total / ACCOUNTS_PER_PAGE))


def _text(value) -> str:
    return escape(str(value)) if value not in (None, "") else "-"


def _copyable(value) -> str:
    return f"<code>{escape(str(value))}</code>" if value not in (None, "") else "-"


def _username(value) -> str:
    if value in (None, ""):
        return "-"
    username = str(value)
    if not username.startswith("@"):
        username = f"@{username}"
    return f"<code>{escape(username)}</code>"


def _origin_is_valid(origin: str) -> bool:
    return origin == "storage"


def _account_connection_params(account, config: Config) -> tuple[int, str, dict[str, str]]:
    data = None
    raw_path = account.json_original_path or account.json_effective_path
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            data = load_json(path)
    api_id, api_hash = pick_api(data, config)
    runtime = runtime_from_json(data or {})
    return api_id, api_hash, runtime


def _account_file_paths(account) -> list[Path]:
    paths: list[Path] = []
    for raw in (account.session_path, account.json_original_path, account.json_effective_path):
        if raw:
            path = Path(raw)
            if path not in paths:
                paths.append(path)
    return paths


def _resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_allowed_storage_file(config: Config, path: Path) -> bool:
    resolved = _resolved_path(path)
    allowed_roots = (config.data_dir, config.sessions_dir, config.json_dir, config.temp_dir)
    for root in allowed_roots:
        try:
            resolved.relative_to(_resolved_path(root))
            return path.exists() and path.is_file()
        except ValueError:
            continue
    return False


def _delete_local_account_files(config: Config, accounts: list) -> int:
    selected_ids = {account.id for account in accounts}
    remaining_paths = {
        str(_resolved_path(path))
        for account in list_accounts_by_scope(config)
        if account.id not in selected_ids
        for path in _account_file_paths(account)
    }
    removed = 0
    seen: set[str] = set()
    for account in accounts:
        for path in _account_file_paths(account):
            resolved = str(_resolved_path(path))
            if resolved in seen or resolved in remaining_paths:
                continue
            seen.add(resolved)
            if not _is_allowed_storage_file(config, path):
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _make_accounts_zip(config: Config, accounts: list) -> tuple[Path, int]:
    zip_path = unique_path(config.temp_dir, f"accounts_{secrets.token_hex(4)}.zip")
    files_count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive_names: set[str] = set()
        for account in accounts:
            added_paths: set[str] = set()
            for path in _account_file_paths(account):
                resolved = str(_resolved_path(path))
                if resolved in added_paths or not path.exists() or not path.is_file():
                    continue
                added_paths.add(resolved)
                archive_name = path.name
                if archive_name in archive_names:
                    archive_name = f"{account.id}_{path.name}"
                archive_names.add(archive_name)
                archive.write(path, arcname=archive_name)
                files_count += 1
    return zip_path, files_count


def _normalize_login_code(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _normalize_login_phone(raw: str) -> str | None:
    raw = (raw or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if raw.startswith("00") and len(digits) > 2:
        digits = digits[2:]
    if not 8 <= len(digits) <= 15:
        return None
    return f"+{digits}"


def _delivery_type_label(raw_type: str | None) -> str:
    labels = {
        "Authorized": "сессия уже авторизована",
        "SentCodeTypeApp": "в Telegram-приложение аккаунта",
        "SentCodeTypeSms": "SMS",
        "SentCodeTypeCall": "звонком",
        "SentCodeTypeFlashCall": "flash-call",
        "SentCodeTypeMissedCall": "пропущенным звонком",
        "SentCodeTypeEmailCode": "на email",
        "SentCodeTypeSetUpEmailRequired": "требуется указать email",
        "CodeTypeSms": "SMS",
        "CodeTypeCall": "звонком",
        "CodeTypeFlashCall": "flash-call",
        "CodeTypeMissedCall": "пропущенным звонком",
        "CodeTypeFragmentSms": "Fragment SMS",
    }
    return labels.get(raw_type or "", raw_type or "неизвестно")


def _code_request_text(request) -> str:
    lines = [
        "Telegram принял запрос кода.",
        f"Куда отправлен: {_delivery_type_label(request.delivery_type)}",
        f"Raw type: {request.delivery_type}",
    ]
    if request.code_length:
        lines.append(f"Длина кода: {request.code_length} цифр")
    if request.next_type:
        lines.append(f"Следующий способ: {_delivery_type_label(request.next_type)}")
    if request.timeout:
        lines.append(f"Повторный запрос будет доступен примерно через {request.timeout} сек.")
    if request.delivery_type == "SentCodeTypeSetUpEmailRequired":
        lines.append("")
        lines.append("Telegram просит привязать email перед продолжением регистрации.")
    elif request.delivery_type == "SentCodeTypeApp":
        lines.append("")
        lines.append("Telegram отправил код в приложение аккаунта. Email здесь не принимается API.")
        lines.append("Если кода нет, можно попробовать кнопку «Другой способ» после таймера.")
    elif request.delivery_type == "SentCodePaymentRequired":
        lines.append("")
        lines.append("Telegram требует платное подтверждение для этого номера. Обычный API не может продолжить регистрацию.")
    if request.delivery_type != "SentCodePaymentRequired":
        lines.append("")
        lines.append("Введите код кнопками или одним сообщением.")
    return "\n".join(lines)


def _code_entry_text(info_text: str, code: str) -> str:
    current = code if code else "-"
    return f"{info_text}\n\nТекущий ввод: <code>{current}</code>"


def _code_request_needs_email(request) -> bool:
    return request.delivery_type == "SentCodeTypeSetUpEmailRequired"


def _code_request_is_blocked(request) -> bool:
    return request.delivery_type == "SentCodePaymentRequired"


def _friendly_code_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, TelegramCaptchaRequired) or "RECAPTCHA_CHECK" in text:
        site_key = exc.site_key if isinstance(exc, TelegramCaptchaRequired) else None
        site_key_line = f"\nSiteKey: <code>{escape(site_key)}</code>" if site_key else ""
        return (
            "Telegram запросил reCAPTCHA для регистрации этого номера.\n\n"
            f"Page URL: <code>https://telegram.org</code>{site_key_line}\n\n"
            "Через обычный API-клиент бот не может безопасно показать или пройти эту проверку. "
            "Попробуй позже, другой номер/IP, либо регистрируй номер в официальном Telegram-приложении."
        )
    if "all available options" in text or "were already used" in text:
        return (
            "Telegram не дал SMS/звонок/email для этого номера.\n\n"
            "Даже если SIM сейчас твоя, у Telegram номер может числиться как уже занятый "
            "или привязанный к старой активной сессии. Попробуй другой номер или подожди."
        )
    if "PHONE_CODE_HASH" in text.upper() or "phone_code_hash" in text:
        return "Кодовый запрос устарел или не подходит для этого действия. Начни регистрацию заново."
    return f"Telegram вернул ошибку: {escape(text)}"


def _normalize_email(raw: str) -> str | None:
    email = (raw or "").strip()
    if not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return None
    return email


def _promote_login_session(config: Config, temp_session_path: Path, phone: str, login_id: str) -> Path:
    phone_digits = phone.lstrip("+")
    final_path = unique_path(config.sessions_dir, f"{phone_digits}_{login_id}.session")
    if temp_session_path.resolve() == final_path.resolve():
        return final_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if not temp_session_path.exists():
        raise RuntimeError(f"Temporary session file not found: {temp_session_path}")
    shutil.move(str(temp_session_path), str(final_path))
    return final_path


async def _show_storage_page(callback: CallbackQuery, config: Config, ref_id: int, page: int) -> None:
    total = count_accounts(config)
    page = max(0, min(page, _pages(total) - 1))
    accounts = list_accounts(config, limit=ACCOUNTS_PER_PAGE, offset=page * ACCOUNTS_PER_PAGE)

    if total == 0:
        text = "Хранилище\n\nАккаунтов пока нет."
    else:
        text = f"Хранилище\n\nВсего: {total}\nСтраница: {page + 1}/{_pages(total)}"

    await callback.message.edit_text(
        text,
        reply_markup=accounts_page_keyboard(
            accounts,
            total=total,
            page=page,
            origin="storage",
            ref_id=ref_id,
        ),
    )
    await callback.answer()


def _account_detail_text(account) -> str:
    full_name = " ".join(part for part in (account.first_name, account.last_name) if part not in (None, "")).strip()
    full_name = full_name or "-"
    return (
        f"<b>Аккаунт #{account.id}</b>\n"
        f"Статус: <code>{_text(account.status)}</code>\n\n"
        f"Имя: <b>{escape(full_name)}</b>\n"
        f"Номер: {_copyable(account.phone)}\n"
        f"Username: {_username(account.username)}\n"
        f"User ID: {_copyable(account.telegram_user_id)}\n\n"
        f"JSON: {_text(account.json_source)}\n"
        f"Источник: {_text(account.source_type)}"
    )


async def finalize_code_login(
    message: Message,
    state: FSMContext,
    config: Config,
    *,
    twofa: str | None,
    user,
) -> None:
    data = await state.get_data()
    await _finalize_code_login_impl(
        message,
        config,
        session_path=data["session_path"],
        phone=data["phone"],
        login_id=data["login_id"],
        runtime=data["runtime"],
        admin_id=data.get("admin_id") or (message.from_user.id if message.from_user else None),
        twofa=twofa,
        user=user,
        clear_state=True,
        state=state,
    )


async def _finalize_code_login_impl(
    message: Message,
    config: Config,
    *,
    session_path: str | Path,
    phone: str,
    login_id: str,
    runtime: dict[str, str],
    admin_id: int | None,
    twofa: str | None,
    user,
    clear_state: bool,
    state: FSMContext | None = None,
) -> None:
    session_path = _promote_login_session(config, Path(session_path), phone, login_id)
    fields = user_fields(user)
    json_path = unique_path(config.json_dir, session_path.with_suffix(".json").name)
    generated = generated_account_json(
        config,
        runtime=runtime,
        twofa=twofa,
        session_file=session_path.name,
        phone=fields["phone"],
        user_id=fields["telegram_user_id"],
        username=fields["username"],
        first_name=fields["first_name"],
        last_name=fields["last_name"],
    )
    write_json(json_path, generated)

    now = utc_now_iso()
    account_id = add_account(
        config,
        {
            "phone": fields["phone"],
            "telegram_user_id": fields["telegram_user_id"],
            "username": fields["username"],
            "first_name": fields["first_name"],
            "last_name": fields["last_name"],
            "session_path": str(session_path),
            "json_original_path": None,
            "json_effective_path": str(json_path),
            "json_source": "generated",
            "twofa_password": twofa,
            "source_type": "code",
            "status": "active",
            "created_by": admin_id,
            "created_at": now,
            "updated_at": now,
        },
    )
    if clear_state and state is not None:
        await state.clear()
    await message.answer(
        f"Аккаунт добавлен в хранилище.\nID: {account_id}\nТелефон: {fields['phone'] or '-'}",
        reply_markup=accounts_menu(),
    )


@router.message(F.text == "/captcha_stats")
async def captcha_stats(message: Message, config: Config) -> None:
    stats = get_captcha_stats(config)
    await message.answer(
        f"📊 <b>Статистика капчи</b>\n\n"
        f"В обработке: {stats['pending']}\n"
        f"В ожидании (cooldown): {stats['cooldown']}\n"
        f"Всего запросов: {stats['total']}",
        parse_mode="HTML",
    )


@router.message(F.text.startswith("/clear_captcha "))
async def clear_captcha(message: Message, config: Config) -> None:
    """Команда для админа: сброс cooldown для номера"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /clear_captcha +79001234567")
        return
    phone = _normalize_login_phone(parts[1])
    if not phone:
        await message.answer("Некорректный номер. Используйте формат: +79001234567")
        return
    clear_captcha_cooldown(config, phone)
    await message.answer(f"✅ Cooldown сброшен для номера {phone}")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Аккаунты", reply_markup=accounts_menu())


@router.callback_query(F.data == "accounts:menu")
async def show_accounts_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear
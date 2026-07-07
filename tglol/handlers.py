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
    count_accounts,
    delete_account_row,
    delete_all_accounts,
    get_account,
    list_accounts,
    list_accounts_by_scope,
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


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Аккаунты", reply_markup=accounts_menu())


@router.callback_query(F.data == "accounts:menu")
async def show_accounts_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Аккаунты", reply_markup=accounts_menu())
    await callback.answer()


@router.message(F.text == "/cancel")
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=accounts_menu())


@router.callback_query(F.data == "accounts:register")
async def add_by_code_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddByCode.waiting_phone)
    await callback.message.edit_text(
        "Отправь номер телефона.\n\nМожно с плюсом или без него, например:\n+15074486037\n15074486037"
    )
    await callback.answer()


@router.message(AddByCode.waiting_phone)
async def add_by_code_phone(message: Message, state: FSMContext, config: Config) -> None:
    phone = _normalize_login_phone(message.text or "")
    if not phone:
        await message.answer("Номер некорректный. Отправь номер с кодом страны, например: +15074486037")
        return

    runtime = random_android_runtime()
    admin_id = message.from_user.id if message.from_user else 0
    login_id = secrets.token_hex(4)
    phone_digits = phone.lstrip("+")
    session_path = unique_path(config.temp_dir, f"temp_session_{admin_id}_{phone_digits}_{login_id}.session")

    try:
        code_request = await send_code(
            session_path,
            phone,
            config.telegram_api_id,
            config.telegram_api_hash,
            runtime,
        )
    except TelegramCaptchaRequired as exc:
    # ===== ОБХОД КАПЧИ ЧЕРЕЗ RUCAPTCHA =====
        if not config.captcha_api_key or not config.captcha_service:
            await state.clear()
            await message.answer(
                f"❌ Telegram запросил капчу. Добавь CAPTCHA_API_KEY в .env для автоматического обхода.\n\n"
                f"SiteKey: <code>{exc.site_key or 'неизвестен'}</code>",
                reply_markup=accounts_menu(),
            )
            return

        try:
            solving_msg = await message.answer("⏳ Решаю reCAPTCHA через RuCaptcha...")
            
            solver = CaptchaSolver(
                api_key=config.captcha_api_key,
                service=config.captcha_service
            )
            
            token = await solver.solve_recaptcha_v2(
                sitekey=exc.site_key or "6LdcRsEqAAAAAHUaNCc1GUe47g5jKlOzbJJiyIZt",
                page_url="https://telegram.org",
                timeout=config.captcha_timeout or 120
            )
            
            await solving_msg.edit_text("✅ Капча решена! Отправляю код...")
            
            # Повторяем отправку с токеном капчи
            code_request = await send_code(
                session_path,
                phone,
                config.telegram_api_id,
                config.telegram_api_hash,
                runtime,
                captcha_token=token,
            )
            
        except Exception as e:
            await state.clear()
            await message.answer(f"❌ Не удалось решить капчу: {e}", reply_markup=accounts_menu())
            return
        # =======================================

    except Exception as exc:
        await state.clear()
        await message.answer(f"Не удалось отправить код Telegram:\n{_friendly_code_error(exc)}", reply_markup=accounts_menu())
        return

    await state.update_data(
        phone=phone,
        phone_code_hash=code_request.phone_code_hash,
        session_path=str(session_path),
        login_id=login_id,
        admin_id=admin_id,
        runtime=runtime,
        login_started_at=utc_now_iso(),
        code="",
    )
    if code_request.already_authorized and code_request.user:
        await finalize_code_login(message, state, config, twofa=None, user=code_request.user)
        return
    if code_request.already_authorized:
        await state.clear()
        await message.answer("Сессия уже авторизована, но Telegram не вернул данные аккаунта.", reply_markup=accounts_menu())
        return
    if _code_request_is_blocked(code_request):
        await state.clear()
        await message.answer(_code_request_text(code_request), reply_markup=accounts_menu())
        return
    if _code_request_needs_email(code_request):
        await state.set_state(AddByCode.waiting_email)
        await message.answer(
            f"Telegram просит указать email для регистрации.\n\n"
            f"Raw type: {code_request.delivery_type}\n\n"
            "Отправь email, на который придет код подтверждения."
        )
        return

    info_text = _code_request_text(code_request)
    await state.update_data(code_info_text=info_text)
    await state.set_state(AddByCode.waiting_code)
    await message.answer(_code_entry_text(info_text, ""), reply_markup=digit_code_keyboard())


@router.message(AddByCode.waiting_email)
async def add_by_code_email(message: Message, state: FSMContext, config: Config) -> None:
    email = _normalize_email(message.text or "")
    if not email:
        await message.answer("Email выглядит некорректно. Отправь email ещё раз.")
        return
    await _start_email_setup(message, state, config, email)


async def _start_email_setup(message: Message, state: FSMContext, config: Config, email: str) -> None:
    data = await state.get_data()
    phone_code_hash = data.get("phone_code_hash")
    if not phone_code_hash:
        await state.clear()
        await message.answer("Не найден phone_code_hash. Начни регистрацию заново.", reply_markup=accounts_menu())
        return

    try:
        email_request = await send_login_email_code(
            Path(data["session_path"]),
            data["phone"],
            phone_code_hash,
            email,
            config.telegram_api_id,
            config.telegram_api_hash,
            data["runtime"],
        )
    except Exception as exc:
        await message.answer(f"Не удалось отправить код на email: {exc}\nОтправь другой email или /cancel.")
        return

    await state.update_data(email=email, email_code_length=email_request.code_length)
    await state.set_state(AddByCode.waiting_email_code)
    await message.answer(
        f"Код отправлен на email: <code>{escape(email_request.email_pattern)}</code>\n"
        f"Длина кода: {email_request.code_length}\n\n"
        "Отправь код из письма одним сообщением."
    )


@router.message(AddByCode.waiting_email_code)
async def add_by_code_email_code(message: Message, state: FSMContext, config: Config) -> None:
    email_code = _normalize_login_code(message.text or "")
    if not email_code:
        await message.answer("Код с email пустой. Отправь код ещё раз.")
        return

    data = await state.get_data()
    phone_code_hash = data.get("phone_code_hash")
    if not phone_code_hash:
        await state.clear()
        await message.answer("Не найден phone_code_hash. Начни регистрацию заново.", reply_markup=accounts_menu())
        return

    expected_length = data.get("email_code_length")
    if expected_length and len(email_code) != int(expected_length):
        await message.answer(f"Код с email должен быть длиной {expected_length}. Отправь код ещё раз.")
        return

    try:
        code_request = await verify_login_email_code(
            Path(data["session_path"]),
            data["phone"],
            phone_code_hash,
            email_code,
            config.telegram_api_id,
            config.telegram_api_hash,
            data["runtime"],
        )
    except Exception as exc:
        await message.answer(f"Код с email не подошёл: {exc}\nОтправь код ещё раз или /cancel.")
        return

    await state.update_data(
        phone_code_hash=code_request.phone_code_hash,
        code="",
        code_info_text=_code_request_text(code_request),
    )
    if _code_request_is_blocked(code_request):
        await state.clear()
        await message.answer(_code_request_text(code_request), reply_markup=accounts_menu())
        return
    if _code_request_needs_email(code_request):
        await state.set_state(AddByCode.waiting_email)
        await message.answer(
            f"Telegram снова просит указать email для регистрации.\n\n"
            f"Raw type: {code_request.delivery_type}\n\n"
            "Отправь email, на который придет код подтверждения."
        )
        return

    info_text = _code_request_text(code_request)
    await state.update_data(code_info_text=info_text)
    await state.set_state(AddByCode.waiting_code)
    await message.answer(_code_entry_text(info_text, ""), reply_markup=digit_code_keyboard())


@router.message(AddByCode.waiting_code)
async def add_by_code_message_code(message: Message, state: FSMContext, config: Config) -> None:
    await complete_code(message, state, config, _normalize_login_code(message.text or ""))


@router.callback_query(AddByCode.waiting_code, F.data.startswith("code:"))
async def add_by_code_digit(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    data = await state.get_data()
    code = data.get("code", "")
    info_text = data.get("code_info_text", "Код отправлен в Telegram. Введите код кнопками или одним сообщением.")

    if callback.data.startswith("code:digit:"):
        if len(code) >= 8:
            await callback.answer("Максимум 8 цифр.")
            return
        code += callback.data.rsplit(":", 1)[-1]
        await state.update_data(code=code)
        await callback.message.edit_text(_code_entry_text(info_text, code), reply_markup=digit_code_keyboard())
        await callback.answer()
        return

    if callback.data == "code:clear":
        await state.update_data(code="")
        await callback.message.edit_text(_code_entry_text(info_text, ""), reply_markup=digit_code_keyboard())
        await callback.answer("Код очищен.")
        return

    if callback.data == "code:backspace":
        code = code[:-1]
        await state.update_data(code=code)
        await callback.message.edit_text(_code_entry_text(info_text, code), reply_markup=digit_code_keyboard())
        await callback.answer()
        return

    if callback.data == "code:done":
        await callback.answer()
        await complete_code(callback.message, state, config, code)
        return

    if callback.data == "code:resend":
        data = await state.get_data()
        phone_code_hash = data.get("phone_code_hash")
        if not phone_code_hash:
            await callback.answer("Нет phone_code_hash. Начни регистрацию заново.", show_alert=True)
            return
        try:
            code_request = await resend_code(
                Path(data["session_path"]),
                data["phone"],
                phone_code_hash,
                config.telegram_api_id,
                config.telegram_api_hash,
                data["runtime"],
            )
        except Exception as exc:
            await callback.answer("Telegram не дал другой способ.", show_alert=True)
            await callback.message.answer(_friendly_code_error(exc))
            return

        await state.update_data(
            phone_code_hash=code_request.phone_code_hash,
            code="",
            code_info_text=_code_request_text(code_request),
        )
        if _code_request_is_blocked(code_request):
            await state.clear()
            await callback.message.answer(_code_request_text(code_request), reply_markup=accounts_menu())
            await callback.answer()
            return
        if _code_request_needs_email(code_request):
            await state.set_state(AddByCode.waiting_email)
            await callback.message.answer(
                f"Telegram просит указать email для регистрации.\n\n"
                f"Raw type: {code_request.delivery_type}\n\n"
                "Отправь email, на который придет код подтверждения."
            )
        else:
            await callback.message.edit_text(_code_entry_text(_code_request_text(code_request), ""), reply_markup=digit_code_keyboard())
        await callback.answer("Способ обновлен.")


async def complete_code(message: Message, state: FSMContext, config: Config, code: str) -> None:
    code = _normalize_login_code(code)
    if not code:
        await message.answer("Код пустой.")
        return
    if not 5 <= len(code) <= 8:
        await message.answer("Код должен быть длиной 5-8 цифр. Введи заново.")
        return

    data = await state.get_data()
    phone_code_hash = data.get("phone_code_hash")
    if not phone_code_hash:
        await message.answer("Не найден phone_code_hash. Запроси код еще раз.", reply_markup=digit_code_keyboard())
        return
    try:
        user = await sign_in_or_sign_up(
            Path(data["session_path"]),
            data["phone"],
            code,
            phone_code_hash,
            config.telegram_api_id,
            config.telegram_api_hash,
            data["runtime"],
        )
    except SessionPasswordNeededError:
        await state.update_data(code=code)
        await state.set_state(AddByCode.waiting_twofa)
        await message.answer("Нужен пароль 2FA. Отправь пароль.")
        return
    except Exception as exc:
        await state.update_data(code="")
        await message.answer(f"Вход не удался: {exc}\nВведи код заново.", reply_markup=digit_code_keyboard())
        return

    await finalize_code_login(message, state, config, twofa=None, user=user)


@router.message(AddByCode.waiting_twofa)
async def add_by_code_twofa(message: Message, state: FSMContext, config: Config) -> None:
    password = message.text or ""
    data = await state.get_data()
    try:
        user = await sign_in_password(
            Path(data["session_path"]),
            password,
            config.telegram_api_id,
            config.telegram_api_hash,
            data["runtime"],
        )
    except Exception as exc:
        await message.answer(f"Проверка 2FA не прошла: {exc}")
        return
    await finalize_code_login(message, state, config, twofa=password, user=user)


@router.callback_query(F.data.startswith("accounts:page:"))
async def show_accounts_page(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    await state.clear()
    _, _, origin, raw_ref, raw_page = callback.data.split(":", 4)
    if not _origin_is_valid(origin):
        await callback.answer("Раздел больше недоступен.", show_alert=True)
        return
    await _show_storage_page(callback, config, int(raw_ref), int(raw_page))


@router.callback_query(F.data.startswith("accounts:phone:"))
async def send_account_phone(callback: CallbackQuery, config: Config) -> None:
    account_id = int(callback.data.rsplit(":", 1)[-1])
    account = get_account(config, account_id)
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    if not account.phone:
        await callback.answer("Номер не указан.", show_alert=True)
        return
    await callback.message.answer(_copyable(account.phone))
    await callback.answer("Номер отправлен.")


@router.callback_query(F.data.startswith("account:check_ask:"))
async def ask_check_account(callback: CallbackQuery, config: Config) -> None:
    _, _, raw_account_id, origin, raw_ref, raw_page = callback.data.split(":", 5)
    if not _origin_is_valid(origin):
        await callback.answer("Раздел больше недоступен.", show_alert=True)
        return
    account = get_account(config, int(raw_account_id))
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        "Проверить аккаунт?\n\nБот подключится к текущей session и проверит авторизацию. Новый код запрашиваться не будет.",
        reply_markup=confirm_check_account_menu(account.id, origin, int(raw_ref), int(raw_page)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("account:check_confirm:"))
async def confirm_check_account(callback: CallbackQuery, config: Config) -> None:
    _, _, raw_account_id, origin, raw_ref, raw_page = callback.data.split(":", 5)
    if not _origin_is_valid(origin):
        await callback.answer("Раздел больше недоступен.", show_alert=True)
        return
    account_id = int(raw_account_id)
    account = get_account(config, account_id)
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return

    session_path = Path(account.session_path)
    if not session_path.exists():
        update_account_status(config, account_id, "missing_file")
        account = get_account(config, account_id)
        await callback.message.edit_text(
            _account_detail_text(account),
            reply_markup=account_detail_menu(account.id, origin=origin, ref_id=int(raw_ref), page=int(raw_page)),
        )
        await callback.answer("Session файл не найден.", show_alert=True)
        return

    try:
        api_id, api_hash, runtime = _account_connection_params(account, config)
        status, user, note = await inspect_session(session_path, api_id, api_hash, runtime)
    except Exception as exc:
        status = "error"
        user = None
        note = str(exc)

    update_account_status(config, account_id, status)
    account = get_account(config, account_id)
    text = _account_detail_text(account)
    if status == "active" and user:
        fields = user_fields(user)
        text += (
            "\n\nПроверка: <b>живой</b>"
            f"\nTelegram ID: {_copyable(fields['telegram_user_id'])}"
            f"\nUsername: {_username(fields['username'])}"
        )
    elif status == "unauthorized":
        text += "\n\nПроверка: <b>не авторизован</b>"
    elif status == "empty":
        text += "\n\nПроверка: <b>Telegram не вернул данные аккаунта</b>"
    elif status == "twofa_required":
        text += "\n\nПроверка: <b>требуется 2FA</b>"
    else:
        text += f"\n\nПроверка: <b>ошибка</b>\n{_text(note)}"

    await callback.message.edit_text(
        text,
        reply_markup=account_detail_menu(account.id, origin=origin, ref_id=int(raw_ref), page=int(raw_page)),
    )
    await callback.answer("Проверка завершена.")


@router.callback_query(F.data.startswith("account:open:"))
async def show_account_detail_callback(callback: CallbackQuery, config: Config) -> None:
    _, _, raw_id, origin, raw_ref, raw_page = callback.data.split(":", 5)
    if not _origin_is_valid(origin):
        await callback.answer("Раздел больше недоступен.", show_alert=True)
        return
    account = get_account(config, int(raw_id))
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        _account_detail_text(account),
        reply_markup=account_detail_menu(account.id, origin=origin, ref_id=int(raw_ref), page=int(raw_page)),
    )
    await callback.answer()


@router.message(F.text.regexp(r"^/account_\d+$"))
async def show_account_detail_message(message: Message, config: Config) -> None:
    account_id = int((message.text or "").rsplit("_", 1)[-1])
    account = get_account(config, account_id)
    if not account:
        await message.answer("Аккаунт не найден.")
        return
    await message.answer(
        _account_detail_text(account),
        reply_markup=account_detail_menu(account.id, origin="storage", ref_id=0, page=0),
    )


@router.callback_query(F.data.startswith("accounts:file:"))
async def download_account_file(callback: CallbackQuery, config: Config) -> None:
    _, _, file_type, raw_id = callback.data.split(":", 3)
    account = get_account(config, int(raw_id))
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return

    path = Path(account.session_path) if file_type == "session" else Path(account.json_original_path or account.json_effective_path or "")
    if not path.exists():
        await callback.answer("Файл не найден.", show_alert=True)
        return

    await callback.message.answer_document(FSInputFile(path))
    await callback.answer()


@router.callback_query(F.data == "accounts:zip_all")
async def download_storage_zip(callback: CallbackQuery, config: Config) -> None:
    accounts = list_accounts_by_scope(config)
    if not accounts:
        await callback.answer("В хранилище нет аккаунтов.", show_alert=True)
        return
    zip_path, files_count = _make_accounts_zip(config, accounts)
    if files_count == 0:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        await callback.answer("Файлы для архива не найдены.", show_alert=True)
        return
    await callback.message.answer_document(
        FSInputFile(zip_path),
        caption=f"Хранилище: {len(accounts)} аккаунтов, {files_count} файлов.",
    )
    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass
    await callback.answer("ZIP сформирован.")


@router.callback_query(F.data.startswith("account:delete_ask:"))
async def ask_delete_account(callback: CallbackQuery, config: Config) -> None:
    _, _, raw_account_id, origin, raw_ref, raw_page = callback.data.split(":", 5)
    if not _origin_is_valid(origin):
        await callback.answer("Удаление здесь недоступно.", show_alert=True)
        return
    account = get_account(config, int(raw_account_id))
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        "ВЫ УВЕРЕНЫ ЧТО ХОТИТЕ УДАЛИТЬ АККАУНТ И ЕГО ФАЙЛЫ С СЕРВЕРА?",
        reply_markup=confirm_delete_account_menu(account.id, origin, int(raw_ref), int(raw_page)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("account:delete_confirm:"))
async def confirm_delete_account(callback: CallbackQuery, config: Config) -> None:
    _, _, raw_account_id, origin, _raw_ref, _raw_page = callback.data.split(":", 5)
    if not _origin_is_valid(origin):
        await callback.answer("Удаление здесь недоступно.", show_alert=True)
        return
    account = get_account(config, int(raw_account_id))
    if not account:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    removed_files = _delete_local_account_files(config, [account])
    delete_account_row(config, account.id)
    total = count_accounts(config)
    await callback.message.edit_text(
        f"Аккаунт #{account.id} удален из бота.\nФайлов удалено с сервера: {removed_files}\n\nХранилище: {total}",
        reply_markup=accounts_menu(),
    )
    await callback.answer("Удалено.")


@router.callback_query(F.data == "accounts:delete_all_ask")
async def ask_delete_all_accounts(callback: CallbackQuery, config: Config) -> None:
    total = count_accounts(config)
    if not total:
        await callback.answer("В хранилище нет аккаунтов.", show_alert=True)
        return
    await callback.message.edit_text(
        f"ВЫ УВЕРЕНЫ ЧТО ХОТИТЕ УДАЛИТЬ ВСЕ ХРАНИЛИЩЕ?\nАккаунтов: {total}\nФайлы будут удалены только с сервера.",
        reply_markup=confirm_delete_all_accounts_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:delete_all_confirm")
async def confirm_delete_all_accounts(callback: CallbackQuery, config: Config) -> None:
    accounts = list_accounts_by_scope(config)
    if not accounts:
        await callback.answer("В хранилище нет аккаунтов.", show_alert=True)
        return
    removed_files = _delete_local_account_files(config, accounts)
    removed_rows = delete_all_accounts(config)
    await callback.message.edit_text(
        f"Хранилище очищено.\nАккаунтов удалено из бота: {removed_rows}\nФайлов удалено с сервера: {removed_files}",
        reply_markup=accounts_menu(),
    )
    await callback.answer("Хранилище очищено.")
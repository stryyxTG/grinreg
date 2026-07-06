from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import random
from typing import Any

from telethon import TelegramClient
from telethon import functions, types
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeRequest:
    phone_code_hash: str | None
    delivery_type: str
    next_type: str | None
    timeout: int | None
    code_length: int | None
    already_authorized: bool = False
    user: User | None = None


@dataclass(frozen=True)
class EmailCodeRequest:
    email_pattern: str
    code_length: int


def client_for(
    session_path: Path,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> TelegramClient:
    return TelegramClient(
        str(session_path),
        api_id,
        api_hash,
        device_model=runtime.get("device") or "iPhone 16 Pro",
        system_version=runtime.get("sdk") or "iOS 18.6",
        app_version=runtime.get("app_version") or "12.8.1",
        lang_code=runtime.get("lang_code") or "en",
        system_lang_code=runtime.get("system_lang_code") or "en-US",
        connection_retries=2,
        request_retries=2,
        retry_delay=1,
        timeout=10,
    )


async def send_code(
    session_path: Path,
    phone: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
    *,
    unknown_number: bool = False,
) -> CodeRequest:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info("Telegram session is already authorized: phone=%s", phone)
            return CodeRequest(
                phone_code_hash=None,
                delivery_type="Authorized",
                next_type=None,
                timeout=None,
                code_length=None,
                already_authorized=True,
                user=me,
            )

        sent = await client(
            functions.auth.SendCodeRequest(
                phone_number=phone,
                api_id=api_id,
                api_hash=api_hash,
                settings=types.CodeSettings(unknown_number=unknown_number),
            )
        )
        logger.info(
            "Telegram login code requested: phone=%s delivery=%s next=%s timeout=%s length=%s",
            phone,
            type(sent.type).__name__,
            type(sent.next_type).__name__ if sent.next_type else None,
            sent.timeout,
            getattr(sent.type, "length", None),
        )
        return CodeRequest(
            phone_code_hash=sent.phone_code_hash,
            delivery_type=type(sent.type).__name__,
            next_type=type(sent.next_type).__name__ if sent.next_type else None,
            timeout=sent.timeout,
            code_length=getattr(sent.type, "length", None),
        )
    finally:
        await client.disconnect()


def code_request_from_sent_code(sent) -> CodeRequest:
    return CodeRequest(
        phone_code_hash=sent.phone_code_hash,
        delivery_type=type(sent.type).__name__,
        next_type=type(sent.next_type).__name__ if sent.next_type else None,
        timeout=sent.timeout,
        code_length=getattr(sent.type, "length", None),
    )


async def sign_in_code(
    session_path: Path,
    phone: str,
    code: str,
    phone_code_hash: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> User:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Login succeeded but account info is empty")
        return me
    finally:
        await client.disconnect()


async def send_login_email_code(
    session_path: Path,
    phone: str,
    phone_code_hash: str,
    email: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> EmailCodeRequest:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        result = await client(
            functions.account.SendVerifyEmailCodeRequest(
                purpose=types.EmailVerifyPurposeLoginSetup(phone, phone_code_hash),
                email=email,
            )
        )
        return EmailCodeRequest(
            email_pattern=result.email_pattern,
            code_length=result.length,
        )
    finally:
        await client.disconnect()


async def verify_login_email_code(
    session_path: Path,
    phone: str,
    phone_code_hash: str,
    email_code: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> CodeRequest:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        result = await client(
            functions.account.VerifyEmailRequest(
                purpose=types.EmailVerifyPurposeLoginSetup(phone, phone_code_hash),
                verification=types.EmailVerificationCode(email_code),
            )
        )
        if isinstance(result, types.account.EmailVerifiedLogin):
            return code_request_from_sent_code(result.sent_code)
        raise RuntimeError("Telegram подтвердил email, но не вернул код для телефона")
    finally:
        await client.disconnect()


def random_signup_name() -> tuple[str, str]:
    first_names = (
        "Alex",
        "Daniel",
        "Mark",
        "Nick",
        "Ryan",
        "Sam",
        "Tim",
        "Victor",
    )
    return random.choice(first_names), ""


async def sign_up_account(
    session_path: Path,
    phone: str,
    phone_code_hash: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
    *,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    first_name, default_last_name = random_signup_name() if not first_name else (first_name, "")
    last_name = default_last_name if last_name is None else last_name
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        result = await client(
            functions.auth.SignUpRequest(
                phone_number=phone,
                phone_code_hash=phone_code_hash,
                first_name=first_name,
                last_name=last_name,
                no_joined_notifications=True,
            )
        )
        return await client._on_login(result.user)
    finally:
        await client.disconnect()


async def sign_in_password(
    session_path: Path,
    password: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> User:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Login succeeded but account info is empty")
        return me
    finally:
        await client.disconnect()


async def inspect_session(
    session_path: Path,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> tuple[str, User | None, str | None]:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return "unauthorized", None, None
        me = await client.get_me()
        if me is None:
            return "empty", None, None
        return "active", me, None
    except SessionPasswordNeededError:
        return "twofa_required", None, None
    except Exception as exc:
        return "error", None, str(exc)
    finally:
        await client.disconnect()


def user_fields(user: User | None) -> dict[str, Any]:
    if user is None:
        return {
            "phone": None,
            "telegram_user_id": None,
            "username": None,
            "first_name": None,
            "last_name": None,
        }
    return {
        "phone": user.phone,
        "telegram_user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }

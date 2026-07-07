from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import random
import re
from typing import Any

from telethon import TelegramClient
from telethon import functions, types
from telethon.errors import PhoneNumberUnoccupiedError, RPCError, SessionPasswordNeededError
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


class TelegramCaptchaRequired(RuntimeError):
    def __init__(self, *, site_key: str | None = None) -> None:
        self.site_key = site_key
        super().__init__("Telegram requested reCAPTCHA for this registration attempt")


def _recaptcha_site_key(error_text: str) -> str | None:
    match = re.search(r"RECAPTCHA_CHECK_[^_]+__([A-Za-z0-9_-]+)", error_text)
    return match.group(1) if match else None


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
        device_model=runtime.get("device") or "Google Pixel 10 Pro",
        system_version=runtime.get("sdk") or "Android 16",
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

        try:
            sent = await client(
                functions.auth.SendCodeRequest(
                    phone_number=phone,
                    api_id=api_id,
                    api_hash=api_hash,
                    settings=types.CodeSettings(
                        allow_flashcall=True,
                        allow_missed_call=True,
                        unknown_number=unknown_number,
                    ),
                )
            )
        except RPCError as exc:
            error_text = str(exc)
            if "RECAPTCHA_CHECK" in error_text:
                logger.warning("Telegram requested reCAPTCHA during send_code: phone=%s", phone)
                raise TelegramCaptchaRequired(site_key=_recaptcha_site_key(error_text)) from exc
            raise
        request = code_request_from_sent_code(sent)
        logger.info(
            "Telegram login code requested: phone=%s delivery=%s next=%s timeout=%s length=%s",
            phone,
            request.delivery_type,
            request.next_type,
            request.timeout,
            request.code_length,
        )
        return request
    finally:
        await client.disconnect()


async def resend_code(
    session_path: Path,
    phone: str,
    phone_code_hash: str,
    api_id: int,
    api_hash: str,
    runtime: dict[str, str],
) -> CodeRequest:
    client = client_for(session_path, api_id, api_hash, runtime)
    await client.connect()
    try:
        sent = await client(functions.auth.ResendCodeRequest(phone, phone_code_hash))
        request = code_request_from_sent_code(sent)
        logger.info(
            "Telegram login code resent: phone=%s delivery=%s next=%s timeout=%s length=%s",
            phone,
            request.delivery_type,
            request.next_type,
            request.timeout,
            request.code_length,
        )
        return request
    finally:
        await client.disconnect()


def code_request_from_sent_code(sent) -> CodeRequest:
    if isinstance(sent, types.auth.SentCodeSuccess):
        return CodeRequest(
            phone_code_hash=None,
            delivery_type="SentCodeSuccess",
            next_type=None,
            timeout=None,
            code_length=None,
            already_authorized=True,
            user=sent.authorization.user,
        )
    if not hasattr(sent, "type"):
        return CodeRequest(
            phone_code_hash=getattr(sent, "phone_code_hash", None),
            delivery_type=type(sent).__name__,
            next_type=None,
            timeout=None,
            code_length=None,
        )
    return CodeRequest(
        phone_code_hash=sent.phone_code_hash,
        delivery_type=type(sent.type).__name__,
        next_type=type(sent.next_type).__name__ if sent.next_type else None,
        timeout=sent.timeout,
        code_length=getattr(sent.type, "length", None),
    )


async def sign_in_or_sign_up(
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
        try:
            result = await client(
                functions.auth.SignInRequest(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code,
                )
            )
        except PhoneNumberUnoccupiedError:
            result = types.auth.AuthorizationSignUpRequired()

        if isinstance(result, types.auth.AuthorizationSignUpRequired):
            first_name, last_name = random_signup_name()
            result = await client(
                functions.auth.SignUpRequest(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    first_name=first_name,
                    last_name=last_name,
                    no_joined_notifications=True,
                )
            )
        user = getattr(result, "user", None)
        if user is None:
            raise RuntimeError("Login succeeded but account info is empty")
        return await client._on_login(user)
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

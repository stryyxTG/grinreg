from __future__ import annotations

from collections.abc import Sequence
from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

ACCOUNTS_PER_PAGE = 14


def accounts_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Регистрация", callback_data="accounts:register")
    builder.button(text="Хранилище", callback_data="accounts:page:storage:0:0")
    builder.adjust(1)
    return builder.as_markup()


def digit_code_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for digit in "123456789":
        builder.button(text=digit, callback_data=f"code:digit:{digit}")
    builder.button(text="Очистить", callback_data="code:clear")
    builder.button(text="0", callback_data="code:digit:0")
    builder.button(text="Стереть", callback_data="code:backspace")
    builder.button(text="Подтвердить", callback_data="code:done")
    builder.button(text="Другой способ", callback_data="code:resend")
    builder.button(text="Отмена", callback_data="accounts:menu")
    builder.adjust(3, 3, 3, 3, 1, 1, 1)
    return builder.as_markup()


def _account_label(account) -> str:
    return account.phone or account.username or str(account.telegram_user_id or "без данных")


def accounts_page_keyboard(
    accounts: Sequence,
    *,
    total: int,
    page: int,
    origin: str,
    ref_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for account in accounts:
        builder.button(
            text=_account_label(account),
            callback_data=f"account:open:{account.id}:{origin}:{ref_id}:{page}",
        )

    if total:
        builder.button(text="Скачать ZIP", callback_data="accounts:zip_all")
        builder.button(text="Удалить всё", callback_data="accounts:delete_all_ask")

    pages = max(1, ceil(total / ACCOUNTS_PER_PAGE))
    nav_count = 0
    if page > 0:
        builder.button(text="< Назад", callback_data=f"accounts:page:{origin}:{ref_id}:{page - 1}")
        nav_count += 1
    builder.button(text=f"{page + 1}/{pages}", callback_data="noop")
    nav_count += 1
    if page + 1 < pages:
        builder.button(text="Вперед >", callback_data=f"accounts:page:{origin}:{ref_id}:{page + 1}")
        nav_count += 1

    builder.button(text="Меню аккаунтов", callback_data="accounts:menu")
    if total:
        builder.adjust(*([1] * len(accounts)), 1, 1, nav_count, 1)
    else:
        builder.adjust(nav_count, 1)
    return builder.as_markup()


def account_detail_menu(
    account_id: int,
    *,
    account_stage: str = "storage",
    origin: str,
    ref_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    _ = account_stage
    back = f"accounts:page:{origin}:{ref_id}:{page}"
    builder = InlineKeyboardBuilder()
    builder.button(text="Проверить аккаунт", callback_data=f"account:check_ask:{account_id}:{origin}:{ref_id}:{page}")
    builder.button(text="Скопировать номер", callback_data=f"accounts:phone:{account_id}")
    builder.button(text="Скачать session", callback_data=f"accounts:file:session:{account_id}")
    builder.button(text="Скачать JSON", callback_data=f"accounts:file:json:{account_id}")
    builder.button(text="Удалить аккаунт", callback_data=f"account:delete_ask:{account_id}:{origin}:{ref_id}:{page}")
    builder.button(text="Назад", callback_data=back)
    builder.adjust(1)
    return builder.as_markup()


def confirm_delete_account_menu(account_id: int, origin: str, ref_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="ДА, УДАЛИТЬ", callback_data=f"account:delete_confirm:{account_id}:{origin}:{ref_id}:{page}")
    builder.button(text="Отмена", callback_data=f"account:open:{account_id}:{origin}:{ref_id}:{page}")
    builder.adjust(1)
    return builder.as_markup()


def confirm_check_account_menu(account_id: int, origin: str, ref_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, проверить", callback_data=f"account:check_confirm:{account_id}:{origin}:{ref_id}:{page}")
    builder.button(text="Назад", callback_data=f"account:open:{account_id}:{origin}:{ref_id}:{page}")
    builder.adjust(1)
    return builder.as_markup()


def confirm_delete_all_accounts_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="ДА, УДАЛИТЬ ВСЕ", callback_data="accounts:delete_all_confirm")
    builder.button(text="Отмена", callback_data="accounts:page:storage:0:0")
    builder.adjust(1)
    return builder.as_markup()

def webapp_register_kb(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📱 Зарегистрировать аккаунт",
                web_app=WebAppInfo(url=webapp_url),
            )]
        ]
    )

from aiogram.fsm.state import State, StatesGroup


class AddByCode(StatesGroup):
    waiting_phone = State()
    waiting_email = State()
    waiting_email_code = State()
    waiting_code = State()
    waiting_twofa = State()

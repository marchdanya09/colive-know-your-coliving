from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from database.models import Room

def get_rooms_selection_kb(rooms: List[Room]) -> InlineKeyboardMarkup:
    buttons = []
    for r in rooms:
        count = len(r.users) if r.users else 0
        btn_text = f"🚪 {r.name} ({count}/{r.capacity})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"select_room_{r.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_my_room_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✉️ Написати своїй кімнаті", callback_data="room_broadcast_prompt")
            ],
            [
                InlineKeyboardButton(text="🚪 Залишити колівінг", callback_data="confirm_leave_coliving")
            ]
        ]
    )

def get_role_selection_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👑 Я Сотник (Адміністратор)", callback_data="role_sotnik")
            ],
            [
                InlineKeyboardButton(text="🙋‍♂️ Я мешканець", callback_data="role_resident")
            ]
        ]
    )

def get_sotnik_start_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Зареєструвати новий колівінг", callback_data="sotnik_create_new")
            ],
            [
                InlineKeyboardButton(text="🔗 Приєднатися як сотник за кодом", callback_data="role_resident")
            ]
        ]
    )

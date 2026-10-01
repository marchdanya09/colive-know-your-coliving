from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from database.models import Room

def get_back_kb(callback_data: str, text: str = "◀️ Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback_data)]
        ]
    )

def get_cancel_kb(callback_data: str, text: str = "❌ Скасувати") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback_data)]
        ]
    )

def get_rooms_selection_kb(rooms: List[Room], back_callback: str = "join_back_to_name") -> InlineKeyboardMarkup:
    buttons = []
    for r in rooms:
        count = len(r.users) if r.users else 0
        btn_text = f"🚪 {r.name} ({count}/{r.capacity})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"select_room_{r.id}")])
    # Додаємо кнопку Назад
    buttons.append([InlineKeyboardButton(text="◀️ Назад до зміни імені", callback_data=back_callback)])
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
                InlineKeyboardButton(text="🔗 Приєднатися як сотник за кодом", callback_data="sotnik_join_existing")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад до вибору ролі", callback_data="role_back_to_start")
            ]
        ]
    )

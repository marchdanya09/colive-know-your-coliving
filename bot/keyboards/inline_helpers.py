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

def get_my_room_actions_kb(is_sotnik: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="✉️ Написати кімнаті", callback_data="room_broadcast_prompt"),
            InlineKeyboardButton(text="📋 Обов'язки в кімнаті", callback_data="room_duties_menu")
        ],
        [
            InlineKeyboardButton(text="🏠 Весь колівінг", callback_data="user_nav_my_coliving"),
            InlineKeyboardButton(text="🔄 Оновити", callback_data="user_nav_my_room")
        ]
    ]
    if is_sotnik:
        buttons.append([
            InlineKeyboardButton(text="👑 Панель керування Сотника", callback_data="sotnik_back_panel")
        ])
    buttons.append([
        InlineKeyboardButton(text="🚪 Залишити колівінг", callback_data="confirm_leave_coliving")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_room_duties_kb(room: Room) -> InlineKeyboardMarkup:
    buttons = []
    for u in room.users:
        duty_badge = f" ({u.room_duty})" if u.room_duty and u.room_duty != "Не призначено" else ""
        starosta_icon = "⭐ " if u.room_role == "Староста" else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{starosta_icon}👤 {u.full_name}{duty_badge}",
                callback_data=f"room_member_duty_{u.id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="📝 Правила/чекліст кімнати", callback_data=f"room_edit_rules_{room.id}")
    ])
    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до кімнати", callback_data="user_nav_my_room")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_duty_picker_kb(user_id: int, current_room_role: str, back_callback: str) -> InlineKeyboardMarkup:
    starosta_btn_text = "👤 Зняти статус Старости" if current_room_role == "Староста" else "⭐ Призначити Старостою кімнати"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍳 Кухня", callback_data=f"set_duty_{user_id}_kitchen"),
                InlineKeyboardButton(text="🗑 Сміття", callback_data=f"set_duty_{user_id}_trash")
            ],
            [
                InlineKeyboardButton(text="🧼 Санвузол", callback_data=f"set_duty_{user_id}_bath"),
                InlineKeyboardButton(text="🧹 Порядок", callback_data=f"set_duty_{user_id}_order")
            ],
            [
                InlineKeyboardButton(text=starosta_btn_text, callback_data=f"toggle_starosta_{user_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Скинути обов'язок", callback_data=f"set_duty_{user_id}_none")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)
            ]
        ]
    )

def get_duties_page_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Обов'язки в моїй кімнаті", callback_data="room_duties_menu"),
                InlineKeyboardButton(text="🔄 Оновити", callback_data="user_nav_duties")
            ],
            [
                InlineKeyboardButton(text="🏠 Мій колівінг", callback_data="user_nav_my_coliving"),
                InlineKeyboardButton(text="🚪 Моя кімната", callback_data="user_nav_my_room")
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

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from database.models import User, Room
import texts

def get_sotnik_panel_kb(pending_count: int, is_locked: bool) -> InlineKeyboardMarkup:
    lock_label = "🔓 Відкрити прийом" if is_locked else "🔒 Закрити прийом"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📥 Вхідні запити ({pending_count})",
                    callback_data="sotnik_pending_list"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Мешканці колівінгу",
                    callback_data="sotnik_manage_members"
                ),
                InlineKeyboardButton(
                    text="⚙️ Штрафи та каса",
                    callback_data="sotnik_fines_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Чергування та ротація",
                    callback_data="sotnik_duty_menu"
                ),
                InlineKeyboardButton(
                    text="➕ Додати мешканця",
                    callback_data="sotnik_add_member"
                )
            ],
            [
                InlineKeyboardButton(
                    text=lock_label,
                    callback_data="sotnik_toggle_lock"
                ),
                InlineKeyboardButton(
                    text="🔑 Новий код",
                    callback_data="sotnik_regen_code"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚪 Додати нову кімнату",
                    callback_data="sotnik_add_room"
                ),
                InlineKeyboardButton(
                    text="✏️ Змінити назву/адресу",
                    callback_data="sotnik_edit_coliving"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 Інструкція прив'язки групи",
                    callback_data="sotnik_group_guide"
                )
            ]
        ]
    )


def get_sotnik_members_kb(users: List[User]) -> InlineKeyboardMarkup:
    buttons = []
    for u in users:
        role_icon = "👑 " if u.role == "SOTNIK" else "👤 "
        room_label = f" ({u.room.name})" if u.room else ""
        btn_text = f"{role_icon}{u.full_name}{room_label}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"sotnik_view_user_{u.id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад до панелі сотника", callback_data="sotnik_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sotnik_user_card_kb(user: User, current_tg_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🚪 Змінити кімнату", callback_data=f"sotnik_change_room_{user.id}")
        ]
    ]

    # Кнопка підвищення / пониження Сотника (якщо це не сам користувач)
    if user.role == "SOTNIK":
        buttons.append([InlineKeyboardButton(text="👤 Зняти статус Сотника", callback_data=f"sotnik_toggle_role_{user.id}")])
    else:
        buttons.append([InlineKeyboardButton(text="👑 Призначити Сотником", callback_data=f"sotnik_toggle_role_{user.id}")])

    # Кнопка Старости кімнати
    if user.room_role == "Староста":
        buttons.append([InlineKeyboardButton(text="⭐ Зняти статус Старости", callback_data=f"sotnik_toggle_starosta_{user.id}")])
    else:
        buttons.append([InlineKeyboardButton(text="⭐ Призначити Старостою кімнати", callback_data=f"sotnik_toggle_starosta_{user.id}")])

    duty_name = user.room_duty if user.room_duty and user.room_duty != "Не призначено" else "Не призначено"
    buttons.append([InlineKeyboardButton(text=f"📋 Призначити обов'язок ({duty_name})", callback_data=f"sotnik_pick_duty_{user.id}")])

    buttons.append([
        InlineKeyboardButton(text="💰 Нарахувати штраф", callback_data=f"sotnik_fine_user_{user.id}"),
        InlineKeyboardButton(text="💸 Списати штрафи", callback_data=f"sotnik_clear_fines_{user.id}")
    ])

    # Не можна видалити самого себе через цю кнопку
    if user.telegram_id != current_tg_id:
        buttons.append([
            InlineKeyboardButton(text="⛔ Видалити з колівінгу", callback_data=f"sotnik_kick_{user.id}")
        ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Назад до списку мешканців", callback_data="sotnik_manage_members")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sotnik_reassign_room_kb(user_id: int, rooms: List[Room], current_room_id: Optional[int]) -> InlineKeyboardMarkup:
    buttons = []
    for r in rooms:
        count = len(r.users) if r.users else 0
        is_cur = " (поточна)" if r.id == current_room_id else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"🚪 {r.name} ({count}/{r.capacity}){is_cur}",
                callback_data=f"sotnik_set_room_{user_id}_{r.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Скасувати", callback_data=f"sotnik_view_user_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sotnik_fines_kb(distribution: str, default_fine: float) -> InlineKeyboardMarkup:
    dist_label = "⚖️ Тип: На всю кімнату 🔄" if distribution == "ROOM" else "⚖️ Тип: На людину 🔄"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=dist_label, callback_data="sotnik_toggle_fine_dist")
            ],
            [
                InlineKeyboardButton(text="💵 50 грн", callback_data="sotnik_set_fine_50"),
                InlineKeyboardButton(text="💵 100 грн", callback_data="sotnik_set_fine_100"),
                InlineKeyboardButton(text="💵 200 грн", callback_data="sotnik_set_fine_200")
            ],
            [
                InlineKeyboardButton(text="✏️ Ввести власну суму штрафу", callback_data="sotnik_custom_fine_prompt")
            ],
            [
                InlineKeyboardButton(text="🏢 Оштрафувати кімнату", callback_data="sotnik_fine_room_select")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад до панелі", callback_data="sotnik_back_panel")
            ]
        ]
    )

def get_sotnik_duty_kb(rooms: List[Room], current_room_id: Optional[int]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⚡ Перемкнути на наступну кімнату", callback_data="sotnik_rotate_duty")
        ]
    ]
    for r in rooms:
        status_icon = "🔥 Зараз чергує: " if r.id == current_room_id else "👉 Призначити: "
        buttons.append([
            InlineKeyboardButton(text=f"{status_icon}{r.name}", callback_data=f"sotnik_set_duty_{r.id}")
        ])
    buttons.append([
        InlineKeyboardButton(text="📝 Налаштувати чекліст обов'язків", callback_data="sotnik_edit_duty_rules")
    ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад до панелі", callback_data="sotnik_back_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sotnik_duty_picker_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍳 Кухня", callback_data=f"sotnik_set_user_duty_{user_id}_kitchen"),
                InlineKeyboardButton(text="🗑 Сміття", callback_data=f"sotnik_set_user_duty_{user_id}_trash")
            ],
            [
                InlineKeyboardButton(text="🧼 Санвузол", callback_data=f"sotnik_set_user_duty_{user_id}_bath"),
                InlineKeyboardButton(text="🧹 Порядок", callback_data=f"sotnik_set_user_duty_{user_id}_order")
            ],
            [
                InlineKeyboardButton(text="✍️ Свій обов'язок", callback_data=f"sotnik_custom_duty_{user_id}"),
                InlineKeyboardButton(text="❌ Скинути", callback_data=f"sotnik_set_user_duty_{user_id}_none")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад до картки", callback_data=f"sotnik_view_user_{user_id}")
            ]
        ]
    )

def get_request_action_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Схвалити ✅", callback_data=f"req_app_{request_id}"),
                InlineKeyboardButton(text="Відхилити ❌", callback_data=f"req_rej_{request_id}")
            ],
            [
                InlineKeyboardButton(text="Заблокувати 🚫", callback_data=f"req_blk_{request_id}")
            ]
        ]
    )

def get_add_member_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📩 Готове повідомлення для пересилання", callback_data="sotnik_get_invite_text")
            ],
            [
                InlineKeyboardButton(text="🔑 Скопіювати лише код", callback_data="sotnik_get_raw_code")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад до панелі", callback_data="sotnik_back_panel")
            ]
        ]
    )


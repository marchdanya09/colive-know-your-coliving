from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import texts

def get_sotnik_panel_kb(pending_count: int, is_locked: bool) -> InlineKeyboardMarkup:
    lock_label = "🔓 Відкрити прийом заявок" if is_locked else "🔒 Закрити прийом заявок"
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
                    text="➕ Додати мешканця",
                    callback_data="sotnik_add_member"
                ),
                InlineKeyboardButton(
                    text=lock_label,
                    callback_data="sotnik_toggle_lock"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Ротація чергувань",
                    callback_data="sotnik_rotate_duty"
                ),
                InlineKeyboardButton(
                    text="🔑 Новий код колівінгу",
                    callback_data="sotnik_regen_code"
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

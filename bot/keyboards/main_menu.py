from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from typing import Optional
import texts

def get_main_keyboard(is_sotnik: bool = False, webapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text=texts.BTN_MY_COLIVING),
            KeyboardButton(text=texts.BTN_MY_ROOM)
        ],
        [
            KeyboardButton(text=texts.BTN_CALENDAR),
            KeyboardButton(text=texts.BTN_DUTIES)
        ],
        [
            KeyboardButton(text=texts.BTN_URGENT_COMPLAINT),
            KeyboardButton(text=texts.BTN_FINES)
        ]
    ]

    # Якщо передано URL для Web App
    if webapp_url:
        keyboard.append([
            KeyboardButton(text=texts.BTN_WEBAPP, web_app=WebAppInfo(url=webapp_url))
        ])

    # Якщо користувач є Сотником
    if is_sotnik:
        keyboard.append([
            KeyboardButton(text=texts.BTN_SOTNIK_PANEL)
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Оберіть розділ меню..."
    )


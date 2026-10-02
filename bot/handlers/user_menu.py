from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.db import AsyncSessionLocal
from database import crud
from bot.middlewares.anti_spam import rate_limiter
from bot.keyboards.inline_helpers import (
    get_my_room_actions_kb, get_cancel_kb, get_room_duties_kb,
    get_duty_picker_kb, get_duties_page_kb
)
from bot.keyboards.main_menu import get_main_keyboard
from config import settings
import texts
from typing import Optional

router = Router()

def get_user_main_kb(user, tg_id: int):
    is_sotnik = (user.role == "SOTNIK")
    webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={tg_id}&coliving_id={user.coliving_id}" if user.coliving_id else None
    return get_main_keyboard(is_sotnik=is_sotnik, webapp_url=webapp_url)

class ComplaintState(StatesGroup):
    waiting_for_media_or_text = State()
    waiting_for_comment = State()

class RoomBroadcastState(StatesGroup):
    waiting_for_text = State()

class DirectReplyState(StatesGroup):
    waiting_for_text = State()

class RoomRulesState(StatesGroup):
    waiting_for_rules = State()

class CustomDutyState(StatesGroup):
    waiting_for_duty_name = State()

MENU_BUTTONS = {
    texts.BTN_MY_COLIVING, texts.BTN_MY_ROOM, texts.BTN_CALENDAR,
    texts.BTN_DUTIES, texts.BTN_URGENT_COMPLAINT, texts.BTN_FINES,
    texts.BTN_SOTNIK_PANEL
}

# Команда /menu для миттєвого оновлення кнопок меню
@router.message(Command("menu"))
async def cmd_menu(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу. Скористайтеся /start для початку.")
            return
        await message.answer("📱 Головне меню оновлено!", reply_markup=get_user_main_kb(user, tg_id))

# 0. 🏠 Мій колівінг (Каталог усього простору з усіма мешканцями та контактами)
async def render_my_coliving(message_or_call, tg_id: int):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            msg = "⚠️ Ви ще не є затвердженим мешканцем колівінгу."
            if isinstance(message_or_call, CallbackQuery):
                await message_or_call.answer(msg, show_alert=True)
            else:
                await message_or_call.answer(msg)
            return

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        rooms = await crud.get_rooms_with_users(session, user.coliving_id)
        sotniks = await crud.get_sotniks(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)
        members_count = await crud.count_residents(session, user.coliving_id)

        duty_room_name = current_duty.room.name if (current_duty and current_duty.room) else "Не призначено"
        if current_duty and current_duty.room and current_duty.room.users:
            duty_members_str = ", ".join([u.full_name for u in current_duty.room.users])
        else:
            duty_members_str = "не призначено"

        sotniks_str = ", ".join([
            f"{s.full_name} (@{s.username})" if s.username else s.full_name
            for s in sotniks
        ]) if sotniks else "не призначено"

        directory_lines = []
        for r in rooms:
            directory_lines.append(f"\n🚪 <b>{r.name}</b> ({len(r.users)}/{r.capacity} осіб):")
            if not r.users:
                directory_lines.append("  <i>(Кімната поки що порожня)</i>")
            else:
                for u in r.users:
                    role_badge = " 👑 <i>Сотник</i>" if u.role == "SOTNIK" else ""
                    me_badge = " 👈 <b>(Ви)</b>" if u.id == user.id else ""
                    if u.username:
                        contact_str = f"@{u.username}"
                    else:
                        contact_str = f'<a href="tg://user?id={u.telegram_id}">написати в ЛС</a>'
                    directory_lines.append(f"  • <b>{u.full_name}</b> ({contact_str}){role_badge}{me_badge}")

        directory_text = "\n".join(directory_lines)

        inline_btns = []
        if user.role == "SOTNIK":
            inline_btns.append([InlineKeyboardButton(text="👑 Відкрити Панель Сотника", callback_data="sotnik_back_panel")])
        inline_btns.append([
            InlineKeyboardButton(text="🚪 Моя кімната", callback_data="user_nav_my_room"),
            InlineKeyboardButton(text="🔄 Оновити дані", callback_data="user_nav_my_coliving")
        ])

        kb = InlineKeyboardMarkup(inline_keyboard=inline_btns)
        text = texts.MY_COLIVING_INFO.format(
            name=coliving.name if coliving else "",
            address=coliving.address if coliving else "",
            members_count=members_count,
            max_people=coliving.total_people if coliving else 0,
            rooms_count=len(rooms),
            sotniks_str=sotniks_str,
            duty_room_name=duty_room_name,
            duty_members_str=duty_members_str,
            rooms_directory=directory_text
        )

        if isinstance(message_or_call, CallbackQuery):
            try:
                await message_or_call.message.edit_text(text, reply_markup=kb)
            except Exception:
                try:
                    await message_or_call.message.answer(text, reply_markup=kb)
                except Exception:
                    pass
            await message_or_call.answer("Дані оновлено! 🔄")
        else:
            await message_or_call.answer(text, reply_markup=kb)

@router.message(F.text == texts.BTN_MY_COLIVING)
async def menu_my_coliving(message: Message):
    await render_my_coliving(message, message.from_user.id)

# 1. 📅 Календар чергувань
@router.message(F.text == texts.BTN_CALENDAR)
async def menu_calendar(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу.")
            return

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)
        rooms = await crud.get_rooms_with_users(session, user.coliving_id)

        if current_duty and current_duty.room:
            duty_room = current_duty.room
            members = ", ".join([u.full_name for u in duty_room.users]) if duty_room.users else "немає призначених"
            dates_str = f"{current_duty.start_date.strftime('%d.%m')} - {current_duty.end_date.strftime('%d.%m')}"
        else:
            duty_room = rooms[0] if rooms else None
            members = "не визначено"
            dates_str = "поточний період"

        # Формуємо наступний графік
        upcoming = []
        if rooms:
            cur_idx = 0
            if current_duty:
                for idx, r in enumerate(rooms):
                    if r.id == current_duty.room_id:
                        cur_idx = idx
                        break
            for i in range(1, min(4, len(rooms))):
                nxt = rooms[(cur_idx + i) % len(rooms)]
                upcoming.append(f"• Наступний тиждень: <b>{nxt.name}</b>")

        upcoming_str = "\n".join(upcoming) if upcoming else "Графік формується"

        await message.answer(
            texts.CALENDAR_INFO.format(
                coliving_name=coliving.name if coliving else "",
                current_room=duty_room.name if duty_room else "Немає",
                current_members=members,
                period_dates=dates_str,
                upcoming_schedule=upcoming_str
            ),
            reply_markup=get_user_main_kb(user, tg_id)
        )

# 2. 🚪 Моя кімната
async def render_my_room(message_or_call, tg_id: int):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            msg = "⚠️ Ви ще не є затвердженим мешканцем колівінгу."
            if isinstance(message_or_call, CallbackQuery):
                await message_or_call.answer(msg, show_alert=True)
            else:
                await message_or_call.answer(msg)
            return

        room = await crud.get_room_by_id(session, user.room_id) if user.room_id else None
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        sotniks = await crud.get_sotniks(session, user.coliving_id)

        if not room:
            msg = "⚠️ Вас ще не розподілено в кімнату."
            if isinstance(message_or_call, CallbackQuery):
                await message_or_call.answer(msg, show_alert=True)
            else:
                await message_or_call.answer(msg, reply_markup=get_user_main_kb(user, tg_id))
            return

        members_lines = []
        for u in room.users:
            role_badge = " (👑 Сотник)" if u.role == "SOTNIK" else ""
            starosta_badge = " [⭐ Староста]" if u.room_role == "Староста" else ""
            duty_badge = f" | {u.room_duty}" if u.room_duty and u.room_duty != "Не призначено" else ""
            me_badge = " (Ви)" if u.id == user.id else ""
            username_part = f" (@{u.username})" if u.username else ""
            members_lines.append(f"• <b>{u.full_name}</b>{username_part}{role_badge}{starosta_badge}{duty_badge}{me_badge}")

        sotniks_str = ", ".join([s.full_name for s in sotniks]) if sotniks else "не призначено"
        is_sotnik = (user.role == "SOTNIK")

        text = texts.MY_ROOM_INFO.format(
            room_name=room.name,
            coliving_name=coliving.name if coliving else "",
            count=len(room.users),
            capacity=room.capacity,
            members_list="\n".join(members_lines),
            sotniks_list=sotniks_str
        )
        kb = get_my_room_actions_kb(is_sotnik=is_sotnik)

        if isinstance(message_or_call, CallbackQuery):
            try:
                await message_or_call.message.edit_text(text, reply_markup=kb)
            except Exception:
                try:
                    await message_or_call.message.answer(text, reply_markup=kb)
                except Exception:
                    pass
            await message_or_call.answer("Дані оновлено! 🔄")
        else:
            await message_or_call.answer(text, reply_markup=kb)

@router.message(F.text == texts.BTN_MY_ROOM)
async def menu_my_room(message: Message):
    await render_my_room(message, message.from_user.id)

@router.callback_query(F.data == "user_nav_my_coliving")
async def cb_nav_my_coliving(call: CallbackQuery):
    await render_my_coliving(call, call.from_user.id)

@router.callback_query(F.data == "user_nav_my_room")
async def cb_nav_my_room(call: CallbackQuery):
    await render_my_room(call, call.from_user.id)


async def check_menu_redirection(message: Message, state: FSMContext) -> bool:
    if message.text and message.text in MENU_BUTTONS:
        await state.clear()
        if message.text == texts.BTN_MY_COLIVING:
            await menu_my_coliving(message)
        elif message.text == texts.BTN_MY_ROOM:
            await menu_my_room(message)
        elif message.text == texts.BTN_CALENDAR:
            await menu_calendar(message)
        elif message.text == texts.BTN_DUTIES:
            await menu_duties(message)
        elif message.text == texts.BTN_URGENT_COMPLAINT:
            await menu_urgent_complaint(message, state)
        elif message.text == texts.BTN_FINES:
            await menu_fines(message)
        elif message.text == texts.BTN_SOTNIK_PANEL:
            from bot.handlers.sotnik_panel import menu_sotnik_panel
            await menu_sotnik_panel(message)
        return True
    return False


# --- Керування обов'язками в кімнаті ---

@router.callback_query(F.data == "room_duties_menu")
async def cb_room_duties_menu(call: CallbackQuery, answer: bool = True):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.room_id:
            if answer:
                await call.answer("Ви ще не розподілені в кімнату.", show_alert=True)
            return
        room = await crud.get_room_by_id(session, user.room_id)
        if not room:
            return

        members_list = []
        for u in room.users:
            starosta_str = " [⭐ Староста]" if u.room_role == "Староста" else ""
            duty_str = f" | {u.room_duty}" if u.room_duty and u.room_duty != "Не призначено" else " | Не призначено"
            sotnik_str = " (👑 Сотник)" if u.role == "SOTNIK" else ""
            members_list.append(f"• <b>{u.full_name}</b>{sotnik_str}{starosta_str}{duty_str}")
        members_duties_text = "\n".join(members_list) if members_list else "Немає мешканців"
        custom_rules = room.custom_duties or "Загальні правила чергування колівінгу"

        text = texts.ROOM_DUTIES_PAGE_INFO.format(
            room_name=room.name,
            members_duties_list=members_duties_text,
            custom_rules=custom_rules
        )
        kb = get_room_duties_kb(room)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except Exception:
            try:
                await call.message.answer(text, reply_markup=kb)
            except Exception:
                pass
    if answer:
        try:
            await call.answer()
        except Exception:
            pass


@router.callback_query(F.data.startswith("room_member_duty_"))
async def cb_room_member_duty(call: CallbackQuery):
    user_id = int(call.data.replace("room_member_duty_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, user_id)
        if not target_user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return
        kb = get_duty_picker_kb(user_id, target_user.room_role or "Мешканець", "room_duties_menu")
        await call.message.edit_text(
            f"⚙️ <b>Оберіть обов'язок або роль для {target_user.full_name}:</b>\n\n"
            f"• Поточний обов'язок: <b>{target_user.room_duty or 'Не призначено'}</b>\n"
            f"• Роль у кімнаті: <b>{target_user.room_role or 'Мешканець'}</b>",
            reply_markup=kb
        )
    await call.answer()


@router.callback_query(F.data.startswith("set_duty_"))
async def cb_set_duty(call: CallbackQuery):
    parts = call.data.replace("set_duty_", "").split("_")
    user_id = int(parts[0])
    duty_code = parts[1]
    duty_map = {
        "kitchen": "🍳 Кухня",
        "trash": "🗑 Сміття",
        "bath": "🧼 Санвузол",
        "order": "🧹 Порядок",
        "none": "Не призначено"
    }
    duty_name = duty_map.get(duty_code, "Не призначено")
    async with AsyncSessionLocal() as session:
        user = await crud.set_user_room_duty(session, user_id, duty_name)
        if user:
            try:
                notif = f"🔔 <b>Ваш обов'язок у кімнаті оновлено:</b> {duty_name}!"
                await call.bot.send_message(chat_id=user.telegram_id, text=notif)
            except Exception:
                pass

    await call.answer(f"Обов'язок встановлено: {duty_name}!", show_alert=True)
    await cb_room_duties_menu(call, answer=False)


@router.callback_query(F.data.startswith("toggle_starosta_"))
async def cb_toggle_starosta(call: CallbackQuery):
    user_id = int(call.data.replace("toggle_starosta_", ""))
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_id(session, user_id)
        if not user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return
        new_role = "Мешканець" if user.room_role == "Староста" else "Староста"
        await crud.set_user_room_role(session, user_id, new_role)
        try:
            notif = f"⭐ <b>Ваш статус у кімнаті оновлено:</b> {new_role}!"
            await call.bot.send_message(chat_id=user.telegram_id, text=notif)
        except Exception:
            pass

    await call.answer(f"Статус Старости оновлено: {new_role}!", show_alert=True)
    await cb_room_duties_menu(call, answer=False)


@router.callback_query(F.data.startswith("custom_duty_prompt_"))
async def cb_custom_duty_prompt(call: CallbackQuery, state: FSMContext):
    user_id = int(call.data.replace("custom_duty_prompt_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, user_id)
        if not target_user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return
        user_name = target_user.full_name
    await state.set_state(CustomDutyState.waiting_for_duty_name)
    await state.update_data(target_user_id=user_id)
    await call.message.edit_text(
        f"✍️ <b>Введіть назву власного обов'язку для {user_name}:</b>\n\n"
        "<i>(Наприклад: 🪴 Полив рослин, 📦 Прийом посилок, ☕ Закупівля кави/хімії тощо)</i>\n\n"
        "Максимальна довжина: до 40 символів.",
        reply_markup=get_cancel_kb("cancel_custom_duty", "◀️ Скасувати")
    )
    await call.answer()


@router.callback_query(F.data == "cancel_custom_duty")
async def cb_cancel_custom_duty(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Введення власного обов'язку скасовано.")
    await call.answer()
    await cb_room_duties_menu(call)


@router.message(CustomDutyState.waiting_for_duty_name)
async def process_custom_duty(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    duty_text = (message.text or message.caption or "").strip()
    if len(duty_text) < 2 or len(duty_text) > 40:
        await message.answer("⚠️ Назва обов'язку повинна містити від 2 до 40 символів. Спробуйте ще раз або оберіть пункт меню:")
        return
    await state.clear()
    if target_user_id:
        async with AsyncSessionLocal() as session:
            user = await crud.set_user_room_duty(session, target_user_id, duty_text)
            if user:
                try:
                    await message.bot.send_message(
                        chat_id=user.telegram_id,
                        text=f"🔔 <b>Ваш обов'язок у кімнаті оновлено:</b> {duty_text}!"
                    )
                except Exception:
                    pass
    await message.answer(f"✅ Власний обов'язок успішно встановлено: <b>{duty_text}</b>!")
    await render_my_room(message, message.from_user.id)


@router.callback_query(F.data.startswith("room_edit_rules_"))
async def cb_room_edit_rules(call: CallbackQuery, state: FSMContext):
    room_id = int(call.data.replace("room_edit_rules_", ""))
    await state.set_state(RoomRulesState.waiting_for_rules)
    await state.update_data(edit_room_id=room_id)
    await call.message.edit_text(
        "📝 <b>Введіть текст внутрішніх правил або чекліста для вашої кімнати:</b>\n"
        "(Наприклад: графік тиші, черговість миття раковини тощо)",
        reply_markup=get_cancel_kb("cancel_room_rules", "❌ Скасувати")
    )
    await call.answer()


@router.callback_query(F.data == "cancel_room_rules")
async def cb_cancel_room_rules(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Зміну правил скасовано.")
    await call.answer()
    await cb_room_duties_menu(call)


@router.message(RoomRulesState.waiting_for_rules)
async def process_room_edit_rules(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return
    data = await state.get_data()
    room_id = data.get("edit_room_id")
    await state.clear()
    rules_text = (message.text or message.caption or "").strip()
    if room_id and rules_text:
        async with AsyncSessionLocal() as session:
            await crud.set_room_custom_duties(session, room_id, rules_text)
    await message.answer("✅ Внутрішні правила кімнати збережено!")
    await render_my_room(message, message.from_user.id)


# --- Масова розсилка в ЛС кімнаті та особисті відповіді ---

@router.callback_query(F.data == "room_broadcast_prompt")
async def cb_room_broadcast_prompt(call: CallbackQuery, state: FSMContext):
    tg_id = call.from_user.id
    if not rate_limiter.can_broadcast_room(tg_id):
        await call.answer(texts.ROOM_BROADCAST_THROTTLED, show_alert=True)
        return
    await state.set_state(RoomBroadcastState.waiting_for_text)
    await call.message.answer(
        texts.ROOM_BROADCAST_PROMPT,
        reply_markup=get_cancel_kb("cancel_room_broadcast", "❌ Скасувати відправку")
    )
    await call.answer()


@router.callback_query(F.data == "cancel_room_broadcast")
async def cb_cancel_room_broadcast(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Відправку повідомлення кімнаті скасовано.")
    await call.answer()


@router.message(RoomBroadcastState.waiting_for_text)
async def process_room_broadcast(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return
    tg_id = message.from_user.id
    text = (message.text or message.caption or "").strip()
    await state.clear()

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.room_id:
            await message.answer("⚠️ Ви не прив'язані до кімнати.")
            return

        room = await crud.get_room_by_id(session, user.room_id)
        if not room:
            return

        # Розсилаємо всім сусідам по кімнаті з 2 кнопками відповіді
        sent_count = 0
        reply_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📢 Відповісти кімнаті", callback_data="room_broadcast_prompt"),
                    InlineKeyboardButton(text=f"👤 Відповісти {user.full_name}", callback_data=f"room_reply_user_{user.id}")
                ]
            ]
        )

        for neighbor in room.users:
            if neighbor.telegram_id != tg_id:
                try:
                    await message.bot.send_message(
                        chat_id=neighbor.telegram_id,
                        text=(
                            f"✉️ **Повідомлення від сусіда по кімнаті ({room.name}):**\n"
                            f"👤 **{user.full_name}:**\n\n"
                            f"{text}"
                        ),
                        reply_markup=reply_kb
                    )
                    sent_count += 1
                except Exception:
                    pass

        await message.answer(f"✅ Повідомлення надіслано сусідам ({sent_count} осіб)!")


@router.callback_query(F.data.startswith("room_reply_user_"))
async def cb_room_reply_user(call: CallbackQuery, state: FSMContext):
    target_user_id = int(call.data.replace("room_reply_user_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, target_user_id)
        if not target_user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return

    await state.set_state(DirectReplyState.waiting_for_text)
    await state.update_data(reply_target_id=target_user_id, reply_target_name=target_user.full_name)
    await call.message.answer(
        f"✉️ <b>Введіть особисту відповідь для {target_user.full_name}:</b>",
        reply_markup=get_cancel_kb("cancel_direct_reply", "❌ Скасувати відповідь")
    )
    await call.answer()


@router.callback_query(F.data == "cancel_direct_reply")
async def cb_cancel_direct_reply(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Відповідь скасовано.")
    await call.answer()


@router.message(DirectReplyState.waiting_for_text)
async def process_direct_reply(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return
    data = await state.get_data()
    target_id = data.get("reply_target_id")
    await state.clear()

    sender_tg_id = message.from_user.id
    reply_text = (message.text or message.caption or "").strip()

    async with AsyncSessionLocal() as session:
        sender = await crud.get_user_by_tg_id(session, sender_tg_id)
        target = await crud.get_user_by_id(session, target_id)
        if not target or not sender:
            await message.answer("⚠️ Не вдалося доставити відповідь.")
            return

        sender_room = await crud.get_room_by_id(session, sender.room_id) if sender.room_id else None
        room_name = sender_room.name if sender_room else "Колівінг"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=f"👤 Відповісти {sender.full_name}", callback_data=f"room_reply_user_{sender.id}"),
                    InlineKeyboardButton(text="📢 Відповісти кімнаті", callback_data="room_broadcast_prompt")
                ]
            ]
        )

        try:
            await message.bot.send_message(
                chat_id=target.telegram_id,
                text=(
                    f"✉️ <b>Особиста відповідь від {sender.full_name} ({room_name}):</b>\n\n"
                    f"{reply_text}"
                ),
                reply_markup=kb
            )
            await message.answer(f"✅ Відповідь успішно надіслано користувачу {target.full_name}!")
        except Exception:
            await message.answer("⚠️ Не вдалося надіслати повідомлення.")


# Залишити колівінг — підтвердження
@router.callback_query(F.data == "confirm_leave_coliving")
async def cb_confirm_leave_coliving(call: CallbackQuery):
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Так, вийти з колівінгу 🚪", callback_data="do_leave_coliving")
            ],
            [
                InlineKeyboardButton(text="◀️ Скасувати / Залишитися", callback_data="cancel_leave_coliving")
            ]
        ]
    )
    await call.message.edit_text("⚠️ **Ви впевнені, що хочете залишити колівінг?**\nВсі ваші дані прив'язки до кімнати буде скинуто.", reply_markup=confirm_kb)
    await call.answer()


@router.callback_query(F.data == "cancel_leave_coliving")
async def cb_cancel_leave_coliving(call: CallbackQuery):
    await call.message.edit_text("✅ Дія скасована. Ви залишаєтесь у своєму колівінгу.")
    await call.answer()


@router.callback_query(F.data == "do_leave_coliving")
async def cb_do_leave_coliving(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        await crud.remove_user_from_coliving(session, tg_id)
    await call.message.edit_text("🚪 Ви покинули колівінг. Щоб зареєструватися знову, скористайтесь /start.")
    await call.message.answer("👋 Меню оновлено.", reply_markup=ReplyKeyboardRemove())
    await call.answer()


# 3. 📋 Мої обов'язки (Динамічний екран)
async def render_duties_page(message_or_call, tg_id: int):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            msg = "⚠️ Ви ще не є затвердженим мешканцем колівінгу."
            if isinstance(message_or_call, CallbackQuery):
                await message_or_call.answer(msg, show_alert=True)
            else:
                await message_or_call.answer(msg)
            return

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)
        my_room = await crud.get_room_by_id(session, user.room_id) if user.room_id else None

        duty_room_name = current_duty.room.name if (current_duty and current_duty.room) else "Не призначено"
        is_my_room_duty = (current_duty and current_duty.room_id == user.room_id)

        if is_my_room_duty:
            duty_status = "🚨 <b>ЗАРАЗ ЧЕРГУЄ ВАША КІМНАТА!</b> Будь ласка, слідкуйте за порядком."
        else:
            duty_status = f"🧹 Зараз чергує: <b>{duty_room_name}</b>"

        room_members_list = []
        if my_room and my_room.users:
            for u in my_room.users:
                starosta = " [⭐ Староста]" if u.room_role == "Староста" else ""
                duty_val = u.room_duty if u.room_duty and u.room_duty != "Не призначено" else "Не призначено"
                sotnik_badge = " (👑 Сотник)" if u.role == "SOTNIK" else ""
                room_members_list.append(f"  • <b>{u.full_name}</b>{sotnik_badge}{starosta}: <i>{duty_val}</i>")
        room_members_str = "\n".join(room_members_list) if room_members_list else "  (Мешканців немає)"

        checklist = coliving.custom_duty_rules if (coliving and coliving.custom_duty_rules) else texts.DEFAULT_DUTIES_CHECKLIST
        my_role_str = "👑 Сотник" if user.role == "SOTNIK" else "👤 Мешканець"
        if user.room_role == "Староста":
            my_role_str += " (⭐ Староста кімнати)"

        text = texts.DUTIES_PAGE_INFO.format(
            coliving_name=coliving.name if coliving else "",
            my_room_name=my_room.name if my_room else "Не призначено",
            my_duty=user.room_duty or "Не призначено",
            my_role=my_role_str,
            duty_status=duty_status,
            room_members_duties=room_members_str,
            checklist=checklist
        )
        kb = get_duties_page_kb()

        if isinstance(message_or_call, CallbackQuery):
            try:
                await message_or_call.message.edit_text(text, reply_markup=kb)
            except Exception:
                pass
            await message_or_call.answer("Дані оновлено! 🔄")
        else:
            await message_or_call.answer(text, reply_markup=kb)

@router.message(F.text == texts.BTN_DUTIES)
async def menu_duties(message: Message):
    await render_duties_page(message, message.from_user.id)

@router.callback_query(F.data == "user_nav_duties")
async def cb_user_nav_duties(call: CallbackQuery):
    await render_duties_page(call, call.from_user.id)


# 4. 🚨 Термінові скарги (Підтримка фото, відео, кружечків та тексту)

async def submit_complaint(
    bot,
    tg_id: int,
    photo_file_id: Optional[str] = None,
    video_file_id: Optional[str] = None,
    video_note_id: Optional[str] = None,
    comment: str = "Неприбраний спільний простір"
):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id:
            return False, "Користувач не знайдений"

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)
        sotniks = await crud.get_sotniks(session, user.coliving_id)
        user_room = await crud.get_room_by_id(session, user.room_id) if user.room_id else None
        room_name = user_room.name if user_room else "Не призначено"

        target_room = current_duty.room if (current_duty and current_duty.room) else None

        await crud.create_complaint(
            session=session,
            coliving_id=user.coliving_id,
            reporter_id=user.id,
            target_room_id=target_room.id if target_room else (user.room_id or 1),
            photo_file_id=photo_file_id or video_file_id or video_note_id or "text_only",
            comment=comment
        )

        # 1. Надсилаємо черговій кімнаті якщо вона є
        if target_room and target_room.users:
            for member in target_room.users:
                try:
                    caption_text = texts.COMPLAINT_DM_ALERT.format(comment=comment)
                    if photo_file_id:
                        await bot.send_photo(chat_id=member.telegram_id, photo=photo_file_id, caption=caption_text)
                    elif video_file_id:
                        await bot.send_video(chat_id=member.telegram_id, video=video_file_id, caption=caption_text)
                    elif video_note_id:
                        await bot.send_video_note(chat_id=member.telegram_id, video_note=video_note_id)
                        await bot.send_message(chat_id=member.telegram_id, text=caption_text)
                    else:
                        await bot.send_message(chat_id=member.telegram_id, text=f"🚨 <b>УВАГА! СПОВІЩЕННЯ ДЛЯ ЧЕРГОВОЇ КІМНАТИ!</b>\n\n📍 <b>Повідомлення:</b> {comment}\n\n⏰ Будь ласка, наведіть лад!")
                except Exception:
                    pass
        else:
            # Чергової кімнати немає -> сповіщаємо сотників
            for s in sotniks:
                try:
                    alert_text = texts.COMPLAINT_SOTNIK_ALERT.format(
                        reporter_name=user.full_name,
                        room_name=room_name,
                        comment=comment
                    )
                    if photo_file_id:
                        await bot.send_photo(chat_id=s.telegram_id, photo=photo_file_id, caption=alert_text)
                    elif video_file_id:
                        await bot.send_video(chat_id=s.telegram_id, video=video_file_id, caption=alert_text)
                    elif video_note_id:
                        await bot.send_video_note(chat_id=s.telegram_id, video_note=video_note_id)
                        await bot.send_message(chat_id=s.telegram_id, text=alert_text)
                    else:
                        await bot.send_message(chat_id=s.telegram_id, text=alert_text)
                except Exception:
                    pass

        # 2. Якщо підключена група
        if coliving and coliving.group_chat_id:
            tags = " ".join([
                f"@{u.username}" if u.username else f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>'
                for u in (target_room.users if target_room else sotniks)
            ])
            caption_group = texts.COMPLAINT_GROUP_ALERT.format(
                room_name=target_room.name if target_room else "Сотники",
                duty_tags=tags,
                comment=comment
            )
            try:
                if photo_file_id:
                    await bot.send_photo(chat_id=coliving.group_chat_id, message_thread_id=coliving.duty_topic_id, photo=photo_file_id, caption=caption_group)
                elif video_file_id:
                    await bot.send_video(chat_id=coliving.group_chat_id, message_thread_id=coliving.duty_topic_id, video=video_file_id, caption=caption_group)
                else:
                    await bot.send_message(chat_id=coliving.group_chat_id, message_thread_id=coliving.duty_topic_id, text=caption_group)
            except Exception:
                pass

        return True, "Скаргу успішно надіслано!"


@router.message(F.text == texts.BTN_URGENT_COMPLAINT)
async def menu_urgent_complaint(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if not rate_limiter.can_send_complaint(tg_id):
        await message.answer(texts.COMPLAINT_THROTTLED)
        return

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу.")
            return

    await state.set_state(ComplaintState.waiting_for_media_or_text)
    await message.answer(
        texts.COMPLAINT_INTRO,
        reply_markup=get_cancel_kb("cancel_complaint", "❌ Скасувати скаргу")
    )


@router.callback_query(F.data == "cancel_complaint")
async def cb_cancel_complaint(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Подання термінової скарги скасовано.")
    await call.answer()


@router.message(ComplaintState.waiting_for_media_or_text)
async def process_complaint_first_step(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return

    tg_id = message.from_user.id

    if message.photo:
        photo_id = message.photo[-1].file_id
        if message.caption:
            await state.clear()
            await submit_complaint(message.bot, tg_id, photo_file_id=photo_id, comment=message.caption.strip())
            await message.answer(texts.COMPLAINT_SENT_SUCCESS)
        else:
            await state.update_data(photo_file_id=photo_id)
            await state.set_state(ComplaintState.waiting_for_comment)
            await message.answer(texts.COMPLAINT_COMMENT_PROMPT, reply_markup=get_cancel_kb("cancel_complaint", "❌ Скасувати скаргу"))
    elif message.video:
        video_id = message.video.file_id
        if message.caption:
            await state.clear()
            await submit_complaint(message.bot, tg_id, video_file_id=video_id, comment=message.caption.strip())
            await message.answer(texts.COMPLAINT_SENT_SUCCESS)
        else:
            await state.update_data(video_file_id=video_id)
            await state.set_state(ComplaintState.waiting_for_comment)
            await message.answer(texts.COMPLAINT_COMMENT_PROMPT, reply_markup=get_cancel_kb("cancel_complaint", "❌ Скасувати скаргу"))
    elif message.video_note:
        await state.clear()
        await submit_complaint(message.bot, tg_id, video_note_id=message.video_note.file_id, comment="Відеосповіщення")
        await message.answer(texts.COMPLAINT_SENT_SUCCESS)
    elif message.text:
        # Пряме текстове повідомлення скарги
        await state.clear()
        await submit_complaint(message.bot, tg_id, comment=message.text.strip())
        await message.answer(texts.COMPLAINT_SENT_SUCCESS)
    else:
        await message.answer("Будь ласка, надішліть фото, відео або текстовий опис проблеми:")


@router.message(ComplaintState.waiting_for_comment)
async def process_complaint_comment_step(message: Message, state: FSMContext):
    if await check_menu_redirection(message, state):
        return

    tg_id = message.from_user.id
    comment = (message.text or message.caption or "").strip()
    if not comment or comment == "-":
        comment = "Неприбраний спільний простір"

    data = await state.get_data()
    photo_file_id = data.get("photo_file_id")
    video_file_id = data.get("video_file_id")
    await state.clear()

    await submit_complaint(message.bot, tg_id, photo_file_id=photo_file_id, video_file_id=video_file_id, comment=comment)
    await message.answer(texts.COMPLAINT_SENT_SUCCESS)

# 5. 💰 Штрафи
@router.message(F.text == texts.BTN_FINES)
async def menu_fines(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу.")
            return

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        room = await crud.get_room_by_id(session, user.room_id) if user.room_id else None

        fine_type_label = "На всю кімнату порівну" if coliving.fine_distribution == "ROOM" else "Персонально на людину"
        room_fines_total = sum([u.unpaid_fines for u in room.users]) if room else 0.0

        await message.answer(
            texts.FINES_INFO.format(
                fine_amount=coliving.default_fine_amount,
                fine_type=fine_type_label,
                treasury_balance=coliving.treasury_balance,
                user_fines=user.unpaid_fines,
                room_fines=room_fines_total
            ),
            reply_markup=get_user_main_kb(user, tg_id)
        )


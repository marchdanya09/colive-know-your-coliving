from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.db import AsyncSessionLocal
from database import crud
from bot.middlewares.anti_spam import rate_limiter
from bot.keyboards.inline_helpers import get_my_room_actions_kb, get_cancel_kb
from bot.keyboards.main_menu import get_main_keyboard
from config import settings
import texts

router = Router()

def get_user_main_kb(user, tg_id: int):
    is_sotnik = (user.role == "SOTNIK")
    webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={tg_id}&coliving_id={user.coliving_id}" if user.coliving_id else None
    return get_main_keyboard(is_sotnik=is_sotnik, webapp_url=webapp_url)

class ComplaintState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_comment = State()

class RoomBroadcastState(StatesGroup):
    waiting_for_text = State()

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
            role_badge = " (Сотник 👑)" if u.role == "SOTNIK" else ""
            me_badge = " (Ви)" if u.id == user.id else ""
            username_part = f" (@{u.username})" if u.username else ""
            members_lines.append(f"• <b>{u.full_name}</b>{username_part}{role_badge}{me_badge}")

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



# Масова розсилка в ЛС кімнаті
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
    tg_id = message.from_user.id
    text = message.text.strip()
    await state.clear()

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.room_id:
            await message.answer("⚠️ Ви не прив'язані до кімнати.")
            return

        room = await crud.get_room_by_id(session, user.room_id)
        if not room:
            return

        # Розсилаємо всім сусідам по кімнаті, крім самого відправника
        sent_count = 0
        for neighbor in room.users:
            if neighbor.telegram_id != tg_id:
                try:
                    await message.bot.send_message(
                        chat_id=neighbor.telegram_id,
                        text=(
                            f"✉️ **Повідомлення від сусіда по кімнаті ({room.name}):**\n"
                            f"👤 **{user.full_name}:**\n\n"
                            f"{text}"
                        )
                    )
                    sent_count += 1
                except Exception:
                    pass

        await message.answer(f"✅ Повідомлення надіслано сусідам ({sent_count} осіб)!")

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

# 3. 📋 Мої обов'язки
@router.message(F.text == texts.BTN_DUTIES)
async def menu_duties(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу.")
            return
        await message.answer(texts.DUTIES_INFO, reply_markup=get_user_main_kb(user, tg_id))

# 4. 🚨 Термінові скарги
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

    await state.set_state(ComplaintState.waiting_for_photo)
    await message.answer(
        texts.COMPLAINT_INTRO,
        reply_markup=get_cancel_kb("cancel_complaint", "❌ Скасувати скаргу")
    )

@router.callback_query(F.data == "cancel_complaint")
async def cb_cancel_complaint(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Подання термінової скарги скасовано.")
    await call.answer()

@router.message(ComplaintState.waiting_for_photo, F.photo)
async def complaint_photo(message: Message, state: FSMContext):
    # Беремо найбільший розмір фото
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)
    await state.set_state(ComplaintState.waiting_for_comment)
    await message.answer(
        texts.COMPLAINT_COMMENT_PROMPT,
        reply_markup=get_cancel_kb("cancel_complaint", "❌ Скасувати скаргу")
    )

@router.message(ComplaintState.waiting_for_comment)
async def complaint_comment(message: Message, state: FSMContext):
    comment_text = message.text.strip()
    if comment_text == "-":
        comment_text = "Неприбраний спільний простір"

    data = await state.get_data()
    photo_file_id = data["photo_file_id"]
    await state.clear()

    tg_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)

        if not current_duty or not current_duty.room:
            await message.answer("⚠️ Наразі немає активної чергової кімнати.")
            return

        target_room = current_duty.room

        # Зберігаємо скаргу в БД
        await crud.create_complaint(
            session=session,
            coliving_id=user.coliving_id,
            reporter_id=user.id,
            target_room_id=target_room.id,
            photo_file_id=photo_file_id,
            comment=comment_text
        )

        # 1. Розсилаємо в особисті повідомлення кожному мешканцю чергової кімнати
        for duty_member in target_room.users:
            try:
                await message.bot.send_photo(
                    chat_id=duty_member.telegram_id,
                    photo=photo_file_id,
                    caption=texts.COMPLAINT_DM_ALERT.format(comment=comment_text)
                )
            except Exception:
                pass

        # 2. Якщо прив'язана група — публікуємо в топік з тегами
        if coliving.group_chat_id:
            tags = " ".join([
                f"@{u.username}" if u.username else f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>'
                for u in target_room.users
            ])
            try:
                await message.bot.send_photo(
                    chat_id=coliving.group_chat_id,
                    message_thread_id=coliving.duty_topic_id,
                    photo=photo_file_id,
                    caption=texts.COMPLAINT_GROUP_ALERT.format(
                        room_name=target_room.name,
                        duty_tags=tags,
                        comment=comment_text
                    )
                )
            except Exception:
                pass

        await message.answer(texts.COMPLAINT_SENT_SUCCESS, reply_markup=get_user_main_kb(user, tg_id))

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


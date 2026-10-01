from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.db import AsyncSessionLocal
from database import crud
from bot.middlewares.anti_spam import rate_limiter
from bot.keyboards.inline_helpers import get_my_room_actions_kb
from bot.keyboards.main_menu import get_main_keyboard
from config import settings
import texts

router = Router()

class ComplaintState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_comment = State()

class RoomBroadcastState(StatesGroup):
    waiting_for_text = State()

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
                upcoming.append(f"• Наступний тиждень: **{nxt.name}**")

        upcoming_str = "\n".join(upcoming) if upcoming else "Графік формується"

        await message.answer(
            texts.CALENDAR_INFO.format(
                coliving_name=coliving.name if coliving else "",
                current_room=duty_room.name if duty_room else "Немає",
                current_members=members,
                period_dates=dates_str,
                upcoming_schedule=upcoming_str
            )
        )

# 2. 🚪 Моя кімната
@router.message(F.text == texts.BTN_MY_ROOM)
async def menu_my_room(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id or not user.is_approved:
            await message.answer("⚠️ Ви ще не є затвердженим мешканцем колівінгу.")
            return

        room = await crud.get_room_by_id(session, user.room_id) if user.room_id else None
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        sotniks = await crud.get_sotniks(session, user.coliving_id)

        if not room:
            await message.answer("⚠️ Вас ще не розподілено в кімнату.")
            return

        members_lines = []
        for u in room.users:
            role_badge = " (Сотник 👑)" if u.role == "SOTNIK" else ""
            me_badge = " (Ви)" if u.id == user.id else ""
            username_part = f" (@{u.username})" if u.username else ""
            members_lines.append(f"• **{u.full_name}**{username_part}{role_badge}{me_badge}")

        sotniks_str = ", ".join([s.full_name for s in sotniks]) if sotniks else "не призначено"

        await message.answer(
            texts.MY_ROOM_INFO.format(
                room_name=room.name,
                coliving_name=coliving.name if coliving else "",
                count=len(room.users),
                capacity=room.capacity,
                members_list="\n".join(members_lines),
                sotniks_list=sotniks_str
            ),
            reply_markup=get_my_room_actions_kb()
        )

# Масова розсилка в ЛС кімнаті
@router.callback_query(F.data == "room_broadcast_prompt")
async def cb_room_broadcast_prompt(call: CallbackQuery, state: FSMContext):
    tg_id = call.from_user.id
    if not rate_limiter.can_broadcast_room(tg_id):
        await call.answer(texts.ROOM_BROADCAST_THROTTLED, show_alert=True)
        return
    await state.set_state(RoomBroadcastState.waiting_for_text)
    await call.message.answer(texts.ROOM_BROADCAST_PROMPT)
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

# Залишити колівінг
@router.callback_query(F.data == "confirm_leave_coliving")
async def cb_leave_coliving(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        await crud.remove_user_from_coliving(session, tg_id)
    await call.message.edit_text("🚪 Ви покинули колівінг. Щоб приєднатися знову, скористайтесь /start.")
    await call.answer()

# 3. 📋 Мої обов'язки
@router.message(F.text == texts.BTN_DUTIES)
async def menu_duties(message: Message):
    await message.answer(texts.DUTIES_INFO)

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
    await message.answer(texts.COMPLAINT_INTRO)

@router.message(ComplaintState.waiting_for_photo, F.photo)
async def complaint_photo(message: Message, state: FSMContext):
    # Беремо найбільший розмір фото
    photo = message.photo[-1]
    await state.update_data(photo_file_id=photo.file_id)
    await state.set_state(ComplaintState.waiting_for_comment)
    await message.answer(texts.COMPLAINT_COMMENT_PROMPT)

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
                f"@{u.username}" if u.username else f"[{u.full_name}](tg://user?id={u.telegram_id})"
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

        await message.answer(texts.COMPLAINT_SENT_SUCCESS)

# 5. 💰 Штрафи
@router.message(F.text == texts.BTN_FINES)
async def menu_fines(message: Message):
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or not user.coliving_id:
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
            )
        )

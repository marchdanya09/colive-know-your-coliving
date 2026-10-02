from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.db import AsyncSessionLocal
from database import crud
from bot.keyboards.sotnik_kb import (
    get_sotnik_panel_kb,
    get_request_action_kb,
    get_add_member_kb,
    get_sotnik_members_kb,
    get_sotnik_user_card_kb,
    get_sotnik_reassign_room_kb,
    get_sotnik_fines_kb,
    get_sotnik_duty_kb,
    get_sotnik_duty_picker_kb
)
from bot.keyboards.inline_helpers import get_back_kb
from bot.keyboards.main_menu import get_main_keyboard
from config import settings
import texts
import logging


logger = logging.getLogger("CO:LIVE.sotnik")
router = Router()

async def render_sotnik_panel(message_or_call, tg_id: int):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or user.role != "SOTNIK" or not user.coliving_id:
            text = "⛔ У вас немає прав Сотника."
            if isinstance(message_or_call, CallbackQuery):
                await message_or_call.answer(text, show_alert=True)
            else:
                await message_or_call.answer(text)
            return

        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        pending_count = await crud.count_pending_requests(session, user.coliving_id)
        members_count = await crud.count_residents(session, user.coliving_id)
        sotniks = await crud.get_sotniks(session, user.coliving_id)

        lock_status = "🔒 Закрито" if coliving.is_join_locked else "🔓 Відкрито"

        panel_text = texts.SOTNIK_PANEL_TEXT.format(
            coliving_name=coliving.name,
            lock_status=lock_status,
            pending_count=pending_count,
            members_count=members_count,
            max_people=coliving.total_people,
            sotniks_count=len(sotniks),
            code=coliving.invite_code
        )

        kb = get_sotnik_panel_kb(pending_count=pending_count, is_locked=coliving.is_join_locked)

        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.message.edit_text(panel_text, reply_markup=kb)
            await message_or_call.answer()
        else:
            await message_or_call.answer(panel_text, reply_markup=kb)

@router.message(Command("sotnik", "admin", "panel"))
@router.message(F.text == texts.BTN_SOTNIK_PANEL)
async def menu_sotnik_panel(message: Message):
    tg_id = message.from_user.id
    if message.text and message.text.startswith("/"):
        async with AsyncSessionLocal() as session:
            user = await crud.get_user_by_tg_id(session, tg_id)
            if user and user.role == "SOTNIK":
                webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={tg_id}&coliving_id={user.coliving_id}" if user.coliving_id else None
                await message.answer("👑 Панель Сотника відкрита.", reply_markup=get_main_keyboard(is_sotnik=True, webapp_url=webapp_url))
    await render_sotnik_panel(message, message.from_user.id)


@router.callback_query(F.data == "sotnik_back_panel")
async def cb_sotnik_back(call: CallbackQuery):
    await render_sotnik_panel(call, call.from_user.id)

# 1. Вхідні запити
@router.callback_query(F.data == "sotnik_pending_list")
async def cb_pending_list(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or user.role != "SOTNIK":
            await call.answer("Немає доступу", show_alert=True)
            return

        requests = await crud.get_pending_requests(session, user.coliving_id)
        if not requests:
            await call.answer("Немає нових заявок у черзі!", show_alert=True)
            return

        await call.message.answer(f"📥 <b>Список очікуючих заявок ({len(requests)}):</b>")
        for req in requests:
            username_str = f"@{req.username}" if req.username else "без username"
            role_label = "👑 Заявка на СОТНИКА" if getattr(req, "target_role", "RESIDENT") == "SOTNIK" else "🙋‍♂️ Заявка мешканця"
            card_text = (
                f"{role_label}\n"
                f"👤 <b>{req.full_name}</b> ({username_str})\n"
                f"🚪 Обрана кімната: <b>{req.room.name if req.room else 'Невідомо'}</b>\n"
                f"🕒 Дата подачі: {req.created_at.strftime('%d.%m %H:%M')}"
            )
            await call.message.answer(card_text, reply_markup=get_request_action_kb(req.id))

        await call.message.answer(
            "Натисніть кнопку нижче, щоб повернутися до панелі керування:",
            reply_markup=get_back_kb("sotnik_back_panel", "◀️ Назад до панелі сотника")
        )

    await call.answer()

# Схвалення заявки
@router.callback_query(F.data.startswith("req_app_"))
async def cb_approve_request(call: CallbackQuery):
    req_id = int(call.data.replace("req_app_", ""))
    async with AsyncSessionLocal() as session:
        result = await crud.approve_request(session, req_id)
        if not result:
            await call.answer("Заявка вже була оброблена.", show_alert=True)
            return

        req, approved_user = result
        coliving = await crud.get_coliving_by_id(session, approved_user.coliving_id)
        room = await crud.get_room_by_id(session, approved_user.room_id)

        # Сповіщаємо мешканця
        try:
            is_sotnik = (approved_user.role == "SOTNIK")
            notif_text = texts.REQUEST_APPROVED_SOTNIK_NOTIF_USER if is_sotnik else texts.REQUEST_APPROVED_NOTIF_USER
            webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={approved_user.telegram_id}&coliving_id={coliving.id}"
            await call.bot.send_message(
                chat_id=approved_user.telegram_id,
                text=notif_text.format(
                    coliving_name=coliving.name,
                    room_name=room.name if room else ""
                ),
                reply_markup=get_main_keyboard(is_sotnik=is_sotnik, webapp_url=webapp_url)
            )
        except Exception as e:
            logger.warning(f"Could not notify approved user {approved_user.telegram_id}: {e}")

    await call.message.edit_text(f"✅ Заявку користувача <b>{req.full_name}</b> схвалено!")
    await call.answer()

# Відхилення заявки
@router.callback_query(F.data.startswith("req_rej_"))
async def cb_reject_request(call: CallbackQuery):
    req_id = int(call.data.replace("req_rej_", ""))
    async with AsyncSessionLocal() as session:
        req = await crud.reject_request(session, req_id)
        if req:
            try:
                await call.bot.send_message(
                    chat_id=req.telegram_id,
                    text=texts.REQUEST_REJECTED_NOTIF_USER
                )
            except Exception as e:
                logger.warning(f"Could not notify rejected user: {e}")
            await call.message.edit_text(f"❌ Заявку <b>{req.full_name}</b> відхилено.")
        else:
            await call.answer("Заявка вже оброблена.", show_alert=True)
    await call.answer()

# Заблокувати та відхилити
@router.callback_query(F.data.startswith("req_blk_"))
async def cb_block_request(call: CallbackQuery):
    req_id = int(call.data.replace("req_blk_", ""))
    async with AsyncSessionLocal() as session:
        req = await crud.block_and_reject_request(session, req_id)
        if req:
            try:
                await call.bot.send_message(
                    chat_id=req.telegram_id,
                    text="⛔ Вам відмовлено у доступі до колівінгу та додано до чорного списку."
                )
            except Exception as e:
                logger.warning(f"Could not notify blocked user: {e}")
            await call.message.edit_text(f"🚫 Користувача <b>{req.full_name}</b> заблоковано!")
        else:
            await call.answer("Заявка вже оброблена.", show_alert=True)
    await call.answer()

# 2. Додати мешканця
@router.callback_query(F.data == "sotnik_add_member")
async def cb_add_member(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

    await call.message.edit_text(
        texts.ADD_MEMBER_OPTIONS.format(coliving_name=coliving.name),
        reply_markup=get_add_member_kb()
    )
    await call.answer()

@router.callback_query(F.data == "sotnik_get_invite_text")
async def cb_get_invite_text(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

    bot_username = "colive_bot"
    try:
        bot_info = await call.bot.get_me()
        bot_username = bot_info.username or bot_username
    except Exception:
        pass

    invite_link = f"https://t.me/{bot_username}?start=join_{coliving.invite_code}"

    text = texts.INVITE_FORWARD_TEMPLATE.format(
        coliving_name=coliving.name,
        bot_name=texts.BOT_NAME,
        invite_link=invite_link,
        code=coliving.invite_code
    )
    await call.message.answer(text, reply_markup=get_back_kb("sotnik_back_panel", "◀️ Назад до панелі"))
    await call.answer()

@router.callback_query(F.data == "sotnik_get_raw_code")
async def cb_get_raw_code(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

    await call.message.answer(
        f"🔑 Код вашого колівінгу для ручного вводу: <code>{coliving.invite_code}</code>",
        reply_markup=get_back_kb("sotnik_back_panel", "◀️ Назад до панелі")
    )
    await call.answer()

# 3. Перемкнути прийом заявок
@router.callback_query(F.data == "sotnik_toggle_lock")
async def cb_toggle_lock(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        is_locked = await crud.toggle_coliving_lock(session, user.coliving_id)

    if is_locked:
        await call.answer(texts.LOCK_ENABLED_MSG, show_alert=True)
    else:
        await call.answer(texts.LOCK_DISABLED_MSG, show_alert=True)

    await render_sotnik_panel(call, tg_id)

# 4. Ручна ротація чергувань
@router.callback_query(F.data == "sotnik_rotate_duty")
async def cb_rotate_duty(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        new_duty = await crud.rotate_duty(session, user.coliving_id)
        if new_duty and new_duty.room:
            await call.answer(f"Чергування перемкнуто на: {new_duty.room.name}!", show_alert=True)
        else:
            await call.answer("Не вдалося перемкнути чергування.", show_alert=True)

    await render_sotnik_panel(call, tg_id)

# 5. Згенерувати новий код
@router.callback_query(F.data == "sotnik_regen_code")
async def cb_regen_code(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        new_code = await crud.regenerate_coliving_code(session, user.coliving_id)

    bot_username = "colive_bot"
    try:
        bot_info = await call.bot.get_me()
        bot_username = bot_info.username or bot_username
    except Exception:
        pass
    new_link = f"https://t.me/{bot_username}?start=join_{new_code}"

    await call.message.answer(
        texts.CODE_REGENERATED_MSG.format(new_code=new_code, new_link=new_link),
        reply_markup=get_back_kb("sotnik_back_panel", "◀️ Назад до панелі")
    )
    await render_sotnik_panel(call, tg_id)

# 6. Інструкція прив'язки групи
@router.callback_query(F.data == "sotnik_group_guide")
async def cb_group_guide(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

    guide_text = (
        "💬 <b>Як підключити груповий чат колівінгу:</b>\n\n"
        "1. Додайте бота до вашої групи або супергрупи колівінгу;\n"
        "2. Надайте боту права адміністратора (для надсилання повідомлень у топіки);\n"
        f"3. У групі (або в потрібному топіку «Чергування») напишіть команду:\n"
        f"<code>/link_group {coliving.invite_code}</code>\n\n"
        "Після цього бот автоматично надсилатиме щотижневі графіки та термінові сповіщення саме туди!"
    )
    await call.message.answer(guide_text, reply_markup=get_back_kb("sotnik_back_panel", "◀️ Назад до панелі"))
    await call.answer()


class SotnikFineFSM(StatesGroup):
    waiting_for_custom_default_fine = State()
    waiting_for_room_fine_amount = State()
    waiting_for_room_fine_reason = State()
    waiting_for_user_fine_amount = State()
    waiting_for_user_fine_reason = State()
    waiting_for_new_room_name = State()
    waiting_for_new_room_capacity = State()
    waiting_for_edit_coliving_name = State()
    waiting_for_edit_coliving_address = State()
    waiting_for_duty_rules = State()



# ----------------- КЕРУВАННЯ МЕШКАНЦЯМИ -----------------

@router.callback_query(F.data == "sotnik_manage_members")
async def cb_manage_members(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if not user or user.role != "SOTNIK":
            await call.answer("Немає доступу", show_alert=True)
            return

        members = await crud.get_all_coliving_members(session, user.coliving_id)
        if not members:
            await call.answer("Немає зареєстрованих мешканців.", show_alert=True)
            return

        await call.message.edit_text(
            texts.SOTNIK_MEMBERS_TITLE,
            reply_markup=get_sotnik_members_kb(members)
        )
    await call.answer()


@router.callback_query(F.data.startswith("sotnik_view_user_"))
async def cb_view_user(call: CallbackQuery, answer: bool = True):
    target_user_id = int(call.data.replace("sotnik_view_user_", ""))
    tg_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        admin = await crud.get_user_by_tg_id(session, tg_id)
        if not admin or admin.role != "SOTNIK":
            if answer:
                await call.answer("Немає доступу", show_alert=True)
            return

        target_user = await crud.get_user_by_id(session, target_user_id)
        if not target_user or target_user.coliving_id != admin.coliving_id:
            if answer:
                await call.answer("Користувача не знайдено або він залишив колівінг.", show_alert=True)
            await cb_manage_members(call)
            return

        username_str = f"@{target_user.username}" if target_user.username else f'<a href="tg://user?id={target_user.telegram_id}">написати в ЛС</a>'
        role_badge = "👑 Сотник (Адміністратор)" if target_user.role == "SOTNIK" else "👤 Мешканець"
        room_name = target_user.room.name if target_user.room else "Не призначено"

        card_text = texts.SOTNIK_MEMBER_CARD.format(
            full_name=target_user.full_name,
            username_str=username_str,
            room_name=room_name,
            role_badge=role_badge,
            room_role=target_user.room_role or "Мешканець",
            room_duty=target_user.room_duty or "Не призначено",
            fines=target_user.unpaid_fines
        )

        kb = get_sotnik_user_card_kb(target_user, tg_id)
        await call.message.edit_text(card_text, reply_markup=kb)
    if answer:
        try:
            await call.answer()
        except Exception:
            pass


@router.callback_query(F.data.startswith("sotnik_change_room_"))
async def cb_change_room(call: CallbackQuery):
    target_user_id = int(call.data.replace("sotnik_change_room_", ""))
    tg_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        admin = await crud.get_user_by_tg_id(session, tg_id)
        target_user = await crud.get_user_by_id(session, target_user_id)
        rooms = await crud.get_rooms_with_users(session, admin.coliving_id)

        await call.message.edit_text(
            f"🚪 <b>Оберіть нову кімнату для {target_user.full_name}:</b>",
            reply_markup=get_sotnik_reassign_room_kb(target_user_id, rooms, target_user.room_id)
        )
    await call.answer()


@router.callback_query(F.data.startswith("sotnik_set_room_"))
async def cb_set_room(call: CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[3])
    new_room_id = int(parts[4])

    async with AsyncSessionLocal() as session:
        await crud.update_user_room(session, user_id, new_room_id)
        new_room = await crud.get_room_by_id(session, new_room_id)
        user = await crud.get_user_by_id(session, user_id)

        # Сповіщаємо мешканця
        try:
            await call.bot.send_message(
                chat_id=user.telegram_id,
                text=f"🚪 Сотник перемістив вас у кімнату: <b>{new_room.name}</b>!"
            )
        except Exception:
            pass

    await call.answer(f"Кімнату успішно змінено на {new_room.name}!", show_alert=True)
    call.data = f"sotnik_view_user_{user_id}"
    await cb_view_user(call, answer=False)


@router.callback_query(F.data.startswith("sotnik_toggle_role_"))
async def cb_toggle_role(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_toggle_role_", ""))
    async with AsyncSessionLocal() as session:
        success, msg, target_user = await crud.toggle_sotnik_role(session, user_id)
        if success and target_user:
            is_sotnik = (target_user.role == "SOTNIK")
            try:
                webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={target_user.telegram_id}&coliving_id={target_user.coliving_id}"
                notif = (
                    "👑 <b>Вам надано права Сотника колівінгу!</b> У вас з'явилася Панель Сотника."
                    if is_sotnik
                    else "👤 <b>Ваш статус оновлено:</b> тепер ви звичайний мешканець колівінгу."
                )
                await call.bot.send_message(
                    chat_id=target_user.telegram_id,
                    text=notif,
                    reply_markup=get_main_keyboard(is_sotnik=is_sotnik, webapp_url=webapp_url)
                )
            except Exception:
                pass

    await call.answer(msg, show_alert=True)
    call.data = f"sotnik_view_user_{user_id}"
    await cb_view_user(call, answer=False)


@router.callback_query(F.data.startswith("sotnik_toggle_starosta_"))
async def cb_sotnik_toggle_starosta(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_toggle_starosta_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, user_id)
        if not target_user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return
        new_role = "Мешканець" if target_user.room_role == "Староста" else "Староста"
        await crud.set_user_room_role(session, user_id, new_role)
        try:
            notif = f"⭐ <b>Сотник оновив ваш статус у кімнаті:</b> {new_role}!"
            await call.bot.send_message(chat_id=target_user.telegram_id, text=notif)
        except Exception:
            pass

    await call.answer(f"Статус Старости оновлено: {new_role}!", show_alert=True)
    call.data = f"sotnik_view_user_{user_id}"
    await cb_view_user(call, answer=False)


@router.callback_query(F.data.startswith("sotnik_pick_duty_"))
async def cb_sotnik_pick_duty(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_pick_duty_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, user_id)
        if not target_user:
            await call.answer("Користувача не знайдено.", show_alert=True)
            return
    kb = get_sotnik_duty_picker_kb(user_id)
    await call.message.edit_text(
        f"📋 <b>Оберіть обов'язок для {target_user.full_name}:</b>\nПоточний: <b>{target_user.room_duty or 'Не призначено'}</b>",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("sotnik_set_user_duty_"))
async def cb_sotnik_set_user_duty(call: CallbackQuery):
    parts = call.data.replace("sotnik_set_user_duty_", "").split("_")
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
                notif = f"📋 <b>Сотник призначив вам обов'язок у кімнаті:</b> {duty_name}!"
                await call.bot.send_message(chat_id=user.telegram_id, text=notif)
            except Exception:
                pass

    await call.answer(f"Обов'язок встановлено: {duty_name}!", show_alert=True)
    call.data = f"sotnik_view_user_{user_id}"
    await cb_view_user(call, answer=False)


@router.callback_query(F.data.startswith("sotnik_kick_"))
async def cb_kick_prompt(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_kick_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, user_id)

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⛔ Так, видалити", callback_data=f"sotnik_do_kick_{user_id}")],
            [InlineKeyboardButton(text="◀️ Скасувати", callback_data=f"sotnik_view_user_{user_id}")]
        ]
    )
    await call.message.edit_text(
        f"⚠️ <b>Ви впевнені, що хочете видалити {target_user.full_name} з колівінгу?</b>\n"
        "Користувач втратить доступ до колівінгу, а його місце в кімнаті буде звільнено.",
        reply_markup=confirm_kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("sotnik_do_kick_"))
async def cb_do_kick(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_do_kick_", ""))
    async with AsyncSessionLocal() as session:
        kicked = await crud.kick_user_from_coliving(session, user_id)
        if kicked:
            try:
                await call.bot.send_message(
                    chat_id=kicked.telegram_id,
                    text="🚪 <b>Вас було виключено з колівінгу сотником.</b>",
                    reply_markup=ReplyKeyboardRemove()
                )
            except Exception:
                pass

    await call.answer("Мешканця успішно видалено з колівінгу!", show_alert=True)
    await cb_manage_members(call)


@router.callback_query(F.data.startswith("sotnik_clear_fines_"))
async def cb_clear_fines(call: CallbackQuery):
    user_id = int(call.data.replace("sotnik_clear_fines_", ""))
    async with AsyncSessionLocal() as session:
        cleared = await crud.clear_user_fines(session, user_id)

    await call.answer(f"Списано штрафів на суму {cleared} грн!", show_alert=True)
    call.data = f"sotnik_view_user_{user_id}"
    await cb_view_user(call)


# ----------------- НАЛАШТУВАННЯ ШТРАФІВ ТА КАСИ -----------------

@router.callback_query(F.data == "sotnik_fines_menu")
async def cb_fines_menu(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

        dist_label = "На всю кімнату" if coliving.fine_distribution == "ROOM" else "Персонально на людину"
        text = texts.SOTNIK_FINES_PANEL_TEXT.format(
            fine_amount=coliving.default_fine_amount,
            fine_type_label=dist_label,
            treasury_balance=coliving.treasury_balance
        )
        kb = get_sotnik_fines_kb(coliving.fine_distribution, coliving.default_fine_amount)
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sotnik_toggle_fine_dist")
async def cb_toggle_fine_dist(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        new_dist = "INDIVIDUAL" if coliving.fine_distribution == "ROOM" else "ROOM"
        await crud.update_fine_settings(session, user.coliving_id, distribution=new_dist)

    await call.answer(f"Тип розподілу змінено на: {'На кімнату' if new_dist == 'ROOM' else 'Персонально'}!", show_alert=True)
    await cb_fines_menu(call)


@router.callback_query(F.data.in_(["sotnik_set_fine_50", "sotnik_set_fine_100", "sotnik_set_fine_200"]))
async def cb_set_preset_fine(call: CallbackQuery):
    val = float(call.data.replace("sotnik_set_fine_", ""))
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        await crud.update_fine_settings(session, user.coliving_id, default_fine=val)

    await call.answer(f"Базовий штраф встановлено: {val} грн!", show_alert=True)
    await cb_fines_menu(call)


@router.callback_query(F.data == "sotnik_custom_fine_prompt")
async def cb_custom_fine_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikFineFSM.waiting_for_custom_default_fine)
    await call.message.edit_text(
        "✏️ <b>Введіть бажаний новий розмір базового штрафу в гривнях (число, наприклад 75 або 150):</b>",
        reply_markup=get_back_kb("sotnik_fines_menu", "◀️ Скасувати")
    )
    await call.answer()


@router.message(SotnikFineFSM.waiting_for_custom_default_fine)
async def process_custom_fine(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        val = float(text)
        if val < 0 or val > 50000:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Будь ласка, введіть числове значення від 0 до 50000:")
        return

    await state.clear()
    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        await crud.update_fine_settings(session, user.coliving_id, default_fine=val)

    await message.answer(f"✅ Базовий розмір штрафу оновлено: <b>{val} грн</b>!")
    await render_sotnik_panel(message, tg_id)


# Ручне нарахування штрафу кімнаті
@router.callback_query(F.data == "sotnik_fine_room_select")
async def cb_fine_room_select(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        rooms = await crud.get_rooms_with_users(session, user.coliving_id)

    buttons = []
    for r in rooms:
        buttons.append([InlineKeyboardButton(text=f"🚪 {r.name} ({len(r.users)} осіб)", callback_data=f"sotnik_fine_room_{r.id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Скасувати", callback_data="sotnik_fines_menu")])

    await call.message.edit_text(
        "🏢 <b>Оберіть кімнату для нарахування штрафу:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()


@router.callback_query(F.data.startswith("sotnik_fine_room_"))
async def cb_fine_room_input(call: CallbackQuery, state: FSMContext):
    room_id = int(call.data.replace("sotnik_fine_room_", ""))
    await state.update_data(target_room_id=room_id)
    await state.set_state(SotnikFineFSM.waiting_for_room_fine_amount)
    await call.message.edit_text(
        "💵 <b>Введіть суму штрафу для кімнати в грн:</b>",
        reply_markup=get_back_kb("sotnik_fines_menu", "◀️ Скасувати")
    )
    await call.answer()


@router.message(SotnikFineFSM.waiting_for_room_fine_amount)
async def process_room_fine_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip())
        if amt <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Введіть коректне число більше 0:")
        return

    await state.update_data(fine_amount=amt)
    await state.set_state(SotnikFineFSM.waiting_for_room_fine_reason)
    await message.answer("✍️ <b>Вкажіть причину нарахування штрафу (наприклад: не винесене сміття):</b>")


@router.message(SotnikFineFSM.waiting_for_room_fine_reason)
async def process_room_fine_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    room_id = data["target_room_id"]
    amount = data["fine_amount"]
    await state.clear()

    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        room = await crud.get_room_by_id(session, room_id)
        await crud.add_fine(
            session=session,
            coliving_id=user.coliving_id,
            amount=amount,
            reason=reason,
            room_id=room_id
        )

        for m in room.users:
            try:
                await message.bot.send_message(
                    chat_id=m.telegram_id,
                    text=f"⚠️ <b>Вашій кімнаті ({room.name}) нараховано штраф {amount} грн!</b>\nПричина: {reason}"
                )
            except Exception:
                pass

    await message.answer(f"✅ Штраф {amount} грн успішно нараховано кімнаті {room.name}!")
    await render_sotnik_panel(message, tg_id)


# ----------------- КЕРУВАННЯ ЧЕРГУВАННЯМ -----------------

@router.callback_query(F.data == "sotnik_duty_menu")
async def cb_duty_menu(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)
        current_duty = await crud.get_current_duty(session, user.coliving_id)
        rooms = await crud.get_rooms_with_users(session, user.coliving_id)

        if current_duty and current_duty.room:
            cur_name = current_duty.room.name
            cur_members = ", ".join([u.full_name for u in current_duty.room.users]) if current_duty.room.users else "порожня"
            period = f"{current_duty.start_date.strftime('%d.%m')} - {current_duty.end_date.strftime('%d.%m')}"
            cur_id = current_duty.room_id
        else:
            cur_name = "Не призначено"
            cur_members = "—"
            period = "—"
            cur_id = None

        rules_preview = coliving.custom_duty_rules if (coliving and coliving.custom_duty_rules) else texts.DEFAULT_DUTIES_CHECKLIST

        text = texts.SOTNIK_DUTY_PANEL_TEXT.format(
            room_name=cur_name,
            members=cur_members,
            period=period,
            rules_preview=rules_preview
        )
        kb = get_sotnik_duty_kb(rooms, cur_id)
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "sotnik_edit_duty_rules")
async def cb_sotnik_edit_duty_rules(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikFineFSM.waiting_for_duty_rules)
    edit_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Скинути до стандартних", callback_data="sotnik_reset_duty_rules")],
            [InlineKeyboardButton(text="◀️ Скасувати", callback_data="sotnik_duty_menu")]
        ]
    )
    await call.message.edit_text(
        "📝 <b>Введіть оновлений список / чекліст обов'язків чергової кімнати:</b>\n\n"
        "Надішліть текст повідомленням (або натисніть кнопку нижче, щоб скинути до стандартних):",
        reply_markup=edit_kb
    )
    await call.answer()


@router.callback_query(F.data == "sotnik_reset_duty_rules")
async def cb_sotnik_reset_duty_rules(call: CallbackQuery, state: FSMContext):
    await state.clear()
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if user and user.coliving_id:
            await crud.set_coliving_duty_rules(session, user.coliving_id, "")
    await call.answer("Правила скинуто до стандартних!", show_alert=True)
    await cb_duty_menu(call)


@router.message(SotnikFineFSM.waiting_for_duty_rules)
async def process_sotnik_edit_duty_rules(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    new_rules = message.text.strip() if message.text else ""
    await state.clear()
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        if user and user.coliving_id and new_rules:
            await crud.set_coliving_duty_rules(session, user.coliving_id, new_rules)
    await message.answer("✅ Чекліст обов'язків чергування успішно оновлено!")
    await render_sotnik_panel(message, tg_id)


@router.callback_query(F.data.startswith("sotnik_set_duty_"))
async def cb_set_duty_direct(call: CallbackQuery):
    room_id = int(call.data.replace("sotnik_set_duty_", ""))
    tg_id = call.from_user.id

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        await crud.set_current_duty_room(session, user.coliving_id, room_id)
        room = await crud.get_room_by_id(session, room_id)

    await call.answer(f"Черговою кімнатою призначено: {room.name}!", show_alert=True)
    await cb_duty_menu(call)


# ----------------- НАРАХУВАННЯ ШТРАФУ КОРИСТУВАЧУ -----------------

@router.callback_query(F.data.startswith("sotnik_fine_user_"))
async def cb_fine_user_prompt(call: CallbackQuery, state: FSMContext):
    target_user_id = int(call.data.replace("sotnik_fine_user_", ""))
    async with AsyncSessionLocal() as session:
        target_user = await crud.get_user_by_id(session, target_user_id)

    await state.update_data(fine_target_user_id=target_user_id)
    await state.set_state(SotnikFineFSM.waiting_for_user_fine_amount)
    await call.message.edit_text(
        f"💵 <b>Введіть суму штрафу в грн для {target_user.full_name}:</b>",
        reply_markup=get_back_kb(f"sotnik_view_user_{target_user_id}", "◀️ Скасувати")
    )
    await call.answer()


@router.message(SotnikFineFSM.waiting_for_user_fine_amount)
async def process_user_fine_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip())
        if amt <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Введіть коректне додатне число:")
        return

    await state.update_data(fine_amount=amt)
    await state.set_state(SotnikFineFSM.waiting_for_user_fine_reason)
    await message.answer("✍️ <b>Вкажіть причину штрафу:</b>")


@router.message(SotnikFineFSM.waiting_for_user_fine_reason)
async def process_user_fine_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    user_id = data["fine_target_user_id"]
    amount = data["fine_amount"]
    await state.clear()

    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        admin = await crud.get_user_by_tg_id(session, tg_id)
        target_user = await crud.get_user_by_id(session, user_id)
        await crud.add_fine(
            session=session,
            coliving_id=admin.coliving_id,
            amount=amount,
            reason=reason,
            user_id=user_id
        )

        try:
            await message.bot.send_message(
                chat_id=target_user.telegram_id,
                text=f"⚠️ <b>Вам нараховано штраф {amount} грн!</b>\nПричина: {reason}"
            )
        except Exception:
            pass

    await message.answer(f"✅ Штраф {amount} грн успішно нараховано користувачу {target_user.full_name}!")
    await render_sotnik_panel(message, tg_id)


# ----------------- ДОДАВАННЯ КІМНАТИ -----------------

@router.callback_query(F.data == "sotnik_add_room")
async def cb_add_room_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikFineFSM.waiting_for_new_room_name)
    await call.message.edit_text(
        "🚪 <b>Введіть назву нової кімнати (наприклад: Кімната 5 або Мансарда):</b>",
        reply_markup=get_back_kb("sotnik_back_panel", "◀️ Скасувати")
    )
    await call.answer()


@router.message(SotnikFineFSM.waiting_for_new_room_name)
async def process_new_room_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 50:
        await message.answer("⚠️ Введіть коректну назву кімнати (до 50 символів):")
        return
    await state.update_data(new_room_name=name)
    await state.set_state(SotnikFineFSM.waiting_for_new_room_capacity)
    await message.answer("👥 <b>Скільки мешканців вміщує ця кімната? (число від 1 до 50):</b>")


@router.message(SotnikFineFSM.waiting_for_new_room_capacity)
async def process_new_room_capacity(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 50):
        await message.answer("⚠️ Введіть коректне число від 1 до 50:")
        return

    capacity = int(text)
    data = await state.get_data()
    room_name = data["new_room_name"]
    await state.clear()

    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        room = await crud.add_room_to_coliving(session, user.coliving_id, room_name, capacity)

    await message.answer(f"✅ Кімнату <b>{room.name}</b> (місткість: {capacity} осіб) успішно додано до колівінгу!")
    await render_sotnik_panel(message, tg_id)


# ----------------- РЕДАГУВАННЯ ДАНИХ КОЛІВІНГУ -----------------

@router.callback_query(F.data == "sotnik_edit_coliving")
async def cb_edit_coliving_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikFineFSM.waiting_for_edit_coliving_name)
    await call.message.edit_text(
        "✏️ <b>Введіть нову назву колівінгу (або '-' щоб залишити поточну):</b>",
        reply_markup=get_back_kb("sotnik_back_panel", "◀️ Скасувати")
    )
    await call.answer()


@router.message(SotnikFineFSM.waiting_for_edit_coliving_name)
async def process_edit_coliving_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(edit_coliving_name=name if name != "-" else None)
    await state.set_state(SotnikFineFSM.waiting_for_edit_coliving_address)
    await message.answer("📍 <b>Введіть нову адресу колівінгу (або '-' щоб залишити поточну):</b>")


@router.message(SotnikFineFSM.waiting_for_edit_coliving_address)
async def process_edit_coliving_address(message: Message, state: FSMContext):
    addr = message.text.strip()
    data = await state.get_data()
    new_name = data.get("edit_coliving_name")
    new_addr = addr if addr != "-" else None
    await state.clear()

    tg_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.update_coliving_info(session, user.coliving_id, name=new_name, address=new_addr)

    await message.answer(
        f"✅ Дані колівінгу оновлено!\n🏢 Назва: <b>{coliving.name}</b>\n📍 Адреса: <b>{coliving.address}</b>"
    )
    await render_sotnik_panel(message, tg_id)



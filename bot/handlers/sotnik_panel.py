from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from database.db import AsyncSessionLocal
from database import crud
from bot.keyboards.sotnik_kb import (
    get_sotnik_panel_kb,
    get_request_action_kb,
    get_add_member_kb
)
from bot.keyboards.main_menu import get_main_keyboard
from config import settings
import texts

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

@router.message(F.text == texts.BTN_SOTNIK_PANEL)
async def menu_sotnik_panel(message: Message):
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

        await call.message.answer(f"📥 **Список очікуючих заявок ({len(requests)}):**")
        for req in requests:
            username_str = f"@{req.username}" if req.username else "без username"
            card_text = (
                f"👤 **{req.full_name}** ({username_str})\n"
                f"🚪 Обрана кімната: **{req.room.name if req.room else 'Невідомо'}**\n"
                f"🕒 Дата подачі: {req.created_at.strftime('%d.%m %H:%M')}"
            )
            await call.message.answer(card_text, reply_markup=get_request_action_kb(req.id))

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
            webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={approved_user.telegram_id}&coliving_id={coliving.id}"
            await call.bot.send_message(
                chat_id=approved_user.telegram_id,
                text=texts.REQUEST_APPROVED_NOTIF_USER.format(
                    coliving_name=coliving.name,
                    room_name=room.name if room else ""
                ),
                reply_markup=get_main_keyboard(is_sotnik=False, webapp_url=webapp_url)
            )
        except Exception:
            pass

    await call.message.edit_text(f"✅ Заявку користувача **{req.full_name}** схвалено!")
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
            except Exception:
                pass
            await call.message.edit_text(f"❌ Заявку **{req.full_name}** відхилено.")
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
            except Exception:
                pass
            await call.message.edit_text(f"🚫 Користувача **{req.full_name}** заблоковано!")
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

    bot_info = await call.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start=join_{coliving.invite_code}"

    text = texts.INVITE_FORWARD_TEMPLATE.format(
        coliving_name=coliving.name,
        bot_name=texts.BOT_NAME,
        invite_link=invite_link,
        code=coliving.invite_code
    )
    await call.message.answer(text)
    await call.answer()

@router.callback_query(F.data == "sotnik_get_raw_code")
async def cb_get_raw_code(call: CallbackQuery):
    tg_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)
        coliving = await crud.get_coliving_by_id(session, user.coliving_id)

    await call.message.answer(f"🔑 Код вашого колівінгу для ручного вводу: `{coliving.invite_code}`")
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

    bot_info = await call.bot.get_me()
    new_link = f"https://t.me/{bot_info.username}?start=join_{new_code}"

    await call.message.answer(
        texts.CODE_REGENERATED_MSG.format(new_code=new_code, new_link=new_link)
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
        "💬 **Як підключити груповий чат колівінгу:**\n\n"
        "1. Додайте бота до вашої групи або супергрупи колівінгу;\n"
        "2. Надайте боту права адміністратора (для надсилання повідомлень у топіки);\n"
        f"3. У групі (або в потрібному топіку «Чергування») напишіть команду:\n"
        f"`/link_group {coliving.invite_code}`\n\n"
        "Після цього бот автоматично надсилатиме щотижневі графіки та термінові сповіщення саме туди!"
    )
    await call.message.answer(guide_text)
    await call.answer()

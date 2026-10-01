import re
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database.db import AsyncSessionLocal
from database import crud
from sqlalchemy import select
from database.models import Coliving, Room
import texts

router = Router()

# 1. Прив'язка групи до колівінгу
@router.message(Command("link_group"))
async def cmd_link_group(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("⚠️ Цю команду потрібно викликати в груповому чаті колівінгу.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("⚠️ Вкажіть код колівінгу. Приклад:\n<code>/link_group Xk9mP2vL</code>")
        return

    code = parts[1].strip()
    chat_id = message.chat.id
    topic_id = message.message_thread_id

    async with AsyncSessionLocal() as session:
        coliving = await crud.get_coliving_by_code(session, code)
        if not coliving:
            await message.answer("❌ Колівінг із таким кодом не знайдено.")
            return

        await crud.link_group_to_coliving(session, coliving.id, chat_id, topic_id)
        topic_info = f" (топік ID: {topic_id})" if topic_id else ""
        await message.answer(
            f"✅ <b>Груповий чат успішно прив'язано до колівінгу «{coliving.name}»!</b>{topic_info}\n\n"
            "Тепер бот надсилатиме сюди анонси чергувань та термінові сповіщення про неприбрані зони."
        )

# 2. Тегування цілої кімнати одним тегом у групі
ROOM_TAG_REGEX = re.compile(r"(?:/|@|!)(?:room|кімната)[_ ]?(\d+)", re.IGNORECASE)

@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_mentions(message: Message):
    if not message.text:
        return

    match = ROOM_TAG_REGEX.search(message.text)
    if not match:
        if message.text.startswith("/duty"):
            await show_group_duty(message)
        return

    room_num = int(match.group(1))
    chat_id = message.chat.id

    async with AsyncSessionLocal() as session:
        stmt = select(Coliving).where(Coliving.group_chat_id == chat_id)
        res = await session.execute(stmt)
        coliving = res.scalar_one_or_none()

        if not coliving:
            return

        rooms = await crud.get_rooms_with_users(session, coliving.id)
        target_room = None
        for r in rooms:
            if r.rotation_order == room_num or str(room_num) in r.name:
                target_room = r
                break

        if not target_room:
            await message.reply(f"⚠️ Кімнату №{room_num} у цьому колівінгу не знайдено.")
            return

        if not target_room.users:
            await message.reply(f"🚪 <b>{target_room.name}:</b> Наразі у цій кімнаті немає зареєстрованих мешканців.")
            return

        # Формуємо клікабельні згадки у форматі HTML
        tags = []
        for u in target_room.users:
            if u.username:
                tags.append(f"@{u.username}")
            else:
                tags.append(f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>')

        tags_str = " ".join(tags)
        await message.reply(f"📢 <b>{target_room.name}:</b> {tags_str}")

async def show_group_duty(message: Message):
    chat_id = message.chat.id
    async with AsyncSessionLocal() as session:
        stmt = select(Coliving).where(Coliving.group_chat_id == chat_id)
        res = await session.execute(stmt)
        coliving = res.scalar_one_or_none()

        if not coliving:
            return

        duty = await crud.get_current_duty(session, coliving.id)
        if not duty or not duty.room:
            await message.reply("⚠️ На цей тиждень чергова кімната не встановлена.")
            return

        tags = " ".join([
            f"@{u.username}" if u.username else f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>'
            for u in duty.room.users
        ]) if duty.room.users else "немає мешканців"

        await message.reply(
            f"🧹 <b>Поточне чергування:</b> {duty.room.name}\n"
            f"👥 <b>Чергові:</b> {tags}\n"
            f"📅 До: {duty.end_date.strftime('%d.%m.%Y')}"
        )

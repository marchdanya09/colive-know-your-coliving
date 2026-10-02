import re
from typing import List, Optional
from datetime import timedelta, date
from aiogram import Router, F
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from database.db import AsyncSessionLocal
from database import crud
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from database.models import Coliving, Room, User, Complaint
import texts

router = Router()

async def get_coliving_by_chat_id(session, chat_id: int) -> Optional[Coliving]:
    stmt = (
        select(Coliving)
        .options(selectinload(Coliving.rooms).selectinload(Room.users))
        .where(Coliving.group_chat_id == chat_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

# -------------------------------------------------------------
# 1. Прив'язка групи та топіків
# -------------------------------------------------------------

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
        topic_info = f" (топік чергувань ID: {topic_id})" if topic_id else ""
        await message.answer(
            f"✅ <b>Груповий чат успішно прив'язано до колівінгу «{coliving.name}»!</b>{topic_info}\n\n"
            "Тепер бот може надсилати сюди анонси, термінові скарги та реагувати на команди."
        )


@router.message(Command("link_duty", "link_complaints", "link_lost_found", "link_topic"))
async def cmd_link_topics(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    chat_id = message.chat.id
    topic_id = message.message_thread_id
    text = (message.text or "").strip().lower()

    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            await message.reply("⚠️ Ця група ще не прив'язана до жодного колівінгу. Спочатку викличте <code>/link_group [КОД]</code>.")
            return

        if "complaint" in text or "скарг" in text:
            await crud.update_coliving_topics(session, coliving.id, complaints_topic_id=topic_id)
            await message.reply(f"✅ Цей топік (ID: {topic_id}) встановлено як <b>Топік для скарг</b> 🚨!")
        elif "lost" in text or "реч" in text or "found" in text:
            await crud.update_coliving_topics(session, coliving.id, lost_found_topic_id=topic_id)
            await message.reply(f"✅ Цей топік (ID: {topic_id}) встановлено як <b>Топік «Чиї речі?»</b> 📦!")
        elif "duty" in text or "чергув" in text:
            await crud.update_coliving_topics(session, coliving.id, duty_topic_id=topic_id)
            await message.reply(f"✅ Цей топік (ID: {topic_id}) встановлено як <b>Топік чергувань</b> 🧹!")
        else:
            await message.reply(
                "ℹ️ <b>Як прив'язати конкретні топіки:</b>\n"
                "• <code>/link_topic duty</code> — для топіку чергувань\n"
                "• <code>/link_topic complaints</code> — для топіку скарг\n"
                "• <code>/link_topic lost_found</code> — для топіку «Чиї речі?»"
            )


# -------------------------------------------------------------
# 2. Рольові виклики та тегування кімнат (@all, @sotnik, @roomX)
# -------------------------------------------------------------

ROOM_TAG_REGEX = re.compile(r"(?:/|@|!)(?:room|кімната)[_ ]?(\d+)", re.IGNORECASE)
ALL_TAG_REGEX = re.compile(r"(?:^|\s)(?:@all|@колівінг|!all)(?:\s|$)", re.IGNORECASE)
SOTNIK_TAG_REGEX = re.compile(r"(?:^|\s)(?:@sotnik|@сотники|!sotnik)(?:\s|$)", re.IGNORECASE)
DUTY_TAG_REGEX = re.compile(r"(?:^|\s)(?:@duty|@чергові|!duty|!чергові)(?:\s|$)", re.IGNORECASE)

@router.message(Command("all", "колівінг"))
async def cmd_tag_all(message: Message):
    await handle_tag_all(message)

@router.message(Command("sotnik", "сотники", "sotniks"))
async def cmd_tag_sotnik(message: Message):
    await handle_tag_sotnik(message)

@router.message(Command("duty", "чергові"))
async def cmd_duty_info(message: Message):
    await show_group_duty(message)

async def handle_tag_all(message: Message):
    chat_id = message.chat.id
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return
        users = await crud.get_coliving_users(session, coliving.id)
        if not users:
            await message.reply("👥 У колівінгу ще немає зареєстрованих мешканців.")
            return

        tags = []
        for u in users:
            if u.username:
                tags.append(f"@{u.username}")
            else:
                tags.append(f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>')

        await message.reply(f"📢 <b>Всі мешканці колівінгу ({len(users)}):</b>\n{' '.join(tags)}")

async def handle_tag_sotnik(message: Message):
    chat_id = message.chat.id
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return
        sotniks = await crud.get_sotniks(session, coliving.id)
        if not sotniks:
            await message.reply("👑 Сотників у колівінгу не знайдено.")
            return

        tags = []
        for u in sotniks:
            if u.username:
                tags.append(f"@{u.username}")
            else:
                tags.append(f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>')

        await message.reply(f"👑 <b>Сотники колівінгу ({len(sotniks)}):</b>\n{' '.join(tags)}")


# -------------------------------------------------------------
# 3. Інформаційні команди (/rules, /rooms, /calendar, /fines)
# -------------------------------------------------------------

@router.message(Command("rules", "правила"))
async def cmd_group_rules(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, message.chat.id)
        if not coliving:
            return
        rules = coliving.custom_duty_rules or texts.DEFAULT_DUTIES_CHECKLIST
        await message.reply(f"📋 <b>Правила та чекліст чергування «{coliving.name}»:</b>\n\n{rules}")


@router.message(Command("rooms", "кімнати"))
async def cmd_group_rooms(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, message.chat.id)
        if not coliving:
            return
        rooms = await crud.get_rooms_with_users(session, coliving.id)
        lines = [f"🏢 <b>Кімнати колівінгу «{coliving.name}»:</b>\n"]
        for r in rooms:
            residents = ", ".join([u.full_name for u in r.users]) if r.users else "порожня"
            lines.append(f"🚪 <b>{r.name}</b> ({len(r.users)}/{r.capacity}): {residents}")
        await message.reply("\n".join(lines))


@router.message(Command("calendar", "графік"))
async def cmd_group_calendar(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, message.chat.id)
        if not coliving:
            return
        current_duty = await crud.get_current_duty(session, coliving.id)
        rooms = await crud.get_rooms_with_users(session, coliving.id)

        cur_room_str = current_duty.room.name if (current_duty and current_duty.room) else "Не призначено"
        cur_dates = f"{current_duty.start_date.strftime('%d.%m')} - {current_duty.end_date.strftime('%d.%m')}" if current_duty else "поточний період"

        upcoming = []
        if rooms:
            cur_idx = 0
            if current_duty:
                for idx, r in enumerate(rooms):
                    if r.id == current_duty.room_id:
                        cur_idx = idx
                        break
            base_date = current_duty.end_date if (current_duty and current_duty.end_date) else (date.today() + timedelta(days=7))
            for i in range(1, min(4, len(rooms))):
                nxt = rooms[(cur_idx + i) % len(rooms)]
                w_start = base_date + timedelta(days=7 * (i - 1))
                w_end = base_date + timedelta(days=7 * i)
                dates_part = f"{w_start.strftime('%d.%m')} - {w_end.strftime('%d.%m')}"
                upcoming.append(f"• {dates_part}: <b>{nxt.name}</b>")

        upcoming_str = "\n".join(upcoming) if upcoming else "Графік формується"

        text = (
            f"🗓 <b>Графік чергувань у «{coliving.name}»</b>\n\n"
            f"🔥 <b>Зараз чергує:</b> {cur_room_str}\n"
            f"⏱ <b>Період:</b> {cur_dates}\n\n"
            f"🔜 <b>Наступні чергування:</b>\n{upcoming_str}"
        )
        await message.reply(text)


@router.message(Command("fines", "штрафи", "каса"))
async def cmd_group_fines(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, message.chat.id)
        if not coliving:
            return
        fines = await crud.get_unpaid_fines(session, coliving.id)
        lines = [
            f"💰 <b>Скарбничка колівінгу:</b> {coliving.treasury_balance:.2f} грн",
            f"Базовий штраф: {coliving.default_fine_amount:.0f} грн\n",
            f"📌 <b>Неоплачені штрафи ({len(fines)}):</b>"
        ]
        if fines:
            for f in fines[:10]:
                u_name = f.user.full_name if f.user else (f.room.name if f.room else "Невідомо")
                lines.append(f"• {u_name}: <b>{f.amount:.0f} грн</b> ({f.reason})")
        else:
            lines.append("Усі штрафи сплачені! Чистота і порядок 🎉")
        await message.reply("\n".join(lines))


# -------------------------------------------------------------
# 4. Реєстрація скарг (/скарга, /complaint)
# -------------------------------------------------------------

@router.message(Command("скарга", "complaint"))
async def cmd_group_complaint(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    chat_id = message.chat.id
    sender = message.from_user
    sender_name = sender.full_name if sender else "Мешканець"

    # Текст скарги з команди або з цитованого повідомлення
    raw_args = ""
    parts = (message.text or message.caption or "").strip().split(maxsplit=1)
    if len(parts) > 1:
        raw_args = parts[1].strip()

    replied_text = ""
    replied_photo = None
    replied_video = None
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if message.reply_to_message.photo:
            replied_photo = message.reply_to_message.photo[-1].file_id
        elif message.reply_to_message.video:
            replied_video = message.reply_to_message.video.file_id

    complaint_text = raw_args or replied_text or "Порушення чистоти / порядку"

    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return

        all_residents = await crud.get_coliving_users(session, coliving.id)

        # Визначаємо адресатів скарги
        is_all_tagged = bool(ALL_TAG_REGEX.search(raw_args) or ALL_TAG_REGEX.search(replied_text))
        tagged_usernames = set(re.findall(r"@([a-zA-Z0-9_]{3,})", f"{raw_args} {replied_text}"))
        tagged_usernames.discard("all")
        tagged_usernames.discard("колівінг")
        tagged_usernames.discard("sotnik")

        target_users: List[User] = []

        if is_all_tagged:
            # 1. Тегнуто @all -> відправляємо всім мешканцям колівінгу крім відправника
            target_users = [u for u in all_residents if u.telegram_id != sender.id]
        elif tagged_usernames:
            # 2. Тегнуто конкретних користувачів
            for u in all_residents:
                if u.username and u.username.lower() in [tun.lower() for tun in tagged_usernames]:
                    if u.telegram_id != sender.id:
                        target_users.append(u)
        
        # 3. Якщо нікого не тегнули -> дефолт: чергова кімната поточного тижня
        if not target_users and not is_all_tagged and not tagged_usernames:
            current_duty = await crud.get_current_duty(session, coliving.id)
            if current_duty and current_duty.room and current_duty.room.users:
                target_users = [u for u in current_duty.room.users if u.telegram_id != sender.id]
            else:
                # Резерв: якщо чергової кімнати немає, відправляємо сотникам
                sotniks = await crud.get_sotniks(session, coliving.id)
                target_users = [u for u in sotniks if u.telegram_id != sender.id]

        target_names = [u.full_name for u in target_users] if target_users else ["Чергова кімната"]
        target_names_str = ", ".join(target_names)

        # А) Відправка в особисті повідомлення кожному адресату
        pm_text = (
            f"🚨 <b>УВАГА! Надійшла скарга у колівінгу «{coliving.name}»:</b>\n\n"
            f"👤 Від: <b>{sender_name}</b>\n"
            f"📝 Зміст: <i>{complaint_text}</i>\n\n"
            "⚠️ Будь ласка, оперативно зверніть увагу та приведіть зону до ладу!"
        )
        for u in target_users:
            try:
                if replied_photo:
                    await message.bot.send_photo(chat_id=u.telegram_id, photo=replied_photo, caption=pm_text)
                elif replied_video:
                    await message.bot.send_video(chat_id=u.telegram_id, video=replied_video, caption=pm_text)
                else:
                    await message.bot.send_message(chat_id=u.telegram_id, text=pm_text)
            except Exception:
                pass

        # Б) Дублювання в топік "Скарги" (або топік чергувань / загальний чат)
        topic_target = coliving.complaints_topic_id or coliving.duty_topic_id
        group_alert = (
            f"🚨 <b>Нова скарга!</b>\n\n"
            f"• <b>Від:</b> {sender_name}\n"
            f"• <b>Адресовано:</b> {target_names_str}\n"
            f"• <b>Суть:</b> <i>{complaint_text}</i>"
        )
        try:
            if topic_target:
                if replied_photo:
                    await message.bot.send_photo(chat_id=chat_id, message_thread_id=topic_target, photo=replied_photo, caption=group_alert)
                elif replied_video:
                    await message.bot.send_video(chat_id=chat_id, message_thread_id=topic_target, video=replied_video, caption=group_alert)
                else:
                    await message.bot.send_message(chat_id=chat_id, message_thread_id=topic_target, text=group_alert)
        except Exception:
            pass

        # В) Фіксація в базі даних
        reporter = await crud.get_user_by_tg_id(session, sender.id)
        reporter_id = reporter.id if reporter else None
        target_room_id = target_users[0].room_id if (target_users and target_users[0].room_id) else None
        photo_id = replied_photo or replied_video
        await crud.create_complaint(
            session=session,
            coliving_id=coliving.id,
            reporter_id=reporter_id,
            target_room_id=target_room_id,
            photo_file_id=photo_id,
            comment=complaint_text
        )

        await message.reply(
            f"✅ <b>Скаргу зафіксовано!</b>\n"
            f"Повідомлення надіслано в ЛС: <b>{target_names_str}</b>, а також скопійовано в топік скарг."
        )


# -------------------------------------------------------------
# 5. Команда «Чиї речі?» (/чиї_речі, /whose_things, /чиє)
# -------------------------------------------------------------

@router.message(Command("чиї_речі", "whose_things", "чиє", "чиї"))
async def cmd_lost_found(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    chat_id = message.chat.id
    sender = message.from_user
    sender_name = sender.full_name if sender else "Мешканець"

    raw_args = ""
    parts = (message.text or message.caption or "").strip().split(maxsplit=1)
    if len(parts) > 1:
        raw_args = parts[1].strip()

    replied_text = ""
    replied_photo = None
    replied_video = None
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if message.reply_to_message.photo:
            replied_photo = message.reply_to_message.photo[-1].file_id
        elif message.reply_to_message.video:
            replied_video = message.reply_to_message.video.file_id
    elif message.photo:
        replied_photo = message.photo[-1].file_id

    desc = raw_args or replied_text or "Чиї це речі? Заберіть, будь ласка!"

    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return

        all_residents = await crud.get_coliving_users(session, coliving.id)

        # Перевірка: чи когось тегнули
        tagged_usernames = set(re.findall(r"@([a-zA-Z0-9_]{3,})", f"{raw_args} {replied_text}"))
        tagged_usernames.discard("all")
        tagged_usernames.discard("колівінг")

        tagged_users = []
        for u in all_residents:
            if u.username and u.username.lower() in [tun.lower() for tun in tagged_usernames]:
                if u.telegram_id != sender.id:
                    tagged_users.append(u)

        # Відправляємо в ЛС ТІЛЬКИ якщо когось конкретно тегнули
        if tagged_users:
            pm_text = (
                f"📦 <b>Запит «Чиї речі?» у колівінгу «{coliving.name}»:</b>\n\n"
                f"👤 Від: <b>{sender_name}</b>\n"
                f"📝 Опис: <i>{desc}</i>\n\n"
                "Сусіди цікавляться, чи це не ваші речі. Будь ласка, відгукніться в чаті!"
            )
            for u in tagged_users:
                try:
                    if replied_photo:
                        await message.bot.send_photo(chat_id=u.telegram_id, photo=replied_photo, caption=pm_text)
                    elif replied_video:
                        await message.bot.send_video(chat_id=u.telegram_id, video=replied_video, caption=pm_text)
                    else:
                        await message.bot.send_message(chat_id=u.telegram_id, text=pm_text)
                except Exception:
                    pass

        # Дублюємо у топік "Чиї речі?"
        topic_target = coliving.lost_found_topic_id or coliving.duty_topic_id
        tagged_str = f"\n• <b>Згадка:</b> {', '.join([u.full_name for u in tagged_users])}" if tagged_users else ""
        topic_post = (
            f"📦 <b>Чиї це речі?</b>\n\n"
            f"• <b>Від:</b> {sender_name}{tagged_str}\n"
            f"• <b>Опис:</b> <i>{desc}</i>"
        )
        try:
            if topic_target:
                if replied_photo:
                    await message.bot.send_photo(chat_id=chat_id, message_thread_id=topic_target, photo=replied_photo, caption=topic_post)
                elif replied_video:
                    await message.bot.send_video(chat_id=chat_id, message_thread_id=topic_target, video=replied_video, caption=topic_post)
                else:
                    await message.bot.send_message(chat_id=chat_id, message_thread_id=topic_target, text=topic_post)
        except Exception:
            pass

        note_tagged = f" (та надіслано в ЛС {len(tagged_users)} користувачам)" if tagged_users else ""
        await message.reply(f"✅ <b>Запит опубліковано у топік «Чиї речі?»!</b>{note_tagged}")


# -------------------------------------------------------------
# 6. Штраф сотником прямо з чату (/штраф, /fine)
# -------------------------------------------------------------

@router.message(Command("fine", "штраф"))
async def cmd_chat_fine(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    sender_tg = message.from_user.id
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("⚠️ Цю команду потрібно використовувати у відповідь (Reply) на повідомлення порушника.")
        return

    target_tg = message.reply_to_message.from_user.id
    chat_id = message.chat.id

    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return

        sotnik = await crud.get_user_by_tg_id(session, sender_tg)
        if not sotnik or sotnik.role != "SOTNIK" or sotnik.coliving_id != coliving.id:
            await message.reply("⛔ Тільки Сотник цього колівінгу може виписувати штрафи.")
            return

        target_user = await crud.get_user_by_tg_id(session, target_tg)
        if not target_user or target_user.coliving_id != coliving.id:
            await message.reply("⚠️ Користувач не є зареєстрованим мешканцем цього колівінгу.")
            return

        # Парсимо суму та причину: /штраф 100 брудний посуд
        parts = (message.text or "").strip().split(maxsplit=2)
        amount = coliving.default_fine_amount
        reason = "Порушення чистоти / правил колівінгу"

        if len(parts) >= 2:
            try:
                amount = float(parts[1])
                if len(parts) >= 3:
                    reason = parts[2].strip()
            except ValueError:
                reason = " ".join(parts[1:]).strip()

        await crud.create_fine(
            session=session,
            coliving_id=coliving.id,
            room_id=target_user.room_id,
            user_id=target_user.id,
            amount=amount,
            reason=reason
        )

        try:
            await message.bot.send_message(
                chat_id=target_user.telegram_id,
                text=(
                    f"💸 <b>Вам нараховано штраф у колівінгу «{coliving.name}»!</b>\n\n"
                    f"• Сума: <b>{amount:.0f} грн</b>\n"
                    f"• Причина: <i>{reason}</i>\n"
                    f"• Виписав Сотник: {sotnik.full_name}\n\n"
                    "Оплатіть штраф у розділі «Штрафи та скарбничка»."
                )
            )
        except Exception:
            pass

        await message.reply(
            f"⚖️ <b>Штраф успішно нараховано!</b>\n\n"
            f"• Мешканець: <b>{target_user.full_name}</b>\n"
            f"• Сума: <b>{amount:.0f} грн</b>\n"
            f"• Причина: <i>{reason}</i>"
        )


# -------------------------------------------------------------
# 7. Загальний перехоплювач текстових згадок у чаті
# -------------------------------------------------------------

@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_mentions(message: Message):
    if not message.text:
        return

    text = message.text

    # @all або @колівінг
    if ALL_TAG_REGEX.search(text):
        await handle_tag_all(message)
        return

    # @sotnik або @сотники
    if SOTNIK_TAG_REGEX.search(text):
        await handle_tag_sotnik(message)
        return

    # @duty або @чергові
    if DUTY_TAG_REGEX.search(text):
        await show_group_duty(message)
        return

    # Кімната @roomX, /roomX, @кімнатаX
    match = ROOM_TAG_REGEX.search(text)
    if match:
        room_num = int(match.group(1))
        chat_id = message.chat.id
        async with AsyncSessionLocal() as session:
            coliving = await get_coliving_by_chat_id(session, chat_id)
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

            tags = []
            for u in target_room.users:
                if u.username:
                    tags.append(f"@{u.username}")
                else:
                    tags.append(f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>')

            await message.reply(f"📢 <b>{target_room.name}:</b> {' '.join(tags)}")


async def show_group_duty(message: Message):
    chat_id = message.chat.id
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
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


# -------------------------------------------------------------
# 8. Welcome-модуль для нових учасників
# -------------------------------------------------------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_user_join_group(event: ChatMemberUpdated):
    new_user = event.new_chat_member.user
    if new_user.is_bot:
        return

    chat_id = event.chat.id
    async with AsyncSessionLocal() as session:
        coliving = await get_coliving_by_chat_id(session, chat_id)
        if not coliving:
            return

        bot_info = await event.bot.get_me()
        bot_username = bot_info.username

        # 1. Спроба відправити персональне привітання в ЛС користувачу
        pm_sent = False
        try:
            welcome_text = (
                f"👋 <b>Ласкаво просимо до колівінгу «{coliving.name}»!</b>\n\n"
                f"Щоб отримати доступ до кімнати, графіка чергувань та функцій простору, "
                f"зареєструйтеся в боті за посиланням:\n"
                f"👉 https://t.me/{bot_username}?start={coliving.invite_code}"
            )
            await event.bot.send_message(chat_id=new_user.id, text=welcome_text)
            pm_sent = True
        except Exception:
            pm_sent = False

        # 2. Якщо в ЛС не надіслалось (користувач ще не натискав /start у бота)
        if not pm_sent:
            try:
                mention = f"@{new_user.username}" if new_user.username else f'<a href="tg://user?id={new_user.id}">{new_user.full_name}</a>'
                await event.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"👋 Вітаємо, {mention}! "
                        f"Будь ласка, запустіть бота @{bot_username} та введіть код колівінгу <code>{coliving.invite_code}</code>, "
                        f"щоб обрати кімнату."
                    )
                )
            except Exception:
                pass

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import User as TgUser, Chat, Message
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.db import Base
import database.db as db_mod
from database import crud
from bot.handlers import group_chat

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
AsyncSessionLocal = None

@pytest_asyncio.fixture(autouse=True)
async def init_test_db(monkeypatch):
    global AsyncSessionLocal
    test_engine = create_async_engine(TEST_DB_URL, echo=False)
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False
    )
    AsyncSessionLocal = test_session_factory
    monkeypatch.setattr(db_mod, "engine", test_engine)
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(group_chat, "AsyncSessionLocal", test_session_factory)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


def make_mock_group_message(user_id: int, chat_id: int, text: str = "", username: str = "", thread_id: int = None) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = TgUser(id=user_id, is_bot=False, first_name=f"Name_{user_id}", username=username or f"user_{user_id}")
    msg.chat = Chat(id=chat_id, type="supergroup")
    msg.text = text
    msg.caption = None
    msg.photo = None
    msg.video = None
    msg.message_thread_id = thread_id
    msg.reply_to_message = None

    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.send_message = AsyncMock()
    msg.bot.send_photo = AsyncMock()
    msg.bot.send_video = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_group_link_and_topic_linking():
    """Тест прив'язки групи та топіків (чергування, скарги, чиї речі)."""
    sotnik_tg = 9001
    group_chat_id = -100123456789

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Чат",
            address="вул. Групова, 1",
            total_people=4,
            total_rooms=2,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник Чат"
        )
        invite_code = col.invite_code

    # 1. Прив'язка групи за кодом
    msg_link = make_mock_group_message(sotnik_tg, group_chat_id, f"/link_group {invite_code}", thread_id=10)
    await group_chat.cmd_link_group(msg_link)
    msg_link.answer.assert_called_once()
    assert "успішно прив'язано" in msg_link.answer.call_args[0][0]

    # 2. Прив'язка топіку скарг
    msg_complaints_topic = make_mock_group_message(sotnik_tg, group_chat_id, "/link_topic скарги", thread_id=20)
    await group_chat.cmd_link_topics(msg_complaints_topic)
    msg_complaints_topic.reply.assert_called_once()
    assert "Топік для скарг" in msg_complaints_topic.reply.call_args[0][0]

    # 3. Прив'язка топіку "Чиї речі?"
    msg_lost_found = make_mock_group_message(sotnik_tg, group_chat_id, "/link_topic речі", thread_id=30)
    await group_chat.cmd_link_topics(msg_lost_found)
    msg_lost_found.reply.assert_called_once()
    assert "Топік «Чиї речі?»" in msg_lost_found.reply.call_args[0][0]

    # Перевіряємо в БД
    async with AsyncSessionLocal() as session:
        c = await crud.get_coliving_by_id(session, col.id)
        assert c.group_chat_id == group_chat_id
        assert c.duty_topic_id == 10
        assert c.complaints_topic_id == 20
        assert c.lost_found_topic_id == 30


@pytest.mark.asyncio
async def test_tag_all_and_tag_sotnik():
    """Тест @all та @sotnik: перевірка, що @all можуть викликати всі."""
    sotnik_tg = 9101
    resident_tg = 9102
    group_chat_id = -100998877

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Меншени",
            address="вул. Тегова, 5",
            total_people=4,
            total_rooms=1,
            creator_tg_id=sotnik_tg,
            creator_name="Головний Сотник"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        await crud.create_user(
            session=session,
            tg_id=resident_tg,
            full_name="Оксана Мешканка",
            username="oksana_m",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        await crud.link_group_to_coliving(session, col.id, group_chat_id)

    # 1. Звичайний мешканець викликає @all
    msg_all = make_mock_group_message(resident_tg, group_chat_id, "@all загальний збір на кухні!")
    await group_chat.handle_group_mentions(msg_all)
    msg_all.reply.assert_called_once()
    reply_all = msg_all.reply.call_args[0][0]
    assert "Всі мешканці колівінгу" in reply_all
    assert "@oksana_m" in reply_all

    # 2. Виклик через команду /all
    msg_cmd_all = make_mock_group_message(resident_tg, group_chat_id, "/all")
    await group_chat.cmd_tag_all(msg_cmd_all)
    msg_cmd_all.reply.assert_called_once()

    # 3. Виклик @sotnik
    msg_sotnik = make_mock_group_message(resident_tg, group_chat_id, "@sotnik потрібна допомога")
    await group_chat.handle_group_mentions(msg_sotnik)
    msg_sotnik.reply.assert_called_once()
    assert "Сотники колівінгу" in msg_sotnik.reply.call_args[0][0]


@pytest.mark.asyncio
async def test_chat_complaint_routing_default_and_tagged():
    """Тест скарги в чаті: за замовчуванням черговим, при тегуванні — адресно в ЛС."""
    sotnik_tg = 9201
    duty_resident_tg = 9202
    other_resident_tg = 9203
    sender_tg = 9204
    group_chat_id = -100554433

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Скарг",
            address="вул. Чиста, 10",
            total_people=6,
            total_rooms=2,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        # Чергова кімната 1
        await crud.create_user(
            session=session,
            tg_id=duty_resident_tg,
            full_name="Черговий Іван",
            username="duty_ivan",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        # Інша кімната 2
        await crud.create_user(
            session=session,
            tg_id=other_resident_tg,
            full_name="Тарас Сусід",
            username="taras_neighbor",
            coliving_id=col.id,
            room_id=rooms[1].id,
            is_approved=True
        )
        await crud.create_user(
            session=session,
            tg_id=sender_tg,
            full_name="Скаржник Петро",
            username="petro_author",
            coliving_id=col.id,
            room_id=rooms[1].id,
            is_approved=True
        )
        await crud.link_group_to_coliving(session, col.id, group_chat_id, topic_id=5)
        await crud.update_coliving_topics(session, col.id, complaints_topic_id=77)

    # 1. Скарга БЕЗ тегу -> надсилається черговим (кімната 1)
    msg_complaint_default = make_mock_group_message(sender_tg, group_chat_id, "/скарга Хтось не виніс сміття на кухні!")
    await group_chat.cmd_group_complaint(msg_complaint_default)
    msg_complaint_default.reply.assert_called_once()
    assert "Черговий Іван" in msg_complaint_default.reply.call_args[0][0]
    # Перевіряємо, що черговому надіслано в ЛС
    sent_targets = [call.kwargs.get("chat_id") for call in msg_complaint_default.bot.send_message.call_args_list]
    assert duty_resident_tg in sent_targets
    # Перевіряємо, що в топік скарг (77) також надіслано
    assert any(call.kwargs.get("message_thread_id") == 77 for call in msg_complaint_default.bot.send_message.call_args_list)

    # 2. Скарга З ТЕГОМ @taras_neighbor -> надсилається ТІЛЬКИ Тарасу (не черговим!)
    msg_complaint_tagged = make_mock_group_message(sender_tg, group_chat_id, "/скарга @taras_neighbor брудна сковорідка на плиті")
    await group_chat.cmd_group_complaint(msg_complaint_tagged)
    msg_complaint_tagged.reply.assert_called_once()
    assert "Тарас Сусід" in msg_complaint_tagged.reply.call_args[0][0]

    tagged_sent = [call.kwargs.get("chat_id") for call in msg_complaint_tagged.bot.send_message.call_args_list]
    assert other_resident_tg in tagged_sent
    assert duty_resident_tg not in tagged_sent


@pytest.mark.asyncio
async def test_whose_things_and_chat_fine():
    """Тест команди /чиї_речі та виписки штрафу Сотником у чаті."""
    sotnik_tg = 9301
    resident_tg = 9302
    group_chat_id = -100443322

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Речей",
            address="вул. Речова, 2",
            total_people=4,
            total_rooms=1,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник Речей"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        await crud.create_user(
            session=session,
            tg_id=resident_tg,
            full_name="Володимир",
            username="vova_res",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        await crud.link_group_to_coliving(session, col.id, group_chat_id)
        await crud.update_coliving_topics(session, col.id, lost_found_topic_id=88)

    # 1. /чиї_речі без тегу: надсилається в топік, але НІКОМУ в ЛС
    msg_things_no_tag = make_mock_group_message(resident_tg, group_chat_id, "/чиї_речі Чия куртка в коридорі?")
    await group_chat.cmd_lost_found(msg_things_no_tag)
    msg_things_no_tag.reply.assert_called_once()
    assert "опубліковано у топік «Чиї речі?»" in msg_things_no_tag.reply.call_args[0][0]
    # У ЛС нікому не має відправлятись
    assert all(call.kwargs.get("chat_id") == group_chat_id for call in msg_things_no_tag.bot.send_message.call_args_list)

    # 2. /чиї_речі з тегом @vova_res: надсилається в ЛС Вові
    msg_things_tagged = make_mock_group_message(sotnik_tg, group_chat_id, "/чиї_речі @vova_res це твої навушники?")
    await group_chat.cmd_lost_found(msg_things_tagged)
    msg_things_tagged.reply.assert_called_once()
    assert any(call.kwargs.get("chat_id") == resident_tg for call in msg_things_tagged.bot.send_message.call_args_list)

    # 3. Виписка штрафу Сотником реплаєм
    msg_fine = make_mock_group_message(sotnik_tg, group_chat_id, "/штраф 100 бруд на столі")
    replied_msg = MagicMock()
    replied_msg.from_user = TgUser(id=resident_tg, is_bot=False, first_name="Володимир")
    msg_fine.reply_to_message = replied_msg
    await group_chat.cmd_chat_fine(msg_fine)
    msg_fine.reply.assert_called_once()
    assert "Штраф успішно нараховано" in msg_fine.reply.call_args[0][0]

    # Перевіряємо в БД
    async with AsyncSessionLocal() as session:
        fines = await crud.get_unpaid_fines(session, col.id)
        assert len(fines) == 1
        assert fines[0].amount == 100.0


@pytest.mark.asyncio
async def test_group_help_command():
    """Тест команди /help у груповому чаті."""
    chat_id = -100555666
    msg = make_mock_group_message(101, chat_id, "/help")
    await group_chat.cmd_group_help(msg)
    msg.reply.assert_called_once()
    reply_text = msg.reply.call_args[0][0]
    assert "@all" in reply_text
    assert "@sotnik" in reply_text
    assert "/скарга" in reply_text
    assert "/чиї_речі" in reply_text
    assert "/calendar" in reply_text
    assert "/штраф" in reply_text


@pytest.mark.asyncio
async def test_group_calendar_and_duty_hyperlinks():
    """Тест гіперпосилань імен чергових мешканців у графіку та /duty."""
    sotnik_tg = 9401
    resident_tg = 9402
    group_chat_id = -100998877

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Лінк",
            address="вул. Посилання, 5",
            total_people=4,
            total_rooms=2,
            creator_tg_id=sotnik_tg,
            creator_name="Олександр Сотник"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        user = await crud.create_user(
            session=session,
            tg_id=resident_tg,
            full_name="Марія Коваль",
            username="maria_k",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        await crud.link_group_to_coliving(session, col.id, group_chat_id)

    # 1. Перевірка команди /calendar
    msg_cal = make_mock_group_message(sotnik_tg, group_chat_id, "/calendar")
    await group_chat.cmd_group_calendar(msg_cal)
    msg_cal.reply.assert_called_once()
    cal_text = msg_cal.reply.call_args[0][0]
    assert f'<a href="tg://user?id={resident_tg}">Марія Коваль</a>' in cal_text
    assert f'<a href="tg://user?id={sotnik_tg}">Олександр Сотник</a>' in cal_text

    # 2. Перевірка функції show_group_duty (/duty)
    msg_duty = make_mock_group_message(resident_tg, group_chat_id, "/duty")
    await group_chat.show_group_duty(msg_duty)
    msg_duty.reply.assert_called_once()
    duty_text = msg_duty.reply.call_args[0][0]
    assert f'<a href="tg://user?id={resident_tg}">Марія Коваль</a>' in duty_text
    assert f'<a href="tg://user?id={sotnik_tg}">Олександр Сотник</a>' in duty_text


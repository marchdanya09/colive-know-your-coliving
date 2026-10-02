import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage, StorageKey
from aiogram.types import User as TgUser, Chat, Message, CallbackQuery

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.db import Base
import database.db as db_mod
from database import crud
from bot.handlers import start, user_menu, sotnik_panel
from config import settings
import texts

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
    monkeypatch.setattr(start, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(user_menu, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(sotnik_panel, "AsyncSessionLocal", test_session_factory)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()



@pytest.fixture
def memory_storage():
    return MemoryStorage()

def make_fsm_context(storage: MemoryStorage, user_id: int) -> FSMContext:
    key = StorageKey(bot_id=999, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)

def make_mock_message(user_id: int, text: str = "") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = TgUser(id=user_id, is_bot=False, first_name=f"User_{user_id}", username=f"user_{user_id}")
    msg.chat = Chat(id=user_id, type="private")
    msg.text = text
    msg.caption = None
    msg.photo = None
    msg.video = None
    msg.video_note = None
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.get_me = AsyncMock(return_value=TgUser(id=999, is_bot=True, first_name="CO:LIVE Bot", username="colive_test_bot"))
    msg.bot.send_message = AsyncMock()
    msg.bot.send_photo = AsyncMock()
    msg.bot.send_video = AsyncMock()
    msg.bot.send_video_note = AsyncMock()
    return msg

def make_mock_callback(user_id: int, data: str) -> MagicMock:
    call = MagicMock(spec=CallbackQuery)
    call.from_user = TgUser(id=user_id, is_bot=False, first_name=f"User_{user_id}", username=f"user_{user_id}")
    call.data = data
    call.answer = AsyncMock()
    call.message = MagicMock(spec=Message)
    call.message.from_user = TgUser(id=999, is_bot=True, first_name="CO:LIVE Bot", username="colive_test_bot")
    call.message.edit_text = AsyncMock()
    call.message.answer = AsyncMock()
    call.bot = AsyncMock()
    call.bot.get_me = AsyncMock(return_value=TgUser(id=999, is_bot=True, first_name="CO:LIVE Bot", username="colive_test_bot"))
    call.bot.send_message = AsyncMock()
    return call

@pytest.mark.asyncio
async def test_sotnik_wizard_full_flow(memory_storage):
    """Тест флоу створення колівінгу: назва -> адреса -> люди -> кімнати."""
    sotnik_id = 5551
    state = make_fsm_context(memory_storage, sotnik_id)

    # 1. Крок 1: Введення назви
    msg1 = make_mock_message(sotnik_id, "Колівінг Світанок")
    await start.wizard_name(msg1, state)
    msg1.answer.assert_called_once()
    assert "Крок 2/4" in msg1.answer.call_args[0][0]

    # 2. Крок 2: Введення адреси
    msg2 = make_mock_message(sotnik_id, "вул. Саксаганського, 10")
    await start.wizard_address(msg2, state)
    msg2.answer.assert_called_once()
    assert "Крок 3/4" in msg2.answer.call_args[0][0]

    # 3. Крок 3: Введення кількості людей
    msg3 = make_mock_message(sotnik_id, "16")
    await start.wizard_people(msg3, state)
    msg3.answer.assert_called_once()
    assert "Крок 4/4" in msg3.answer.call_args[0][0]

    # 4. Крок 4: Введення кількості кімнат "4" (Той самий крок, що ламався!)
    msg4 = make_mock_message(sotnik_id, "4")
    await start.wizard_rooms(msg4, state)
    msg4.answer.assert_called_once()
    reply_text = msg4.answer.call_args[0][0]

    # Перевіряємо, що відповідь надіслана, HTML валідний, дані створені
    assert "Колівінг успішно створено!" in reply_text
    assert "Колівінг Світанок" in reply_text
    assert "https://t.me/colive_test_bot?start=join_" in reply_text

    # Перевіряємо БД
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, sotnik_id)
        assert user is not None
        assert user.role == "SOTNIK"
        assert user.is_approved is True
        assert user.coliving.name == "Колівінг Світанок"
        assert len(user.coliving.rooms) == 4

@pytest.mark.asyncio
async def test_sotnik_join_existing_coliving(memory_storage):
    """Тест флоу приєднання другого сотника до наявного колівінгу."""
    # Створюємо колівінг
    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Тестовий Дім",
            address="Адреса",
            total_people=8,
            total_rooms=2,
            creator_tg_id=1111,
            creator_name="Головний Сотник"
        )
        code = col.invite_code
        rooms = await crud.get_rooms_with_users(session, col.id)
        second_room_id = rooms[1].id

    sotnik2_id = 2222
    state = make_fsm_context(memory_storage, sotnik2_id)

    # 1. Другий сотник вводить код
    msg_code = make_mock_message(sotnik2_id, code)
    await start.process_sotnik_code(msg_code, state)
    msg_code.answer.assert_called_once()
    assert "введіть ваше" in msg_code.answer.call_args[0][0].lower()

    # 2. Вводить ім'я
    msg_name = make_mock_message(sotnik2_id, "Олег Заступник")
    await start.sotnik_entered_name(msg_name, state)
    msg_name.answer.assert_called_once()
    assert "Оберіть кімнату" in msg_name.answer.call_args[0][0]

    # 3. Обирає кімнату 2
    call_room = make_mock_callback(sotnik2_id, f"select_room_{second_room_id}")
    await start.sotnik_selected_room(call_room, state)
    call_room.message.edit_text.assert_called_once()
    assert "Заявку на роль Сотника надіслано" in call_room.message.edit_text.call_args[0][0]

    # 4. Перевіряємо, що заявка з роллю SOTNIK є в базі
    async with AsyncSessionLocal() as session:
        reqs = await crud.get_pending_requests(session, col.id)
        assert len(reqs) == 1
        assert reqs[0].target_role == "SOTNIK"
        req_id = reqs[0].id

    # 5. Головний сотник схвалює заявку
    call_app = make_mock_callback(1111, f"req_app_{req_id}")
    await sotnik_panel.cb_approve_request(call_app)
    call_app.message.edit_text.assert_called_once()
    assert "схвалено" in call_app.message.edit_text.call_args[0][0]

    # Перевіряємо статус другого сотника
    async with AsyncSessionLocal() as session:
        user2 = await crud.get_user_by_tg_id(session, sotnik2_id)
        assert user2 is not None
        assert user2.role == "SOTNIK"
        assert user2.is_approved is True
        assert user2.room_id == second_room_id

@pytest.mark.asyncio
async def test_navigation_back_buttons(memory_storage):
    """Тест зворотної навігації на кожному кроці."""
    user_id = 3333
    state = make_fsm_context(memory_storage, user_id)

    # 1. Назад до головного меню з вибору ролі сотника
    call_back_start = make_mock_callback(user_id, "role_back_to_start")
    await start.cb_role_back_to_start(call_back_start, state)
    call_back_start.message.edit_text.assert_called_once()
    assert "Оберіть вашу роль" in call_back_start.message.edit_text.call_args[0][0]

    # 2. Назад з кроку 2 (адреса) до кроку 1 (назва)
    call_back_name = make_mock_callback(user_id, "wizard_back_to_name")
    await start.cb_wizard_back_to_name(call_back_name, state)
    call_back_name.message.edit_text.assert_called_once()
    assert "Крок 1/4" in call_back_name.message.edit_text.call_args[0][0]

    # 3. Назад з введення коду мешканця
    call_back_res = make_mock_callback(user_id, "role_back_to_start")
    await start.cb_role_back_to_start(call_back_res, state)
    call_back_res.message.edit_text.assert_called_once()
    assert "Оберіть вашу роль" in call_back_res.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_user_menu_and_callback_navigation():
    """Тест переходу в Мій колівінг, Моя кімната через повідомлення та CallbackQuery."""
    sotnik_tg = 7777
    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Сонце",
            address="вул. Хрещатик, 1",
            total_people=4,
            total_rooms=2,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник Дмитро"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        # Assign sotnik to room 1
        sotnik_user = await crud.get_user_by_tg_id(session, sotnik_tg)
        sotnik_user.room_id = rooms[0].id
        await session.commit()

    # 1. Запит через звичайне повідомлення (кнопка внизу)
    msg = make_mock_message(sotnik_tg, texts.BTN_MY_COLIVING)
    await user_menu.menu_my_coliving(msg)
    msg.answer.assert_called_once()
    reply_text = msg.answer.call_args[0][0]
    assert "Колівінг Сонце" in reply_text
    assert "Сотник Дмитро" in reply_text

    # 2. Оновлення через інлайн-кнопку [🔄 Оновити дані]
    # Нагадування: call.message.from_user має ID бота (999), а call.from_user має ID мешканця (7777)
    call_refresh = make_mock_callback(sotnik_tg, "user_nav_my_coliving")
    await user_menu.cb_nav_my_coliving(call_refresh)
    call_refresh.message.edit_text.assert_called_once()
    edit_text = call_refresh.message.edit_text.call_args[0][0]
    assert "Колівінг Сонце" in edit_text
    call_refresh.answer.assert_called_once_with("Дані оновлено! 🔄")

    # 3. Перехід у "Моя кімната" через повідомлення
    msg_room = make_mock_message(sotnik_tg, texts.BTN_MY_ROOM)
    await user_menu.menu_my_room(msg_room)
    msg_room.answer.assert_called_once()
    assert "Кімната 1" in msg_room.answer.call_args[0][0]

    # 4. Перехід у "Моя кімната" через інлайн-кнопку
    call_room = make_mock_callback(sotnik_tg, "user_nav_my_room")
    await user_menu.cb_nav_my_room(call_room)
    call_room.message.edit_text.assert_called_once()
    assert "Кімната 1" in call_room.message.edit_text.call_args[0][0]
    call_room.answer.assert_called_once_with("Дані оновлено! 🔄")


@pytest.mark.asyncio
async def test_sotnik_panel_command_and_callbacks():
    """Тест відкриття Панелі Сотника через команду та перемикання кнопок."""
    sotnik_tg = 9991
    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Затишок",
            address="вул. Басейна, 5",
            total_people=6,
            total_rooms=3,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник Іван"
        )

    # 1. Відкриття через /panel
    msg_cmd = make_mock_message(sotnik_tg, "/panel")
    await sotnik_panel.menu_sotnik_panel(msg_cmd)
    # Повинні бути надіслані 2 відповіді: оновлення клавіатури і сама панель
    assert msg_cmd.answer.call_count == 2
    last_text = msg_cmd.answer.call_args[0][0]
    assert "Панель керування Сотника" in last_text or "Колівінг Затишок" in last_text

    # 2. Повернення назад до панелі через callback
    call_back = make_mock_callback(sotnik_tg, "sotnik_back_panel")
    await sotnik_panel.cb_sotnik_back(call_back)
    call_back.message.edit_text.assert_called_once()
    assert "Панель керування Сотника" in call_back.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_urgent_complaint_all_formats_and_redirection(memory_storage):
    """Тест термінової скарги: текст напряму, фото з підписом, роутинг сотникам та скасування."""
    sotnik_tg = 1111
    resident_tg = 2222

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Скарги",
            address="вул. Скаргова, 1",
            total_people=4,
            total_rooms=2,
            creator_tg_id=sotnik_tg,
            creator_name="Сотник Петро"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        # Add resident in room 2
        await crud.create_user(
            session=session,
            tg_id=resident_tg,
            full_name="Максим Мешканець",
            coliving_id=col.id,
            room_id=rooms[1].id,
            is_approved=True
        )

    # 1. Мешканець відкриває розділ скарги
    state = make_fsm_context(memory_storage, resident_tg)
    msg_btn = make_mock_message(resident_tg, texts.BTN_URGENT_COMPLAINT)
    await user_menu.menu_urgent_complaint(msg_btn, state)
    msg_btn.answer.assert_called_once()
    assert "Термінова скарга" in msg_btn.answer.call_args[0][0]

    # 2. Мешканець вводить скаргу ПРЯМО ТЕКСТОМ (як на скріншоті користувача "аьаа")
    msg_text = make_mock_message(resident_tg, "Прорвало трубу на кухні!")
    await user_menu.process_complaint_first_step(msg_text, state)
    msg_text.answer.assert_called_once()
    assert texts.COMPLAINT_SENT_SUCCESS in msg_text.answer.call_args[0][0]

    # Перевіряємо, що скарга доставлена в ЛС черговим або сотникам
    assert msg_text.bot.send_message.call_count >= 1

    # 3. Скарга фотографією з підписом
    msg_photo_cap = make_mock_message(resident_tg)
    photo_obj = MagicMock()
    photo_obj.file_id = "photo_test_123"
    msg_photo_cap.photo = [photo_obj]
    msg_photo_cap.caption = "Брудна плита"
    await user_menu.process_complaint_first_step(msg_photo_cap, state)
    msg_photo_cap.answer.assert_called_once()
    assert texts.COMPLAINT_SENT_SUCCESS in msg_photo_cap.answer.call_args[0][0]

    # 4. Скасування скарги по інлайн-кнопці
    call_cancel = make_mock_callback(resident_tg, "cancel_complaint")
    await user_menu.cb_cancel_complaint(call_cancel, state)
    call_cancel.message.edit_text.assert_called_once()
    assert "скасовано" in call_cancel.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_room_broadcast_two_reply_buttons_and_direct_reply(memory_storage):
    """Тест відправки повідомлення кімнаті з 2 кнопками та особистої відповіді."""
    user1_tg = 4001
    user2_tg = 4002

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Чат",
            address="вул. Чатова, 2",
            total_people=4,
            total_rooms=1,
            creator_tg_id=user1_tg,
            creator_name="Сусід 1"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        # Сусід 2 у тій же кімнаті
        u2 = await crud.create_user(
            session=session,
            tg_id=user2_tg,
            full_name="Сусід 2",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        u1 = await crud.get_user_by_tg_id(session, user1_tg)
        u1_id = u1.id
        u2_id = u2.id

    state1 = make_fsm_context(memory_storage, user1_tg)

    # 1. Сусід 1 надсилає повідомлення кімнаті
    msg_broad = make_mock_message(user1_tg, "Хто залишив чашку?")
    await user_menu.process_room_broadcast(msg_broad, state1)
    msg_broad.answer.assert_called_once()
    assert "Повідомлення надіслано сусідам" in msg_broad.answer.call_args[0][0]

    # Перевіряємо, що у повідомленні сусіду 2 є дві кнопки: відповісти кімнаті та особисто сусіду 1
    assert msg_broad.bot.send_message.call_count == 1
    call_args = msg_broad.bot.send_message.call_args
    sent_kb = call_args[1]["reply_markup"]
    assert len(sent_kb.inline_keyboard[0]) == 2
    assert sent_kb.inline_keyboard[0][0].text == "📢 Відповісти кімнаті"
    assert sent_kb.inline_keyboard[0][1].text == "👤 Відповісти Сусід 1"
    assert sent_kb.inline_keyboard[0][1].callback_data == f"room_reply_user_{u1_id}"

    # 2. Сусід 2 натискає "Відповісти Сусід 1"
    state2 = make_fsm_context(memory_storage, user2_tg)
    call_reply = make_mock_callback(user2_tg, f"room_reply_user_{u1_id}")
    await user_menu.cb_room_reply_user(call_reply, state2)
    call_reply.message.answer.assert_called_once()
    assert "Введіть особисту відповідь для Сусід 1" in call_reply.message.answer.call_args[0][0]

    # 3. Сусід 2 вводить особисту відповідь
    msg_reply_text = make_mock_message(user2_tg, "Це моя чашка, зараз приберу!")
    await user_menu.process_direct_reply(msg_reply_text, state2)
    msg_reply_text.answer.assert_called_once()
    assert "Відповідь успішно надіслано" in msg_reply_text.answer.call_args[0][0]

    # Перевіряємо, що сусіду 1 прийшла особиста відповідь з кнопками зворотного зв'язку
    assert msg_reply_text.bot.send_message.call_count == 1
    direct_args = msg_reply_text.bot.send_message.call_args
    assert direct_args[1]["chat_id"] == user1_tg
    assert "Особиста відповідь від Сусід 2" in direct_args[1]["text"]


@pytest.mark.asyncio
async def test_room_duties_and_starosta_assignment_by_buttons(memory_storage):
    """Тест налаштування обов'язків у кімнаті та призначення Старости через кнопки."""
    user_tg = 5001

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Обов'язки",
            address="вул. Затишна, 10",
            total_people=4,
            total_rooms=1,
            creator_tg_id=user_tg,
            creator_name="Олексій"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        user = await crud.get_user_by_tg_id(session, user_tg)
        user_id = user.id
        room_id = rooms[0].id

    # 1. Відкриття меню обов'язків кімнати
    call_duties = make_mock_callback(user_tg, "room_duties_menu")
    await user_menu.cb_room_duties_menu(call_duties)
    call_duties.message.edit_text.assert_called_once()
    assert "Керування обов'язками кімнати" in call_duties.message.edit_text.call_args[0][0]

    # 2. Вибір мешканця для призначення обов'язку
    call_member = make_mock_callback(user_tg, f"room_member_duty_{user_id}")
    await user_menu.cb_room_member_duty(call_member)
    call_member.message.edit_text.assert_called_once()
    assert "Оберіть обов'язок або роль" in call_member.message.edit_text.call_args[0][0]

    # 3. Призначення обов'язку: Кухня
    call_set_duty = make_mock_callback(user_tg, f"set_duty_{user_id}_kitchen")
    await user_menu.cb_set_duty(call_set_duty)
    call_set_duty.answer.assert_called_once_with("Обов'язок встановлено: 🍳 Кухня!", show_alert=True)

    # 4. Призначення Старостою кімнати
    call_starosta = make_mock_callback(user_tg, f"toggle_starosta_{user_id}")
    await user_menu.cb_toggle_starosta(call_starosta)
    call_starosta.answer.assert_called_once_with("Статус Старости оновлено: Староста!", show_alert=True)

    # 5. Перевірка збереження в БД
    async with AsyncSessionLocal() as session:
        u = await crud.get_user_by_id(session, user_id)
        assert u.room_duty == "🍳 Кухня"
        assert u.room_role == "Староста"

    # 5a. Встановлення власного обов'язку
    state_custom = make_fsm_context(memory_storage, user_tg)
    call_custom = make_mock_callback(user_tg, f"custom_duty_prompt_{user_id}")
    await user_menu.cb_custom_duty_prompt(call_custom, state_custom)
    call_custom.message.edit_text.assert_called_once()
    assert "Введіть назву власного обов'язку" in call_custom.message.edit_text.call_args[0][0]

    msg_custom = make_mock_message(user_tg, "🪴 Полив квітів та рослин")
    await user_menu.process_custom_duty(msg_custom, state_custom)
    assert msg_custom.answer.call_count == 2
    assert "Власний обов'язок успішно встановлено" in msg_custom.answer.call_args_list[0][0][0]

    async with AsyncSessionLocal() as session:
        u = await crud.get_user_by_id(session, user_id)
        assert u.room_duty == "🪴 Полив квітів та рослин"

    # 6. Встановлення внутрішніх правил кімнати
    state = make_fsm_context(memory_storage, user_tg)
    call_rules = make_mock_callback(user_tg, f"room_edit_rules_{room_id}")
    await user_menu.cb_room_edit_rules(call_rules, state)
    call_rules.message.edit_text.assert_called_once()

    msg_rules = make_mock_message(user_tg, "Тиша після 23:00, посуд миємо одразу.")
    await user_menu.process_room_edit_rules(msg_rules, state)
    assert msg_rules.answer.call_count == 2
    assert "правила кімнати збережено" in msg_rules.answer.call_args_list[0][0][0].lower()

    # 7. Перегляд загальної сторінки "Мої обов'язки" (кнопка внизу)
    call_nav_duties = make_mock_callback(user_tg, "user_nav_duties")
    await user_menu.cb_user_nav_duties(call_nav_duties)
    call_nav_duties.message.edit_text.assert_called_once()
    page_text = call_nav_duties.message.edit_text.call_args[0][0]
    assert "🪴 Полив квітів та рослин" in page_text
    assert "Староста кімнати" in page_text


@pytest.mark.asyncio
async def test_sotnik_role_and_duty_assignment_by_buttons(memory_storage):
    """Тест призначення ролей та обов'язків сотником виключно через інтерфейсні кнопки."""
    sotnik_tg = 6001
    resident_tg = 6002

    async with AsyncSessionLocal() as session:
        col, _ = await crud.create_coliving_with_rooms(
            session=session,
            name="Колівінг Панель",
            address="вул. Стрілецька, 5",
            total_people=4,
            total_rooms=1,
            creator_tg_id=sotnik_tg,
            creator_name="Головний Сотник"
        )
        rooms = await crud.get_rooms_with_users(session, col.id)
        res = await crud.create_user(
            session=session,
            tg_id=resident_tg,
            full_name="Віктор Мешканець",
            coliving_id=col.id,
            room_id=rooms[0].id,
            is_approved=True
        )
        res_id = res.id

    # 1. Сотник переглядає картку мешканця через інлайн-кнопку
    call_view = make_mock_callback(sotnik_tg, f"sotnik_view_user_{res_id}")
    await sotnik_panel.cb_view_user(call_view)
    call_view.message.edit_text.assert_called_once()
    assert "Віктор Мешканець" in call_view.message.edit_text.call_args[0][0]

    # 2. Сотник призначає мешканця Старостою кімнати через кнопку
    call_starosta = make_mock_callback(sotnik_tg, f"sotnik_toggle_starosta_{res_id}")
    await sotnik_panel.cb_sotnik_toggle_starosta(call_starosta)
    call_starosta.answer.assert_called_once_with("Статус Старости оновлено: Староста!", show_alert=True)

    # 3. Сотник призначає мешканцю обов'язок: Санвузол через кнопку
    call_duty = make_mock_callback(sotnik_tg, f"sotnik_set_user_duty_{res_id}_bath")
    await sotnik_panel.cb_sotnik_set_user_duty(call_duty)
    call_duty.answer.assert_called_once_with("Обов'язок встановлено: 🧼 Санвузол!", show_alert=True)

    # 3a. Сотник встановлює власний кастомний обов'язок
    state_sotnik_custom = make_fsm_context(memory_storage, sotnik_tg)
    call_s_custom = make_mock_callback(sotnik_tg, f"sotnik_custom_duty_{res_id}")
    await sotnik_panel.cb_sotnik_custom_duty(call_s_custom, state_sotnik_custom)
    call_s_custom.message.edit_text.assert_called_once()
    assert "Введіть назву власного обов'язку" in call_s_custom.message.edit_text.call_args[0][0]

    msg_s_custom = make_mock_message(sotnik_tg, "☕ Закупівля кави для кухні")
    await sotnik_panel.process_sotnik_custom_duty(msg_s_custom, state_sotnik_custom)
    assert msg_s_custom.answer.call_count == 2
    assert "Власний обов'язок успішно встановлено" in msg_s_custom.answer.call_args_list[0][0][0]

    async with AsyncSessionLocal() as session:
        u = await crud.get_user_by_id(session, res_id)
        assert u.room_duty == "☕ Закупівля кави для кухні"

    # 4. Сотник редагує загальні правила чергувань колівінгу
    state = make_fsm_context(memory_storage, sotnik_tg)
    call_edit_rules = make_mock_callback(sotnik_tg, "sotnik_edit_duty_rules")
    await sotnik_panel.cb_sotnik_edit_duty_rules(call_edit_rules, state)
    call_edit_rules.message.edit_text.assert_called_once()

    msg_new_rules = make_mock_message(sotnik_tg, "1. Сортуємо пластик окремо.\n2. Миємо раковину щовечора.")
    await sotnik_panel.process_sotnik_edit_duty_rules(msg_new_rules, state)
    assert msg_new_rules.answer.call_count == 2
    assert "Чекліст обов'язків чергування успішно оновлено!" in msg_new_rules.answer.call_args_list[0][0][0]

    # 5. Перевіряємо стан БД
    async with AsyncSessionLocal() as session:
        u = await crud.get_user_by_id(session, res_id)
        assert u.room_role == "Староста"
        assert u.room_duty == "☕ Закупівля кави для кухні"
        c = await crud.get_coliving_by_id(session, col.id)
        assert "Сортуємо пластик окремо" in c.custom_duty_rules



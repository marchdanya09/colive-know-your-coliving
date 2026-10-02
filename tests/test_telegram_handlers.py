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

def make_mock_message(user_id: int, text: str) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = TgUser(id=user_id, is_bot=False, first_name=f"User_{user_id}", username=f"user_{user_id}")
    msg.chat = Chat(id=user_id, type="private")
    msg.text = text
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.get_me = AsyncMock(return_value=TgUser(id=999, is_bot=True, first_name="CO:LIVE Bot", username="colive_test_bot"))
    msg.bot.send_message = AsyncMock()
    msg.bot.send_photo = AsyncMock()
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


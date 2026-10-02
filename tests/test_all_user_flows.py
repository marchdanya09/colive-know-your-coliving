import pytest
import asyncio
from datetime import date
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database.db import Base
from database.models import Coliving, Room, User, JoinRequest, DutyCycle, Complaint, Fine, Blacklist
from database import crud
from bot.middlewares.anti_spam import RateLimiter
import texts

import pytest_asyncio

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as s:
        yield s
    
    await engine.dispose()

@pytest.mark.asyncio
async def test_sotnik_create_coliving(session: AsyncSession):
    """Тест 1: Створення колівінгу сотником (4 кімнати, 16 осіб)."""
    coliving, sotnik = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Тест",
        address="вул. Тестова, 1",
        total_people=16,
        total_rooms=4,
        creator_tg_id=1001,
        creator_name="Олександр Сотник",
        creator_username="sotnik_alex"
    )
    assert coliving.id is not None
    assert len(coliving.invite_code) >= 8
    assert sotnik.role == "SOTNIK"
    assert sotnik.is_approved is True

    # Перевіряємо кімнати
    rooms = await crud.get_rooms_with_users(session, coliving.id)
    assert len(rooms) == 4
    assert rooms[0].capacity == 4
    # Сотник автоматично в кімнаті 1
    assert sotnik.room_id == rooms[0].id

    # Перевіряємо чергування першого тижня
    duty = await crud.get_current_duty(session, coliving.id)
    assert duty is not None
    assert duty.room_id == rooms[0].id

@pytest.mark.asyncio
async def test_resident_join_flow(session: AsyncSession):
    """Тест 2: Мешканець заходить за кодом, обирає кімнату, чекає схвалення."""
    coliving, _ = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Поділ",
        address="Поділ, 10",
        total_people=8,
        total_rooms=2,
        creator_tg_id=1001,
        creator_name="Сотник 1"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # 1. Створюємо заявку мешканця в кімнату 2
    req = await crud.create_join_request(
        session=session,
        coliving_id=coliving.id,
        room_id=rooms[1].id,
        tg_id=2001,
        full_name="Іван Мешканець",
        username="ivan_m",
        target_role="RESIDENT"
    )
    assert req.status == "PENDING"
    assert req.target_role == "RESIDENT"

    # 2. Сотник бачить заявку
    pending = await crud.get_pending_requests(session, coliving.id)
    assert len(pending) == 1
    assert pending[0].id == req.id

    # 3. Сотник схвалює заявку
    res = await crud.approve_request(session, req.id)
    assert res is not None
    approved_req, approved_user = res
    assert approved_req.status == "APPROVED"
    assert approved_user.role == "RESIDENT"
    assert approved_user.is_approved is True
    assert approved_user.room_id == rooms[1].id
    assert approved_user.coliving_id == coliving.id

@pytest.mark.asyncio
async def test_second_sotnik_join_flow(session: AsyncSession):
    """Тест 3: Другий сотник приєднується до наявного колівінгу."""
    coliving, sotnik1 = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Центр",
        address="Центр, 5",
        total_people=12,
        total_rooms=3,
        creator_tg_id=1001,
        creator_name="Головний Сотник"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # Заявка від другого сотника в кімнату 2
    req = await crud.create_join_request(
        session=session,
        coliving_id=coliving.id,
        room_id=rooms[1].id,
        tg_id=1002,
        full_name="Другий Сотник",
        username="sotnik_two",
        target_role="SOTNIK"
    )
    assert req.target_role == "SOTNIK"

    # Схвалення заявки
    _, new_sotnik = await crud.approve_request(session, req.id)
    assert new_sotnik.role == "SOTNIK"
    assert new_sotnik.is_approved is True

    # Перевіряємо кількість сотників
    sotniks = await crud.get_sotniks(session, coliving.id)
    assert len(sotniks) == 2

@pytest.mark.asyncio
async def test_max_3_sotniks_limit(session: AsyncSession):
    """Тест 4: Перевірка ліміту в 3 сотники."""
    coliving, _ = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Ліміти",
        address="Адреса",
        total_people=10,
        total_rooms=2,
        creator_tg_id=1001,
        creator_name="Сотник 1"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # Додаємо 2-го та 3-го сотника
    req2 = await crud.create_join_request(session, coliving.id, rooms[0].id, 1002, "Сотник 2", None, "SOTNIK")
    await crud.approve_request(session, req2.id)

    req3 = await crud.create_join_request(session, coliving.id, rooms[1].id, 1003, "Сотник 3", None, "SOTNIK")
    await crud.approve_request(session, req3.id)

    sotniks = await crud.get_sotniks(session, coliving.id)
    assert len(sotniks) == 3

    # Спроба додати 4-го сотника
    req4 = await crud.create_join_request(session, coliving.id, rooms[1].id, 1004, "Кандидат 4", None, "SOTNIK")
    _, approved_user4 = await crud.approve_request(session, req4.id)
    # Через ліміт 3 сотники його роль автоматично стає RESIDENT
    assert approved_user4.role == "RESIDENT"

@pytest.mark.asyncio
async def test_complaints_and_fines(session: AsyncSession):
    """Тест 5: Подання термінової скарги та нарахування штрафу."""
    coliving, _ = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Чистота",
        address="Адреса",
        total_people=8,
        total_rooms=2,
        creator_tg_id=1001,
        creator_name="Сотник"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # Додаємо мешканця в кімнату 2 (який скаржиться на чергову кімнату 1)
    reporter = await crud.create_user(
        session=session,
        tg_id=2001,
        full_name="Пильний Мешканець",
        coliving_id=coliving.id,
        room_id=rooms[1].id,
        is_approved=True
    )

    # Створюємо скаргу на кімнату 1
    complaint = await crud.create_complaint(
        session=session,
        coliving_id=coliving.id,
        reporter_id=reporter.id,
        target_room_id=rooms[0].id,
        photo_file_id="photo_xyz_123",
        comment="Посуд у раковині з вечора"
    )
    assert complaint.id is not None
    assert complaint.status == "OPEN"

    # Нараховуємо штраф 50 грн на кімнату 1
    fine = await crud.add_fine(
        session=session,
        coliving_id=coliving.id,
        room_id=rooms[0].id,
        complaint_id=complaint.id,
        amount=50.0,
        reason="Неприбраний посуд"
    )
    assert fine.amount == 50.0

    # Перевіряємо баланс скарбнички
    col = await crud.get_coliving_by_id(session, coliving.id)
    assert col.treasury_balance == 50.0

@pytest.mark.asyncio
async def test_rotation_and_code_regen(session: AsyncSession):
    """Тест 6: Ротація чергувань та регенерація інвайт-коду."""
    coliving, _ = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Ротація",
        address="Адреса",
        total_people=8,
        total_rooms=2,
        creator_tg_id=1001,
        creator_name="Сотник"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # Спочатку чергує кімната 1
    duty1 = await crud.get_current_duty(session, coliving.id)
    assert duty1.room_id == rooms[0].id

    # Ротація ➔ чергує кімната 2
    duty2 = await crud.rotate_duty(session, coliving.id)
    assert duty2.room_id == rooms[1].id

    # Ротація по колу ➔ повертається до кімнати 1
    duty3 = await crud.rotate_duty(session, coliving.id)
    assert duty3.room_id == rooms[0].id

    # Тест регенерації коду
    old_code = coliving.invite_code
    new_code = await crud.regenerate_coliving_code(session, coliving.id)
    assert new_code != old_code
    assert len(new_code) >= 8

def test_rate_limiter_anti_spam():
    """Тест 7: Тестування антифлуд та рейт-лімітів."""
    limiter = RateLimiter()
    user_id = 9999

    # 1. Спроби введення коду (до 30 спроб OK, на 30 блокує)
    for _ in range(29):
        assert limiter.record_failed_code_attempt(user_id) is False
        assert limiter.is_code_locked(user_id) is False

    # 30-та спроба блокує
    assert limiter.record_failed_code_attempt(user_id) is True
    assert limiter.is_code_locked(user_id) is True

    # 2. Ліміт скарг (1 на 5 хв)
    assert limiter.can_send_complaint(user_id) is True
    # Повторна одразу відхиляється
    assert limiter.can_send_complaint(user_id) is False

    # 3. Ліміт розсилок по кімнаті (1 на 1 хв)
    assert limiter.can_broadcast_room(user_id) is True
    assert limiter.can_broadcast_room(user_id) is False


@pytest.mark.asyncio
async def test_sotnik_member_management(session: AsyncSession):
    """Тест 8: Переміщення мешканців між кімнатами, зміна ролей, видалення (кік)."""
    coliving, sotnik = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Admin Test",
        address="вул. Хрещатик, 1",
        total_people=8,
        total_rooms=2,
        creator_tg_id=7001,
        creator_name="Головний Сотник",
        creator_username="sotnik_chief"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)

    # Додаємо мешканця в кімнату 1
    resident = await crud.create_user(
        session=session,
        tg_id=7002,
        full_name="Богдан Мешканець",
        username="bogdan_m",
        role="RESIDENT",
        coliving_id=coliving.id,
        room_id=rooms[0].id,
        is_approved=True
    )

    # 1. Переміщення в кімнату 2
    await crud.update_user_room(session, resident.id, rooms[1].id)
    updated_res = await crud.get_user_by_id(session, resident.id)
    assert updated_res.room_id == rooms[1].id

    # 2. Призначення другого Сотника
    success, msg, promoted = await crud.toggle_sotnik_role(session, resident.id)
    assert success is True
    assert promoted.role == "SOTNIK"
    sotniks = await crud.get_sotniks(session, coliving.id)
    assert len(sotniks) == 2

    # 3. Зняття ролі Сотника
    success, msg, demoted = await crud.toggle_sotnik_role(session, resident.id)
    assert success is True
    assert demoted.role == "RESIDENT"

    # 4. Спроба зняти роль з єдиного сотника (має бути заборонено)
    success, msg, _ = await crud.toggle_sotnik_role(session, sotnik.id)
    assert success is False
    assert "єдиного сотника" in msg

    # 5. Видалення мешканця (кік)
    kicked = await crud.kick_user_from_coliving(session, resident.id)
    assert kicked is not None
    assert kicked.coliving_id is None
    assert kicked.is_approved is False


@pytest.mark.asyncio
async def test_sotnik_fine_and_duty_settings(session: AsyncSession):
    """Тест 9: Налаштування штрафів, зміна типу розподілу та пряме призначення чергової кімнати."""
    coliving, _ = await crud.create_coliving_with_rooms(
        session=session,
        name="CO:LIVE Fines Test",
        address="вул. Сковороди, 10",
        total_people=8,
        total_rooms=2,
        creator_tg_id=8001,
        creator_name="Сотник Фінансист",
        creator_username="sotnik_fin"
    )
    rooms = await crud.get_rooms_with_users(session, coliving.id)
    room2_id = rooms[1].id

    # 1. Зміна суми штрафу та типу розподілу
    c_updated = await crud.update_fine_settings(session, coliving.id, default_fine=150.0, distribution="INDIVIDUAL")
    assert c_updated.default_fine_amount == 150.0
    assert c_updated.fine_distribution == "INDIVIDUAL"

    # 2. Пряме призначення чергової кімнати 2
    new_duty = await crud.set_current_duty_room(session, coliving.id, room2_id)
    assert new_duty.room_id == room2_id
    assert new_duty.is_current is True

    current_duty = await crud.get_current_duty(session, coliving.id)
    assert current_duty.room_id == room2_id



def test_main_keyboard_layout():
    """Тест 10: Перевірка наявності кнопки 'Мій колівінг' та оновлення розмітки."""
    from bot.keyboards.main_menu import get_main_keyboard
    import texts

    kb_resident = get_main_keyboard(is_sotnik=False)
    resident_buttons = [btn.text for row in kb_resident.keyboard for btn in row]
    assert texts.BTN_MY_COLIVING in resident_buttons
    assert texts.BTN_MY_ROOM in resident_buttons
    assert texts.BTN_CALENDAR in resident_buttons
    assert texts.BTN_DUTIES in resident_buttons
    assert texts.BTN_URGENT_COMPLAINT in resident_buttons
    assert texts.BTN_FINES in resident_buttons
    assert texts.BTN_SOTNIK_PANEL not in resident_buttons

    kb_sotnik = get_main_keyboard(is_sotnik=True)
    sotnik_buttons = [btn.text for row in kb_sotnik.keyboard for btn in row]
    assert texts.BTN_MY_COLIVING in sotnik_buttons
    assert texts.BTN_SOTNIK_PANEL in sotnik_buttons


import random
import string
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
from sqlalchemy import select, update, delete, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Coliving, Room, User, JoinRequest, DutyCycle, Complaint, Fine, Blacklist
)
from config import settings

def generate_invite_code(length: int = 9) -> str:
    """Генерація 8-10 символьного коду з великих/малих літер та цифр."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))

# --- Користувачі ---

async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> Optional[User]:
    stmt = (
        select(User)
        .options(
            selectinload(User.coliving).selectinload(Coliving.rooms),
            selectinload(User.room)
        )
        .where(User.telegram_id == tg_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def create_user(
    session: AsyncSession,
    tg_id: int,
    full_name: str,
    username: Optional[str] = None,
    role: str = "RESIDENT",
    coliving_id: Optional[int] = None,
    room_id: Optional[int] = None,
    is_approved: bool = False
) -> User:
    user = User(
        telegram_id=tg_id,
        full_name=full_name,
        username=username,
        role=role,
        coliving_id=coliving_id,
        room_id=room_id,
        is_approved=is_approved
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

async def update_user_room(session: AsyncSession, user_id: int, new_room_id: int):
    stmt = update(User).where(User.id == user_id).values(room_id=new_room_id)
    await session.execute(stmt)
    await session.commit()

async def remove_user_from_coliving(session: AsyncSession, tg_id: int):
    user = await get_user_by_tg_id(session, tg_id)
    if user:
        user.coliving_id = None
        user.room_id = None
        user.is_approved = False
        user.role = "RESIDENT"
        await session.commit()

# --- Колівінг ---

async def create_coliving_with_rooms(
    session: AsyncSession,
    name: str,
    address: str,
    total_people: int,
    total_rooms: int,
    creator_tg_id: int,
    creator_name: str,
    creator_username: Optional[str] = None
) -> Tuple[Coliving, User]:
    # Генеруємо унікальний код
    code = generate_invite_code(9)
    coliving = Coliving(
        name=name,
        address=address,
        invite_code=code,
        total_people=total_people,
        total_rooms=total_rooms
    )
    session.add(coliving)
    await session.flush()

    # Створюємо кімнати
    capacity_per_room = max(1, total_people // total_rooms)
    created_rooms = []
    for i in range(1, total_rooms + 1):
        room = Room(
            coliving_id=coliving.id,
            name=f"Кімната {i}",
            capacity=capacity_per_room,
            rotation_order=i
        )
        session.add(room)
        created_rooms.append(room)
    await session.flush()

    # Створюємо перший період чергування для 1-ї кімнати
    if created_rooms:
        duty = DutyCycle(
            coliving_id=coliving.id,
            room_id=created_rooms[0].id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=7),
            is_current=True
        )
        session.add(duty)

    # Додаємо творця як першого Сотника у кімнату 1
    user = await get_user_by_tg_id(session, creator_tg_id)
    if not user:
        user = User(
            telegram_id=creator_tg_id,
            full_name=creator_name,
            username=creator_username,
            role="SOTNIK",
            coliving_id=coliving.id,
            room_id=created_rooms[0].id,
            is_approved=True
        )
        session.add(user)
    else:
        user.role = "SOTNIK"
        user.coliving_id = coliving.id
        user.room_id = created_rooms[0].id
        user.is_approved = True

    await session.commit()
    await session.refresh(coliving)
    await session.refresh(user)
    return coliving, user

async def get_coliving_by_code(session: AsyncSession, code: str) -> Optional[Coliving]:
    stmt = (
        select(Coliving)
        .options(selectinload(Coliving.rooms).selectinload(Room.users))
        .where(Coliving.invite_code == code.strip())
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

async def get_coliving_by_id(session: AsyncSession, coliving_id: int) -> Optional[Coliving]:
    stmt = (
        select(Coliving)
        .options(selectinload(Coliving.rooms).selectinload(Room.users), selectinload(Coliving.users))
        .where(Coliving.id == coliving_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

async def toggle_coliving_lock(session: AsyncSession, coliving_id: int) -> bool:
    coliving = await get_coliving_by_id(session, coliving_id)
    if coliving:
        coliving.is_join_locked = not coliving.is_join_locked
        await session.commit()
        return coliving.is_join_locked
    return False

async def regenerate_coliving_code(session: AsyncSession, coliving_id: int) -> str:
    new_code = generate_invite_code(9)
    stmt = update(Coliving).where(Coliving.id == coliving_id).values(invite_code=new_code)
    await session.execute(stmt)
    await session.commit()
    return new_code

async def link_group_to_coliving(session: AsyncSession, coliving_id: int, chat_id: int, topic_id: Optional[int] = None):
    stmt = update(Coliving).where(Coliving.id == coliving_id).values(group_chat_id=chat_id, duty_topic_id=topic_id)
    await session.execute(stmt)
    await session.commit()

async def update_coliving_topics(
    session: AsyncSession,
    coliving_id: int,
    duty_topic_id: Optional[int] = None,
    complaints_topic_id: Optional[int] = None,
    lost_found_topic_id: Optional[int] = None
):
    values = {}
    if duty_topic_id is not None:
        values["duty_topic_id"] = duty_topic_id
    if complaints_topic_id is not None:
        values["complaints_topic_id"] = complaints_topic_id
    if lost_found_topic_id is not None:
        values["lost_found_topic_id"] = lost_found_topic_id
    if values:
        stmt = update(Coliving).where(Coliving.id == coliving_id).values(**values)
        await session.execute(stmt)
        await session.commit()

async def get_coliving_users(session: AsyncSession, coliving_id: int) -> List[User]:
    stmt = (
        select(User)
        .options(selectinload(User.room))
        .where(and_(User.coliving_id == coliving_id, User.is_approved == True))
        .order_by(User.full_name)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())

# --- Кімнати та мешканці ---

async def get_rooms_with_users(session: AsyncSession, coliving_id: int) -> List[Room]:
    stmt = (
        select(Room)
        .options(selectinload(Room.users))
        .where(Room.coliving_id == coliving_id)
        .order_by(Room.rotation_order)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())

async def get_room_by_id(session: AsyncSession, room_id: int) -> Optional[Room]:
    stmt = select(Room).options(selectinload(Room.users)).where(Room.id == room_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

async def get_sotniks(session: AsyncSession, coliving_id: int) -> List[User]:
    stmt = select(User).where(and_(User.coliving_id == coliving_id, User.role == "SOTNIK", User.is_approved == True))
    res = await session.execute(stmt)
    return list(res.scalars().all())

async def count_residents(session: AsyncSession, coliving_id: int) -> int:
    stmt = select(func.count(User.id)).where(and_(User.coliving_id == coliving_id, User.is_approved == True))
    res = await session.execute(stmt)
    return res.scalar_one() or 0

# --- Заявки на приєднання ---

async def is_user_blacklisted(session: AsyncSession, coliving_id: int, tg_id: int) -> bool:
    stmt = select(Blacklist).where(and_(Blacklist.coliving_id == coliving_id, Blacklist.telegram_id == tg_id))
    res = await session.execute(stmt)
    return res.scalar_one_or_none() is not None

async def count_pending_requests(session: AsyncSession, coliving_id: int) -> int:
    stmt = select(func.count(JoinRequest.id)).where(and_(JoinRequest.coliving_id == coliving_id, JoinRequest.status == "PENDING"))
    res = await session.execute(stmt)
    return res.scalar_one() or 0

async def has_active_request(session: AsyncSession, tg_id: int) -> bool:
    stmt = select(JoinRequest).where(and_(JoinRequest.telegram_id == tg_id, JoinRequest.status == "PENDING"))
    res = await session.execute(stmt)
    return res.scalar_one_or_none() is not None

async def create_join_request(
    session: AsyncSession,
    coliving_id: int,
    room_id: int,
    tg_id: int,
    full_name: str,
    username: Optional[str],
    target_role: str = "RESIDENT"
) -> JoinRequest:
    req = JoinRequest(
        coliving_id=coliving_id,
        room_id=room_id,
        telegram_id=tg_id,
        full_name=full_name,
        username=username,
        target_role=target_role,
        status="PENDING"
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req

async def get_pending_requests(session: AsyncSession, coliving_id: int) -> List[JoinRequest]:
    stmt = (
        select(JoinRequest)
        .options(selectinload(JoinRequest.room))
        .where(and_(JoinRequest.coliving_id == coliving_id, JoinRequest.status == "PENDING"))
        .order_by(JoinRequest.created_at.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())

async def approve_request(session: AsyncSession, request_id: int) -> Optional[Tuple[JoinRequest, User]]:
    stmt = select(JoinRequest).where(JoinRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if not req or req.status != "PENDING":
        return None

    req.status = "APPROVED"

    assigned_role = req.target_role or "RESIDENT"
    if assigned_role == "SOTNIK":
        sotniks = await get_sotniks(session, req.coliving_id)
        if len(sotniks) >= settings.MAX_SOTNIKS_PER_COLIVING:
            assigned_role = "RESIDENT"

    # Створюємо чи оновлюємо користувача
    user = await get_user_by_tg_id(session, req.telegram_id)
    if not user:
        user = User(
            telegram_id=req.telegram_id,
            full_name=req.full_name,
            username=req.username,
            role=assigned_role,
            coliving_id=req.coliving_id,
            room_id=req.room_id,
            is_approved=True
        )
        session.add(user)
    else:
        user.full_name = req.full_name
        user.username = req.username
        user.coliving_id = req.coliving_id
        user.room_id = req.room_id
        user.role = assigned_role
        user.is_approved = True

    await session.commit()
    await session.refresh(req)
    await session.refresh(user)
    return req, user

async def reject_request(session: AsyncSession, request_id: int) -> Optional[JoinRequest]:
    stmt = select(JoinRequest).where(JoinRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if req and req.status == "PENDING":
        req.status = "REJECTED"
        await session.commit()
        return req
    return None

async def block_and_reject_request(session: AsyncSession, request_id: int) -> Optional[JoinRequest]:
    stmt = select(JoinRequest).where(JoinRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if req:
        req.status = "BLOCKED"
        blacklist = Blacklist(
            coliving_id=req.coliving_id,
            telegram_id=req.telegram_id,
            reason="Заблоковано сотником при подачі заявки"
        )
        session.add(blacklist)
        await session.commit()
        return req
    return None

# --- Чергування (Duty Cycles) ---

async def get_current_duty(session: AsyncSession, coliving_id: int) -> Optional[DutyCycle]:
    stmt = (
        select(DutyCycle)
        .options(selectinload(DutyCycle.room).selectinload(Room.users))
        .where(and_(DutyCycle.coliving_id == coliving_id, DutyCycle.is_current == True))
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()

async def rotate_duty(session: AsyncSession, coliving_id: int) -> Optional[DutyCycle]:
    """Перемикання чергування на наступну кімнату у списку."""
    rooms = await get_rooms_with_users(session, coliving_id)
    if not rooms:
        return None

    current_duty = await get_current_duty(session, coliving_id)
    next_room = rooms[0]

    if current_duty:
        current_duty.is_current = False
        # Знаходимо індекс поточної кімнати
        current_idx = next((i for i, r in enumerate(rooms) if r.id == current_duty.room_id), 0)
        next_idx = (current_idx + 1) % len(rooms)
        next_room = rooms[next_idx]

    new_duty = DutyCycle(
        coliving_id=coliving_id,
        room_id=next_room.id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=7),
        is_current=True
    )
    session.add(new_duty)
    await session.commit()
    await session.refresh(new_duty)
    return new_duty

# --- Скарги та Штрафи ---

async def create_complaint(
    session: AsyncSession,
    coliving_id: int,
    reporter_id: int,
    target_room_id: int,
    photo_file_id: Optional[str] = None,
    comment: Optional[str] = None
) -> Complaint:
    complaint = Complaint(
        coliving_id=coliving_id,
        reporter_id=reporter_id,
        target_room_id=target_room_id,
        photo_file_id=photo_file_id,
        comment=comment,
        status="OPEN"
    )
    session.add(complaint)
    await session.commit()
    await session.refresh(complaint)
    return complaint

async def add_fine(
    session: AsyncSession,
    coliving_id: int,
    amount: float,
    reason: str,
    room_id: Optional[int] = None,
    user_id: Optional[int] = None,
    complaint_id: Optional[int] = None
) -> Fine:
    fine = Fine(
        coliving_id=coliving_id,
        room_id=room_id,
        user_id=user_id,
        complaint_id=complaint_id,
        amount=amount,
        reason=reason
    )
    session.add(fine)

    # Оновлюємо баланс штрафу користувача або кімнати
    if user_id:
        user = await session.get(User, user_id)
        if user:
            user.unpaid_fines += amount
    elif room_id:
        room = await get_room_by_id(session, room_id)
        if room and room.users:
            split_amount = round(amount / len(room.users), 2)
            for u in room.users:
                u.unpaid_fines += split_amount

    # Додаємо до скарбнички
    coliving = await session.get(Coliving, coliving_id)
    if coliving:
        coliving.treasury_balance += amount

    await session.commit()
    await session.refresh(fine)
    return fine

create_fine = add_fine


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    stmt = (
        select(User)
        .options(selectinload(User.room), selectinload(User.coliving))
        .where(User.id == user_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def get_all_coliving_members(session: AsyncSession, coliving_id: int) -> List[User]:
    stmt = (
        select(User)
        .options(selectinload(User.room))
        .where(and_(User.coliving_id == coliving_id, User.is_approved == True))
        .order_by(User.room_id.asc(), User.role.desc(), User.full_name.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def kick_user_from_coliving(session: AsyncSession, user_id: int) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if user:
        user.coliving_id = None
        user.room_id = None
        user.is_approved = False
        user.role = "RESIDENT"
        await session.commit()
        await session.refresh(user)
        return user
    return None


async def toggle_sotnik_role(session: AsyncSession, user_id: int) -> Tuple[bool, str, Optional[User]]:
    user = await get_user_by_id(session, user_id)
    if not user or not user.coliving_id:
        return False, "Користувача не знайдено.", None

    if user.role == "SOTNIK":
        # Перевіряємо чи це не єдиний сотник
        sotniks = await get_sotniks(session, user.coliving_id)
        if len(sotniks) <= 1:
            return False, "Неможливо зняти права з єдиного сотника колівінгу!", user
        user.role = "RESIDENT"
        await session.commit()
        await session.refresh(user)
        return True, "Права сотника успішно відкликано (тепер звичайний мешканець).", user
    else:
        # Призначаємо сотником, перевіряємо ліміт (макс. 3)
        sotniks = await get_sotniks(session, user.coliving_id)
        if len(sotniks) >= settings.MAX_SOTNIKS_PER_COLIVING:
            return False, f"Досягнуто ліміту сотників ({settings.MAX_SOTNIKS_PER_COLIVING} з {settings.MAX_SOTNIKS_PER_COLIVING})!", user
        user.role = "SOTNIK"
        await session.commit()
        await session.refresh(user)
        return True, "Користувачу успішно надано права Сотника! 👑", user


async def update_fine_settings(
    session: AsyncSession,
    coliving_id: int,
    default_fine: Optional[float] = None,
    distribution: Optional[str] = None
) -> Optional[Coliving]:
    coliving = await get_coliving_by_id(session, coliving_id)
    if not coliving:
        return None
    if default_fine is not None:
        coliving.default_fine_amount = default_fine
    if distribution is not None:
        coliving.fine_distribution = distribution
    await session.commit()
    await session.refresh(coliving)
    return coliving


async def set_current_duty_room(session: AsyncSession, coliving_id: int, room_id: int) -> Optional[DutyCycle]:
    # Деактивуємо всі поточні чергування
    stmt = (
        update(DutyCycle)
        .where(and_(DutyCycle.coliving_id == coliving_id, DutyCycle.is_current == True))
        .values(is_current=False)
    )
    await session.execute(stmt)

    new_duty = DutyCycle(
        coliving_id=coliving_id,
        room_id=room_id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=7),
        is_current=True
    )
    session.add(new_duty)
    await session.commit()
    await session.refresh(new_duty)
    return new_duty


async def clear_user_fines(session: AsyncSession, user_id: int) -> float:
    user = await get_user_by_id(session, user_id)
    if not user:
        return 0.0
    cleared = user.unpaid_fines
    user.unpaid_fines = 0.0
    await session.commit()
    return cleared


async def get_unpaid_fines(session: AsyncSession, coliving_id: int) -> List[Fine]:
    stmt = (
        select(Fine)
        .options(selectinload(Fine.user), selectinload(Fine.room))
        .where(and_(Fine.coliving_id == coliving_id, Fine.is_paid == False))
        .order_by(Fine.created_at.desc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def update_coliving_info(
    session: AsyncSession,
    coliving_id: int,
    name: Optional[str] = None,
    address: Optional[str] = None
) -> Optional[Coliving]:
    coliving = await get_coliving_by_id(session, coliving_id)
    if not coliving:
        return None
    if name is not None:
        coliving.name = name.strip()
    if address is not None:
        coliving.address = address.strip()
    await session.commit()
    await session.refresh(coliving)
    return coliving


async def add_room_to_coliving(
    session: AsyncSession,
    coliving_id: int,
    room_name: str,
    capacity: int = 4
) -> Room:
    rooms = await get_rooms_with_users(session, coliving_id)
    next_order = len(rooms) + 1
    room = Room(
        coliving_id=coliving_id,
        name=room_name.strip(),
        capacity=capacity,
        rotation_order=next_order
    )
    session.add(room)
    coliving = await get_coliving_by_id(session, coliving_id)
    if coliving:
        coliving.total_rooms = len(rooms) + 1
    await session.commit()
    await session.refresh(room)
    return room


async def set_user_room_duty(session: AsyncSession, user_id: int, duty: str) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    user.room_duty = duty
    await session.commit()
    await session.refresh(user)
    return user


async def set_user_room_role(session: AsyncSession, user_id: int, role: str) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    user.room_role = role
    await session.commit()
    await session.refresh(user)
    return user


async def set_room_custom_duties(session: AsyncSession, room_id: int, duties_text: str) -> Optional[Room]:
    room = await get_room_by_id(session, room_id)
    if not room:
        return None
    room.custom_duties = duties_text.strip()
    await session.commit()
    await session.refresh(room)
    return room


async def set_coliving_duty_rules(session: AsyncSession, coliving_id: int, rules_text: str) -> Optional[Coliving]:
    coliving = await get_coliving_by_id(session, coliving_id)
    if not coliving:
        return None
    coliving.custom_duty_rules = rules_text.strip()
    await session.commit()
    await session.refresh(coliving)
    return coliving




from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database.db import AsyncSessionLocal
from database import crud
from bot.middlewares.anti_spam import rate_limiter
from bot.keyboards.main_menu import get_main_keyboard
from bot.keyboards.sotnik_kb import get_request_action_kb
from bot.keyboards.inline_helpers import (
    get_role_selection_kb,
    get_sotnik_start_choice_kb,
    get_rooms_selection_kb,
    get_back_kb
)
from config import settings
import texts
import logging

logger = logging.getLogger("CO:LIVE.start")
router = Router()

class ColivingWizard(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_people = State()
    waiting_for_rooms = State()

class ResidentJoinState(StatesGroup):
    waiting_for_code = State()
    waiting_for_name = State()
    waiting_for_room = State()

class SotnikJoinState(StatesGroup):
    waiting_for_code = State()
    waiting_for_name = State()
    waiting_for_room = State()

@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    tg_id = message.from_user.id
    args = command.args

    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, tg_id)

        # Якщо вже є затвердженим мешканцем або сотником
        if user and user.is_approved and user.coliving_id:
            coliving = await crud.get_coliving_by_id(session, user.coliving_id)
            is_sotnik = (user.role == "SOTNIK")
            webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={tg_id}&coliving_id={user.coliving_id}"
            
            nav_buttons = []
            if is_sotnik:
                nav_buttons.append([InlineKeyboardButton(text="👑 Відкрити Панель Сотника", callback_data="sotnik_back_panel")])
            nav_buttons.append([
                InlineKeyboardButton(text="🏠 Мій колівінг", callback_data="user_nav_my_coliving"),
                InlineKeyboardButton(text="🚪 Моя кімната", callback_data="user_nav_my_room")
            ])

            role_title = "👑 Сотник (Адміністратор)" if is_sotnik else "🙋‍♂️ Мешканець"
            await message.answer(
                f"👋 З поверненням, <b>{user.full_name}</b>!\n"
                f"🏢 Колівінг: <b>{coliving.name if coliving else ''}</b>\n"
                f"🚪 Кімната: <b>{user.room.name if user.room else 'Не призначено'}</b>\n"
                f"🏷 Ваша роль: <b>{role_title}</b>",
                reply_markup=get_main_keyboard(is_sotnik=is_sotnik, webapp_url=webapp_url)
            )
            await message.answer(
                "⚡ <b>Швидкий перехід:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=nav_buttons)
            )
            return


        # Якщо є аргумент deep-link (напр. ?start=join_XXXXX або ?start=XXXXX)
        if args:
            code = args.replace("join_", "").strip()
            await proceed_with_code(message, state, code, is_sotnik=False)
            return

    # Якщо новий користувач — показуємо вибір ролі
    await message.answer(texts.WELCOME_START, reply_markup=get_role_selection_kb())

# Повернення назад до головного вибору ролі
@router.callback_query(F.data == "role_back_to_start")
async def cb_role_back_to_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(texts.WELCOME_START, reply_markup=get_role_selection_kb())
    await call.answer()

# ----------------- ГІЛКА СОТНИКА -----------------

@router.callback_query(F.data == "role_sotnik")
async def cb_role_sotnik(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(texts.SOTNIK_START_OPTIONS, reply_markup=get_sotnik_start_choice_kb())
    await call.answer()

@router.callback_query(F.data == "sotnik_create_new")
async def cb_sotnik_create_new(call: CallbackQuery, state: FSMContext):
    await state.set_state(ColivingWizard.waiting_for_name)
    await call.message.edit_text(texts.WIZARD_NAME_PROMPT, reply_markup=get_back_kb("sotnik_back_to_choice"))
    await call.answer()

@router.callback_query(F.data == "sotnik_back_to_choice")
async def cb_sotnik_back_to_choice(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(texts.SOTNIK_START_OPTIONS, reply_markup=get_sotnik_start_choice_kb())
    await call.answer()

@router.message(ColivingWizard.waiting_for_name)
async def wizard_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 100:
        await message.answer("⚠️ Будь ласка, введіть коректну назву (до 100 символів):", reply_markup=get_back_kb("sotnik_back_to_choice"))
        return
    await state.update_data(coliving_name=name)
    await state.set_state(ColivingWizard.waiting_for_address)
    await message.answer(texts.WIZARD_ADDRESS_PROMPT, reply_markup=get_back_kb("wizard_back_to_name"))

@router.callback_query(F.data == "wizard_back_to_name")
async def cb_wizard_back_to_name(call: CallbackQuery, state: FSMContext):
    await state.set_state(ColivingWizard.waiting_for_name)
    await call.message.edit_text(texts.WIZARD_NAME_PROMPT, reply_markup=get_back_kb("sotnik_back_to_choice"))
    await call.answer()

@router.message(ColivingWizard.waiting_for_address)
async def wizard_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if not address or len(address) > 255:
        await message.answer("⚠️ Будь ласка, введіть коректну адресу:", reply_markup=get_back_kb("wizard_back_to_name"))
        return
    await state.update_data(coliving_address=address)
    await state.set_state(ColivingWizard.waiting_for_people)
    await message.answer(texts.WIZARD_PEOPLE_PROMPT, reply_markup=get_back_kb("wizard_back_to_address"))

@router.callback_query(F.data == "wizard_back_to_address")
async def cb_wizard_back_to_address(call: CallbackQuery, state: FSMContext):
    await state.set_state(ColivingWizard.waiting_for_address)
    await call.message.edit_text(texts.WIZARD_ADDRESS_PROMPT, reply_markup=get_back_kb("wizard_back_to_name"))
    await call.answer()

@router.message(ColivingWizard.waiting_for_people)
async def wizard_people(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= settings.MAX_PEOPLE_PER_COLIVING):
        await message.answer(texts.WIZARD_INVALID_NUMBER, reply_markup=get_back_kb("wizard_back_to_address"))
        return
    await state.update_data(total_people=int(text))
    await state.set_state(ColivingWizard.waiting_for_rooms)
    await message.answer(texts.WIZARD_ROOMS_PROMPT, reply_markup=get_back_kb("wizard_back_to_people"))

@router.callback_query(F.data == "wizard_back_to_people")
async def cb_wizard_back_to_people(call: CallbackQuery, state: FSMContext):
    await state.set_state(ColivingWizard.waiting_for_people)
    await call.message.edit_text(texts.WIZARD_PEOPLE_PROMPT, reply_markup=get_back_kb("wizard_back_to_address"))
    await call.answer()

@router.message(ColivingWizard.waiting_for_rooms)
async def wizard_rooms(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 50):
        await message.answer(texts.WIZARD_INVALID_NUMBER, reply_markup=get_back_kb("wizard_back_to_people"))
        return
    total_rooms = int(text)
    data = await state.get_data()
    await state.clear()

    # Створюємо колівінг
    tg_id = message.from_user.id
    name = data["coliving_name"]
    address = data["coliving_address"]
    total_people = data["total_people"]
    full_name = message.from_user.full_name or "Сотник"
    username = message.from_user.username

    bot_username = "colive_bot"
    try:
        bot_info = await message.bot.get_me()
        bot_username = bot_info.username or bot_username
    except Exception as e:
        logger.warning(f"Failed to fetch bot username: {e}")

    async with AsyncSessionLocal() as session:
        coliving, sotnik_user = await crud.create_coliving_with_rooms(
            session=session,
            name=name,
            address=address,
            total_people=total_people,
            total_rooms=total_rooms,
            creator_tg_id=tg_id,
            creator_name=full_name,
            creator_username=username
        )
        invite_link = f"https://t.me/{bot_username}?start=join_{coliving.invite_code}"
        webapp_url = f"{settings.WEBAPP_BASE_URL}?user_id={tg_id}&coliving_id={coliving.id}"

        await message.answer(
            texts.COLIVING_CREATED_SUCCESS.format(
                name=coliving.name,
                address=coliving.address,
                people=coliving.total_people,
                rooms=coliving.total_rooms,
                code=coliving.invite_code,
                invite_link=invite_link
            ),
            reply_markup=get_main_keyboard(is_sotnik=True, webapp_url=webapp_url)
        )

# ----------------- ПРИЄДНАННЯ СОТНИКА ДО НАЯВНОГО -----------------

@router.callback_query(F.data == "sotnik_join_existing")
async def cb_sotnik_join_existing(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikJoinState.waiting_for_code)
    await call.message.edit_text(
        texts.SOTNIK_ENTER_CODE_PROMPT,
        reply_markup=get_back_kb("sotnik_back_to_choice")
    )
    await call.answer()

@router.message(SotnikJoinState.waiting_for_code)
async def process_sotnik_code(message: Message, state: FSMContext):
    code = message.text.strip()
    await proceed_with_code(message, state, code, is_sotnik=True)

@router.callback_query(F.data == "sotnik_join_back_to_code")
async def cb_sotnik_join_back_to_code(call: CallbackQuery, state: FSMContext):
    await state.set_state(SotnikJoinState.waiting_for_code)
    await call.message.edit_text(
        texts.SOTNIK_ENTER_CODE_PROMPT,
        reply_markup=get_back_kb("sotnik_back_to_choice")
    )
    await call.answer()

@router.message(SotnikJoinState.waiting_for_name)
async def sotnik_entered_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 100:
        await message.answer("⚠️ Введіть коректне Прізвище та Ім'я:", reply_markup=get_back_kb("sotnik_join_back_to_code"))
        return

    await state.update_data(full_name=name)
    data = await state.get_data()
    coliving_id = data["coliving_id"]

    async with AsyncSessionLocal() as session:
        rooms = await crud.get_rooms_with_users(session, coliving_id)
        text_lines = ["🚪 <b>Оберіть кімнату, в якій ви будете проживати:</b>\n"]
        for r in rooms:
            users_str = ", ".join([u.full_name for u in r.users]) if r.users else "порожня"
            count = len(r.users) if r.users else 0
            text_lines.append(f"🚪 <b>{r.name}</b> ({count}/{r.capacity}): <i>{users_str}</i>")

        await state.set_state(SotnikJoinState.waiting_for_room)
        await message.answer("\n".join(text_lines), reply_markup=get_rooms_selection_kb(rooms, back_callback="sotnik_join_back_to_name"))

@router.callback_query(F.data == "sotnik_join_back_to_name")
async def cb_sotnik_join_back_to_name(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    coliving_name = data.get("coliving_name", "")
    address = data.get("coliving_addr", "")
    await state.set_state(SotnikJoinState.waiting_for_name)
    await call.message.edit_text(
        texts.RESIDENT_FULLNAME_PROMPT.format(coliving_name=coliving_name, address=address),
        reply_markup=get_back_kb("sotnik_join_back_to_code")
    )
    await call.answer()

@router.callback_query(SotnikJoinState.waiting_for_room, F.data.startswith("select_room_"))
async def sotnik_selected_room(call: CallbackQuery, state: FSMContext):
    room_id = int(call.data.replace("select_room_", ""))
    data = await state.get_data()
    coliving_id = data["coliving_id"]
    full_name = data["full_name"]
    await state.clear()

    tg_id = call.from_user.id
    username = call.from_user.username

    async with AsyncSessionLocal() as session:
        room = await crud.get_room_by_id(session, room_id)
        coliving = await crud.get_coliving_by_id(session, coliving_id)
        sotniks = await crud.get_sotniks(session, coliving_id)

        # Створюємо заявку з ролью SOTNIK
        req = await crud.create_join_request(
            session=session,
            coliving_id=coliving_id,
            room_id=room_id,
            tg_id=tg_id,
            full_name=full_name,
            username=username,
            target_role="SOTNIK"
        )

        await call.message.edit_text(
            texts.SOTNIK_REQUEST_SUBMITTED.format(room_name=room.name if room else "")
        )
        await call.answer()

        # Надсилаємо сповіщення всім діючим Сотникам
        for s in sotniks:
            try:
                await call.bot.send_message(
                    chat_id=s.telegram_id,
                    text=texts.SOTNIK_NEW_SOTNIK_REQUEST_NOTIFICATION.format(
                        full_name=full_name,
                        username=f"@{username}" if username else "без username",
                        room_name=room.name if room else "",
                        coliving_name=coliving.name if coliving else "",
                        sotniks_count=len(sotniks)
                    ),
                    reply_markup=get_request_action_kb(req.id)
                )
            except Exception:
                pass

# ----------------- ГІЛКА МЕШКАНЦЯ -----------------

@router.callback_query(F.data == "role_resident")
async def cb_role_resident(call: CallbackQuery, state: FSMContext):
    await state.set_state(ResidentJoinState.waiting_for_code)
    await call.message.edit_text(
        texts.RESIDENT_ENTER_CODE_PROMPT,
        reply_markup=get_back_kb("role_back_to_start")
    )
    await call.answer()

@router.message(ResidentJoinState.waiting_for_code)
async def process_entered_code(message: Message, state: FSMContext):
    code = message.text.strip()
    await proceed_with_code(message, state, code, is_sotnik=False)

async def proceed_with_code(message: Message, state: FSMContext, code: str, is_sotnik: bool = False):
    tg_id = message.from_user.id

    back_cb = "sotnik_back_to_choice" if is_sotnik else "role_back_to_start"

    # 1. Перевірка блокування через підбір коду
    if rate_limiter.is_code_locked(tg_id):
        await message.answer(texts.CODE_ATTEMPTS_EXCEEDED, reply_markup=get_back_kb(back_cb))
        return

    async with AsyncSessionLocal() as session:
        # 2. Перевірка, чи не зареєстрований вже десь
        user = await crud.get_user_by_tg_id(session, tg_id)
        if user and user.is_approved and user.coliving_id:
            col = await crud.get_coliving_by_id(session, user.coliving_id)
            await message.answer(texts.ALREADY_IN_COLIVING.format(name=col.name if col else ""))
            return

        # 3. Пошук колівінгу
        coliving = await crud.get_coliving_by_code(session, code)
        if not coliving:
            is_locked = rate_limiter.record_failed_code_attempt(tg_id)
            if is_locked:
                await message.answer(texts.CODE_ATTEMPTS_EXCEEDED, reply_markup=get_back_kb(back_cb))
            else:
                await message.answer(texts.CODE_NOT_FOUND, reply_markup=get_back_kb(back_cb))
            return

        # 4. Перевірка чорного списку
        if await crud.is_user_blacklisted(session, coliving.id, tg_id):
            await message.answer(texts.YOU_ARE_BLACKLISTED)
            return

        # 5. Якщо намагається зайти як сотник — перевірка ліміту 3 сотників
        if is_sotnik:
            sotniks = await crud.get_sotniks(session, coliving.id)
            if len(sotniks) >= settings.MAX_SOTNIKS_PER_COLIVING:
                limit_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🙋‍♂️ Приєднатися як мешканець", callback_data="role_resident")],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="sotnik_back_to_choice")]
                    ]
                )
                await message.answer(texts.SOTNIK_LIMIT_REACHED.format(coliving_name=coliving.name, count=len(sotniks)), reply_markup=limit_kb)
                return

        # 6. Перевірка блокування прийому заявок сотником
        if coliving.is_join_locked:
            await message.answer(texts.REGISTRATION_LOCKED, reply_markup=get_back_kb(back_cb))
            return

        # 7. Перевірка місткості колівінгу (макс 50)
        curr_residents = await crud.count_residents(session, coliving.id)
        if curr_residents >= coliving.total_people or curr_residents >= settings.MAX_PEOPLE_PER_COLIVING:
            await message.answer(texts.COLIVING_FULL, reply_markup=get_back_kb(back_cb))
            return

        # 8. Перевірка черги заявок (макс 30)
        pending_count = await crud.count_pending_requests(session, coliving.id)
        if pending_count >= settings.MAX_PENDING_REQUESTS:
            await message.answer(texts.QUEUE_FULL, reply_markup=get_back_kb(back_cb))
            return

        # 9. Перевірка наявної активної заявки
        if await crud.has_active_request(session, tg_id):
            await message.answer("⚠️ У вас вже є активна заявка на розгляд сотником. Будь ласка, зачекайте.")
            return

        # Зберігаємо ID колівінгу в FSM
        await state.update_data(coliving_id=coliving.id, coliving_name=coliving.name, coliving_addr=coliving.address)
        
        target_state = SotnikJoinState.waiting_for_name if is_sotnik else ResidentJoinState.waiting_for_name
        back_action = "sotnik_join_back_to_code" if is_sotnik else "join_back_to_code"

        await state.set_state(target_state)
        await message.answer(
            texts.RESIDENT_FULLNAME_PROMPT.format(
                coliving_name=coliving.name,
                address=coliving.address
            ),
            reply_markup=get_back_kb(back_action)
        )

@router.callback_query(F.data == "join_back_to_code")
async def cb_join_back_to_code(call: CallbackQuery, state: FSMContext):
    await state.set_state(ResidentJoinState.waiting_for_code)
    await call.message.edit_text(
        texts.RESIDENT_ENTER_CODE_PROMPT,
        reply_markup=get_back_kb("role_back_to_start")
    )
    await call.answer()

@router.message(ResidentJoinState.waiting_for_name)
async def resident_entered_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 100:
        await message.answer("⚠️ Введіть коректне Прізвище та Ім'я:", reply_markup=get_back_kb("join_back_to_code"))
        return

    await state.update_data(full_name=name)
    data = await state.get_data()
    coliving_id = data["coliving_id"]

    async with AsyncSessionLocal() as session:
        rooms = await crud.get_rooms_with_users(session, coliving_id)
        
        # Формуємо красивий опис кімнат із мешканцями
        text_lines = [texts.RESIDENT_CHOOSE_ROOM]
        for r in rooms:
            users_str = ", ".join([u.full_name for u in r.users]) if r.users else "порожня"
            count = len(r.users) if r.users else 0
            text_lines.append(f"🚪 <b>{r.name}</b> ({count}/{r.capacity}): <i>{users_str}</i>")

        await state.set_state(ResidentJoinState.waiting_for_room)
        await message.answer("\n".join(text_lines), reply_markup=get_rooms_selection_kb(rooms, back_callback="join_back_to_name"))

@router.callback_query(F.data == "join_back_to_name")
async def cb_join_back_to_name(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    coliving_name = data.get("coliving_name", "")
    address = data.get("coliving_addr", "")
    await state.set_state(ResidentJoinState.waiting_for_name)
    await call.message.edit_text(
        texts.RESIDENT_FULLNAME_PROMPT.format(
            coliving_name=coliving_name,
            address=address
        ),
        reply_markup=get_back_kb("join_back_to_code")
    )
    await call.answer()

@router.callback_query(ResidentJoinState.waiting_for_room, F.data.startswith("select_room_"))
async def resident_selected_room(call: CallbackQuery, state: FSMContext):
    room_id = int(call.data.replace("select_room_", ""))
    data = await state.get_data()
    coliving_id = data["coliving_id"]
    full_name = data["full_name"]
    await state.clear()

    tg_id = call.from_user.id
    username = call.from_user.username

    async with AsyncSessionLocal() as session:
        room = await crud.get_room_by_id(session, room_id)
        coliving = await crud.get_coliving_by_id(session, coliving_id)

        # Створюємо заявку з роллю RESIDENT
        req = await crud.create_join_request(
            session=session,
            coliving_id=coliving_id,
            room_id=room_id,
            tg_id=tg_id,
            full_name=full_name,
            username=username,
            target_role="RESIDENT"
        )

        # Повідомляємо кандидата
        await call.message.edit_text(
            texts.RESIDENT_APPLICATION_SUBMITTED.format(room_name=room.name if room else "")
        )
        await call.answer()

        # Надсилаємо сповіщення всім Сотникам цього колівінгу
        sotniks = await crud.get_sotniks(session, coliving_id)
        for s in sotniks:
            try:
                await call.bot.send_message(
                    chat_id=s.telegram_id,
                    text=texts.SOTNIK_NEW_REQUEST_NOTIFICATION.format(
                        full_name=full_name,
                        username=f"@{username}" if username else "без username",
                        room_name=room.name if room else "",
                        coliving_name=coliving.name if coliving else ""
                    ),
                    reply_markup=get_request_action_kb(req.id)
                )
            except Exception:
                pass

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from sqlalchemy import select
from database.db import AsyncSessionLocal
from database.models import Coliving
from database import crud
import texts

scheduler = AsyncIOScheduler()

async def weekly_duty_rotation_task(bot: Bot):
    """Щотижнева ротація чергувань у понеділок о 09:00"""
    async with AsyncSessionLocal() as session:
        stmt = select(Coliving)
        res = await session.execute(stmt)
        colivings = res.scalars().all()

        for coliving in colivings:
            try:
                new_duty = await crud.rotate_duty(session, coliving.id)
                if not new_duty or not new_duty.room:
                    continue

                duty_room = new_duty.room
                tags = " ".join([
                    f"@{u.username}" if u.username else f'<a href="tg://user?id={u.telegram_id}">{u.full_name}</a>'
                    for u in duty_room.users
                ]) if duty_room.users else "немає мешканців"

                # 1. Надсилаємо в групу / топік
                if coliving.group_chat_id:
                    try:
                        await bot.send_message(
                            chat_id=coliving.group_chat_id,
                            message_thread_id=coliving.duty_topic_id,
                            text=texts.WEEKLY_ANNOUNCEMENT_TOPIC.format(
                                coliving_name=coliving.name,
                                room_name=duty_room.name,
                                tags=tags,
                                start_date=new_duty.start_date.strftime("%d.%m"),
                                end_date=new_duty.end_date.strftime("%d.%m")
                            )
                        )
                    except Exception:
                        pass

                # 2. Надсилаємо кожному мешканцю чергової кімнати в ЛС
                for member in duty_room.users:
                    try:
                        await bot.send_message(
                            chat_id=member.telegram_id,
                            text=(
                                f"🧹 <b>Увага! Ваша кімната ({duty_room.name}) заступає на чергування на цьому тижні!</b>\n\n"
                                f"Період: {new_duty.start_date.strftime('%d.%m')} - {new_duty.end_date.strftime('%d.%m')}\n\n"
                                "Ознайомтесь з обов'язками чергових у меню «📋 Мої обов'язки». Тримаємо простір у чистоті!"
                            )
                        )
                    except Exception:
                        pass
            except Exception:
                continue

def setup_scheduler(bot: Bot):
    # Кожен понеділок о 09:00
    scheduler.add_job(
        weekly_duty_rotation_task,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        args=[bot]
    )
    scheduler.start()

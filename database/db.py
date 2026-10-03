from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

from sqlalchemy import text

Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for tbl, col, coltype in [
            ("users", "room_role", "VARCHAR(50) DEFAULT 'Мешканець'"),
            ("users", "room_duty", "VARCHAR(50) DEFAULT 'Не призначено'"),
            ("rooms", "custom_duties", "TEXT"),
            ("colivings", "custom_duty_rules", "TEXT"),
            ("colivings", "complaints_topic_id", "INTEGER"),
            ("colivings", "lost_found_topic_id", "INTEGER"),
            ("colivings", "announcements_topic_id", "INTEGER"),
        ]:
            try:
                await conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {coltype}"))
            except Exception:
                pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

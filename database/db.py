from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import settings

import urllib.parse

db_url = settings.DATABASE_URL
connect_args = {}

if "postgresql" in db_url or "postgres://" in db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Neon і Supabase додають ?sslmode=require, який asyncpg не приймає напряму в URL
    if "sslmode=" in db_url:
        parsed = urllib.parse.urlparse(db_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        ssl_val = query_params.pop("sslmode", [None])[0]
        if ssl_val and ssl_val.lower() in ["require", "verify-ca", "verify-full", "true"]:
            connect_args["ssl"] = "require"
        new_query = urllib.parse.urlencode({k: v[0] for k, v in query_params.items()})
        db_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

engine = create_async_engine(db_url, connect_args=connect_args, echo=False)
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

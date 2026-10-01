import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    BOT_TOKEN: str = "YOUR_BOT_TOKEN_HERE"
    SUPER_ADMIN_ID: int = 0
    WEBAPP_HOST: str = "0.0.0.0"
    WEBAPP_PORT: int = 8000
    WEBAPP_BASE_URL: str = "https://your-domain-or-ngrok.com"
    DATABASE_URL: str = "sqlite+aiosqlite:///colive.db"
    
    # Ліміти та безпека
    MAX_PEOPLE_PER_COLIVING: int = 50
    MAX_SOTNIKS_PER_COLIVING: int = 3
    MAX_PEOPLE_PER_ROOM: int = 50
    MAX_PENDING_REQUESTS: int = 30
    CODE_ATTEMPTS_LIMIT: int = 30
    CODE_LOCKOUT_MINUTES: int = 5
    COMPLAINT_RATE_LIMIT_MINUTES: int = 5
    ROOM_BROADCAST_RATE_LIMIT_MINUTES: int = 1

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

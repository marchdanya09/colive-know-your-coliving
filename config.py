import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

DEFAULT_APP_URL = "https://co-live-bwf5.onrender.com"

class Settings(BaseSettings):
    BOT_TOKEN: str = "YOUR_BOT_TOKEN_HERE"
    SUPER_ADMIN_ID: int = 0
    WEBAPP_HOST: str = "0.0.0.0"
    WEBAPP_PORT: int = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))
    WEBAPP_BASE_URL: str = DEFAULT_APP_URL
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def clean_webapp_base_url(self) -> str:
        url = self.WEBAPP_BASE_URL or os.getenv("RENDER_EXTERNAL_URL") or DEFAULT_APP_URL
        if "your-domain" in url:
            url = os.getenv("RENDER_EXTERNAL_URL") or DEFAULT_APP_URL
        return url.rstrip("/")

    def get_webapp_url(self, user_id: Optional[int] = None, coliving_id: Optional[int] = None) -> str:
        base = self.clean_webapp_base_url
        params = []
        if user_id:
            params.append(f"user_id={user_id}")
        if coliving_id:
            params.append(f"coliving_id={coliving_id}")
        if params:
            return f"{base}/?{'&'.join(params)}"
        return f"{base}/"

settings = Settings()

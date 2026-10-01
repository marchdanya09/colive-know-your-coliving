import time
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import settings
import texts

class RateLimiter:
    def __init__(self):
        # user_id -> list of failed attempt timestamps
        self.code_attempts: Dict[int, list] = {}
        # user_id -> locked_until timestamp
        self.code_lockouts: Dict[int, float] = {}
        # user_id -> last complaint timestamp
        self.complaint_cooldowns: Dict[int, float] = {}
        # user_id -> last room broadcast timestamp
        self.room_broadcast_cooldowns: Dict[int, float] = {}
        # user_id -> last click timestamp
        self.click_cooldowns: Dict[int, float] = {}

    def is_code_locked(self, user_id: int) -> bool:
        locked_until = self.code_lockouts.get(user_id, 0)
        if time.time() < locked_until:
            return True
        elif locked_until != 0:
            del self.code_lockouts[user_id]
            self.code_attempts.pop(user_id, None)
        return False

    def record_failed_code_attempt(self, user_id: int) -> bool:
        """Повертає True, якщо користувача заблоковано через досягнення ліміту."""
        now = time.time()
        window = 300  # 5 хвилин
        attempts = self.code_attempts.get(user_id, [])
        # Фільтруємо старі спроби
        attempts = [t for t in attempts if now - t < window]
        attempts.append(now)
        self.code_attempts[user_id] = attempts

        if len(attempts) >= settings.CODE_ATTEMPTS_LIMIT:
            self.code_lockouts[user_id] = now + (settings.CODE_LOCKOUT_MINUTES * 60)
            return True
        return False

    def can_send_complaint(self, user_id: int) -> bool:
        now = time.time()
        last = self.complaint_cooldowns.get(user_id, 0)
        if now - last < (settings.COMPLAINT_RATE_LIMIT_MINUTES * 60):
            return False
        self.complaint_cooldowns[user_id] = now
        return True

    def can_broadcast_room(self, user_id: int) -> bool:
        now = time.time()
        last = self.room_broadcast_cooldowns.get(user_id, 0)
        if now - last < (settings.ROOM_BROADCAST_RATE_LIMIT_MINUTES * 60):
            return False
        self.room_broadcast_cooldowns[user_id] = now
        return True

    def check_double_click(self, user_id: int) -> bool:
        now = time.time()
        last = self.click_cooldowns.get(user_id, 0)
        if now - last < 0.5:
            return False
        self.click_cooldowns[user_id] = now
        return True

rate_limiter = RateLimiter()

class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user and not user.is_bot:
            if not rate_limiter.check_double_click(user.id):
                if isinstance(event, CallbackQuery):
                    await event.answer("Зачекайте секунду...", show_alert=False)
                return
        return await handler(event, data)

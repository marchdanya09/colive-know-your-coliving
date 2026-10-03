import os
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import get_db, AsyncSessionLocal
from database import crud
from config import settings

app = FastAPI(title="CO:LIVE Mini App API")

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def serve_webapp(request: Request, user_id: int = Query(0), coliving_id: int = Query(0)):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user_id": user_id, "coliving_id": coliving_id}
    )

@app.get("/api/coliving-info")
async def get_coliving_info(user_id: int = Query(...), coliving_id: Optional[int] = Query(None)):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Користувача не знайдено. Будь ласка, спочатку зареєструйтесь у боті через /start")

        target_coliving_id = coliving_id or user.coliving_id
        if not target_coliving_id:
            raise HTTPException(status_code=400, detail="Користувач не приєднаний до жодного колівінгу")

        if user.coliving_id != target_coliving_id:
            raise HTTPException(status_code=403, detail="Доступ заборонено")

        coliving = await crud.get_coliving_by_id(session, target_coliving_id)
        if not coliving:
            raise HTTPException(status_code=404, detail="Колівінг не знайдено")

        rooms = await crud.get_rooms_with_users(session, target_coliving_id)
        current_duty = await crud.get_current_duty(session, target_coliving_id)
        pending_count = await crud.count_pending_requests(session, target_coliving_id)

        # Серіалізація кімнат
        rooms_data = []
        for r in rooms:
            rooms_data.append({
                "id": r.id,
                "name": r.name,
                "capacity": r.capacity,
                "rotation_order": r.rotation_order,
                "users": [
                    {
                        "id": u.id,
                        "full_name": u.full_name,
                        "username": u.username,
                        "role": u.role,
                        "unpaid_fines": u.unpaid_fines
                    }
                    for u in r.users
                ]
            })

        duty_data = None
        if current_duty and current_duty.room:
            duty_data = {
                "room": {
                    "id": current_duty.room.id,
                    "name": current_duty.room.name,
                    "users": [{"full_name": u.full_name} for u in current_duty.room.users]
                },
                "start_date": current_duty.start_date.strftime("%d.%m"),
                "end_date": current_duty.end_date.strftime("%d.%m")
            }

        return {
            "coliving": {
                "id": coliving.id,
                "name": coliving.name,
                "address": coliving.address,
                "invite_code": coliving.invite_code,
                "is_join_locked": coliving.is_join_locked,
                "treasury_balance": coliving.treasury_balance,
                "default_fine_amount": coliving.default_fine_amount,
                "fine_distribution": coliving.fine_distribution
            },
            "current_user": {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "full_name": user.full_name,
                "role": user.role,
                "unpaid_fines": user.unpaid_fines
            },
            "current_duty": duty_data,
            "rooms": rooms_data,
            "pending_requests_count": pending_count
        }

@app.post("/api/sotnik/toggle-lock")
async def api_toggle_lock(user_id: int = Query(...), coliving_id: Optional[int] = Query(None)):
    async with AsyncSessionLocal() as session:
        user = await crud.get_user_by_tg_id(session, user_id)
        if not user or user.role != "SOTNIK":
            raise HTTPException(status_code=403, detail="Лише Сотник має право перемикати блокування")

        target_coliving_id = coliving_id or user.coliving_id
        if not target_coliving_id or user.coliving_id != target_coliving_id:
            raise HTTPException(status_code=403, detail="Доступ заборонено")

        is_locked = await crud.toggle_coliving_lock(session, target_coliving_id)
        return {"status": "ok", "is_locked": is_locked}

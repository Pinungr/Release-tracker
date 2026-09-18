from fastapi import APIRouter

from . import admin, attachments, auth, bookings, schedule, tenants

api_router = APIRouter(prefix="/api")
api_router.include_router(schedule.router)
api_router.include_router(auth.router)
api_router.include_router(bookings.router)
api_router.include_router(bookings.my_bookings_router)
api_router.include_router(attachments.router)
api_router.include_router(admin.router)
api_router.include_router(tenants.router)

__all__ = ["api_router"]

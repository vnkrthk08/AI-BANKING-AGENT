"""FastAPI Notification Router: In-app notification center and channel status."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from kural.persistence.database import Database
from kural.notifications.service import NotificationService

notification_router = APIRouter(tags=["notifications"])


def _get_notification_service(request: Request) -> NotificationService:
    svc = getattr(request.app.state, "notification_service", None)
    if svc is not None:
        return svc
    db: Database = getattr(request.app.state, "database", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database not configured"
        )
    return NotificationService(db)


@notification_router.get("/api/notifications")
@notification_router.get("/api/v1/notifications")
async def list_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
    role: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    items = svc.list_notifications(
        limit=limit, unread_only=unread_only, recipient_role=role, user_id=user_id
    )
    unread_count = svc.get_unread_count(recipient_role=role, user_id=user_id)
    return {
        "notifications": items,
        "unread_count": unread_count,
        "total": len(items),
    }


@notification_router.patch("/api/notifications/{notification_id}/read")
@notification_router.post("/api/notifications/{notification_id}/read")
@notification_router.patch("/api/v1/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request: Request) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    success = svc.mark_as_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True, "id": notification_id}


@notification_router.post("/api/notifications/read-all")
@notification_router.post("/api/v1/notifications/read-all")
async def mark_all_notifications_read(
    request: Request,
    role: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    count = svc.mark_all_read(recipient_role=role, user_id=user_id)
    return {"success": True, "marked_count": count}


@notification_router.get("/api/notifications/channels")
@notification_router.get("/api/v1/notifications/channels")
async def get_notification_channels(request: Request) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    channels = svc.get_channel_statuses()
    return {"channels": channels}

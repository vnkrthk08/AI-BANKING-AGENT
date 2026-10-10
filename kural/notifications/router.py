"""Notification API: personal in-app inbox, channel status and the delivery log."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from kural.notifications.service import NotificationService
from kural.persistence.database import Database
from kural.security.deps import Principal, require

notification_router = APIRouter(tags=["notifications"])


def _get_notification_service(request: Request) -> NotificationService:
    svc = getattr(request.app.state, "notification_service", None)
    if svc is not None:
        return svc
    db: Database = getattr(request.app.state, "database", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database not configured")
    return NotificationService(db)


@notification_router.get("/api/notifications")
@notification_router.get("/api/v1/notifications")
async def list_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
    principal: Principal = Depends(require("notification:read")),
) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    items = svc.list_notifications(limit=limit, unread_only=unread_only,
                                   recipient_role=principal.role, user_id=principal.user_id)
    unread_count = svc.get_unread_count(recipient_role=principal.role, user_id=principal.user_id)
    return {"notifications": items, "unread_count": unread_count, "total": len(items)}


@notification_router.patch("/api/notifications/{notification_id}/read")
@notification_router.post("/api/notifications/{notification_id}/read")
@notification_router.patch("/api/v1/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request: Request,
                                 principal: Principal = Depends(require("notification:read"))) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    if not svc.mark_as_read(notification_id, user_id=principal.user_id, recipient_role=principal.role):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True, "id": notification_id}


@notification_router.post("/api/notifications/read-all")
@notification_router.post("/api/v1/notifications/read-all")
async def mark_all_notifications_read(request: Request,
                                      principal: Principal = Depends(require("notification:read"))) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    count = svc.mark_all_read(recipient_role=principal.role, user_id=principal.user_id)
    return {"success": True, "marked_count": count}


@notification_router.get("/api/notifications/channels")
@notification_router.get("/api/v1/notifications/channels")
async def get_notification_channels(request: Request,
                                    _: Principal = Depends(require("notification:read"))) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    return {"channels": svc.get_channel_statuses(), "summary": svc.delivery_summary()}


@notification_router.get("/api/notifications/deliveries")
async def list_deliveries(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    channel: Optional[str] = Query(None),
    _: Principal = Depends(require("notification:deliveries")),
) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    return {"deliveries": svc.list_deliveries(limit=limit, status=status_filter, channel=channel),
            "summary": svc.delivery_summary()}


@notification_router.post("/api/notifications/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str, request: Request,
                         _: Principal = Depends(require("notification:deliveries"))) -> Dict[str, Any]:
    svc = _get_notification_service(request)
    try:
        return svc.retry_delivery(delivery_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Delivery not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

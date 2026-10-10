"""Durable notification domain service: in-app alerts, channel status, and pluggable delivery."""

import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import func, select, update

from kural.persistence.database import Database
from kural.persistence.models import NotificationRow, utcnow
from kural.telephony.config import get_telephony_provider

logger = logging.getLogger("kural.notifications")


class NotificationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_notification(
        self,
        title: str,
        message: str,
        level: str = "INFO",
        category: str = "SYSTEM",
        recipient_role: Optional[str] = None,
        user_id: Optional[str] = None,
        link_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates an in-app notification record atomically."""
        nid = f"NOTIF-{uuid4().hex[:10].upper()}"
        now = utcnow()
        row = NotificationRow(
            id=nid,
            recipient_role=recipient_role,
            user_id=user_id,
            title=title,
            message=message,
            level=level.upper(),
            category=category.upper(),
            link_url=link_url,
            is_read=False,
            created_at=now,
            read_at=None,
        )
        with self.database.session() as s:
            s.add(row)
            s.commit()
            return self._serialize(row)

    def list_notifications(
        self,
        limit: int = 50,
        unread_only: bool = False,
        recipient_role: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lists recent in-app notifications matching user/role filters."""
        with self.database.session() as s:
            q = select(NotificationRow)
            if unread_only:
                q = q.where(NotificationRow.is_read.is_(False))
            if recipient_role:
                q = q.where(
                    (NotificationRow.recipient_role.is_(None))
                    | (NotificationRow.recipient_role == recipient_role)
                )
            if user_id:
                q = q.where(
                    (NotificationRow.user_id.is_(None)) | (NotificationRow.user_id == user_id)
                )
            q = q.order_by(NotificationRow.created_at.desc()).limit(limit)
            rows = s.scalars(q).all()
            return [self._serialize(r) for r in rows]

    def get_unread_count(
        self,
        recipient_role: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Returns the total number of unread notifications."""
        with self.database.session() as s:
            q = select(func.count(NotificationRow.id)).where(NotificationRow.is_read.is_(False))
            if recipient_role:
                q = q.where(
                    (NotificationRow.recipient_role.is_(None))
                    | (NotificationRow.recipient_role == recipient_role)
                )
            if user_id:
                q = q.where(
                    (NotificationRow.user_id.is_(None)) | (NotificationRow.user_id == user_id)
                )
            return s.scalar(q) or 0

    def mark_as_read(self, notification_id: str) -> bool:
        """Marks a single notification as read."""
        now = utcnow()
        with self.database.session() as s:
            row = s.get(NotificationRow, notification_id)
            if not row:
                return False
            row.is_read = True
            row.read_at = now
            s.commit()
            return True

    def mark_all_read(
        self,
        recipient_role: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Marks all eligible notifications as read."""
        now = utcnow()
        with self.database.session() as s:
            stmt = (
                update(NotificationRow)
                .where(NotificationRow.is_read.is_(False))
                .values(is_read=True, read_at=now)
            )
            if recipient_role:
                stmt = stmt.where(
                    (NotificationRow.recipient_role.is_(None))
                    | (NotificationRow.recipient_role == recipient_role)
                )
            if user_id:
                stmt = stmt.where(
                    (NotificationRow.user_id.is_(None)) | (NotificationRow.user_id == user_id)
                )
            res = s.execute(stmt)
            s.commit()
            return res.rowcount

    def get_channel_statuses(self) -> List[Dict[str, Any]]:
        """Truthfully reports availability of all notification delivery channels."""
        telephony = get_telephony_provider()
        telephony_configured = telephony.is_configured
        telephony_name = telephony.provider_name

        sms_configured = bool(os.environ.get("SMS_API_KEY") or os.environ.get("KARIX_API_KEY"))
        email_configured = bool(os.environ.get("SMTP_HOST") or os.environ.get("AWS_SES_REGION"))

        return [
            {
                "channel": "in_app",
                "label": "In-App Alerts",
                "status": "ACTIVE",
                "description": "Real-time institutional notification center & drawer",
                "is_active": True,
            },
            {
                "channel": "sms",
                "label": "Customer SMS (DLT / TRAI)",
                "status": "CONFIGURED" if sms_configured else "NOT_CONFIGURED",
                "description": "Transactional SMS via Karix / Exotel DLT gateway"
                if sms_configured
                else "SMS gateway unconfigured. Set SMS_API_KEY in environment.",
                "is_active": sms_configured,
            },
            {
                "channel": "email",
                "label": "Bank Operations Email",
                "status": "CONFIGURED" if email_configured else "NOT_CONFIGURED",
                "description": "SMTP / AWS SES secure notification transport"
                if email_configured
                else "Email transport unconfigured. Set SMTP_HOST in environment.",
                "is_active": email_configured,
            },
            {
                "channel": "telephony",
                "label": f"Telephony Outdial ({telephony_name.capitalize()})",
                "status": "ACTIVE" if telephony_configured else "NOT_CONFIGURED",
                "description": f"Voice calling via {telephony_name} adapter"
                if telephony_configured
                else "Physical telephony trunk unconfigured. Set TELEPHONY_PROVIDER=sandbox or exotel credentials.",
                "is_active": telephony_configured,
            },
        ]

    def _serialize(self, row: NotificationRow) -> Dict[str, Any]:
        return {
            "id": row.id,
            "recipient_role": row.recipient_role,
            "user_id": row.user_id,
            "title": row.title,
            "message": row.message,
            "level": row.level,
            "category": row.category,
            "link_url": row.link_url,
            "is_read": row.is_read,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "read_at": row.read_at.isoformat() if row.read_at else None,
        }

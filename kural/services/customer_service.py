"""Customer domain service: customer registry, E.164 phone normalization, DND scrub, and import/export."""

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CustomerRow


def normalize_indian_phone(phone_raw: str) -> str:
    """Normalizes an Indian phone number to E.164 format (+91XXXXXXXXXX).
    Rejects invalid formats or non-mobile prefixes.
    """
    cleaned = re.sub(r"[\s\-\(\)\.]", "", str(phone_raw).strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    if not re.fullmatch(r"[6-9]\d{9}", cleaned):
        raise ValueError(f"Invalid Indian mobile number: {phone_raw}")

    return f"+91{cleaned}"


class CustomerService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_customer(
        self,
        full_name: str,
        phone: str,
        customer_ref: str | None = None,
        email: str | None = None,
        preferred_language: str = "Hindi",
        app_status: str = "NOT_INSTALLED",
        app_version: str | None = None,
        dnd_status: bool = False,
        account_type: str = "SAVINGS",
        branch: str = "Mumbai Metro",
        region: str = "West",
        assigned_agent_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_phone = normalize_indian_phone(phone)
        ref = customer_ref or f"CUST-{uuid4().hex[:5].upper()}"
        now = datetime.now(timezone.utc)

        with self.database.session() as s:
            existing = s.scalar(select(CustomerRow).where(CustomerRow.phone == normalized_phone))
            if existing is not None:
                # Update existing record
                existing.full_name = full_name
                existing.email = email or existing.email
                existing.preferred_language = preferred_language
                existing.app_status = app_status
                existing.app_version = app_version or existing.app_version
                existing.dnd_status = dnd_status
                existing.account_type = account_type
                existing.branch = branch
                existing.region = region
                existing.assigned_agent_id = assigned_agent_id or existing.assigned_agent_id
                existing.updated_at = now
                s.commit()
                return self._serialize_customer(existing)

            row = CustomerRow(
                customer_ref=ref,
                full_name=full_name,
                phone=normalized_phone,
                email=email,
                preferred_language=preferred_language,
                app_status=app_status,
                app_version=app_version,
                dnd_status=dnd_status,
                account_type=account_type,
                branch=branch,
                region=region,
                assigned_agent_id=assigned_agent_id,
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            s.commit()
            return self._serialize_customer(row)

    def get_customer(self, customer_ref: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.get(CustomerRow, customer_ref)
            return self._serialize_customer(row) if row else None

    def get_customer_by_phone(self, phone: str) -> dict[str, Any] | None:
        try:
            norm = normalize_indian_phone(phone)
        except ValueError:
            return None
        with self.database.session() as s:
            row = s.scalar(select(CustomerRow).where(CustomerRow.phone == norm))
            return self._serialize_customer(row) if row else None

    def list_customers(
        self,
        search: str | None = None,
        app_status: str | None = None,
        dnd_status: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.database.session() as s:
            query = select(CustomerRow)
            if app_status:
                query = query.where(CustomerRow.app_status == app_status)
            if dnd_status is not None:
                query = query.where(CustomerRow.dnd_status == dnd_status)
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(
                        CustomerRow.full_name.ilike(pattern),
                        CustomerRow.customer_ref.ilike(pattern),
                        CustomerRow.phone.ilike(pattern),
                    )
                )
            query = query.order_by(CustomerRow.created_at.desc()).limit(limit).offset(offset)
            rows = s.scalars(query).all()
            return [self._serialize_customer(r) for r in rows]

    def import_customers_csv(self, csv_content: str, dnd_scrub: bool = True) -> dict[str, Any]:
        """Imports customers from a CSV string with validation and DND scrubbing."""
        reader = csv.DictReader(io.StringIO(csv_content))
        total_rows = 0
        imported = 0
        skipped = 0
        dnd_suppressed = 0
        errors: list[dict[str, Any]] = []

        for index, row in enumerate(reader, start=1):
            total_rows += 1
            raw_phone = row.get("phone") or row.get("mobile") or ""
            full_name = row.get("full_name") or row.get("name") or ""
            if not raw_phone or not full_name:
                skipped += 1
                errors.append({"row": index, "reason": "Missing required field: full_name or phone"})
                continue

            try:
                norm_phone = normalize_indian_phone(raw_phone)
            except ValueError as e:
                skipped += 1
                errors.append({"row": index, "reason": str(e)})
                continue

            # Check DND scrub
            is_dnd = str(row.get("dnd", "")).strip().lower() in {"1", "true", "yes"}
            if dnd_scrub and is_dnd:
                dnd_suppressed += 1

            pref_lang = row.get("preferred_language") or row.get("language") or "Hindi"
            app_status = row.get("app_status") or "NOT_INSTALLED"
            app_version = row.get("app_version")
            account_type = row.get("account_type") or "SAVINGS"
            branch = row.get("branch") or "Mumbai Metro"
            region = row.get("region") or "West"
            customer_ref = row.get("customer_ref") or row.get("id")

            self.create_customer(
                full_name=full_name,
                phone=norm_phone,
                customer_ref=customer_ref,
                email=row.get("email"),
                preferred_language=pref_lang,
                app_status=app_status,
                app_version=app_version,
                dnd_status=is_dnd,
                account_type=account_type,
                branch=branch,
                region=region,
            )
            imported += 1

        return {
            "total_rows": total_rows,
            "imported": imported,
            "skipped": skipped,
            "dnd_suppressed": dnd_suppressed,
            "errors": errors,
        }

    def export_customers_csv(self) -> str:
        """Exports all customers as a CSV string."""
        customers = self.list_customers(limit=10000)
        output = io.StringIO()
        fieldnames = [
            "customer_ref",
            "full_name",
            "phone",
            "email",
            "preferred_language",
            "app_status",
            "app_version",
            "dnd_status",
            "account_type",
            "branch",
            "region",
            "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for c in customers:
            row = {k: c.get(k, "") for k in fieldnames}
            writer.writerow(row)
        return output.getvalue()

    @staticmethod
    def _serialize_customer(row: CustomerRow) -> dict[str, Any]:
        return {
            "customer_ref": row.customer_ref,
            "full_name": row.full_name,
            "phone": row.phone,
            "masked_phone": f"{row.phone[:6]}XX XX{row.phone[-2:]}" if len(row.phone) >= 10 else row.phone,
            "email": row.email,
            "preferred_language": row.preferred_language,
            "app_status": row.app_status,
            "app_version": row.app_version or "—",
            "dnd_status": row.dnd_status,
            "account_type": row.account_type,
            "branch": row.branch,
            "region": row.region,
            "assigned_agent_id": row.assigned_agent_id,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

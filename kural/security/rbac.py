"""Role-Based Access Control (RBAC) and permission matrices for Phase 4."""

from enum import Enum
from typing import Set
from fastapi import HTTPException, status


class Role(str, Enum):
    AGENT = "AGENT"
    SUPERVISOR = "SUPERVISOR"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    AUDITOR = "AUDITOR"


ALL_ROLES = {r.value for r in Role}

# Roles permitted to view customer data and call records (SYSTEM_ADMIN is strictly excluded)
CUSTOMER_DATA_ROLES: Set[str] = {
    Role.AGENT.value,
    Role.SUPERVISOR.value,
    Role.COMPLIANCE_OFFICER.value,
    Role.AUDITOR.value,
}

# Roles with administration capabilities
ADMIN_ROLES: Set[str] = {Role.SYSTEM_ADMIN.value}

# Roles with compliance oversight
COMPLIANCE_ROLES: Set[str] = {Role.COMPLIANCE_OFFICER.value, Role.AUDITOR.value}


def check_pii_access_allowed(user_role: str) -> None:
    """Enforce the non-negotiable Phase 4 invariant:
    SYSTEM_ADMIN is strictly forbidden from accessing customer PII, call recordings,
    transcripts, and customer profile details.
    """
    if user_role == Role.SYSTEM_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: SYSTEM_ADMIN is strictly prohibited from accessing customer PII, call recordings, or transcripts.",
        )
    if user_role not in CUSTOMER_DATA_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Role {user_role} does not have customer data access permissions.",
        )


def check_role_membership(user_role: str, allowed_roles: Set[str]) -> None:
    """Verify that the user's role is in the allowed set."""
    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Insufficient privileges. Required one of: {sorted(list(allowed_roles))}",
        )

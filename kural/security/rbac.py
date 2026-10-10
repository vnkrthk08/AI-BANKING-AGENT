"""Role-Based Access Control (RBAC): roles, permission matrix and enforcement helpers.

Every operational API route declares the permission it needs; the matrix below is the
single server-side source of truth. The frontend mirrors it only to hide unusable
controls — hiding is never relied upon for protection.
"""

from enum import Enum
from typing import Set

from fastapi import HTTPException, status


class Role(str, Enum):
    OPS_MANAGER = "OPS_MANAGER"
    SUPERVISOR = "SUPERVISOR"
    AGENT = "AGENT"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    AUDITOR = "AUDITOR"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


ALL_ROLES = {r.value for r in Role}

# Roles permitted to view customer data and call records (SYSTEM_ADMIN is strictly excluded)
CUSTOMER_DATA_ROLES: Set[str] = {
    Role.OPS_MANAGER.value,
    Role.AGENT.value,
    Role.SUPERVISOR.value,
    Role.COMPLIANCE_OFFICER.value,
    Role.AUDITOR.value,
    Role.SUPER_ADMIN.value,
}

# Roles with administration capabilities
ADMIN_ROLES: Set[str] = {Role.SYSTEM_ADMIN.value, Role.SUPER_ADMIN.value}

# Roles with compliance oversight
COMPLIANCE_ROLES: Set[str] = {Role.COMPLIANCE_OFFICER.value, Role.AUDITOR.value, Role.SUPER_ADMIN.value}

_OPS = Role.OPS_MANAGER.value
_SUP = Role.SUPERVISOR.value
_AGT = Role.AGENT.value
_CMP = Role.COMPLIANCE_OFFICER.value
_AUD = Role.AUDITOR.value
_ADM = Role.SYSTEM_ADMIN.value
_SAD = Role.SUPER_ADMIN.value

PERMISSIONS: dict[str, Set[str]] = {
    # Operational read models (customer-linked, so SYSTEM_ADMIN is excluded)
    "dashboard:view": {_OPS, _SUP, _AGT, _CMP, _AUD, _SAD},
    "customer:read": set(CUSTOMER_DATA_ROLES),
    "customer:write": {_OPS, _SUP, _SAD},
    "call:read": set(CUSTOMER_DATA_ROLES),
    "transcript:read": {_OPS, _SUP, _AGT, _CMP, _AUD, _SAD},
    "recording:read": {_SUP, _CMP, _AUD, _SAD},
    "voice:operate": {_OPS, _SUP, _AGT, _SAD},
    "case:read": set(CUSTOMER_DATA_ROLES),
    "case:work": {_OPS, _SUP, _AGT, _SAD},
    "case:assign": {_OPS, _SUP, _SAD},
    "callback:read": set(CUSTOMER_DATA_ROLES),
    "callback:manage": {_OPS, _SUP, _AGT, _SAD},
    "campaign:read": {_OPS, _SUP, _CMP, _AUD, _SAD},
    "campaign:manage": {_OPS, _SAD},
    "campaign:approve": {_CMP, _SAD},
    "campaign:execute": {_OPS, _SAD},
    "agent:read": {_OPS, _SUP, _AGT, _SAD},
    "agent:manage": {_OPS, _SUP, _SAD},
    "audit:read": {_OPS, _SUP, _CMP, _AUD, _ADM, _SAD},
    "report:export": {_OPS, _CMP, _AUD, _SAD},
    "compliance:read": {_OPS, _CMP, _AUD, _SAD},
    "notification:read": ALL_ROLES,
    "notification:deliveries": {_OPS, _SUP, _CMP, _AUD, _ADM, _SAD},
    "system:read": ALL_ROLES,
    "system:emergency_stop": {_OPS, _SUP, _CMP, _ADM, _SAD},
    "system:resume_dialing": {_OPS, _ADM, _SAD},
    "telephony:dial": {_OPS, _SUP, _AGT, _SAD},
    "telephony:transfer": {_SUP, _AGT, _SAD},
    "user:manage": {_ADM, _SAD},
    "admin:portal": {_SAD},
}


def has_permission(user_role: str, permission: str) -> bool:
    return user_role in PERMISSIONS.get(permission, set())


_CUSTOMER_DATA_PERMISSIONS = {"customer:read", "call:read", "transcript:read", "recording:read",
                              "case:read", "callback:read"}


def check_permission(user_role: str, permission: str) -> None:
    if user_role == Role.SYSTEM_ADMIN.value and permission in _CUSTOMER_DATA_PERMISSIONS:
        check_pii_access_allowed(user_role)
    if not has_permission(user_role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: your role does not grant '{permission}'.",
        )


def permissions_for(user_role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if user_role in roles)


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

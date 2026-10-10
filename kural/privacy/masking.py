"""Display masking for customer identifiers shown in operator UIs, exports and logs."""

from __future__ import annotations

import re


def mask_phone(phone: str | None) -> str:
    """Return ``+91 ••••• ••123`` style masking that keeps only the last three digits."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "•••"
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return f"+91 ••••• ••{digits[-3:]}"


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1]}•••@{domain}"

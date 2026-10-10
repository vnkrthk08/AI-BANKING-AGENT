"""Outbound notification transports.

A transport reports ``configured`` truthfully from its environment and ``send`` either
returns a provider message id (accepted for delivery) or raises ``DeliveryError``.
"Accepted" means the SMTP server or SMS gateway took the message; neither transport
receives end-user delivery receipts, so the delivery log records ``SENT``, never
``DELIVERED``, for these channels.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from uuid import uuid4

import httpx


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class Transport(Protocol):
    channel: str

    @property
    def configured(self) -> bool: ...

    def describe(self) -> str: ...

    def send(self, address: str, subject: str, body: str) -> str: ...


@dataclass
class SmtpEmailTransport:
    channel: str = "EMAIL"

    @property
    def host(self) -> str:
        return os.getenv("SMTP_HOST", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.host and os.getenv("SMTP_FROM", "").strip())

    def describe(self) -> str:
        if not self.configured:
            return "Set SMTP_HOST and SMTP_FROM (plus SMTP_USERNAME/SMTP_PASSWORD if required)."
        return f"SMTP relay {self.host}:{os.getenv('SMTP_PORT', '587')}"

    def send(self, address: str, subject: str, body: str) -> str:
        if not self.configured:
            raise DeliveryError("Email transport is not configured", permanent=True)
        message = EmailMessage()
        message_id = f"<{uuid4().hex}@kural-ava>"
        message["From"] = os.getenv("SMTP_FROM", "")
        message["To"] = address
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(body)
        port = int(os.getenv("SMTP_PORT", "587"))
        timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
        try:
            if os.getenv("SMTP_USE_SSL", "false").lower() == "true":
                server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, port, timeout=timeout, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(self.host, port, timeout=timeout)
            with server:
                if os.getenv("SMTP_STARTTLS", "true").lower() == "true" and not isinstance(server, smtplib.SMTP_SSL):
                    server.starttls(context=ssl.create_default_context())
                username = os.getenv("SMTP_USERNAME")
                if username:
                    server.login(username, os.getenv("SMTP_PASSWORD", ""))
                refused = server.send_message(message)
                if refused:
                    raise DeliveryError(f"Recipient refused by SMTP server", permanent=True)
        except DeliveryError:
            raise
        except smtplib.SMTPRecipientsRefused as exc:
            raise DeliveryError("Recipient refused by SMTP server", permanent=True) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(f"SMTP error: {type(exc).__name__}") from exc
        return message_id


@dataclass
class HttpSmsTransport:
    """Generic HTTPS SMS gateway (DLT-registered sender in India).

    POSTs JSON ``{"to", "message", "sender", "template_id"}`` with a bearer token and expects
    a 2xx response containing an optional ``id``/``message_id``.
    """

    channel: str = "SMS"

    @property
    def url(self) -> str:
        return os.getenv("SMS_GATEWAY_URL", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.url and os.getenv("SMS_GATEWAY_TOKEN", "").strip() and os.getenv("SMS_SENDER_ID", "").strip())

    def describe(self) -> str:
        if not self.configured:
            return "Set SMS_GATEWAY_URL, SMS_GATEWAY_TOKEN and SMS_SENDER_ID (DLT-registered)."
        return f"HTTPS SMS gateway, sender {os.getenv('SMS_SENDER_ID')}"

    def send(self, address: str, subject: str, body: str) -> str:
        if not self.configured:
            raise DeliveryError("SMS transport is not configured", permanent=True)
        payload = {
            "to": address,
            "message": body[:480],
            "sender": os.getenv("SMS_SENDER_ID"),
            "template_id": os.getenv("SMS_DLT_TEMPLATE_ID") or None,
        }
        try:
            with httpx.Client(timeout=float(os.getenv("SMS_TIMEOUT_SECONDS", "8"))) as client:
                response = client.post(self.url, json=payload,
                                       headers={"Authorization": f"Bearer {os.getenv('SMS_GATEWAY_TOKEN')}"})
        except httpx.HTTPError as exc:
            raise DeliveryError(f"SMS gateway unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise DeliveryError(f"SMS gateway temporary error HTTP {response.status_code}")
        if response.status_code >= 400:
            raise DeliveryError(f"SMS gateway rejected message HTTP {response.status_code}", permanent=True)
        try:
            body_json = response.json()
        except ValueError:
            body_json = {}
        return str(body_json.get("message_id") or body_json.get("id") or f"sms-{uuid4().hex[:12]}")


def default_transports() -> dict[str, Transport]:
    return {"EMAIL": SmtpEmailTransport(), "SMS": HttpSmsTransport()}

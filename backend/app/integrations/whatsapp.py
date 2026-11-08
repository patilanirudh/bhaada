"""WhatsApp sending abstraction.

Only official click-to-chat links (wa.me) are used today. ``WhatsAppSender`` is an
interface so an official WhatsApp Cloud API sender can be dropped in later
without touching routers or the daily job.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class WhatsAppResult:
    channel: str  # e.g. WHATSAPP_MANUAL, WHATSAPP_CLOUD
    requires_user_action: bool  # True: the owner must tap the link to send
    link: str | None = None
    sent: bool = False
    error: str | None = None


class WhatsAppSender(ABC):
    channel: str

    @abstractmethod
    def send(self, phone_e164: str, text: str) -> WhatsAppResult: ...


class ManualLinkSender(WhatsAppSender):
    """Builds https://wa.me/<number>?text=<message>; the owner taps it to send from their phone."""

    channel = "WHATSAPP_MANUAL"

    def send(self, phone_e164: str, text: str) -> WhatsAppResult:
        return WhatsAppResult(channel=self.channel, requires_user_action=True, link=wa_link(phone_e164, text))


def wa_link(phone_e164: str | None, text: str) -> str:
    encoded = quote(text, safe="")
    if not phone_e164:
        return f"https://wa.me/?text={encoded}"
    return f"https://wa.me/{phone_e164.lstrip('+')}?text={encoded}"


def get_sender() -> WhatsAppSender:
    # Future: return CloudApiSender(...) when WHATSAPP_CLOUD_TOKEN is configured.
    return ManualLinkSender()

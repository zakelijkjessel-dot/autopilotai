import asyncio
import logging

from twilio.rest import Client

from config import settings

logger = logging.getLogger(__name__)

_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


async def send_whatsapp_message(to_phone: str, message: str) -> None:
    """Verstuur een WhatsApp-bericht via Twilio."""
    if not to_phone.startswith("whatsapp:"):
        to_phone = f"whatsapp:{to_phone}"

    try:
        await asyncio.to_thread(
            _client.messages.create,
            from_=settings.TWILIO_WHATSAPP_FROM,
            to=to_phone,
            body=message,
        )
        logger.info("WhatsApp bericht verstuurd naar %s", to_phone)
    except Exception as exc:
        logger.error("Fout bij versturen WhatsApp naar %s: %s", to_phone, exc)
        raise

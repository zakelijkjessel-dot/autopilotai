import logging

from database import SessionLocal
from services.ai_service import process_message
from services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)

_ERROR_MSG = (
    "Sorry, er is een technisch probleem opgetreden. 😔\n"
    "Probeer het opnieuw of bel ons direct."
)


def _split(text: str, max_len: int = 4000) -> list[str]:
    """Splits een lang bericht op regeleinden zodat het onder de WhatsApp-limiet blijft."""
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


async def handle_incoming_message(
    phone: str,
    message: str,
    media_urls: list[str],
    media_types: list[str],
) -> None:
    """Centrale handler voor een inkomend WhatsApp-bericht."""
    logger.info(
        "Bericht ontvangen van %s | tekst=%r | media=%d",
        phone,
        message[:60],
        len(media_urls),
    )
    db = SessionLocal()
    try:
        response = await process_message(
            phone=phone,
            message=message,
            media_urls=media_urls,
            media_types=media_types,
            db=db,
        )
        for part in _split(response):
            await send_whatsapp_message(phone, part)

    except Exception as exc:
        logger.error("Fout bij verwerken bericht van %s: %s", phone, exc, exc_info=True)
        try:
            await send_whatsapp_message(phone, _ERROR_MSG)
        except Exception:
            pass
    finally:
        db.close()

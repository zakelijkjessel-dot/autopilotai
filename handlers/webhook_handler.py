"""
Webhook-handler: verwerkt inkomende WhatsApp-berichten van Twilio.
Downloadt media-bestanden vooraf zodat ai_service ontkoppeld blijft van Twilio.
"""

import base64
import logging
import os
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from services.ai_service import process_message
from services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)

_ERROR_MSG = (
    "Sorry, er is een technisch probleem opgetreden. 😔\n"
    "Probeer het opnieuw of bel ons direct."
)


def _download_twilio_image(url: str, phone: str, index: int) -> tuple[dict, str]:
    """
    Download een Twilio-mediabestand en sla het op in /uploads.

    Returns:
        (image_dict, filename)
        image_dict: {"data": "<base64>", "media_type": "<type>"}
    """
    resp = requests.get(
        url,
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    resp.raise_for_status()
    media_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    ext = "jpg" if "jpeg" in media_type else media_type.split("/")[-1]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{phone.replace('+', '')}_{ts}_{index}.{ext}"

    os.makedirs("uploads", exist_ok=True)
    with open(os.path.join("uploads", filename), "wb") as f:
        f.write(resp.content)

    b64 = base64.standard_b64encode(resp.content).decode()
    return {"data": b64, "media_type": media_type}, filename


def _split(text: str, max_len: int = 4000) -> list[str]:
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
        "Bericht van %s | tekst=%r | media=%d",
        phone, message[:60], len(media_urls),
    )
    db = SessionLocal()
    try:
        images: list[dict] = []
        photo_filenames: list[str] = []

        for i, url in enumerate(media_urls):
            try:
                img_dict, filename = _download_twilio_image(url, phone, i)
                images.append(img_dict)
                photo_filenames.append(filename)
            except Exception as exc:
                logger.warning("Kon media niet downloaden (%s): %s", url, exc)

        response = await process_message(
            phone=phone,
            message=message,
            images=images,
            db=db,
            photo_filenames=photo_filenames,
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

"""
AutoGarage WhatsApp Chatbot – FastAPI applicatie

Endpoints:
  POST /webhook/whatsapp               – Twilio webhook voor inkomende berichten
  GET  /                               – Welkomstpagina
  GET  /chat                           – Web-chat demo (geen WhatsApp nodig)
  POST /chat/api/message               – Chat-API voor de web interface
  GET  /admin                          – Dashboard voor de garage
  GET  /admin/api/appointments         – JSON API voor afspraken
  PATCH /admin/api/appointments/{id}/status – Status bijwerken
  POST /dev/test-message               – Lokaal testen zonder Twilio
"""

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import uvicorn
from twilio.request_validator import RequestValidator
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import get_db, init_db
from handlers.webhook_handler import SUPPORTED_IMAGE_TYPES, handle_incoming_message
from services.reminder_service import start_reminder_scheduler
import models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AutoGarage WhatsApp Chatbot wordt gestart...")
    os.makedirs("uploads", exist_ok=True)
    init_db()
    scheduler = start_reminder_scheduler()
    yield
    scheduler.shutdown()
    logger.info("Chatbot gestopt.")


app = FastAPI(
    title="AutoGarage WhatsApp Chatbot",
    description="AI-assistent voor afsprakenbeheer via WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
)

# Serveer geüploade foto's als statische bestanden.
# Map alvast aanmaken: de mount gebeurt bij het importeren, vóór de lifespan-startup,
# en 'uploads/' is gitignored dus ontbreekt op een verse checkout.
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")


# ─────────────────────────────────────────────
# WhatsApp Webhook
# ─────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=HTMLResponse)
async def whatsapp_webhook(request: Request):
    form = await request.form()

    # Controleer dat het verzoek echt van Twilio komt (voorkomt nep-berichten en kosten)
    if settings.TWILIO_AUTH_TOKEN:
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        url = f"{settings.BASE_URL.rstrip('/')}/webhook/whatsapp"
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(url, dict(form), signature):
            logger.warning("Webhook geweigerd: ongeldige Twilio-handtekening (verwacht URL %s)", url)
            raise HTTPException(status_code=403, detail="Ongeldige handtekening")
    else:
        logger.warning("TWILIO_AUTH_TOKEN ontbreekt: webhook-handtekening wordt NIET gecontroleerd")

    from_value = form.get("From")
    if not from_value:
        raise HTTPException(status_code=400, detail="Ontbrekend veld: From")
    Body = str(form.get("Body", "") or "")
    phone = from_value.replace("whatsapp:", "")

    media_urls: list[str] = []
    media_types: list[str] = []
    for i in range(3):
        url = form.get(f"MediaUrl{i}")
        if url:
            media_urls.append(str(url))
            media_types.append(str(form.get(f"MediaContentType{i}") or "image/jpeg"))

    # Verwerk het bericht asynchroon; geef Twilio direct een lege TwiML-response
    asyncio.create_task(
        handle_incoming_message(
            phone=phone,
            message=Body,
            media_urls=media_urls,
            media_types=media_types,
        )
    )

    return HTMLResponse(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )


# ─────────────────────────────────────────────
# Admin Dashboard
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(
        "<h2 style='font-family:sans-serif'>AutoGarage Chatbot actief ✅"
        " &nbsp;|&nbsp; <a href='/admin'>Open dashboard</a></h2>"
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    db = next(get_db())
    appointments = (
        db.query(models.Appointment)
        .order_by(models.Appointment.scheduled_datetime.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "appointments": appointments,
            "garage_naam": settings.GARAGE_NAAM,
        },
    )


@app.get("/admin/api/appointments")
async def get_appointments_api(status: Optional[str] = None):
    db = next(get_db())
    query = db.query(models.Appointment).order_by(
        models.Appointment.scheduled_datetime.asc()
    )
    if status:
        query = query.filter(models.Appointment.status == status)

    return [
        {
            "id": a.id,
            "klant_naam": a.klant_naam,
            "klant_telefoon": a.klant_telefoon,
            "klant_email": a.klant_email,
            "auto_merk": a.auto_merk,
            "auto_model": a.auto_model,
            "bouwjaar": a.bouwjaar,
            "kenteken": a.kenteken,
            "service_type": a.service_type,
            "probleem_omschrijving": a.probleem_omschrijving,
            "foto_paths": a.foto_paths or [],
            "scheduled_datetime": a.scheduled_datetime.isoformat() if a.scheduled_datetime else None,
            "duur_minuten": a.duur_minuten,
            "prijs_min": a.prijs_min,
            "prijs_max": a.prijs_max,
            "status": a.status,
            "ai_notities": a.ai_notities,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in query.all()
    ]


@app.patch("/admin/api/appointments/{appointment_id}/status")
async def update_appointment_status(appointment_id: int, status: str):
    valid = {"bevestigd", "geannuleerd", "voltooid"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Geldige statussen: {valid}")

    db = next(get_db())
    apt = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
    if not apt:
        raise HTTPException(status_code=404, detail="Afspraak niet gevonden")

    apt.status = status
    db.commit()
    return {"message": f"Status bijgewerkt naar '{status}'", "id": appointment_id}


# ─────────────────────────────────────────────
# Dev/test endpoint
# ─────────────────────────────────────────────

@app.post("/dev/test-message")
async def dev_test_message(phone: str, body: str):
    """Simuleer een inkomend WhatsApp-bericht (alleen met ENABLE_DEV_ROUTES=true)."""
    if not settings.ENABLE_DEV_ROUTES:
        raise HTTPException(status_code=404, detail="Not Found")
    db = next(get_db())
    from services.ai_service import process_message
    response = await process_message(
        phone=phone,
        message=body,
        images=[],
        db=db,
    )
    return {"phone": phone, "response": response}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AutoGarage WhatsApp Chatbot"}


@app.get("/debug")
async def debug_config():
    """Controleer of de environment-variabelen zijn ingeladen (alleen met ENABLE_DEV_ROUTES=true).

    Geen geheimen of delen daarvan in de respons.
    """
    if not settings.ENABLE_DEV_ROUTES:
        raise HTTPException(status_code=404, detail="Not Found")
    return {
        "anthropic_api_key": "ingesteld" if settings.ANTHROPIC_API_KEY else "NIET INGESTELD",
        "anthropic_model": settings.ANTHROPIC_MODEL,
        "garage_naam": settings.GARAGE_NAAM,
        "timezone": settings.TIMEZONE,
        "base_url": settings.BASE_URL,
        "twilio": "ingesteld" if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN else "NIET INGESTELD",
        "smtp_user": "ingesteld" if settings.SMTP_USER else "NIET INGESTELD",
    }


# ─────────────────────────────────────────────
# Web-chat (testen zonder WhatsApp/Twilio)
# ─────────────────────────────────────────────

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Web-based chat-interface voor demo en testing."""
    return templates.TemplateResponse(request, "chat.html", {})


@app.post("/chat/api/message")
async def chat_api_message(
    session_id: str = Form(...),
    message: str = Form(default=""),
    images: list[UploadFile] = File(default=[]),
):
    """
    Verwerk een bericht vanuit de web-chat interface.
    Accepteert optionele afbeeldingen als multipart-upload.
    """
    logger.info("POST /chat/api/message – session=%s msg=%r", session_id[:8], message[:80])

    if not settings.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY is niet geconfigureerd!")
        return JSONResponse(
            status_code=503,
            content={"response": "De bot is nog niet geconfigureerd (API-key ontbreekt). Neem contact op met de beheerder."},
        )

    db = next(get_db())

    img_content: list[dict] = []
    photo_filenames: list[str] = []

    for img_file in images:
        if not img_file or not img_file.filename:
            continue
        content = await img_file.read()
        if not content:
            continue
        media_type = (img_file.content_type or "image/jpeg").split(";")[0].strip()
        if media_type not in SUPPORTED_IMAGE_TYPES:
            return JSONResponse(
                status_code=400,
                content={"response": "Alleen JPG, PNG, GIF of WEBP-foto's kunnen worden verwerkt."},
            )
        b64 = base64.standard_b64encode(content).decode()
        img_content.append({"data": b64, "media_type": media_type})

        # Sla lokaal op voor het admin-dashboard
        os.makedirs("uploads", exist_ok=True)
        ext = "jpg" if "jpeg" in media_type else media_type.split("/")[-1]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"web_{session_id[:8]}_{ts}.{ext}"
        with open(os.path.join("uploads", filename), "wb") as f:
            f.write(content)
        photo_filenames.append(filename)

    # Gebruik het sessie-ID als 'telefoonnummer' voor de DB
    phone = f"web_{session_id}"

    try:
        from services.ai_service import process_message
        response = await process_message(
            phone=phone,
            message=message,
            images=img_content,
            db=db,
            photo_filenames=photo_filenames,
        )
        logger.info("Antwoord klaar – %d tekens", len(response))
        return {"response": response}
    except Exception as exc:
        logger.exception("Fout bij verwerken chatbericht: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"response": f"Er is een technische fout opgetreden: {type(exc).__name__}: {exc}"},
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

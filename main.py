"""
AutoGarage WhatsApp Chatbot – FastAPI applicatie

Endpoints:
  POST /webhook/whatsapp    – Twilio webhook voor inkomende berichten
  GET  /                    – Welkomstpagina
  GET  /admin               – Dashboard voor de garage (afsprakenoverzicht)
  GET  /admin/api/appointments           – JSON API voor afspraken
  PATCH /admin/api/appointments/{id}/status  – Status bijwerken
  POST /dev/test-message    – Lokaal testen zonder Twilio (alleen in debug-modus)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import get_db, init_db
from handlers.webhook_handler import handle_incoming_message
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

# Serveer geüploade foto's als statische bestanden
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")


# ─────────────────────────────────────────────
# WhatsApp Webhook
# ─────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=HTMLResponse)
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(default=""),
    NumMedia: int = Form(default=0),
    MediaUrl0: Optional[str] = Form(default=None),
    MediaUrl1: Optional[str] = Form(default=None),
    MediaUrl2: Optional[str] = Form(default=None),
    MediaContentType0: Optional[str] = Form(default=None),
    MediaContentType1: Optional[str] = Form(default=None),
    MediaContentType2: Optional[str] = Form(default=None),
):
    phone = From.replace("whatsapp:", "")

    media_urls: list[str] = []
    media_types: list[str] = []
    for url, mtype in [
        (MediaUrl0, MediaContentType0),
        (MediaUrl1, MediaContentType1),
        (MediaUrl2, MediaContentType2),
    ]:
        if url:
            media_urls.append(url)
            media_types.append(mtype or "image/jpeg")

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
        "admin.html",
        {
            "request": request,
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
    """Simuleer een inkomend WhatsApp-bericht (gebruik alleen lokaal)."""
    db = next(get_db())
    from services.ai_service import process_message
    response = await process_message(
        phone=phone,
        message=body,
        media_urls=[],
        media_types=[],
        db=db,
    )
    return {"phone": phone, "response": response}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AutoGarage WhatsApp Chatbot"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

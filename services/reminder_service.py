import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import now_local, settings
from database import SessionLocal
import models
from services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)

_DAGEN = {
    0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
    4: "vrijdag", 5: "zaterdag", 6: "zondag",
}


async def _check_and_send_reminders() -> None:
    """Controleer elke 30 minuten op afspraken die een herinnering nodig hebben."""
    db = SessionLocal()
    try:
        now = now_local()

        # 24-uurs herinnering: afspraken die over 23:30–24:30 uur beginnen
        window_24h_start = now + timedelta(hours=23, minutes=30)
        window_24h_end = now + timedelta(hours=24, minutes=30)

        for apt in _due_appointments(db, "reminder_24h_sent", window_24h_start, window_24h_end):
            if await _safe_send_reminder(apt, "24h"):
                apt.reminder_24h_sent = True
                db.commit()

        # 1-uurs herinnering: afspraken die over 45–75 minuten beginnen
        window_1h_start = now + timedelta(minutes=45)
        window_1h_end = now + timedelta(minutes=75)

        for apt in _due_appointments(db, "reminder_1h_sent", window_1h_start, window_1h_end):
            if await _safe_send_reminder(apt, "1h"):
                apt.reminder_1h_sent = True
                db.commit()

    finally:
        db.close()


def _due_appointments(db, flag: str, start: datetime, end: datetime) -> list[models.Appointment]:
    """Bevestigde afspraken in het tijdvak waarvoor de herinnering nog niet is verstuurd.

    Afspraken die via de web-chat zijn gemaakt (klant_telefoon begint met 'web_')
    hebben geen WhatsApp-nummer en krijgen geen herinnering.
    """
    column = getattr(models.Appointment, flag)
    return (
        db.query(models.Appointment)
        .filter(
            models.Appointment.status == "bevestigd",
            column.is_(False),
            models.Appointment.scheduled_datetime >= start,
            models.Appointment.scheduled_datetime <= end,
            ~models.Appointment.klant_telefoon.startswith("web_"),
        )
        .all()
    )


async def _safe_send_reminder(appointment: models.Appointment, soort: str) -> bool:
    """Verstuur één herinnering; een fout bij één afspraak stopt de rest niet."""
    try:
        await _send_reminder(appointment, soort)
        return True
    except Exception as exc:
        logger.error(
            "Herinnering (%s) voor afspraak #%s mislukt: %s", soort, appointment.id, exc
        )
        return False


async def _send_reminder(appointment: models.Appointment, soort: str) -> None:
    dag = _DAGEN[appointment.scheduled_datetime.weekday()]
    datum = appointment.scheduled_datetime.strftime("%d-%m-%Y")
    tijd = appointment.scheduled_datetime.strftime("%H:%M")
    auto = " ".join(
        filter(None, [appointment.auto_merk, appointment.auto_model, f"({appointment.kenteken})" if appointment.kenteken else ""])
    )

    if soort == "24h":
        bericht = (
            f"Goedendag {appointment.klant_naam}! 👋\n\n"
            f"Dit is een herinnering voor uw afspraak bij {settings.GARAGE_NAAM} "
            f"morgen {dag} {datum} om {tijd} uur.\n\n"
            f"Service: {appointment.service_type.replace('_', ' ').title()}\n"
            + (f"Auto: {auto}\n" if auto else "")
            + f"\n📍 {settings.GARAGE_ADRES}\n\n"
            f"Kunt u niet komen? Stuur dan een bericht om de afspraak te verplaatsen."
        )
    else:
        bericht = (
            f"Herinnering: uw afspraak bij {settings.GARAGE_NAAM} "
            f"begint over 1 uur om {tijd} uur. ⏰\n\n"
            f"📍 {settings.GARAGE_ADRES}\n\n"
            f"Tot straks!"
        )

    await send_whatsapp_message(appointment.klant_telefoon, bericht)
    logger.info("Herinnering (%s) verstuurd naar %s", soort, appointment.klant_telefoon)


def start_reminder_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _check_and_send_reminders,
        trigger="interval",
        minutes=30,
        id="reminder_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Herinnerings-scheduler gestart (elke 30 minuten)")
    return scheduler

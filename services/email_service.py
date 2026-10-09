import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

from config import settings

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=FileSystemLoader("templates"), autoescape=True)

# Nederlandse maand- en dagnamen voor de e-mailtemplate
_MAANDEN = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}
_DAGEN = {
    0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
    4: "vrijdag", 5: "zaterdag", 6: "zondag",
}


def _nl_date(dt) -> str:
    if not dt:
        return "-"
    return f"{_DAGEN[dt.weekday()]} {dt.day} {_MAANDEN[dt.month]} {dt.year}"


_jinja_env.filters["nl_date"] = _nl_date


async def send_confirmation_email(appointment) -> None:
    """Verstuur een bevestigingsmail naar de klant."""
    if not appointment.klant_email:
        return

    try:
        template = _jinja_env.get_template("email_confirmation.html")
        html = template.render(
            appointment=appointment,
            garage_naam=settings.GARAGE_NAAM,
            garage_adres=settings.GARAGE_ADRES,
            garage_telefoon=settings.GARAGE_TELEFOON,
            garage_email=settings.GARAGE_EMAIL,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Afspraakbevestiging – {settings.GARAGE_NAAM}"
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = appointment.klant_email
        msg.attach(MIMEText(html, "html"))

        await asyncio.to_thread(_smtp_send, msg)
        logger.info("Bevestigingsmail verstuurd naar %s", appointment.klant_email)
    except Exception as exc:
        logger.error("Fout bij versturen mail naar %s: %s", appointment.klant_email, exc)


def _smtp_send(msg: MIMEMultipart) -> None:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)

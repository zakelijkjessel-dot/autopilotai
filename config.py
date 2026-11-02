from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # E-mail
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # Garage
    GARAGE_NAAM: str = "AutoGarage Nederland"
    GARAGE_ADRES: str = "Hoofdstraat 1, 1234 AB Amsterdam"
    GARAGE_TELEFOON: str = "+31 20 123 4567"
    GARAGE_EMAIL: str = "info@autogarage.nl"

    # App
    DATABASE_URL: str = "sqlite:///./garage.db"
    BASE_URL: str = "http://localhost:8000"

    # Tijdzone van de garage: afspraken en herinneringen gebruiken lokale tijd
    TIMEZONE: str = "Europe/Amsterdam"

    # Claude-model dat de bot gebruikt
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Dev-routes (/debug en /dev/test-message) alleen lokaal aanzetten
    ENABLE_DEV_ROUTES: bool = False

    # Web-chat (/chat) alleen aanzetten voor lokaal testen of een demo
    ENABLE_WEB_CHAT: bool = False

    # Admin-dashboard: basic-auth. Zonder ADMIN_PASSWORD is het dashboard uitgeschakeld.
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def now_local() -> datetime:
    """Huidige lokale tijd van de garage, naive zoals opgeslagen in de database."""
    return datetime.now(ZoneInfo(settings.TIMEZONE)).replace(tzinfo=None)

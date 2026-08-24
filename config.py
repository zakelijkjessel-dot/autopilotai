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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

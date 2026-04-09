from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.sql import func

from database import Base


class Conversation(Base):
    """Slaat de gespreksgeschiedenis per telefoonnummer op."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    # Lijst van {"role": "user"|"assistant", "content": "..."}
    messages = Column(JSON, default=list)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Appointment(Base):
    """Afspraak met alle bijbehorende auto- en serviceinformatie."""

    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)

    # Klantgegevens
    klant_naam = Column(String(100), nullable=False)
    klant_telefoon = Column(String(20), nullable=False, index=True)
    klant_email = Column(String(100))

    # Autogegevens
    auto_merk = Column(String(50))
    auto_model = Column(String(50))
    bouwjaar = Column(Integer)
    kenteken = Column(String(20))

    # Service
    service_type = Column(String(50), nullable=False)
    probleem_omschrijving = Column(Text)
    foto_paths = Column(JSON, default=list)  # bestandsnamen in /uploads

    # Planning
    scheduled_datetime = Column(DateTime, nullable=False)
    duur_minuten = Column(Integer, default=60)

    # Prijs
    prijs_min = Column(Float)
    prijs_max = Column(Float)

    # Status & notities voor monteur
    status = Column(String(20), default="bevestigd")  # bevestigd | geannuleerd | voltooid
    ai_notities = Column(Text)

    # Herinneringen
    reminder_24h_sent = Column(Boolean, default=False)
    reminder_1h_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

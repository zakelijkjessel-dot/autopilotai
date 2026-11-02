"""Herinneringen: één fout stopt niet de rest, web-afspraken krijgen geen WhatsApp."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

import models
from config import now_local
from services import reminder_service


def _apt(db, telefoon, minuten, naam):
    apt = models.Appointment(
        klant_naam=naam, klant_telefoon=telefoon, service_type="apk",
        scheduled_datetime=now_local() + timedelta(minutes=minuten),
        duur_minuten=60, status="bevestigd",
    )
    db.add(apt)
    db.commit()
    db.refresh(apt)
    return apt


async def test_mislukte_verzending_stopt_de_rest_niet(db, monkeypatch):
    eerste = _apt(db, "+31600000001", 60, "Eerste")
    tweede = _apt(db, "+31600000002", 60, "Tweede")

    calls = []

    async def send(to, body):
        calls.append(to)
        if to == "+31600000001":
            raise RuntimeError("Twilio down")

    monkeypatch.setattr(reminder_service, "send_whatsapp_message", send)
    await reminder_service._check_and_send_reminders()

    db.refresh(eerste)
    db.refresh(tweede)
    assert eerste.reminder_1h_sent is False, "mislukte herinnering mag niet als verstuurd gelden"
    assert tweede.reminder_1h_sent is True, "de tweede afspraak moet alsnog een herinnering krijgen"
    assert calls == ["+31600000001", "+31600000002"]


async def test_web_afspraken_krijgen_geen_whatsapp_herinnering(db, monkeypatch):
    web = _apt(db, "web_abc123", 60, "Web")
    send = AsyncMock()
    monkeypatch.setattr(reminder_service, "send_whatsapp_message", send)
    await reminder_service._check_and_send_reminders()
    send.assert_not_awaited()
    db.refresh(web)
    assert web.reminder_1h_sent is False


async def test_herinnering_wordt_niet_dubbel_verstuurd(db, monkeypatch):
    _apt(db, "+31600000001", 60, "Eén")
    send = AsyncMock()
    monkeypatch.setattr(reminder_service, "send_whatsapp_message", send)
    await reminder_service._check_and_send_reminders()
    await reminder_service._check_and_send_reminders()
    assert send.await_count == 1

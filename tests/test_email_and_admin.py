"""Bevestigingsmail (template-rendering, SMTP gemockt) en admin-statusendpoint."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
import models
from config import settings
from services import email_service


def _apt(**kw):
    base = dict(
        id=7, klant_naam="Jan Test", klant_telefoon="+31600000001", klant_email="jan@example.com",
        auto_merk="Volkswagen", auto_model="Golf", bouwjaar=2015, kenteken="AB-123-C",
        service_type="apk", probleem_omschrijving="APK",
        scheduled_datetime=datetime(2030, 3, 4, 10, 0), duur_minuten=60,
        prijs_min=45.0, prijs_max=55.0, ai_notities=None,
    )
    base.update(kw)
    return models.Appointment(**base)


async def test_bevestigingsmail_wordt_gerenderd_en_verstuurd(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_USER", "garage@example.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "x")
    sent = {}

    def fake_smtp_send(msg):
        sent["msg"] = msg

    monkeypatch.setattr(email_service, "_smtp_send", fake_smtp_send)
    await email_service.send_confirmation_email(_apt())

    msg = sent["msg"]
    assert msg["To"] == "jan@example.com"
    assert "Afspraakbevestiging" in msg["Subject"]
    html = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
    assert "Jan Test" in html and "AB-123-C" in html and "€45" in html and "#7" in html


async def test_geen_mail_zonder_emailadres(monkeypatch):
    smtp = MagicMock()
    monkeypatch.setattr(email_service, "_smtp_send", smtp)
    await email_service.send_confirmation_email(_apt(klant_email=None))
    smtp.assert_not_called()


async def test_smtp_fout_wordt_gelogd_en_gooit_niet(monkeypatch):
    def boom(msg):
        raise OSError("SMTP down")
    monkeypatch.setattr(email_service, "_smtp_send", boom)
    await email_service.send_confirmation_email(_apt())  # mag niet crashen


def test_admin_status_wijzigen(db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "geheim")
    auth = ("admin", "geheim")
    apt = _apt(id=None, scheduled_datetime=datetime.now() + timedelta(days=3), status="bevestigd")
    db.add(apt)
    db.commit()
    db.refresh(apt)
    with TestClient(main.app) as c:
        r = c.patch(f"/admin/api/appointments/{apt.id}/status", params={"status": "voltooid"}, auth=auth)
        assert r.status_code == 200
        r = c.patch(f"/admin/api/appointments/{apt.id}/status", params={"status": "onzin"}, auth=auth)
        assert r.status_code == 400
        rows = c.get("/admin/api/appointments", auth=auth).json()
    assert rows[0]["status"] == "voltooid"
    assert "klant_telefoon" in rows[0]

"""Boekingslogica: openingstijden, dubbel boeken, verplaatsen en annuleren."""
from datetime import datetime, timedelta

import pytest

from config import now_local
from services import ai_service


def _next_weekday(days_ahead: int = 14):
    d = now_local().date() + timedelta(days=days_ahead)
    while d.weekday() >= 5:  # ma–vr voor de hoofdtests
        d += timedelta(days=1)
    return d


def _args(datum, tijd, duur=60, naam="Jan Test"):
    return {
        "klant_naam": naam,
        "klant_email": "jan@example.com",
        "auto_merk": "Volkswagen",
        "auto_model": "Golf",
        "bouwjaar": 2015,
        "kenteken": "ab-123-c",
        "service_type": "apk",
        "probleem_omschrijving": "APK",
        "datum": datum,
        "tijd": tijd,
        "duur_minuten": duur,
        "prijs_min": 45,
        "prijs_max": 55,
    }


def test_vrij_tijdstip_is_beschikbaar(db):
    d = _next_weekday().isoformat()
    result = ai_service._check_availability({"datum": d, "tijd": "10:00"}, db)
    assert "beschikbaar" in result and "bezet" not in result


def test_boeking_maakt_afspraak_aan(db):
    d = _next_weekday().isoformat()
    text, apt = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    assert apt is not None and apt.id is not None
    assert apt.scheduled_datetime == datetime.strptime(f"{d} 10:00", "%Y-%m-%d %H:%M")
    assert apt.kenteken == "AB-123-C"
    assert "geboekt" in text


def test_dubbele_boeking_wordt_geweigerd_server_side(db):
    d = _next_weekday().isoformat()
    ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    text, apt = ai_service._book_appointment(_args(d, "10:00", naam="Piet"), "+31600000002", db)
    assert apt is None
    assert "NIET geboekt" in text and "bezet" in text
    assert db.query(ai_service.models.Appointment).count() == 1


def test_overlappende_boeking_wordt_geweigerd(db):
    d = _next_weekday().isoformat()
    ai_service._book_appointment(_args(d, "10:00", duur=60), "+31600000001", db)
    _, apt = ai_service._book_appointment(_args(d, "10:30", duur=60), "+31600000002", db)
    assert apt is None


def test_zondag_is_gesloten(db):
    d = now_local().date() + timedelta(days=14)
    while d.weekday() != 6:
        d += timedelta(days=1)
    text, apt = ai_service._book_appointment(_args(d.isoformat(), "10:00"), "+31600000001", db)
    assert apt is None and "zondag" in text


def test_buiten_openingstijden_wordt_geweigerd(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "07:00"), "+31600000001", db)
    assert apt is None
    _, apt = ai_service._book_appointment(_args(d, "17:00", duur=90), "+31600000001", db)
    assert apt is None, "dienst die na sluiting eindigt moet geweigerd worden"


def test_zaterdag_sluit_om_13_uur(db):
    d = now_local().date() + timedelta(days=14)
    while d.weekday() != 5:
        d += timedelta(days=1)
    _, apt = ai_service._book_appointment(_args(d.isoformat(), "12:30", duur=60), "+31600000001", db)
    assert apt is None
    _, apt = ai_service._book_appointment(_args(d.isoformat(), "09:00", duur=60), "+31600000001", db)
    assert apt is not None


def test_verleden_wordt_geweigerd(db):
    d = (now_local() - timedelta(days=3)).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    _, apt = ai_service._book_appointment(_args(d.isoformat(), "10:00"), "+31600000001", db)
    assert apt is None


def test_annuleren_maakt_tijdstip_weer_vrij(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    ai_service._cancel_appointment({"afspraak_id": apt.id}, "+31600000001", db)
    assert "beschikbaar" in ai_service._check_availability({"datum": d, "tijd": "10:00"}, db)


def test_verplaatsen_naar_bezet_tijdstip_wordt_geweigerd(db):
    d = _next_weekday().isoformat()
    _, a1 = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    _, a2 = ai_service._book_appointment(_args(d, "13:00", naam="Piet"), "+31600000001", db)
    result = ai_service._reschedule_appointment(
        {"afspraak_id": a2.id, "nieuwe_datum": d, "nieuwe_tijd": "10:00"}, "+31600000001", db
    )
    assert "niet verplaatst" in result and "bezet" in result
    db.refresh(a2)
    assert a2.scheduled_datetime.hour == 13


def test_verplaatsen_naar_vrij_tijdstip_werkt(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    result = ai_service._reschedule_appointment(
        {"afspraak_id": apt.id, "nieuwe_datum": d, "nieuwe_tijd": "14:00"}, "+31600000001", db
    )
    assert "verplaatst" in result
    db.refresh(apt)
    assert apt.scheduled_datetime.hour == 14


def test_verplaatsen_binnen_eigen_tijdvak_mag(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "10:00", duur=60), "+31600000001", db)
    result = ai_service._reschedule_appointment(
        {"afspraak_id": apt.id, "nieuwe_datum": d, "nieuwe_tijd": "10:30"}, "+31600000001", db
    )
    assert "verplaatst" in result


def test_geannuleerde_afspraak_kan_niet_verplaatst(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    ai_service._cancel_appointment({"afspraak_id": apt.id}, "+31600000001", db)
    result = ai_service._reschedule_appointment(
        {"afspraak_id": apt.id, "nieuwe_datum": d, "nieuwe_tijd": "14:00"}, "+31600000001", db
    )
    assert "kan niet verplaatst" in result


def test_andere_klant_kan_niet_annuleren(db):
    d = _next_weekday().isoformat()
    _, apt = ai_service._book_appointment(_args(d, "10:00"), "+31600000001", db)
    result = ai_service._cancel_appointment({"afspraak_id": apt.id}, "+31699999999", db)
    assert "niet gevonden" in result
    db.refresh(apt)
    assert apt.status == "bevestigd"

"""Agentic loop met een nep-Claude-client: boeken via tools, foto's, model."""
import types
from unittest.mock import AsyncMock

import pytest

from config import settings, now_local
from services import ai_service


class ScriptedClient:
    """Geeft per aanroep het volgende antwoord uit het script terug en onthoudt de aanroepen."""

    def __init__(self, steps):
        self.steps = steps
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return types.SimpleNamespace(content=content, stop_reason=stop)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _tool(id_, name, inp):
    return types.SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


@pytest.fixture()
def email_mock(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(ai_service, "send_confirmation_email", mock)
    return mock


@pytest.fixture()
def fake_claude(monkeypatch):
    def install(steps):
        client = ScriptedClient(steps)
        monkeypatch.setattr(ai_service, "_async_client", client)
        return client
    return install


async def test_volledige_boekingsflow_via_tools(db, fake_claude, email_mock, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    d = (now_local().date().toordinal() + 14)
    import datetime as dt
    datum = dt.date.fromordinal(d)
    while datum.weekday() >= 5:
        datum += dt.timedelta(days=1)
    datum = datum.isoformat()

    client = fake_claude([
        [_tool("t1", "controleer_beschikbaarheid", {"datum": datum, "tijd": "10:00"})],
        [_tool("t2", "boek_afspraak", {
            "klant_naam": "Jan", "klant_email": "jan@example.com", "service_type": "apk",
            "datum": datum, "tijd": "10:00", "duur_minuten": 60, "prijs_min": 45, "prijs_max": 55,
        })],
        [_text("Uw APK-afspraak staat gepland.")],
    ])
    reply = await ai_service.process_message("+31600000001", "Ik wil een APK", [], db)

    assert reply == "Uw APK-afspraak staat gepland."
    assert len(client.calls) == 3
    assert client.calls[0]["model"] == settings.ANTHROPIC_MODEL
    apts = db.query(ai_service.models.Appointment).all()
    assert len(apts) == 1 and apts[0].service_type == "apk"
    email_mock.assert_awaited_once()


async def test_ai_die_beschikbaarheid_overslaat_boekt_nog_steeds_niet_dubbel(db, fake_claude, email_mock, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    import datetime as dt
    datum = now_local().date() + dt.timedelta(days=14)
    while datum.weekday() >= 5:
        datum += dt.timedelta(days=1)
    datum = datum.isoformat()
    args = {"klant_naam": "Jan", "klant_email": "j@x.nl", "service_type": "apk",
            "datum": datum, "tijd": "10:00"}

    fake_claude([
        [_tool("a", "boek_afspraak", args)],
        [_tool("b", "boek_afspraak", {**args, "klant_naam": "Piet"})],
        [_text("Helaas, dat tijdstip is al bezet.")],
    ])
    await ai_service.process_message("+31600000001", "boek", [], db)
    assert db.query(ai_service.models.Appointment).count() == 1
    email_mock.assert_awaited_once()  # alleen voor de echte boeking


async def test_foto_s_komen_bij_de_juiste_afspraak(db, fake_claude, email_mock, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    import datetime as dt
    datum = now_local().date() + dt.timedelta(days=14)
    while datum.weekday() >= 5:
        datum += dt.timedelta(days=1)

    # Oudere afspraak van dezelfde klant met eigen foto
    oud = ai_service.models.Appointment(
        klant_naam="Jan", klant_telefoon="+31600000001", service_type="apk",
        scheduled_datetime=datetime_at(datum, 9), duur_minuten=60, status="voltooid",
        foto_paths=["oud.jpg"],
    )
    db.add(oud)
    db.commit()

    fake_claude([
        [_tool("a", "boek_afspraak", {
            "klant_naam": "Jan", "klant_email": "j@x.nl", "service_type": "banden",
            "datum": datum.isoformat(), "tijd": "14:00",
        })],
        [_text("Afspraak gepland.")],
    ])
    await ai_service.process_message("+31600000001", "banden", [], db, photo_filenames=["nieuw.jpg"])

    nieuw = db.query(ai_service.models.Appointment).filter_by(service_type="banden").one()
    db.refresh(oud)
    assert nieuw.foto_paths == ["nieuw.jpg"]
    assert oud.foto_paths == ["oud.jpg"], "oude afspraak mag niet overschreven worden"


def datetime_at(d, hour):
    import datetime as dt
    return dt.datetime.combine(d, dt.time(hour, 0))


async def test_zonder_api_key_geeft_duidelijke_fout(db, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(ai_service, "_async_client", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await ai_service.process_message("+31600000001", "hoi", [], db)

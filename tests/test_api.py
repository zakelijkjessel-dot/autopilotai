"""HTTP-endpoints: pagina's, web-chat, Twilio-webhook en dev-routes."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import main
from config import settings


@pytest.fixture()
def client(db):
    with TestClient(main.app) as c:
        yield c


def test_health_en_pagina_s(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_WEB_CHAT", True)
    assert client.get("/health").status_code == 200
    assert client.get("/chat").status_code == 200
    assert client.get("/").status_code == 200


def test_web_chat_is_standaard_uit(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_WEB_CHAT", False)
    assert client.get("/chat").status_code == 404
    assert client.post("/chat/api/message", data={"session_id": "s1", "message": "hoi"}).status_code == 404


def test_chat_zonder_api_key_geeft_503(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_WEB_CHAT", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    r = client.post("/chat/api/message", data={"session_id": "s1", "message": "hoi"})
    assert r.status_code == 503


def test_chat_weigert_pdf_upload(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_WEB_CHAT", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test")
    r = client.post(
        "/chat/api/message",
        data={"session_id": "s1", "message": "kijk hier"},
        files={"images": ("rapport.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400


def test_debug_en_dev_routes_zijn_standaard_uit(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_DEV_ROUTES", False)
    assert client.get("/debug").status_code == 404
    assert client.post("/dev/test-message", params={"phone": "+31600000001", "body": "hoi"}).status_code == 404


def test_debug_toont_geen_api_key_fragment(client, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_DEV_ROUTES", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-SECRETVALUE1234")
    body = client.get("/debug").text
    assert "SECRETVALUE" not in body and "sk-ant" not in body


@pytest.fixture()
def webhook_mock(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(main, "handle_incoming_message", mock)
    return mock


def test_webhook_met_geldige_handtekening(client, monkeypatch, webhook_mock):
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "geheim")
    monkeypatch.setattr(settings, "BASE_URL", "https://garage.example.com")
    params = {"From": "whatsapp:+31611111111", "Body": "Hoi"}
    url = "https://garage.example.com/webhook/whatsapp"
    sig = RequestValidator("geheim").compute_signature(url, params)
    r = client.post("/webhook/whatsapp", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200
    assert webhook_mock.call_count == 1
    assert webhook_mock.call_args.kwargs["phone"] == "+31611111111"


def test_webhook_weigert_ongeldige_handtekening(client, monkeypatch, webhook_mock):
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "geheim")
    monkeypatch.setattr(settings, "BASE_URL", "https://garage.example.com")
    r = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+31611111111", "Body": "Hoi"},
        headers={"X-Twilio-Signature": "nep"},
    )
    assert r.status_code == 403
    webhook_mock.assert_not_awaited()


async def test_handler_slaat_pdf_media_over(monkeypatch):
    from handlers import webhook_handler

    download = AsyncMock()
    process = AsyncMock(return_value="ok")
    send = AsyncMock()
    monkeypatch.setattr(webhook_handler, "_download_twilio_image", download)
    monkeypatch.setattr(webhook_handler, "process_message", process)
    monkeypatch.setattr(webhook_handler, "send_whatsapp_message", send)

    await webhook_handler.handle_incoming_message(
        phone="+31611111111",
        message="zie bijlage",
        media_urls=["https://api.twilio.com/x.pdf"],
        media_types=["application/pdf"],
    )
    download.assert_not_called()
    assert process.call_args.kwargs["images"] == []
    send.assert_awaited()


def test_admin_zonder_wachtwoord_is_uitgeschakeld(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    assert client.get("/admin").status_code == 503
    assert client.get("/admin/api/appointments").status_code == 503


def test_admin_vereist_inloggen(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "goed-wachtwoord")
    assert client.get("/admin").status_code == 401
    assert client.get("/admin/api/appointments").status_code == 401
    assert client.get("/admin/api/appointments", auth=("admin", "fout")).status_code == 401
    assert client.get("/admin/api/appointments", auth=("admin", "goed-wachtwoord")).status_code == 200
    assert client.get("/admin", auth=("admin", "goed-wachtwoord")).status_code == 200
    r = client.patch("/admin/api/appointments/1/status", params={"status": "voltooid"})
    assert r.status_code == 401

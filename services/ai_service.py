"""
AI-service: beheert de conversatie met Claude en voert tool-calls uit.
Elke functie die een tool uitvoert is puur synchroon (snelle SQLite-queries).
De top-level `process_message` is async zodat e-mail en WhatsApp niet blokkeren.
"""

import base64
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import anthropic
import requests
from sqlalchemy.orm import Session

import models
from config import settings
from database import SessionLocal
from prompts.system_prompt import get_system_prompt
from services.email_service import send_confirmation_email

logger = logging.getLogger(__name__)

_async_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MAX_HISTORY = 20  # maximaal aantal berichten dat we bewaren

# ─────────────────────────────────────────────
# Tool-definities voor Claude
# ─────────────────────────────────────────────
TOOLS: list[dict] = [
    {
        "name": "controleer_beschikbaarheid",
        "description": (
            "Controleer of een datum en tijd beschikbaar is voor een afspraak. "
            "Gebruik dit ALTIJD vóór het boeken."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "datum": {"type": "string", "description": "YYYY-MM-DD"},
                "tijd": {"type": "string", "description": "HH:MM"},
                "duur_minuten": {"type": "integer", "description": "Duur in minuten (standaard 60)", "default": 60},
            },
            "required": ["datum", "tijd"],
        },
    },
    {
        "name": "boek_afspraak",
        "description": "Boek een nieuwe afspraak in het systeem. Controleer eerst de beschikbaarheid.",
        "input_schema": {
            "type": "object",
            "properties": {
                "klant_naam": {"type": "string"},
                "klant_email": {"type": "string"},
                "auto_merk": {"type": "string"},
                "auto_model": {"type": "string"},
                "bouwjaar": {"type": "integer"},
                "kenteken": {"type": "string"},
                "service_type": {
                    "type": "string",
                    "enum": [
                        "apk", "kleine_beurt", "grote_beurt", "apk_kleine_beurt",
                        "banden", "remmen_voor", "remmen_achter",
                        "diagnose", "schade", "overig",
                    ],
                },
                "probleem_omschrijving": {"type": "string"},
                "datum": {"type": "string", "description": "YYYY-MM-DD"},
                "tijd": {"type": "string", "description": "HH:MM"},
                "duur_minuten": {"type": "integer"},
                "prijs_min": {"type": "number"},
                "prijs_max": {"type": "number"},
                "ai_notities": {"type": "string", "description": "Notities voor de monteur"},
            },
            "required": ["klant_naam", "klant_email", "service_type", "datum", "tijd"],
        },
    },
    {
        "name": "haal_afspraken_op",
        "description": "Haal alle actieve afspraken op voor de huidige klant (op basis van telefoonnummer).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "annuleer_afspraak",
        "description": "Annuleer een bestaande afspraak van de huidige klant.",
        "input_schema": {
            "type": "object",
            "properties": {
                "afspraak_id": {"type": "integer"},
                "reden": {"type": "string"},
            },
            "required": ["afspraak_id"],
        },
    },
    {
        "name": "verplaats_afspraak",
        "description": "Verplaats een bestaande afspraak naar een nieuwe datum en tijd.",
        "input_schema": {
            "type": "object",
            "properties": {
                "afspraak_id": {"type": "integer"},
                "nieuwe_datum": {"type": "string", "description": "YYYY-MM-DD"},
                "nieuwe_tijd": {"type": "string", "description": "HH:MM"},
            },
            "required": ["afspraak_id", "nieuwe_datum", "nieuwe_tijd"],
        },
    },
]

# ─────────────────────────────────────────────
# Hulpfuncties – media downloaden
# ─────────────────────────────────────────────

def _download_as_base64(url: str) -> tuple[str, str]:
    """Download media van Twilio en geef (base64_data, media_type) terug."""
    resp = requests.get(
        url,
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    resp.raise_for_status()
    media_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    data = base64.standard_b64encode(resp.content).decode()
    return data, media_type


def _save_image(url: str, phone: str, index: int) -> tuple[str, str]:
    """Sla een afbeelding op in /uploads en geef (bestandsnaam, media_type) terug."""
    os.makedirs("uploads", exist_ok=True)
    resp = requests.get(
        url,
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    resp.raise_for_status()
    media_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    ext = "jpg" if "jpeg" in media_type else media_type.split("/")[-1]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{phone.replace('+', '')}_{ts}_{index}.{ext}"
    with open(os.path.join("uploads", filename), "wb") as f:
        f.write(resp.content)
    return filename, media_type


# ─────────────────────────────────────────────
# Tool-uitvoering (synchroon)
# ─────────────────────────────────────────────

def _check_availability(args: dict, db: Session) -> str:
    datum, tijd = args["datum"], args["tijd"]
    duur = int(args.get("duur_minuten") or 60)
    try:
        dt = datetime.strptime(f"{datum} {tijd}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "Ongeldige datum- of tijdnotatie. Gebruik YYYY-MM-DD en HH:MM."

    wd = dt.weekday()
    if wd == 6:
        return "De garage is op zondag gesloten. Kies een andere dag."
    if wd == 5 and (dt.hour < 8 or dt.hour >= 13):
        return "Op zaterdag zijn we open van 08:00–13:00. Kies een tijd binnen deze uren."
    if wd < 5 and (dt.hour < 8 or (dt.hour == 17 and dt.minute > 30) or dt.hour >= 18):
        return "Op werkdagen zijn we open van 08:00–17:30. Kies een tijd binnen deze uren."
    if dt < datetime.now():
        return "Dit tijdstip ligt in het verleden. Kies een toekomstige datum."

    end_dt = dt + timedelta(minutes=duur)
    existing = db.query(models.Appointment).filter(
        models.Appointment.status == "bevestigd",
        models.Appointment.scheduled_datetime < end_dt,
    ).all()

    conflicts = [a for a in existing if (a.scheduled_datetime + timedelta(minutes=a.duur_minuten or 60)) > dt]
    if not conflicts:
        return f"Het tijdstip {tijd} op {datum} is beschikbaar voor een afspraak van {duur} minuten."

    # Zoek alternatieven
    alts: list[str] = []
    for offset in [30, 60, 90, 120, 150, -30, -60]:
        alt = dt + timedelta(minutes=offset)
        alt_end = alt + timedelta(minutes=duur)
        aw = alt.weekday()
        if aw == 6:
            continue
        if aw == 5 and (alt.hour < 8 or alt.hour >= 13):
            continue
        if aw < 5 and (alt.hour < 8 or alt.hour >= 18):
            continue
        if alt < datetime.now():
            continue
        overlap = [
            a for a in db.query(models.Appointment).filter(
                models.Appointment.status == "bevestigd",
                models.Appointment.scheduled_datetime < alt_end,
            ).all()
            if (a.scheduled_datetime + timedelta(minutes=a.duur_minuten or 60)) > alt
        ]
        if not overlap:
            alts.append(alt.strftime("%H:%M"))
        if len(alts) >= 3:
            break

    alts_str = ", ".join(alts) if alts else "geen vrije tijden op deze dag"
    return (
        f"Het tijdstip {tijd} op {datum} is helaas bezet. "
        f"Beschikbare alternatieven op {datum}: {alts_str}."
    )


def _book_appointment(args: dict, phone: str, db: Session) -> tuple[str, Optional[models.Appointment]]:
    try:
        dt = datetime.strptime(f"{args['datum']} {args['tijd']}", "%Y-%m-%d %H:%M")
    except (ValueError, KeyError):
        return "Ongeldige datum of tijd. Gebruik YYYY-MM-DD en HH:MM.", None

    apt = models.Appointment(
        klant_naam=args["klant_naam"],
        klant_telefoon=phone,
        klant_email=args.get("klant_email"),
        auto_merk=args.get("auto_merk"),
        auto_model=args.get("auto_model"),
        bouwjaar=args.get("bouwjaar"),
        kenteken=(args.get("kenteken") or "").upper() or None,
        service_type=args["service_type"],
        probleem_omschrijving=args.get("probleem_omschrijving"),
        foto_paths=[],
        scheduled_datetime=dt,
        duur_minuten=int(args.get("duur_minuten") or 60),
        prijs_min=args.get("prijs_min"),
        prijs_max=args.get("prijs_max"),
        status="bevestigd",
        ai_notities=args.get("ai_notities"),
        reminder_24h_sent=False,
        reminder_1h_sent=False,
    )
    db.add(apt)
    db.commit()
    db.refresh(apt)

    _DAGEN = {0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
               4: "vrijdag", 5: "zaterdag", 6: "zondag"}
    dag = _DAGEN[dt.weekday()]
    result = (
        f"Afspraak #{apt.id} succesvol geboekt!\n"
        f"Datum: {dag} {dt.strftime('%d-%m-%Y')} om {dt.strftime('%H:%M')} uur\n"
        f"Service: {apt.service_type.replace('_', ' ').title()}\n"
        f"Geschatte duur: ±{apt.duur_minuten} minuten\n"
    )
    if apt.prijs_min and apt.prijs_max:
        result += f"Prijsindicatie: €{apt.prijs_min:.0f} – €{apt.prijs_max:.0f}\n"
    if apt.klant_email:
        result += f"Bevestigingsmail wordt verstuurd naar {apt.klant_email}\n"

    return result, apt


def _get_appointments(phone: str, db: Session) -> str:
    apts = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.klant_telefoon == phone,
            models.Appointment.status == "bevestigd",
        )
        .order_by(models.Appointment.scheduled_datetime)
        .all()
    )
    if not apts:
        return "Er zijn geen actieve afspraken gevonden voor uw telefoonnummer."

    _DAGEN = {0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
               4: "vrijdag", 5: "zaterdag", 6: "zondag"}
    lines = [f"Uw afspraken ({len(apts)}):\n"]
    for a in apts:
        dag = _DAGEN[a.scheduled_datetime.weekday()]
        auto = " ".join(filter(None, [a.auto_merk, a.auto_model, f"({a.kenteken})" if a.kenteken else ""]))
        lines.append(
            f"Afspraak #{a.id}\n"
            f"  {dag} {a.scheduled_datetime.strftime('%d-%m-%Y')} om {a.scheduled_datetime.strftime('%H:%M')}\n"
            f"  Service: {a.service_type.replace('_', ' ').title()}\n"
            + (f"  Auto: {auto}\n" if auto else "")
        )
    return "\n".join(lines)


def _cancel_appointment(args: dict, phone: str, db: Session) -> str:
    apt = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.id == args["afspraak_id"],
            models.Appointment.klant_telefoon == phone,
        )
        .first()
    )
    if not apt:
        return f"Afspraak #{args['afspraak_id']} niet gevonden voor uw telefoonnummer."
    if apt.status == "geannuleerd":
        return f"Afspraak #{args['afspraak_id']} is al eerder geannuleerd."

    apt.status = "geannuleerd"
    db.commit()
    return f"Afspraak #{args['afspraak_id']} is geannuleerd. Kan ik u verder helpen?"


def _reschedule_appointment(args: dict, phone: str, db: Session) -> str:
    apt = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.id == args["afspraak_id"],
            models.Appointment.klant_telefoon == phone,
        )
        .first()
    )
    if not apt:
        return f"Afspraak #{args['afspraak_id']} niet gevonden voor uw telefoonnummer."

    try:
        nieuwe_dt = datetime.strptime(f"{args['nieuwe_datum']} {args['nieuwe_tijd']}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "Ongeldige datum of tijd. Gebruik YYYY-MM-DD en HH:MM."

    apt.scheduled_datetime = nieuwe_dt
    apt.reminder_24h_sent = False
    apt.reminder_1h_sent = False
    db.commit()

    _DAGEN = {0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
               4: "vrijdag", 5: "zaterdag", 6: "zondag"}
    dag = _DAGEN[nieuwe_dt.weekday()]
    return (
        f"Afspraak #{apt.id} is verplaatst naar "
        f"{dag} {nieuwe_dt.strftime('%d-%m-%Y')} om {nieuwe_dt.strftime('%H:%M')} uur."
    )


def _execute_tool(name: str, tool_input: dict, phone: str, db: Session) -> tuple[str, Optional[models.Appointment]]:
    """Voer een tool uit en geef (tekst_resultaat, optionele_afspraak) terug."""
    if name == "controleer_beschikbaarheid":
        return _check_availability(tool_input, db), None
    if name == "boek_afspraak":
        return _book_appointment(tool_input, phone, db)
    if name == "haal_afspraken_op":
        return _get_appointments(phone, db), None
    if name == "annuleer_afspraak":
        return _cancel_appointment(tool_input, phone, db), None
    if name == "verplaats_afspraak":
        return _reschedule_appointment(tool_input, phone, db), None
    return f"Onbekende tool: {name}", None


# ─────────────────────────────────────────────
# Conversatiegeschiedenis – hulpfuncties
# ─────────────────────────────────────────────

def _get_or_create_conversation(phone: str, db: Session) -> models.Conversation:
    conv = db.query(models.Conversation).filter(
        models.Conversation.phone_number == phone
    ).first()
    if not conv:
        conv = models.Conversation(phone_number=phone, messages=[])
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def _strip_images_from_history(history: list[dict]) -> list[dict]:
    """Vervang afbeeldingen in opgeslagen berichten door een placeholder (ruimtebesparing)."""
    result = []
    for msg in history:
        content = msg["content"]
        if isinstance(content, list):
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image":
                    new_content.append({"type": "text", "text": "[eerder gestuurde foto]"})
                else:
                    new_content.append(block)
            result.append({"role": msg["role"], "content": new_content})
        else:
            result.append(msg)
    return result


def _attach_photos(phone: str, filenames: list[str], db: Session) -> None:
    """Koppel foto-bestandsnamen aan de meest recent aangemaakte afspraak."""
    apt = (
        db.query(models.Appointment)
        .filter(models.Appointment.klant_telefoon == phone)
        .order_by(models.Appointment.created_at.desc())
        .first()
    )
    if apt:
        apt.foto_paths = filenames
        db.commit()


# ─────────────────────────────────────────────
# Hoofd-entrypoint
# ─────────────────────────────────────────────

async def process_message(
    phone: str,
    message: str,
    media_urls: list[str],
    media_types: list[str],
    db: Session,
) -> str:
    """
    Verwerk een inkomend WhatsApp-bericht:
    1. Bouw het berichtinhoud op (tekst + eventuele foto's)
    2. Voer de Claude agentic loop uit (inclusief tool-calls)
    3. Sla de bijgewerkte conversatiegeschiedenis op
    4. Stuur bevestigingsmails voor nieuwe afspraken
    5. Geef de uiteindelijke assistent-reactie terug
    """
    conv = _get_or_create_conversation(phone, db)
    history = list(conv.messages or [])

    # ── Bouw gebruikerscontent ──
    user_content: list[dict] = []
    saved_filenames: list[str] = []

    for i, (url, mtype) in enumerate(zip(media_urls, media_types)):
        try:
            b64, actual_type = _download_as_base64(url)
            user_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": actual_type, "data": b64},
            })
            filename, _ = _save_image(url, phone, i)
            saved_filenames.append(filename)
        except Exception as exc:
            logger.warning("Kon afbeelding %s niet laden: %s", url, exc)

    if message.strip():
        user_content.append({"type": "text", "text": message})
    elif not user_content:
        user_content = [{"type": "text", "text": "(leeg bericht)"}]

    # ── Bereid API-berichten voor ──
    messages: list[dict] = _strip_images_from_history(history) + [
        {"role": "user", "content": user_content}
    ]

    # ── Agentic loop ──
    booked_appointments: list[models.Appointment] = []
    final_text = ""

    for _ in range(6):  # max 6 rondes (tool-chains)
        response = await _async_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=get_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        # Verzamel tekst + tool-calls
        text_parts: list[str] = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        if response.stop_reason == "end_turn" or not tool_calls:
            final_text = "".join(text_parts)
            break

        # Verwerk tool-calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tc in tool_calls:
            result_text, apt = _execute_tool(tc.name, tc.input, phone, db)
            if apt:
                booked_appointments.append(apt)
                if saved_filenames:
                    _attach_photos(phone, saved_filenames, db)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result_text,
            })
        messages.append({"role": "user", "content": tool_results})

    # ── Bewaar gespreksgeschiedenis (zonder ruwe afbeeldingen) ──
    history.append({"role": "user", "content": message or "[foto gestuurd]"})
    history.append({"role": "assistant", "content": final_text})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    conv.messages = history
    db.add(conv)
    db.commit()

    # ── Stuur bevestigingsmails ──
    for apt in booked_appointments:
        await send_confirmation_email(apt)

    return final_text or "Er is een technisch probleem opgetreden. Probeer het opnieuw."

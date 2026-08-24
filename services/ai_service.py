"""
AI-service: beheert de conversatie met Claude en voert tool-calls uit.

Afbeeldingen worden meegegeven als vooraf gedownloade base64-dicts
zodat deze service volledig ontkoppeld is van Twilio of andere media-bronnen.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

import models
from config import settings
from database import SessionLocal
from prompts.system_prompt import get_system_prompt
from services.email_service import send_confirmation_email

logger = logging.getLogger(__name__)

_async_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MAX_HISTORY = 20

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
                "duur_minuten": {"type": "integer", "default": 60},
            },
            "required": ["datum", "tijd"],
        },
    },
    {
        "name": "boek_afspraak",
        "description": "Boek een nieuwe afspraak. Controleer eerst de beschikbaarheid.",
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
                "ai_notities": {"type": "string"},
            },
            "required": ["klant_naam", "klant_email", "service_type", "datum", "tijd"],
        },
    },
    {
        "name": "haal_afspraken_op",
        "description": "Haal alle actieve afspraken op voor de huidige klant.",
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

_DAGEN = {0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
           4: "vrijdag", 5: "zaterdag", 6: "zondag"}


# ─────────────────────────────────────────────
# Tool-uitvoering (synchroon / snel)
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
        return "Op zaterdag zijn we open van 08:00–13:00."
    if wd < 5 and (dt.hour < 8 or (dt.hour == 17 and dt.minute > 30) or dt.hour >= 18):
        return "Op werkdagen zijn we open van 08:00–17:30."
    if dt < datetime.now():
        return "Dit tijdstip ligt in het verleden. Kies een toekomstige datum."

    end_dt = dt + timedelta(minutes=duur)
    existing = db.query(models.Appointment).filter(
        models.Appointment.status == "bevestigd",
        models.Appointment.scheduled_datetime < end_dt,
    ).all()
    conflicts = [a for a in existing if (a.scheduled_datetime + timedelta(minutes=a.duur_minuten or 60)) > dt]

    if not conflicts:
        return f"Het tijdstip {tijd} op {datum} is beschikbaar voor {duur} minuten."

    alts: list[str] = []
    for offset in [30, 60, 90, 120, 150, -30, -60]:
        alt = dt + timedelta(minutes=offset)
        alt_end = alt + timedelta(minutes=duur)
        aw = alt.weekday()
        if aw == 6 or (aw == 5 and (alt.hour < 8 or alt.hour >= 13)):
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
    return f"Het tijdstip {tijd} op {datum} is bezet. Alternatieven: {alts_str}."


def _book_appointment(
    args: dict, phone: str, db: Session
) -> tuple[str, Optional[models.Appointment]]:
    try:
        dt = datetime.strptime(f"{args['datum']} {args['tijd']}", "%Y-%m-%d %H:%M")
    except (ValueError, KeyError):
        return "Ongeldige datum of tijd.", None

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

    result = (
        f"Afspraak #{apt.id} geboekt!\n"
        f"Datum: {_DAGEN[dt.weekday()]} {dt.strftime('%d-%m-%Y')} om {dt.strftime('%H:%M')}\n"
        f"Service: {apt.service_type.replace('_', ' ').title()}\n"
        f"Duur: ±{apt.duur_minuten} min\n"
    )
    if apt.prijs_min and apt.prijs_max:
        result += f"Prijs: €{apt.prijs_min:.0f}–€{apt.prijs_max:.0f}\n"
    if apt.klant_email:
        result += f"Bevestigingsmail → {apt.klant_email}\n"
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
        return "Geen actieve afspraken gevonden voor uw nummer."
    lines = [f"Uw afspraken ({len(apts)}):\n"]
    for a in apts:
        auto = " ".join(filter(None, [a.auto_merk, a.auto_model, f"({a.kenteken})" if a.kenteken else ""]))
        lines.append(
            f"#{a.id} – {_DAGEN[a.scheduled_datetime.weekday()]} "
            f"{a.scheduled_datetime.strftime('%d-%m-%Y')} {a.scheduled_datetime.strftime('%H:%M')}\n"
            f"  {a.service_type.replace('_',' ').title()}"
            + (f" | {auto}" if auto else "") + "\n"
        )
    return "\n".join(lines)


def _cancel_appointment(args: dict, phone: str, db: Session) -> str:
    apt = db.query(models.Appointment).filter(
        models.Appointment.id == args["afspraak_id"],
        models.Appointment.klant_telefoon == phone,
    ).first()
    if not apt:
        return f"Afspraak #{args['afspraak_id']} niet gevonden."
    if apt.status == "geannuleerd":
        return f"Afspraak #{args['afspraak_id']} is al geannuleerd."
    apt.status = "geannuleerd"
    db.commit()
    return f"Afspraak #{args['afspraak_id']} geannuleerd. Kan ik u verder helpen?"


def _reschedule_appointment(args: dict, phone: str, db: Session) -> str:
    apt = db.query(models.Appointment).filter(
        models.Appointment.id == args["afspraak_id"],
        models.Appointment.klant_telefoon == phone,
    ).first()
    if not apt:
        return f"Afspraak #{args['afspraak_id']} niet gevonden."
    try:
        nieuwe_dt = datetime.strptime(f"{args['nieuwe_datum']} {args['nieuwe_tijd']}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "Ongeldige datum of tijd."
    apt.scheduled_datetime = nieuwe_dt
    apt.reminder_24h_sent = False
    apt.reminder_1h_sent = False
    db.commit()
    return (
        f"Afspraak #{apt.id} verplaatst naar "
        f"{_DAGEN[nieuwe_dt.weekday()]} {nieuwe_dt.strftime('%d-%m-%Y')} om {nieuwe_dt.strftime('%H:%M')}."
    )


def _execute_tool(
    name: str, tool_input: dict, phone: str, db: Session
) -> tuple[str, Optional[models.Appointment]]:
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
# Conversatiegeschiedenis
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


def _strip_images(history: list[dict]) -> list[dict]:
    """Vervang afbeeldingen door placeholder om opslagruimte te besparen."""
    result = []
    for msg in history:
        content = msg["content"]
        if isinstance(content, list):
            new = [
                {"type": "text", "text": "[eerder gestuurde foto]"}
                if isinstance(b, dict) and b.get("type") == "image"
                else b
                for b in content
            ]
            result.append({"role": msg["role"], "content": new})
        else:
            result.append(msg)
    return result


def _attach_photos(phone: str, filenames: list[str], db: Session) -> None:
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
    images: list[dict],
    db: Session,
    photo_filenames: list[str] | None = None,
) -> str:
    """
    Verwerk een bericht en geef de AI-reactie terug.

    Args:
        phone:           Telefoonnummer of sessie-ID van de klant.
        message:         Tekstinhoud van het bericht.
        images:          Lijst van {"data": "<base64>", "media_type": "image/jpeg"}.
        db:              Database-sessie.
        photo_filenames: Lokale bestandsnamen van de afbeeldingen (voor koppeling aan afspraak).
    """
    photo_filenames = photo_filenames or []
    conv = _get_or_create_conversation(phone, db)
    history = list(conv.messages or [])

    # Bouw gebruikerscontent
    user_content: list[dict] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
        }
        for img in images
    ]
    if message.strip():
        user_content.append({"type": "text", "text": message})
    if not user_content:
        user_content = [{"type": "text", "text": "(leeg bericht)"}]

    messages: list[dict] = _strip_images(history) + [
        {"role": "user", "content": user_content}
    ]

    # Agentic loop
    booked: list[models.Appointment] = []
    final_text = ""

    for _ in range(6):
        response = await _async_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=get_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_calls = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "end_turn" or not tool_calls:
            final_text = "".join(text_parts)
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tc in tool_calls:
            result_text, apt = _execute_tool(tc.name, tc.input, phone, db)
            if apt:
                booked.append(apt)
                if photo_filenames:
                    _attach_photos(phone, photo_filenames, db)
            tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result_text})
        messages.append({"role": "user", "content": tool_results})

    # Bewaar geschiedenis
    history.append({"role": "user", "content": message or "[foto gestuurd]"})
    history.append({"role": "assistant", "content": final_text})
    conv.messages = history[-MAX_HISTORY:]
    db.add(conv)
    db.commit()

    for apt in booked:
        await send_confirmation_email(apt)

    return final_text or "Er is een technisch probleem opgetreden. Probeer het opnieuw."

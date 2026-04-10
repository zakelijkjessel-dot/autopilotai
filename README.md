# AutoGarage WhatsApp Chatbot

Een AI-gestuurde WhatsApp chatbot voor autogarages, gebouwd met **FastAPI**, **Claude (Anthropic)** en **Twilio**.

## Functionaliteiten

| Feature | Omschrijving |
|---|---|
| 💬 Vragen beantwoorden | Diensten, prijzen, openingstijden |
| 📅 Afspraken inplannen | Met beschikbaarheidscontrole op werkuren |
| 🔄 Annuleren / verplaatsen | Klant beheert zelf via WhatsApp |
| 🚗 Auto-informatie opvragen | Kenteken, merk, model, bouwjaar, probleem |
| ⏱️ Tijdschatting | AI schat duur per servicetype |
| 💶 Prijsindicatie | Ranges per dienst, opgeslagen bij afspraak |
| 📸 Fotoanalyse | Schade, banden, roest — via Claude vision |
| 📣 Upselling | Vriendelijk, eenmalig, na de hoofdboeking |
| ✉️ Bevestigingsmail | HTML-mail via SMTP direct na boeking |
| 🔔 WhatsApp herinneringen | 24 uur en 1 uur van tevoren |
| 📋 Admin dashboard | Overzicht, filters, status beheren |
| 🌐 Web-chat demo | Testen zonder WhatsApp via `/chat` |

---

## Projectstructuur

```
autopilotai/
├── main.py                     # FastAPI app (alle routes)
├── config.py                   # Omgevingsvariabelen
├── database.py                 # SQLAlchemy engine + session
├── models.py                   # DB-modellen (Conversation, Appointment)
├── prompts/
│   └── system_prompt.py        # Nederlandstalige AI-instructies
├── services/
│   ├── ai_service.py           # Claude agentic loop + tool-uitvoering
│   ├── whatsapp_service.py     # Twilio WhatsApp
│   ├── email_service.py        # SMTP bevestigingsmail
│   └── reminder_service.py     # APScheduler herinneringen
├── handlers/
│   └── webhook_handler.py      # Twilio-webhook verwerker
├── templates/
│   ├── chat.html               # Web-chat interface
│   ├── admin.html              # Admin dashboard
│   └── email_confirmation.html # HTML bevestigingsmail
├── uploads/                    # Ontvangen foto's (gitignored)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Snel starten (lokaal)

### 1. Omgevingsvariabelen

```bash
cp .env.example .env
```

Vul de volgende waarden in `.env` in:

| Variabele | Omschrijving |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID (van console.twilio.com) |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_WHATSAPP_FROM` | Sandbox: `whatsapp:+14155238886` |
| `ANTHROPIC_API_KEY` | API-sleutel van console.anthropic.com |
| `SMTP_HOST` | SMTP-server (bijv. `smtp.gmail.com`) |
| `SMTP_PORT` | Meestal `587` |
| `SMTP_USER` | E-mailadres voor verzenden |
| `SMTP_PASSWORD` | App-wachtwoord (niet je inlogwachtwoord) |
| `GARAGE_NAAM` | Naam van de garage |
| `GARAGE_ADRES` | Adres van de garage |
| `GARAGE_TELEFOON` | Telefoonnummer van de garage |

### 2. Installeer dependencies

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start de app

```bash
python main.py
```

De app draait op `http://localhost:8000`.

---

## Testen zonder WhatsApp

Open de web-chat demo in je browser:

```
http://localhost:8000/chat
```

Je kunt tekst sturen én foto's uploaden. De AI-reacties zijn identiek aan wat klanten via WhatsApp ontvangen.

---

## WhatsApp koppelen (Twilio Sandbox)

1. Maak een account op [twilio.com](https://twilio.com)
2. Ga naar **Messaging → Try it out → Send a WhatsApp message**
3. Verbind je eigen WhatsApp met de sandbox via de QR-code
4. Maak een publieke URL met [ngrok](https://ngrok.com):
   ```bash
   ngrok http 8000
   ```
5. Stel de webhook in op:
   ```
   https://<jouw-ngrok-url>/webhook/whatsapp
   ```
   bij **"A message comes in"** → HTTP POST

---

## Admin Dashboard

```
http://localhost:8000/admin
```

Functionaliteiten:
- Statistieken (totaal / bevestigd / geannuleerd / voltooid)
- Filterbaar overzicht van alle afspraken
- Detailweergave per afspraak (klant, auto, prijs, AI-notities, foto's)
- Status wijzigen (voltooid / annuleren / herbevestigen)
- Automatisch vernieuwen elke 5 minuten

---

## Uitrollen met Docker

```bash
# Bouw en start
docker compose up -d

# Logs bekijken
docker compose logs -f

# Stoppen
docker compose down
```

---

## Prijzen en servicetypes

| Service | Enum-waarde | Prijs | Duur |
|---|---|---|---|
| APK Keuring | `apk` | €45–€55 | 60 min |
| Kleine beurt | `kleine_beurt` | €89–€129 | 90 min |
| Grote beurt | `grote_beurt` | €149–€249 | 180 min |
| APK + kleine beurt | `apk_kleine_beurt` | €119–€169 | 120 min |
| Banden wisselen | `banden` | €30–€60 | 45 min |
| Remmen voor | `remmen_voor` | €120–€200 | 120 min |
| Remmen achter | `remmen_achter` | €100–€180 | 120 min |
| Diagnose | `diagnose` | €49–€69 | 60 min |
| Schade beoordeling | `schade` | gratis | 30 min |
| Overig | `overig` | n.v.t. | n.v.t. |

Prijzen en diensten aanpassen: `prompts/system_prompt.py`

---

## Garage aanpassen

Stel de garagegegevens in via `.env`:

```env
GARAGE_NAAM=Garage Jansen
GARAGE_ADRES=Dorpsstraat 15, 5678 CD Utrecht
GARAGE_TELEFOON=+31 30 123 4567
GARAGE_EMAIL=info@garagejansen.nl
```

---

## Technische details

- **AI-model**: `claude-sonnet-4-6` (Anthropic)
- **Tool-calling**: Agentic loop met max. 6 rondes per bericht
- **Database**: SQLite (development) — vervang `DATABASE_URL` voor PostgreSQL in productie
- **Gesprekgeschiedenis**: Laatste 20 berichten per klant bewaard
- **Herinneringen**: APScheduler controleert elke 30 minuten op aankomende afspraken
- **Afbeeldingen**: Worden lokaal opgeslagen in `/uploads` en getoond in het admin-dashboard

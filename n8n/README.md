# AutoGarage WhatsApp-bot in n8n

Dezelfde bot als de Python-versie in de rest van deze repo, maar dan als n8n-workflows.
De functionaliteit en de systeemprompt komen uit `README.md` en `prompts/system_prompt.py`.

## Wat er in deze map staat

| Bestand | Doel |
|---|---|
| `workflows/autogarage-whatsapp-bot.json` | Hoofdflow: inkomende WhatsApp -> Claude met tools -> antwoord + bevestigingsmail |
| `workflows/autogarage-herinneringen.json` | Elke 30 minuten herinneringen 24 uur en 1 uur vooraf |
| `lib/afspraken.js` | Gedeelde logica (beschikbaarheid, boeken, annuleren, verplaatsen, prompt, mails) |
| `code/*.js` | De inhoud van de Code-nodes (klein, één taak per node) |
| `build.js` | Zet `lib/` en `code/` om naar de JSON-workflows |
| `test/` | Tests voor de logica en de workflow-structuur (zonder n8n te draaien) |

## Architectuur

```
Twilio (WhatsApp) ──POST──► Webhook /webhook/whatsapp
                              ├─► Direct TwiML (lege response, Twilio tevreden)
                              └─► Config ─► Normaliseer ─► Heeft foto's?
                                              ├─ ja ─► Download foto (Twilio, basic auth)
                                              │        ─► Claude vision (fotoanalyse) ─┐
                                              └─ nee ───────────────────────────────┤
                                                                                     ▼
                              Google Sheets: Gesprekken + Afspraken lezen ─► Maak state
                                                                                     ▼
                              ┌──────────── Bouw verzoek ─► Claude (met 5 tools) ─► Verwerk ◄┐
                              │                                   │                          │
                              │                          Klaar? ──┴── nee: tool-resultaten ──┘
                              │                            │ ja (max. 6 rondes)
                              ▼                            ▼
              Sheets: afspraken upsert   Sheets: gesprek upsert   SMTP: bevestigingsmail
                                                                   Twilio: antwoord (in delen van max. 4000 tekens)
```

De herinneringsflow is een apart workflow: Schedule (30 min) ─► Sheets lezen ─► bepalen wat er verstuurd moet ─► Twilio ─► vlaggen terugschrijven.

## Functies: README-lijst tegenover n8n

| Feature | Waar |
|---|---|
| Vragen beantwoorden (diensten, prijzen, openingstijden) | Systeemprompt in `lib/afspraken.js` (`botSysteemprompt`) |
| Afspraken inplannen met beschikbaarheidscontrole | Tool `controleer_beschikbaarheid` + `boek_afspraak` (`botBeschikbaar`, `botBoek`) |
| Annuleren / verplaatsen | Tools `haal_afspraken_op`, `annuleer_afspraak`, `verplaats_afspraak` |
| Auto-informatie (kenteken, merk, model, bouwjaar, probleem) | Velden in `boek_afspraak` |
| Tijdschatting en prijsindicatie | `BOT_DUUR` en `BOT_PRIJS` in `lib/afspraken.js`, opgeslagen bij de afspraak |
| Fotoanalyse (schade, banden, roest) | `Vision-verzoek` + `Claude vision` + `Foto-tekst` |
| Upselling (max. 1x, na de boeking) | Systeemprompt |
| Bevestigingsmail (HTML, via SMTP) | `Bevestigingsmails` + `Stuur bevestigingsmail` |
| WhatsApp-herinneringen 24 uur en 1 uur | Workflow *Herinneringen* |
| Admin dashboard | De Google Sheet zelf (tab *Afspraken*, filteren en sorteren kan direct in Sheets) |
| Web-chat demo `/chat` | Niet meegenomen. n8n heeft een ingebouwde Chat Trigger die je hier later aan kunt koppelen |

## Installatie

### 1. Google Sheet maken

Maak een Google Sheet met twee tabbladen. De kolomnamen moeten exact zo staan (in de eerste rij):

**Tab `Afspraken`**
```
id,klant_naam,klant_telefoon,klant_email,auto_merk,auto_model,bouwjaar,kenteken,service_type,probleem_omschrijving,foto_paths,scheduled_datetime,duur_minuten,prijs_min,prijs_max,status,ai_notities,reminder_24h_sent,reminder_1h_sent,created_at,updated_at
```

**Tab `Gesprekken`**
```
telefoon,berichten,bijgewerkt
```

Zet de kolommen `klant_telefoon`, `scheduled_datetime`, `created_at` en `updated_at` op opmaak **Gewone tekst**. Anders maakt Google Sheets er getallen of datums van, en klopt de vergelijking met `+31...` of `2026-11-20 10:00` niet meer.

Het Sheet-ID is het stuk tussen `/d/` en `/edit` in de URL.

### 2. Credentials in n8n

Maak deze vier credentials aan (Settings → Credentials):

| Naam in n8n | Type | Waarde |
|---|---|---|
| `Anthropic API key` | Header Auth | Header-naam `x-api-key`, waarde = je Anthropic-sleutel |
| `Twilio (SID als user, Auth Token als password)` | Basic Auth | User = Account SID, Password = Auth Token |
| `Google Sheets account` | Google Sheets OAuth2 API | Inloggen met het Google-account dat het Sheet beheert |
| `SMTP (garage e-mail)` | SMTP | Zelfde gegevens als in `.env` (bijv. Gmail met app-wachtwoord) |

### 3. Workflows importeren

Bouw eerst de JSON met je Sheet-ID (anders blijft de placeholder staan):

```bash
N8N_SHEET_ID=<jouw-sheet-id> node n8n/build.js
```

Importeer daarna in n8n: **Add workflow → ⋯ → Import from file**, één keer per bestand in `n8n/workflows/`.
Koppel na de import de credentials in de nodes die rood zijn.

### 4. Gegevens van de garage

Open de node **Config** (in beide workflows) en pas de waarden aan: naam, adres, telefoon, e-mail, Twilio-SID, Twilio-sandbox-nummer, afzender van de mail en het Claude-model.
De Config-node bevat geen geheimen. Die staan in de credentials.

### 5. Twilio koppelen

1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message** (sandbox).
2. Bij **"When a message comes in"** de n8n-URL zetten, methode **POST**:
   ```
   https://<jouw-n8n-domein>/webhook/whatsapp
   ```
3. Zet de workflow **AutoGarage – WhatsApp-bot** aan (Active). Ook **AutoGarage – Herinneringen** zetten voor de herinneringen.

De productie-URL werkt alleen als de workflow actief is. Tijdens het bouwen gebruik je de test-URL (`/webhook-test/whatsapp`) met **Listen for test event**.

### 6. Testen zonder WhatsApp

Met de test-URL en curl kun je de hele flow testen zonder telefoon. Twilio stuurt `application/x-www-form-urlencoded`:

```bash
curl -X POST "https://<jouw-n8n-domein>/webhook-test/whatsapp" \
  --data-urlencode "From=whatsapp:+31600000001" \
  --data-urlencode "Body=Hoi, wat kost een APK?"
```

Het antwoord van de bot komt via Twilio op je WhatsApp (de sandbox moet dan aan jouw nummer gekoppeld zijn). De Sheet laat zien of er een gesprek is opgeslagen.

## Tests

```bash
node --test n8n/test/logica.test.js n8n/test/workflows.test.js
```

- `logica.test.js` test beschikbaarheid, openingstijden, boeken, annuleren, verplaatsen, de agentic loop (met gemockte Claude-antwoorden), splitsen van lange antwoorden en de herinneringsvensters.
- `workflows.test.js` controleert of de JSON geldig is, of alle verbindingen naar bestaande nodes wijzen, of de JavaScript in de Code-nodes syntactisch klopt en of alle nodes bereikbaar zijn vanaf de trigger.

## Wat ik niet kon verifiëren

Ik heb deze workflows gebouwd en de logica getest, maar **niet in een draaiende n8n-instantie geïmporteerd of uitgevoerd** (er is hier geen n8n-server en geen Twilio/Google/Anthropic-account). Let bij de eerste keer op deze punten:

- **Google Sheets-node.** De nodes staan op typeVersion 4.5 met operaties `read` en `appendOrUpdate` (matching op `id` of `telefoon`). Controleer dat de kolomkoppeling de juiste velden toont. Bij een afwijking in je n8n-versie is dat in de UI in één klik te zetten.
- **Binaire foto's.** De Code-node `Vision-verzoek` gebruikt `this.helpers.getBinaryDataBuffer`. Ik weet niet zeker dat dit in jouw n8n-versie beschikbaar is. Als het ontbreekt, is dit de enige plek die aangepast moet worden. Met een testfoto via Twilio zie je dat meteen.
- **Beveiliging van de webhook.** De webhook controleert de `X-Twilio-Signature` nog niet. Iedereen die de URL kent, kan dus berichten sturen. Voor productie hoort er een signature-check voor de Twilio-webhook bij (Twilio's `validateRequest` of een Code-node met de auth token).
- **Het Claude-model.** Standaard staat `claude-sonnet-5-5` in `Config`. Dat is één regel om te wijzigen als je account een ander model vraagt.
- **Concurrency.** Sheets is geen database. Twee berichten van dezelfde klant tegelijk kunnen elkaars geschiedenis overschrijven. Voor een echte productie-uitrol is Postgres of de ingebouwde n8n Data Table beter.

## Verschillen met de Python-versie

- **Boeken controleert altijd eerst de beschikbaarheid.** De Python-versie vertrouwde op de systeemprompt. Hier weigert de tool een dubbele boeking.
- **Verplaatsen controleert ook de beschikbaarheid.** De Python-versie deed dat niet.
- **Openingstijden kijken naar het eindtijdstip.** Een afspraak die na 17:30 eindigt, wordt geweigerd. In de Python-versie werd alleen de starttijd gecontroleerd.
- **Alternatieven zijn op dezelfde dag en chronologisch.**
- **Fotoanalyse gebeurt in een apart Claude-verzoek.** Het resultaat wordt als tekst aan het gesprek toegevoegd. De foto zelf wordt niet bewaard, de analyse wel (in `ai_notities`).
- **Gespreksgeschiedenis:** laatste 20 berichten per klant, net als de Python-versie.

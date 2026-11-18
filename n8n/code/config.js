// ---- Instellingen: pas hier de gegevens van de garage aan ----
// Geheimen (Twilio auth token, Anthropic-sleutel, SMTP-wachtwoord, Google-login)
// staan NIET hier maar in de n8n Credentials.
return [{
  json: {
    GARAGE_NAAM: 'AutoGarage Nederland',
    GARAGE_ADRES: 'Hoofdstraat 1, 1234 AB Amsterdam',
    GARAGE_TELEFOON: '+31 20 123 4567',
    GARAGE_EMAIL: 'info@autogarage.nl',
    TWILIO_ACCOUNT_SID: 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    TWILIO_WHATSAPP_FROM: 'whatsapp:+14155238886',
    SMTP_FROM: 'AutoGarage Nederland <info@autogarage.nl>',
    CLAUDE_MODEL: 'claude-sonnet-5-5',
  },
}];

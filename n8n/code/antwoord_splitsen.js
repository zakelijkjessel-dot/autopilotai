// Splitst het antwoord en maakt één Twilio-verzoek per deel.
const s = $input.first().json;
const c = $('Config').first().json;
const naar = 'whatsapp:' + String(s.telefoon).replace(/^whatsapp:/, '');
return botSplits(s.eindTekst || BOT_FALLBACK).map(deel => ({
  json: { sid: c.TWILIO_ACCOUNT_SID, from: c.TWILIO_WHATSAPP_FROM, to: naar, body: deel },
}));

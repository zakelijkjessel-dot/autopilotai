// Twilio stuurt form-velden: From, Body, NumMedia, MediaUrl0.., MediaContentType0..
const b = $('Webhook WhatsApp').first().json.body || {};
const aantal = Number(b.NumMedia || 0);

const media = [];
for (let i = 0; i < aantal; i++) {
  const url = b[`MediaUrl${i}`];
  if (url) media.push({ url, type: b[`MediaContentType${i}`] || 'image/jpeg', index: i });
}
const afbeeldingen = media.filter(m => m.type.startsWith('image/'));

let bericht = String(b.Body || '').trim();
const overig = media.length - afbeeldingen.length;
if (overig > 0) {
  bericht += `\n[Klant stuurde ${overig} bestand(en) die niet ondersteund worden. Alleen foto's kunnen worden beoordeeld.]`;
}

return [{
  json: {
    telefoon: String(b.From || '').replace('whatsapp:', ''),
    bericht,
    afbeeldingen,
    heeftFotos: afbeeldingen.length > 0,
  },
}];

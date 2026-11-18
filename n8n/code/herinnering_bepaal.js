// Zoekt afspraken die nu een herinnering nodig hebben (24 uur of 1 uur vooraf).
const c = $('Config').first().json;
const nu = botNu();
const afspraken = $input.all()
  .map(i => i.json)
  .filter(r => Number(r.id) > 0)
  .map(botNormaliseer);

return botHerinneringen(afspraken, nu, c).map(h => ({
  json: {
    sid: c.TWILIO_ACCOUNT_SID,
    from: c.TWILIO_WHATSAPP_FROM,
    to: 'whatsapp:' + h.afspraak.klant_telefoon,
    body: h.tekst,
    id: h.afspraak.id,
    rij: botAfspraakRij(h.afspraak),
  },
}));

// Eén bevestigingsmail per net geboekte afspraak (alleen als de klant een e-mailadres gaf).
const s = $input.first().json;
const c = $('Config').first().json;
return s.geboekt
  .filter(a => a.klant_email)
  .map(a => {
    const mail = botBevestigingsmail(a, c);
    return { json: { to: a.klant_email, from: c.SMTP_FROM, subject: mail.onderwerp, html: mail.html } };
  });

/* ============================================================
 * AutoGarage WhatsApp-bot: gedeelde logica voor de n8n Code-nodes.
 * build.js plakt dit bestand bovenaan de Code-nodes die het nodig hebben.
 * Gewone JavaScript, geen module-syntax.
 *
 * Tijden zijn wandkloktijden in Europe/Amsterdam, uitgedrukt als minuten
 * sinds 1970. Het rekenwerk gaat via UTC, zodat de tijdzone van de n8n-server
 * geen invloed heeft.
 * ============================================================ */

const BOT_TZ = 'Europe/Amsterdam';
const BOT_DAGEN = ['maandag', 'dinsdag', 'woensdag', 'donderdag', 'vrijdag', 'zaterdag', 'zondag'];
const BOT_MAANDEN = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
  'juli', 'augustus', 'september', 'oktober', 'november', 'december'];

const BOT_DUUR = {
  apk: 60, kleine_beurt: 90, grote_beurt: 180, apk_kleine_beurt: 120, banden: 45,
  remmen_voor: 120, remmen_achter: 120, diagnose: 60, schade: 30, overig: 60,
};
const BOT_PRIJS = {
  apk: [45, 55], kleine_beurt: [89, 129], grote_beurt: [149, 249], apk_kleine_beurt: [119, 169],
  banden: [30, 60], remmen_voor: [120, 200], remmen_achter: [100, 180], diagnose: [49, 69],
  schade: null, overig: null,
};

const BOT_MAX_HISTORIE = 20;
const BOT_MAX_RONDES = 6;
const BOT_FOUTMELDING = 'Sorry, er is een technisch probleem opgetreden. 😔\nProbeer het opnieuw of bel ons direct.';
const BOT_FALLBACK = 'Er is een technisch probleem opgetreden. Probeer het opnieuw.';
const BOT_FOTO_PROMPT = 'Je bent monteur bij een autogarage. Analyseer deze foto van een auto in het Nederlands, '
  + 'kort en zakelijk: 1) type schade of probleem (kras, deuk, barst, slijtage banden, roest, etc.), '
  + '2) ernst (licht / matig / ernstig), 3) is de auto nog veilig te rijden?, '
  + '4) urgentie (direct naar de garage / kan nog een week wachten / niet urgent), '
  + '5) grove kostenindicatie. Maximaal 6 zinnen. Zeg als iets op de foto niet goed te zien is.';

const BOT_AFSPRAAK_KOLOMMEN = [
  'id', 'klant_naam', 'klant_telefoon', 'klant_email', 'auto_merk', 'auto_model', 'bouwjaar',
  'kenteken', 'service_type', 'probleem_omschrijving', 'foto_paths', 'scheduled_datetime',
  'duur_minuten', 'prijs_min', 'prijs_max', 'status', 'ai_notities', 'reminder_24h_sent',
  'reminder_1h_sent', 'created_at', 'updated_at',
];

const BOT_TOOLS = [
  {
    name: 'controleer_beschikbaarheid',
    description: 'Controleer of een datum en tijd beschikbaar is voor een afspraak. Gebruik dit ALTIJD vóór het boeken.',
    input_schema: {
      type: 'object',
      properties: {
        datum: { type: 'string', description: 'YYYY-MM-DD' },
        tijd: { type: 'string', description: 'HH:MM' },
        duur_minuten: { type: 'integer', default: 60 },
      },
      required: ['datum', 'tijd'],
    },
  },
  {
    name: 'boek_afspraak',
    description: 'Boek een nieuwe afspraak. Controleer eerst de beschikbaarheid.',
    input_schema: {
      type: 'object',
      properties: {
        klant_naam: { type: 'string' },
        klant_email: { type: 'string' },
        auto_merk: { type: 'string' },
        auto_model: { type: 'string' },
        bouwjaar: { type: 'integer' },
        kenteken: { type: 'string' },
        service_type: {
          type: 'string',
          enum: ['apk', 'kleine_beurt', 'grote_beurt', 'apk_kleine_beurt', 'banden',
            'remmen_voor', 'remmen_achter', 'diagnose', 'schade', 'overig'],
        },
        probleem_omschrijving: { type: 'string' },
        datum: { type: 'string', description: 'YYYY-MM-DD' },
        tijd: { type: 'string', description: 'HH:MM' },
        duur_minuten: { type: 'integer' },
        prijs_min: { type: 'number' },
        prijs_max: { type: 'number' },
        ai_notities: { type: 'string' },
      },
      required: ['klant_naam', 'klant_email', 'service_type', 'datum', 'tijd'],
    },
  },
  {
    name: 'haal_afspraken_op',
    description: 'Haal alle actieve afspraken op voor de huidige klant.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'annuleer_afspraak',
    description: 'Annuleer een bestaande afspraak van de huidige klant.',
    input_schema: {
      type: 'object',
      properties: { afspraak_id: { type: 'integer' }, reden: { type: 'string' } },
      required: ['afspraak_id'],
    },
  },
  {
    name: 'verplaats_afspraak',
    description: 'Verplaats een bestaande afspraak naar een nieuwe datum en tijd.',
    input_schema: {
      type: 'object',
      properties: {
        afspraak_id: { type: 'integer' },
        nieuwe_datum: { type: 'string', description: 'YYYY-MM-DD' },
        nieuwe_tijd: { type: 'string', description: 'HH:MM' },
      },
      required: ['afspraak_id', 'nieuwe_datum', 'nieuwe_tijd'],
    },
  },
];

/* ---------- Tijd ---------- */

function botPad(n) {
  return String(n).padStart(2, '0');
}

// "YYYY-MM-DD HH:MM" (of met T) -> minuten sinds 1970, of null bij een ongeldige datum
function botMinuten(tekst) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})$/.exec(String(tekst || '').trim());
  if (!m) return null;
  const [j, mnd, d, u, min] = m.slice(1).map(Number);
  const ms = Date.UTC(j, mnd - 1, d, u, min);
  const terug = new Date(ms).toISOString().slice(0, 16);
  if (terug !== `${j}-${botPad(mnd)}-${botPad(d)}T${botPad(u)}:${botPad(min)}`) return null; // bv. 30 februari
  return ms / 60000;
}

function botLokaal(min) {
  const d = new Date(min * 60000);
  const iso = d.toISOString();
  return {
    datum: iso.slice(0, 10),
    tijd: iso.slice(11, 16),
    dag: (d.getUTCDay() + 6) % 7, // 0 = maandag ... 6 = zondag
    minuutVanDag: ((min % 1440) + 1440) % 1440,
  };
}

function botNu() {
  const nu = new Date().toLocaleString('sv-SE', { timeZone: BOT_TZ }); // "YYYY-MM-DD HH:MM:SS"
  return botMinuten(nu.slice(0, 16));
}

function botNuTekst() {
  const l = botLokaal(botNu());
  return `${l.datum} ${l.tijd}`;
}

function botDatumNL(min) {
  const l = botLokaal(min);
  const [j, m, d] = l.datum.split('-');
  return `${BOT_DAGEN[l.dag]} ${d}-${m}-${j}`;
}

function botDatumLang(min) {
  const l = botLokaal(min);
  const [j, m, d] = l.datum.split('-').map(Number);
  return `${BOT_DAGEN[botLokaal(min).dag]} ${d} ${BOT_MAANDEN[m - 1]} ${j}`;
}

function botLabel(dienst) {
  return String(dienst || '').split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/* ---------- Openingstijden en beschikbaarheid ---------- */

// [open, dicht] in minuten na middernacht; null = gesloten
function botUren(dag) {
  if (dag === 6) return null;       // zondag gesloten
  if (dag === 5) return [480, 780]; // zaterdag 08:00-13:00
  return [480, 1050];               // ma-vr 08:00-17:30
}

function botIsOpen(startMin, duurMin) {
  const l = botLokaal(startMin);
  const uren = botUren(l.dag);
  return uren !== null && l.minuutVanDag >= uren[0] && l.minuutVanDag + duurMin <= uren[1];
}

function botStart(a) {
  return botMinuten(a.scheduled_datetime);
}

function botDuur(a) {
  return Number(a.duur_minuten) || 60;
}

function botBezet(afspraken, startMin, duurMin, uitsluitId) {
  return afspraken.some(a => {
    if (a.status !== 'bevestigd' || a.id === uitsluitId) return false;
    const s = botStart(a);
    return s !== null && s < startMin + duurMin && s + botDuur(a) > startMin;
  });
}

// Retourneert { ok, tekst }. Bij "bezet" bevat de tekst maximaal drie alternatieven op dezelfde dag.
function botBeschikbaar(afspraken, datum, tijd, duurMin, nuMin, uitsluitId) {
  const start = botMinuten(`${datum} ${tijd}`);
  if (start === null) {
    return { ok: false, tekst: 'Ongeldige datum- of tijdnotatie. Gebruik YYYY-MM-DD en HH:MM.' };
  }
  const dag = botLokaal(start).dag;
  if (dag === 6) {
    return { ok: false, tekst: 'De garage is op zondag gesloten. Kies een andere dag.' };
  }
  if (!botIsOpen(start, duurMin)) {
    return {
      ok: false,
      tekst: dag === 5
        ? 'Op zaterdag zijn we open van 08:00–13:00.'
        : 'Op werkdagen zijn we open van 08:00–17:30.',
    };
  }
  if (start < nuMin) {
    return { ok: false, tekst: 'Dit tijdstip ligt in het verleden. Kies een toekomstige datum.' };
  }
  if (!botBezet(afspraken, start, duurMin, uitsluitId)) {
    return { ok: true, tekst: `Het tijdstip ${tijd} op ${datum} is beschikbaar voor ${duurMin} minuten.` };
  }
  const alternatieven = [];
  for (const offset of [-60, -30, 30, 60, 90, 120, 150]) {
    const kandidaat = start + offset;
    if (botLokaal(kandidaat).datum !== datum) continue;
    if (!botIsOpen(kandidaat, duurMin) || kandidaat < nuMin) continue;
    if (botBezet(afspraken, kandidaat, duurMin, uitsluitId)) continue;
    alternatieven.push(botLokaal(kandidaat).tijd);
    if (alternatieven.length >= 3) break;
  }
  const lijst = alternatieven.length ? alternatieven.join(', ') : 'geen vrije tijden op deze dag';
  return { ok: false, tekst: `Het tijdstip ${tijd} op ${datum} is bezet. Alternatieven: ${lijst}.` };
}

/* ---------- Afspraken in en uit de sheet ---------- */

function botNormaliseer(r) {
  const ja = v => v === true || String(v).toUpperCase() === 'TRUE';
  const getal = v => (v === '' || v === null || v === undefined ? null : Number(v));
  return {
    id: Number(r.id),
    klant_naam: String(r.klant_naam || ''),
    klant_telefoon: String(r.klant_telefoon || ''),
    klant_email: String(r.klant_email || ''),
    auto_merk: String(r.auto_merk || ''),
    auto_model: String(r.auto_model || ''),
    bouwjaar: r.bouwjaar === undefined || r.bouwjaar === null ? '' : String(r.bouwjaar),
    kenteken: String(r.kenteken || ''),
    service_type: String(r.service_type || 'overig'),
    probleem_omschrijving: String(r.probleem_omschrijving || ''),
    foto_paths: String(r.foto_paths || ''),
    scheduled_datetime: String(r.scheduled_datetime || ''),
    duur_minuten: Number(r.duur_minuten) || 60,
    prijs_min: getal(r.prijs_min),
    prijs_max: getal(r.prijs_max),
    status: String(r.status || 'bevestigd'),
    ai_notities: String(r.ai_notities || ''),
    reminder_24h_sent: ja(r.reminder_24h_sent),
    reminder_1h_sent: ja(r.reminder_1h_sent),
    created_at: String(r.created_at || ''),
    updated_at: String(r.updated_at || ''),
  };
}

function botAfspraakRij(a) {
  const rij = {};
  for (const k of BOT_AFSPRAAK_KOLOMMEN) {
    let v = a[k];
    if (typeof v === 'boolean') v = v ? 'TRUE' : 'FALSE';
    rij[k] = v === null || v === undefined ? '' : v;
  }
  return rij;
}

/* ---------- Tools die Claude aanroept ---------- */

function botZoekEigen(ctx, id) {
  return ctx.afspraken.find(a => a.id === Number(id) && a.klant_telefoon === ctx.telefoon);
}

function botBoek(invoer, ctx) {
  const dienst = BOT_DUUR[invoer.service_type] !== undefined ? invoer.service_type : 'overig';
  const duur = Number(invoer.duur_minuten) || BOT_DUUR[dienst] || 60;
  const check = botBeschikbaar(ctx.afspraken, invoer.datum, invoer.tijd, duur, ctx.nuMin);
  if (!check.ok) return check.tekst;

  const start = botMinuten(`${invoer.datum} ${invoer.tijd}`);
  const prijs = BOT_PRIJS[dienst];
  const id = ctx.afspraken.reduce((max, a) => Math.max(max, a.id), 0) + 1;
  const a = botNormaliseer({
    id,
    klant_naam: invoer.klant_naam || '',
    klant_telefoon: ctx.telefoon,
    klant_email: invoer.klant_email || '',
    auto_merk: invoer.auto_merk || '',
    auto_model: invoer.auto_model || '',
    bouwjaar: invoer.bouwjaar || '',
    kenteken: String(invoer.kenteken || '').toUpperCase().replace(/\s+/g, ''),
    service_type: dienst,
    probleem_omschrijving: invoer.probleem_omschrijving || '',
    scheduled_datetime: `${botLokaal(start).datum} ${botLokaal(start).tijd}`,
    duur_minuten: duur,
    prijs_min: invoer.prijs_min ?? (prijs ? prijs[0] : ''),
    prijs_max: invoer.prijs_max ?? (prijs ? prijs[1] : ''),
    status: 'bevestigd',
    ai_notities: [invoer.ai_notities, ctx.fotoAnalyse ? `Foto-analyse: ${ctx.fotoAnalyse}` : '']
      .filter(Boolean).join(' | '),
    reminder_24h_sent: false,
    reminder_1h_sent: false,
    created_at: botNuTekst(),
    updated_at: botNuTekst(),
  });

  ctx.afspraken.push(a);
  ctx.gewijzigd.add(id);
  ctx.geboekt.push(a);

  let tekst = `Afspraak #${id} geboekt!\n`
    + `Datum: ${botDatumNL(start)} om ${botLokaal(start).tijd}\n`
    + `Service: ${botLabel(dienst)}\n`
    + `Duur: ±${duur} min\n`;
  if (a.prijs_min && a.prijs_max) tekst += `Prijs: €${a.prijs_min}–€${a.prijs_max}\n`;
  if (a.klant_email) tekst += `Bevestigingsmail → ${a.klant_email}\n`;
  return tekst;
}

function botOverzicht(ctx) {
  const lijst = ctx.afspraken
    .filter(a => a.klant_telefoon === ctx.telefoon && a.status === 'bevestigd')
    .sort((a, b) => botStart(a) - botStart(b));
  if (!lijst.length) return 'Geen actieve afspraken gevonden voor uw nummer.';
  const regels = lijst.map(a => {
    const start = botStart(a);
    const auto = [a.auto_merk, a.auto_model, a.kenteken ? `(${a.kenteken})` : ''].filter(Boolean).join(' ');
    return `#${a.id} – ${botDatumNL(start)} ${botLokaal(start).tijd}\n  ${botLabel(a.service_type)}${auto ? ` | ${auto}` : ''}`;
  });
  return `Uw afspraken (${lijst.length}):\n\n${regels.join('\n\n')}`;
}

function botAnnuleer(invoer, ctx) {
  const a = botZoekEigen(ctx, invoer.afspraak_id);
  if (!a) return `Afspraak #${invoer.afspraak_id} niet gevonden.`;
  if (a.status === 'geannuleerd') return `Afspraak #${a.id} is al geannuleerd.`;
  a.status = 'geannuleerd';
  ctx.gewijzigd.add(a.id);
  return `Afspraak #${a.id} geannuleerd. Kan ik u verder helpen?`;
}

function botVerplaats(invoer, ctx) {
  const a = botZoekEigen(ctx, invoer.afspraak_id);
  if (!a) return `Afspraak #${invoer.afspraak_id} niet gevonden.`;
  const check = botBeschikbaar(ctx.afspraken, invoer.nieuwe_datum, invoer.nieuwe_tijd, botDuur(a), ctx.nuMin, a.id);
  if (!check.ok) return check.tekst;
  const start = botMinuten(`${invoer.nieuwe_datum} ${invoer.nieuwe_tijd}`);
  a.scheduled_datetime = `${botLokaal(start).datum} ${botLokaal(start).tijd}`;
  a.reminder_24h_sent = false;
  a.reminder_1h_sent = false;
  ctx.gewijzigd.add(a.id);
  return `Afspraak #${a.id} verplaatst naar ${botDatumNL(start)} om ${botLokaal(start).tijd}.`;
}

function botVoerTool(naam, invoer, ctx) {
  switch (naam) {
    case 'controleer_beschikbaarheid':
      return botBeschikbaar(ctx.afspraken, invoer.datum, invoer.tijd,
        Number(invoer.duur_minuten) || 60, ctx.nuMin).tekst;
    case 'boek_afspraak':
      return botBoek(invoer, ctx);
    case 'haal_afspraken_op':
      return botOverzicht(ctx);
    case 'annuleer_afspraak':
      return botAnnuleer(invoer, ctx);
    case 'verplaats_afspraak':
      return botVerplaats(invoer, ctx);
    default:
      return `Onbekende tool: ${naam}`;
  }
}

/* ---------- Systeemprompt (zelfde inhoud als prompts/system_prompt.py) ---------- */

function botSysteemprompt(c, nuMin) {
  const l = botLokaal(nuMin);
  const [j, m, d] = l.datum.split('-');
  return `Je bent AutoBot, de vriendelijke WhatsApp-assistent van ${c.GARAGE_NAAM}.

📍 ${c.GARAGE_ADRES}
📞 ${c.GARAGE_TELEFOON}
📧 ${c.GARAGE_EMAIL}

⏰ Openingstijden:
  Maandag t/m vrijdag: 08:00 – 17:30
  Zaterdag: 08:00 – 13:00
  Zondag: gesloten

Vandaag is het ${BOT_DAGEN[l.dag]} ${d}-${m}-${j}, het is nu ${l.tijd} uur.

━━━━━━━━━━━━━━━━━━━━━━━
DIENSTEN & TARIEVEN
━━━━━━━━━━━━━━━━━━━━━━━
Service                   | Prijs          | Duur
APK                       | €45 – €55      | 60 min
Kleine beurt              | €89 – €129     | 90 min
Grote beurt               | €149 – €249    | 180 min
APK + kleine beurt        | €119 – €169    | 120 min
Banden wisselen (4x)      | €30 – €60      | 45 min
Remmen voor               | €120 – €200    | 120 min
Remmen achter             | €100 – €180    | 120 min
Diagnose & uitlezen       | €49 – €69      | 60 min
Schade beoordeling        | gratis         | 30 min

━━━━━━━━━━━━━━━━━━━━━━━
WERKWIJZE BIJ AFSPRAKEN
━━━━━━━━━━━━━━━━━━━━━━━
Verzamel altijd deze informatie voordat je een afspraak boekt:
1. Naam van de klant
2. E-mailadres (voor bevestigingsmail)
3. Kenteken (of merk/model/bouwjaar als kenteken niet beschikbaar is)
4. Omschrijving van het probleem of gevraagde service
5. Gewenste datum en tijd

Gebruik ALTIJD de tool "controleer_beschikbaarheid" voordat je een datum/tijd bevestigt.
Als het tijdstip bezet is, stel dan de alternatieven voor die de tool teruggeeft.
Voor annuleren of verplaatsen: haal eerst de afspraken op (haal_afspraken_op) om het afspraaknummer te vinden.

━━━━━━━━━━━━━━━━━━━━━━━
UPSELLING (vriendelijk, max. 1x)
━━━━━━━━━━━━━━━━━━━━━━━
Doe upselling ná de hoofdafspraakaanvraag, nooit ervoor. Doe het één keer en accepteer een "nee".
- APK geboekt? → "Wil je er gelijk een kleine beurt bij? APK + kleine beurt kost €119–€169 en bespaart je een extra afspraak."
- Banden gewisseld? → "We kunnen ook meteen de bandenspanning en wieluitlijning controleren."
- Remmen voor/achter? → "We checken altijd ook de remvloeistof erbij, helemaal gratis."
- Grote beurt? → "Wil je de APK ook gelijk meenemen? Dan regelen we alles in één keer."

━━━━━━━━━━━━━━━━━━━━━━━
FOTOANALYSE
━━━━━━━━━━━━━━━━━━━━━━━
Als een klant een foto stuurt, staat de analyse van die foto in het bericht als "[Foto-analyse van de klant: ...]".
Gebruik die analyse en geef de klant advies over:
- Type schade of probleem (kras, deuk, barst, slijtage banden, etc.)
- Ernst: licht / matig / ernstig
- Veiligheid: is de auto nog veilig te rijden?
- Urgentie: direct naar garage / kan nog een week wachten / niet urgent
- Geschatte kosten op basis van wat je ziet
- Vraag indien nodig om aanvullende foto's vanuit een andere hoek

━━━━━━━━━━━━━━━━━━━━━━━
STIJL & TOON
━━━━━━━━━━━━━━━━━━━━━━━
- Reageer altijd in het Nederlands (tenzij klant in andere taal schrijft)
- Vriendelijk en professioneel, maar bondig
- Gebruik emoji's spaarzaam (max. 1–2 per bericht)
- Vat afspraakdetails altijd samen vóór bevestiging zodat de klant kan controleren
- Als je een afspraak hebt geboekt, vertel de klant dat ze een bevestigingsmail ontvangen
- Wees nooit drammatisch bij een annulering – bied gewoon alternatieven aan
`;
}

/* ---------- Gesprek en agentic loop ---------- */

function botInitState(o) {
  const nuMin = o.nuMin ?? botNu();
  const rij = (o.gesprekRijen || []).find(r => r && r.telefoon === o.telefoon);
  let historie = [];
  try {
    historie = JSON.parse((rij && rij.berichten) || '[]');
  } catch (e) {
    historie = [];
  }
  historie = historie.filter(m => m && (m.role === 'user' || m.role === 'assistant')
    && String(m.content || '').trim() !== '');
  while (historie.length && historie[0].role !== 'user') historie.shift();

  const tekst = [o.fotoAnalyse ? `[Foto-analyse van de klant: ${o.fotoAnalyse}]` : '', o.bericht]
    .filter(Boolean).join('\n') || '(leeg bericht)';

  return {
    telefoon: o.telefoon,
    bericht: o.bericht || '',
    fotoAnalyse: o.fotoAnalyse || '',
    model: o.config.CLAUDE_MODEL,
    system: botSysteemprompt(o.config, nuMin),
    nuMin,
    historie,
    messages: [...historie, { role: 'user', content: tekst }],
    afspraken: (o.afspraakRijen || []).filter(r => Number(r.id) > 0).map(botNormaliseer),
    gewijzigd: [],
    geboekt: [],
    ronde: 0,
    klaar: false,
    eindTekst: '',
  };
}

function botClaudeVerzoek(s, model) {
  return { model: model || s.model, max_tokens: 1024, system: s.system, tools: BOT_TOOLS, messages: s.messages };
}

// Verwerkt één Claude-antwoord en geeft de nieuwe staat terug. Voert tool-calls uit.
function botVerwerkAntwoord(state, resp) {
  const s = JSON.parse(JSON.stringify(state));
  if (!resp || resp.error || !Array.isArray(resp.content)) {
    s.eindTekst = BOT_FOUTMELDING;
    s.klaar = true;
    return s;
  }
  s.ronde = (s.ronde || 0) + 1;

  const tekst = resp.content.filter(b => b.type === 'text').map(b => b.text).join('').trim();
  const gereedschap = resp.content.filter(b => b.type === 'tool_use');

  if (resp.stop_reason === 'end_turn' || gereedschap.length === 0) {
    s.eindTekst = tekst || BOT_FALLBACK;
    s.klaar = true;
    return s;
  }

  s.messages.push({ role: 'assistant', content: resp.content });
  const ctx = {
    telefoon: s.telefoon,
    afspraken: s.afspraken,
    nuMin: s.nuMin,
    fotoAnalyse: s.fotoAnalyse,
    gewijzigd: new Set(s.gewijzigd),
    geboekt: s.geboekt,
  };
  const resultaten = gereedschap.map(t => ({
    type: 'tool_result',
    tool_use_id: t.id,
    content: botVoerTool(t.name, t.input || {}, ctx),
  }));
  s.messages.push({ role: 'user', content: resultaten });
  s.gewijzigd = [...ctx.gewijzigd];

  if (s.ronde >= BOT_MAX_RONDES) {
    s.eindTekst = BOT_FALLBACK;
    s.klaar = true;
  }
  return s;
}

function botNieuweHistorie(s) {
  return [
    ...s.historie,
    { role: 'user', content: s.bericht || '[foto gestuurd]' },
    { role: 'assistant', content: s.eindTekst },
  ].slice(-BOT_MAX_HISTORIE);
}

// Splitst lange antwoorden op regeleinden (WhatsApp-limiet ±4000 tekens)
function botSplits(tekst, max = 4000) {
  let rest = String(tekst || '');
  const delen = [];
  while (rest.length > max) {
    let snede = rest.lastIndexOf('\n', max - 1);
    if (snede <= 0) snede = max;
    delen.push(rest.slice(0, snede).trim());
    rest = rest.slice(snede).trim();
  }
  if (rest) delen.push(rest);
  return delen.filter(Boolean);
}

function botEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function botBevestigingsmail(a, c) {
  const start = botStart(a);
  const rij = (label, waarde) => `<tr><td style="padding:10px 0;color:#6b7280;border-bottom:1px solid #f0f2f5">${botEsc(label)}</td>`
    + `<td style="padding:10px 0;text-align:right;font-weight:600;border-bottom:1px solid #f0f2f5">${botEsc(waarde)}</td></tr>`;
  const auto = [a.auto_merk, a.auto_model, a.kenteken ? `(${a.kenteken})` : ''].filter(Boolean).join(' ');
  const prijs = a.prijs_min && a.prijs_max ? `€${a.prijs_min}–€${a.prijs_max}` : 'op aanvraag';
  const html = `<!DOCTYPE html><html lang="nl"><head><meta charset="UTF-8"><title>Afspraakbevestiging</title></head>
<body style="margin:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#333">
<div style="max-width:620px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden">
<div style="background:#1e293b;color:#fff;padding:32px;text-align:center">
<h1 style="margin:0;font-size:22px">🔧 ${botEsc(c.GARAGE_NAAM)}</h1>
<p style="margin:6px 0 0;opacity:.7;font-size:13px">Uw afspraak is bevestigd</p></div>
<div style="padding:32px">
<p style="line-height:1.6">Beste ${botEsc(a.klant_naam)},</p>
<p style="line-height:1.6">Bedankt voor het inplannen van uw afspraak bij <strong>${botEsc(c.GARAGE_NAAM)}</strong>. Hieronder vindt u het overzicht.</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
${rij('📅 Datum', botDatumLang(start))}
${rij('🕐 Tijd', `${botLokaal(start).tijd} uur`)}
${rij('🔧 Service', botLabel(a.service_type))}
${auto ? rij('🚗 Auto', auto) : ''}
${rij('⏱️ Duur', `±${a.duur_minuten} min`)}
${rij('💶 Prijsindicatie', prijs)}
${rij('🔖 Afspraaknummer', `#${a.id}`)}
</table>
<p style="margin-top:24px;line-height:1.6">📍 ${botEsc(c.GARAGE_ADRES)}<br>📞 ${botEsc(c.GARAGE_TELEFOON)}</p>
<p style="line-height:1.6">Kunt u niet komen? Stuur ons een WhatsApp-bericht om de afspraak te verplaatsen.</p>
</div>
<div style="background:#f8fafc;padding:20px 32px;text-align:center;font-size:12px;color:#9ca3af">${botEsc(c.GARAGE_NAAM)} · ${botEsc(c.GARAGE_EMAIL)}</div>
</div></body></html>`;
  return { onderwerp: `Afspraakbevestiging – ${c.GARAGE_NAAM}`, html };
}

/* ---------- Herinneringen (24 uur en 1 uur vooraf) ---------- */

function botHerinneringen(afspraken, nuMin, c) {
  const uit = [];
  for (const origineel of afspraken) {
    if (origineel.status !== 'bevestigd') continue;
    const start = botStart(origineel);
    if (start === null) continue;
    const a = { ...origineel };
    const auto = [a.auto_merk, a.auto_model, a.kenteken ? `(${a.kenteken})` : ''].filter(Boolean).join(' ');

    if (!a.reminder_24h_sent && start >= nuMin + 23 * 60 + 30 && start <= nuMin + 24 * 60 + 30) {
      a.reminder_24h_sent = true;
      const tekst = `Goedendag ${a.klant_naam}! 👋\n\n`
        + `Dit is een herinnering voor uw afspraak bij ${c.GARAGE_NAAM} morgen ${botDatumNL(start)} om ${botLokaal(start).tijd} uur.\n\n`
        + `Service: ${botLabel(a.service_type)}\n`
        + (auto ? `Auto: ${auto}\n` : '')
        + `\n📍 ${c.GARAGE_ADRES}\n\n`
        + 'Kunt u niet komen? Stuur dan een bericht om de afspraak te verplaatsen.';
      uit.push({ afspraak: a, soort: '24h', tekst });
    }
    if (!a.reminder_1h_sent && start >= nuMin + 45 && start <= nuMin + 75) {
      a.reminder_1h_sent = true;
      const tekst = `Herinnering: uw afspraak bij ${c.GARAGE_NAAM} begint over 1 uur om ${botLokaal(start).tijd} uur. ⏰\n\n`
        + `📍 ${c.GARAGE_ADRES}\n\nTot straks!`;
      uit.push({ afspraak: a, soort: '1h', tekst });
    }
  }
  return uit;
}

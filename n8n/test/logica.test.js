// Run: node --test n8n/test/
// Test de gedeelde logica (n8n/lib/afspraken.js) zonder n8n. Tijd wordt vastgezet via nuMin.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const bron = fs.readFileSync(path.join(__dirname, '..', 'lib', 'afspraken.js'), 'utf8');
const B = new Function(`${bron}
return { botMinuten, botLokaal, botIsOpen, botBeschikbaar, botVoerTool, botInitState,
  botVerwerkAntwoord, botSplits, botHerinneringen, botNormaliseer, botAfspraakRij,
  botBevestigingsmail, botNieuweHistorie, botClaudeVerzoek, botSysteemprompt,
  BOT_TOOLS, BOT_FOUTMELDING, BOT_FALLBACK, BOT_FOTO_PROMPT };`)();

const CONFIG = {
  GARAGE_NAAM: 'Test Garage', GARAGE_ADRES: 'Teststraat 1', GARAGE_TELEFOON: '+31 20 000 0000',
  GARAGE_EMAIL: 'info@test.nl', CLAUDE_MODEL: 'test-model', SMTP_FROM: 'Test <info@test.nl>',
};
// Maandag 3 juni 2030, 09:00 (wandkloktijd Amsterdam)
const NU = B.botMinuten('2030-06-03 09:00');
const KLANT = '+31600000001';

function ctx(afspraken = [], extra = {}) {
  return { telefoon: KLANT, afspraken, nuMin: NU, fotoAnalyse: '', gewijzigd: new Set(), geboekt: [], ...extra };
}

test('botMinuten leest geldige datums en weigert ongeldige', () => {
  assert.notEqual(B.botMinuten('2030-06-10 10:00'), null);
  assert.notEqual(B.botMinuten('2030-06-10T10:00'), null);
  assert.equal(B.botMinuten('2030-02-30 10:00'), null); // bestaat niet
  assert.equal(B.botMinuten('morgen'), null);
});

test('openingstijden: ma-vr 08:00-17:30, za 08:00-13:00, zo gesloten', () => {
  const ma = (t) => B.botMinuten(`2030-06-10 ${t}`); // maandag
  const za = (t) => B.botMinuten(`2030-06-08 ${t}`); // zaterdag
  const zo = (t) => B.botMinuten(`2030-06-09 ${t}`); // zondag
  assert.equal(B.botIsOpen(ma('10:00'), 60), true);
  assert.equal(B.botIsOpen(ma('16:30'), 60), true);
  assert.equal(B.botIsOpen(ma('17:00'), 60), false); // eindigt na 17:30
  assert.equal(B.botIsOpen(ma('07:30'), 60), false);
  assert.equal(B.botIsOpen(za('12:00'), 60), true);
  assert.equal(B.botIsOpen(za('12:30'), 60), false);
  assert.equal(B.botIsOpen(zo('10:00'), 60), false);
});

test('beschikbaarheid: vrij tijdstip is beschikbaar', () => {
  const r = B.botBeschikbaar([], '2030-06-10', '10:00', 60, NU);
  assert.equal(r.ok, true);
  assert.match(r.tekst, /beschikbaar voor 60 minuten/);
});

test('beschikbaarheid: verleden en gesloten dagen worden geweigerd', () => {
  const verleden = B.botBeschikbaar([], '2030-06-03', '08:00', 60, NU);
  assert.equal(verleden.ok, false);
  assert.match(verleden.tekst, /verleden/);

  const zondag = B.botBeschikbaar([], '2030-06-09', '10:00', 60, NU);
  assert.equal(zondag.ok, false);
  assert.match(zondag.tekst, /zondag gesloten/);
});

test('beschikbaarheid: bezet tijdstip geeft vrije alternatieven op dezelfde dag', () => {
  const bezet = [B.botNormaliseer({ id: 1, status: 'bevestigd', scheduled_datetime: '2030-06-10 10:00', duur_minuten: 60 })];
  const r = B.botBeschikbaar(bezet, '2030-06-10', '10:00', 60, NU);
  assert.equal(r.ok, false);
  assert.equal(r.tekst, 'Het tijdstip 10:00 op 2030-06-10 is bezet. Alternatieven: 09:00, 11:00, 11:30.');
});

test('beschikbaarheid: geannuleerde afspraken blokkeren niet', () => {
  const geannuleerd = [B.botNormaliseer({ id: 1, status: 'geannuleerd', scheduled_datetime: '2030-06-10 10:00', duur_minuten: 60 })];
  assert.equal(B.botBeschikbaar(geannuleerd, '2030-06-10', '10:00', 60, NU).ok, true);
});

test('tool boek_afspraak: boekt, normaliseert kenteken en vult prijs en duur in', () => {
  const c = ctx();
  const tekst = B.botVoerTool('boek_afspraak', {
    klant_naam: 'Piet', klant_email: 'piet@example.nl', service_type: 'apk',
    datum: '2030-06-10', tijd: '10:00', kenteken: 'ab-12-cd',
  }, c);
  assert.match(tekst, /Afspraak #1 geboekt!/);
  assert.match(tekst, /Prijs: €45–€55/);
  assert.equal(c.afspraken.length, 1);
  assert.equal(c.afspraken[0].kenteken, 'AB-12-CD');
  assert.equal(c.afspraken[0].duur_minuten, 60);
  assert.equal(c.afspraken[0].klant_telefoon, KLANT);
  assert.deepEqual([...c.gewijzigd], [1]);
});

test('tool boek_afspraak: dubbel boeken op hetzelfde moment wordt geweigerd', () => {
  const c = ctx();
  const invoer = { klant_naam: 'Piet', klant_email: 'p@x.nl', service_type: 'kleine_beurt', datum: '2030-06-10', tijd: '13:00' };
  B.botVoerTool('boek_afspraak', invoer, c);
  const tweede = B.botVoerTool('boek_afspraak', { ...invoer, klant_naam: 'Klaas' }, c);
  assert.match(tweede, /is bezet/);
  assert.equal(c.afspraken.length, 1);
});

test('tool annuleer en verplaats werken alleen op eigen afspraken', () => {
  const eigen = B.botNormaliseer({ id: 7, klant_telefoon: KLANT, status: 'bevestigd', scheduled_datetime: '2030-06-10 10:00', duur_minuten: 60 });
  const vreemd = { ...eigen, id: 8, klant_telefoon: '+31699999999' };
  const c = ctx([eigen, vreemd]);

  assert.match(B.botVoerTool('annuleer_afspraak', { afspraak_id: 8 }, c), /niet gevonden/);
  assert.match(B.botVoerTool('annuleer_afspraak', { afspraak_id: 7 }, c), /Afspraak #7 geannuleerd/);
  assert.equal(c.afspraken[0].status, 'geannuleerd');

  const c2 = ctx([{ ...eigen, status: 'bevestigd' }]);
  const tekst = B.botVoerTool('verplaats_afspraak', { afspraak_id: 7, nieuwe_datum: '2030-06-11', nieuwe_tijd: '14:00' }, c2);
  assert.equal(tekst, 'Afspraak #7 verplaatst naar dinsdag 11-06-2030 om 14:00.');
  assert.equal(c2.afspraken[0].scheduled_datetime, '2030-06-11 14:00');
});

test('tool haal_afspraken_op toont alleen actieve afspraken van deze klant', () => {
  const a = B.botNormaliseer({ id: 1, klant_telefoon: KLANT, status: 'bevestigd', scheduled_datetime: '2030-06-12 09:00', duur_minuten: 60, service_type: 'apk' });
  const b = B.botNormaliseer({ id: 2, klant_telefoon: KLANT, status: 'geannuleerd', scheduled_datetime: '2030-06-13 09:00', duur_minuten: 60 });
  const tekst = B.botVoerTool('haal_afspraken_op', {}, ctx([b, a]));
  assert.match(tekst, /Uw afspraken \(1\)/);
  assert.match(tekst, /#1 – woensdag 12-06-2030 09:00/);
  assert.doesNotMatch(tekst, /#2/);
});

test('agentic loop: tool-calls, daarna eindantwoord, met correcte berichtvolgorde', () => {
  const state = B.botInitState({
    config: CONFIG, telefoon: KLANT, bericht: 'Ik wil een APK op maandag 10 juni om 10:00',
    fotoAnalyse: '', gesprekRijen: [], afspraakRijen: [], nuMin: NU,
  });
  const r1 = {
    stop_reason: 'tool_use',
    content: [
      { type: 'text', text: 'Even controleren.' },
      { type: 'tool_use', id: 't1', name: 'controleer_beschikbaarheid', input: { datum: '2030-06-10', tijd: '10:00', duur_minuten: 60 } },
    ],
  };
  const s1 = B.botVerwerkAntwoord(state, r1);
  assert.equal(s1.klaar, false);

  const r2 = {
    stop_reason: 'tool_use',
    content: [{ type: 'tool_use', id: 't2', name: 'boek_afspraak', input: {
      klant_naam: 'Piet', klant_email: 'piet@example.nl', service_type: 'apk', datum: '2030-06-10', tijd: '10:00', kenteken: 'AB12CD',
    } }],
  };
  const s2 = B.botVerwerkAntwoord(s1, r2);
  assert.equal(s2.klaar, false);
  assert.equal(s2.geboekt.length, 1);

  // De verzoeken die naar Claude gaan: rollen moeten afwisselen en de tools moeten erbij zitten
  const verzoek = B.botClaudeVerzoek(s2, 'test-model');
  assert.equal(verzoek.tools.length, 5);
  assert.deepEqual(verzoek.messages.map(m => m.role), ['user', 'assistant', 'user', 'assistant', 'user']);
  assert.equal(verzoek.messages[2].content[0].tool_use_id, 't1');

  const r3 = { stop_reason: 'end_turn', content: [{ type: 'text', text: 'Uw APK is geboekt op maandag 10 juni om 10:00.' }] };
  const s3 = B.botVerwerkAntwoord(s2, r3);
  assert.equal(s3.klaar, true);
  assert.equal(s3.eindTekst, 'Uw APK is geboekt op maandag 10 juni om 10:00.');
  assert.deepEqual(s3.gewijzigd, [1]);

  const historie = B.botNieuweHistorie(s3);
  assert.deepEqual(historie.map(h => h.role), ['user', 'assistant']);
  assert.equal(historie[0].content, 'Ik wil een APK op maandag 10 juni om 10:00');
});

test('agentic loop: stopt na 6 rondes met de fallback-tekst', () => {
  let s = B.botInitState({ config: CONFIG, telefoon: KLANT, bericht: 'test', fotoAnalyse: '', gesprekRijen: [], afspraakRijen: [], nuMin: NU });
  for (let i = 0; i < 6; i++) {
    s = B.botVerwerkAntwoord(s, {
      stop_reason: 'tool_use',
      content: [{ type: 'tool_use', id: `t${i}`, name: 'haal_afspraken_op', input: {} }],
    });
  }
  assert.equal(s.klaar, true);
  assert.equal(s.eindTekst, B.BOT_FALLBACK);
});

test('API-fout geeft de foutmelding en stopt de loop', () => {
  const s = B.botInitState({ config: CONFIG, telefoon: KLANT, bericht: 'hoi', fotoAnalyse: '', gesprekRijen: [], afspraakRijen: [], nuMin: NU });
  const uit = B.botVerwerkAntwoord(s, { error: { type: 'overloaded_error' } });
  assert.equal(uit.klaar, true);
  assert.equal(uit.eindTekst, B.BOT_FOUTMELDING);
});

test('gespreksgeschiedenis: laadt eerdere berichten en start altijd met een gebruikersbericht', () => {
  const rij = { telefoon: KLANT, berichten: JSON.stringify([
    { role: 'assistant', content: 'oud antwoord' }, { role: 'user', content: 'hoi' }, { role: 'assistant', content: 'hallo' },
  ]) };
  const s = B.botInitState({ config: CONFIG, telefoon: KLANT, bericht: 'Wat kost een APK?', fotoAnalyse: '', gesprekRijen: [rij], afspraakRijen: [], nuMin: NU });
  assert.deepEqual(s.messages.map(m => m.content), ['hoi', 'hallo', 'Wat kost een APK?']);
});

test('foto-analyse wordt in het gebruikersbericht meegegeven', () => {
  const s = B.botInitState({ config: CONFIG, telefoon: KLANT, bericht: 'Wat zie je?', fotoAnalyse: 'matige kras op de deur', gesprekRijen: [], afspraakRijen: [], nuMin: NU });
  assert.match(s.messages[0].content, /Foto-analyse van de klant: matige kras op de deur/);
  assert.match(s.messages[0].content, /Wat zie je\?/);
});

test('botSplits houdt delen onder de 4000 tekens', () => {
  const delen = B.botSplits('a'.repeat(9000));
  assert.equal(delen.length, 3);
  assert.ok(delen.every(d => d.length <= 4000));
  assert.deepEqual(B.botSplits('kort'), ['kort']);
});

test('herinneringen: 24 uur en 1 uur vooraf, elk maar één keer', () => {
  const over24 = B.botNormaliseer({ id: 1, klant_naam: 'Piet', klant_telefoon: KLANT, status: 'bevestigd', scheduled_datetime: '2030-06-04 09:00', duur_minuten: 60, service_type: 'apk' });
  const over1 = B.botNormaliseer({ id: 2, klant_naam: 'Klaas', klant_telefoon: KLANT, status: 'bevestigd', scheduled_datetime: '2030-06-03 10:00', duur_minuten: 60, service_type: 'banden' });
  const geannuleerd = B.botNormaliseer({ id: 3, klant_naam: 'Jan', klant_telefoon: KLANT, status: 'geannuleerd', scheduled_datetime: '2030-06-03 10:00', duur_minuten: 60 });

  const eerste = B.botHerinneringen([over24, over1, geannuleerd], NU, CONFIG);
  assert.deepEqual(eerste.map(h => [h.afspraak.id, h.soort]), [[1, '24h'], [2, '1h']]);
  assert.match(eerste[0].tekst, /morgen dinsdag 04-06-2030 om 09:00 uur/);
  assert.match(eerste[1].tekst, /begint over 1 uur om 10:00 uur/);

  const tweede = B.botHerinneringen(eerste.map(h => h.afspraak), NU, CONFIG);
  assert.equal(tweede.length, 0);
});

test('bevestigingsmail escapet gebruikersinvoer', () => {
  const a = B.botNormaliseer({ id: 1, klant_naam: '<b>Piet</b>', klant_telefoon: KLANT, status: 'bevestigd', scheduled_datetime: '2030-06-10 10:00', duur_minuten: 60, service_type: 'apk', prijs_min: 45, prijs_max: 55 });
  const mail = B.botBevestigingsmail(a, CONFIG);
  assert.match(mail.html, /&lt;b&gt;Piet&lt;\/b&gt;/);
  assert.doesNotMatch(mail.html, /<b>Piet/);
  assert.equal(mail.onderwerp, 'Afspraakbevestiging – Test Garage');
});

test('systeemprompt bevat datum, tijd en de garagegegevens', () => {
  const p = B.botSysteemprompt(CONFIG, NU);
  assert.match(p, /Vandaag is het maandag 03-06-2030, het is nu 09:00 uur\./);
  assert.match(p, /AutoBot, de vriendelijke WhatsApp-assistent van Test Garage/);
  assert.match(p, /controleer_beschikbaarheid/);
});

test('tool-definities hebben de namen die de loop verwacht', () => {
  assert.deepEqual(B.BOT_TOOLS.map(t => t.name), [
    'controleer_beschikbaarheid', 'boek_afspraak', 'haal_afspraken_op', 'annuleer_afspraak', 'verplaats_afspraak',
  ]);
});

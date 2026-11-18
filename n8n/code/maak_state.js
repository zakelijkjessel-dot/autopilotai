// Zet bericht, gespreksgeschiedenis en afspraken om naar de staat van de agentic loop.
const c = $('Config').first().json;
const basis = $('Normaliseer').first().json;

let fotoAnalyse = '';
try {
  fotoAnalyse = $('Foto-tekst').first().json.fotoAnalyse || '';
} catch (e) {
  fotoAnalyse = ''; // er waren geen foto's
}

const state = botInitState({
  config: c,
  telefoon: basis.telefoon,
  bericht: basis.bericht,
  fotoAnalyse,
  gesprekRijen: $('Lees gesprekken').all().map(i => i.json),
  afspraakRijen: $('Lees afspraken').all().map(i => i.json),
});
return [{ json: state }];

// Eén item per aangepaste of nieuwe afspraak, voor de Sheets-upsert (match op id).
const s = $input.first().json;
return s.afspraken
  .filter(a => s.gewijzigd.includes(a.id))
  .map(a => ({ json: botAfspraakRij(a) }));

// Gespreksgeschiedenis voor de Gesprekken-tab (upsert op telefoon).
const s = $input.first().json;
return [{
  json: {
    telefoon: s.telefoon,
    berichten: JSON.stringify(botNieuweHistorie(s)),
    bijgewerkt: botNuTekst(),
  },
}];

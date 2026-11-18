// Zet de herinneringsvlaggen terug naar de sheet. Per afspraak wint de laatste versie (beide vlaggen).
const perId = new Map();
for (const item of $('Bepaal herinneringen').all().map(i => i.json)) {
  perId.set(item.id, item.rij);
}
return [...perId.values()].map(rij => ({ json: rij }));

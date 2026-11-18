// Run: node --test n8n/test/workflows.test.js
// Controleert de gegenereerde n8n-workflows: geldige JSON, unieke namen, verbindingen naar bestaande
// nodes, geldige JavaScript in alle Code-nodes, verwijzingen $('Node') naar bestaande nodes,
// en of elke node bereikbaar is vanaf de trigger.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const map = path.join(__dirname, '..', 'workflows');
const bestanden = fs.readdirSync(map).filter(f => f.endsWith('.json'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

for (const bestand of bestanden) {
  test(`${bestand}: structuur en code kloppen`, () => {
    const wf = JSON.parse(fs.readFileSync(path.join(map, bestand), 'utf8'));
    const namen = wf.nodes.map(n => n.name);
    assert.equal(new Set(namen).size, namen.length, 'node-namen moeten uniek zijn');
    assert.equal(new Set(wf.nodes.map(n => n.id)).size, wf.nodes.length, 'node-ids moeten uniek zijn');

    for (const [van, uit] of Object.entries(wf.connections)) {
      assert.ok(namen.includes(van), `verbinding vanaf onbekende node "${van}"`);
      for (const poort of uit.main) {
        for (const doel of poort) {
          assert.ok(namen.includes(doel.node), `verbinding naar onbekende node "${doel.node}" (van "${van}")`);
        }
      }
    }

    for (const n of wf.nodes.filter(n => n.type === 'n8n-nodes-base.code')) {
      assert.doesNotThrow(() => new AsyncFunction('$input', '$', n.parameters.jsCode), `syntaxfout in "${n.name}"`);
      const verwezen = [...n.parameters.jsCode.matchAll(/\$\('([^']+)'\)/g)].map(m => m[1]);
      for (const v of verwezen) {
        assert.ok(namen.includes(v), `"${n.name}" verwijst naar onbekende node "${v}"`);
      }
    }

    const bron = wf.nodes.find(n => /webhook|Trigger$/i.test(n.type));
    assert.ok(bron, 'er moet een trigger zijn');
    const bereikbaar = new Set();
    const stapel = [bron.name];
    while (stapel.length) {
      const naam = stapel.pop();
      if (bereikbaar.has(naam)) continue;
      bereikbaar.add(naam);
      for (const poort of (wf.connections[naam]?.main || [])) {
        for (const d of poort) stapel.push(d.node);
      }
    }
    assert.deepEqual(namen.filter(n => !bereikbaar.has(n)), [], 'nodes die niet bereikbaar zijn vanaf de trigger');
  });
}

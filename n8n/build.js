// Genereert de importeerbare n8n-workflows uit de bronbestanden in n8n/code/ en n8n/lib/.
// Gebruik: node n8n/build.js
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const HIER = __dirname;
const LIB = fs.readFileSync(path.join(HIER, 'lib', 'afspraken.js'), 'utf8');
// Google Sheet-ID (uit de URL). Zet N8N_SHEET_ID bij het bouwen, anders blijft de placeholder staan.
const SHEET_ID = process.env.N8N_SHEET_ID || 'VERVANG_DOOR_GOOGLE_SHEET_ID';

function code(bestand, metLib = true) {
  const body = fs.readFileSync(path.join(HIER, 'code', bestand), 'utf8');
  return (metLib ? `${LIB}\n` : '') + body;
}

function uuid(naam) {
  const h = crypto.createHash('md5').update(naam).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}

function node(naam, type, typeVersion, positie, parameters, extra = {}) {
  return { id: uuid(naam), name: naam, type, typeVersion, position: positie, parameters, ...extra };
}

function codeNode(naam, bestand, positie, metLib = true) {
  return node(naam, 'n8n-nodes-base.code', 2, positie, { jsCode: code(bestand, metLib) });
}

function ifNode(naam, positie, expressie, operatie = 'true', rechts = undefined) {
  const voorwaarde = { id: uuid(`${naam}-cond`), leftValue: expressie, rightValue: rechts ?? '', operator: { type: 'boolean', operation: operatie, singleValue: true } };
  return node(naam, 'n8n-nodes-base.if', 2.2, positie, {
    conditions: {
      options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
      conditions: [voorwaarde],
      combinator: 'and',
    },
    options: {},
  });
}

const ANTHROPIC_CRED = { httpHeaderAuth: { id: 'VERVANG_ANTHROPIC', name: 'Anthropic API key' } };
const TWILIO_CRED = { httpBasicAuth: { id: 'VERVANG_TWILIO', name: 'Twilio (SID als user, Auth Token als password)' } };
const SHEETS_CRED = { googleSheetsOAuth2Api: { id: 'VERVANG_GOOGLE', name: 'Google Sheets account' } };
const SMTP_CRED = { smtp: { id: 'VERVANG_SMTP', name: 'SMTP (garage e-mail)' } };

function anthropicNode(naam, positie, bodyExpressie, onError = 'continueRegularOutput') {
  return {
    ...node(naam, 'n8n-nodes-base.httpRequest', 4.2, positie, {
      method: 'POST',
      url: 'https://api.anthropic.com/v1/messages',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'anthropic-version', value: '2023-06-01' }] },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: bodyExpressie,
      options: { timeout: 120000 },
    }),
    credentials: ANTHROPIC_CRED,
    onError,
  };
}

function twilioNode(naam, positie) {
  return {
    ...node(naam, 'n8n-nodes-base.httpRequest', 4.2, positie, {
      method: 'POST',
      url: '=https://api.twilio.com/2010-04-01/Accounts/{{ $json.sid }}/Messages.json',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpBasicAuth',
      sendBody: true,
      contentType: 'form-urlencoded',
      bodyParameters: {
        parameters: [
          { name: 'From', value: '={{ $json.from }}' },
          { name: 'To', value: '={{ $json.to }}' },
          { name: 'Body', value: '={{ $json.body }}' },
        ],
      },
      options: {},
    }),
    credentials: TWILIO_CRED,
  };
}

function sheetsLees(naam, positie, tabblad, extra = {}) {
  return {
    ...node(naam, 'n8n-nodes-base.googleSheets', 4.5, positie, {
      resource: 'sheet',
      operation: 'read',
      documentId: { __rl: true, mode: 'id', value: SHEET_ID },
      sheetName: { __rl: true, mode: 'name', value: tabblad },
      options: {},
    }),
    credentials: SHEETS_CRED,
    alwaysOutputData: true,
    ...extra,
  };
}

function sheetsUpsert(naam, positie, tabblad, matchKolom) {
  return {
    ...node(naam, 'n8n-nodes-base.googleSheets', 4.5, positie, {
      resource: 'sheet',
      operation: 'appendOrUpdate',
      documentId: { __rl: true, mode: 'id', value: SHEET_ID },
      sheetName: { __rl: true, mode: 'name', value: tabblad },
      columns: { mappingMode: 'autoMapInputData', value: {}, matchingColumns: [matchKolom], schema: [] },
      options: {},
    }),
    credentials: SHEETS_CRED,
  };
}

// connecties: [van, uitgang, naar] ; uitgang is 0 voor de gewone uitgang, 0/1 voor IF (true/false)
function verbind(connecties) {
  const uit = {};
  for (const [van, uitgang, naar] of connecties) {
    uit[van] = uit[van] || { main: [] };
    while (uit[van].main.length <= uitgang) uit[van].main.push([]);
    uit[van].main[uitgang].push({ node: naar, type: 'main', index: 0 });
  }
  return uit;
}

function werkstroom(naam, nodes, connecties, beschrijving) {
  return {
    name: naam,
    nodes,
    connections: verbind(connecties),
    active: false,
    settings: { executionOrder: 'v1', saveManualExecutions: true },
    pinData: {},
    meta: { beschrijving },
  };
}

/* ---------- Hoofdflow: inkomend WhatsApp-bericht ---------- */

function bouwBot() {
  const nodes = [
    node('Webhook WhatsApp', 'n8n-nodes-base.webhook', 2, [0, 200], {
      httpMethod: 'POST', path: 'whatsapp', responseMode: 'responseNode', options: {},
    }, { webhookId: uuid('autogarage-whatsapp-webhook') }),
    node('Direct TwiML', 'n8n-nodes-base.respondToWebhook', 1.1, [220, 40], {
      respondWith: 'text',
      responseBody: '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
      options: { responseHeaders: { entries: [{ name: 'Content-Type', value: 'application/xml' }] } },
    }),
    codeNode('Config', 'config.js', [220, 200], false),
    codeNode('Normaliseer', 'normaliseer.js', [440, 200], false),
    ifNode('Heeft media?', [660, 200], '={{ $json.heeftFotos }}'),
    codeNode('Media-items', 'media_items.js', [880, 120], false),
    node('Download media', 'n8n-nodes-base.httpRequest', 4.2, [1100, 120], {
      method: 'GET',
      url: '={{ $json.url }}',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpBasicAuth',
      options: { response: { response: { responseFormat: 'file', outputPropertyName: 'data' } } },
    }, { credentials: TWILIO_CRED, onError: 'continueRegularOutput' }),
    codeNode('Vision-verzoek', 'vision_verzoek.js', [1320, 120]),
    anthropicNode('Claude vision', [1540, 120], '={{ JSON.stringify($json.body) }}'),
    codeNode('Foto-tekst', 'foto_tekst.js', [1760, 120], false),
    sheetsLees('Lees gesprekken', [1980, 200], 'Gesprekken', { onError: 'stopWorkflow' }),
    sheetsLees('Lees afspraken', [2200, 200], 'Afspraken', { executeOnce: true }),
    codeNode('Maak state', 'maak_state.js', [2420, 200]),
    codeNode('Bouw verzoek', 'bouw_verzoek.js', [2640, 200]),
    anthropicNode('Claude', [2860, 200], '={{ JSON.stringify($json.anthropicBody) }}'),
    codeNode('Verwerk', 'verwerk.js', [3080, 200]),
    ifNode('Klaar?', [3300, 200], '={{ $json.klaar }}'),
    codeNode('Afspraken wegschrijven', 'afspraken_wegschrijven.js', [3520, 60]),
    sheetsUpsert('Sheets: afspraken opslaan', [3740, 60], 'Afspraken', 'id'),
    codeNode('Gesprek voorbereiden', 'gesprek_voorbereiden.js', [3520, 200]),
    sheetsUpsert('Sheets: gesprek opslaan', [3740, 200], 'Gesprekken', 'telefoon'),
    codeNode('Bevestigingsmails', 'bevestigingsmails.js', [3520, 340]),
    node('Stuur bevestigingsmail', 'n8n-nodes-base.emailSend', 2.1, [3740, 340], {
      fromEmail: '={{ $json.from }}',
      toEmail: '={{ $json.to }}',
      subject: '={{ $json.subject }}',
      emailFormat: 'html',
      html: '={{ $json.html }}',
      options: {},
    }, { credentials: SMTP_CRED }),
    codeNode('Antwoord splitsen', 'antwoord_splitsen.js', [3520, 480]),
    twilioNode('Twilio: stuur WhatsApp', [3740, 480]),
  ];

  const connecties = [
    ['Webhook WhatsApp', 0, 'Direct TwiML'],
    ['Webhook WhatsApp', 0, 'Config'],
    ['Config', 0, 'Normaliseer'],
    ['Normaliseer', 0, 'Heeft media?'],
    ['Heeft media?', 0, 'Media-items'],
    ['Heeft media?', 1, 'Lees gesprekken'],
    ['Media-items', 0, 'Download media'],
    ['Download media', 0, 'Vision-verzoek'],
    ['Vision-verzoek', 0, 'Claude vision'],
    ['Claude vision', 0, 'Foto-tekst'],
    ['Foto-tekst', 0, 'Lees gesprekken'],
    ['Lees gesprekken', 0, 'Lees afspraken'],
    ['Lees afspraken', 0, 'Maak state'],
    ['Maak state', 0, 'Bouw verzoek'],
    ['Bouw verzoek', 0, 'Claude'],
    ['Claude', 0, 'Verwerk'],
    ['Verwerk', 0, 'Klaar?'],
    ['Klaar?', 1, 'Bouw verzoek'],
    ['Klaar?', 0, 'Afspraken wegschrijven'],
    ['Klaar?', 0, 'Gesprek voorbereiden'],
    ['Klaar?', 0, 'Bevestigingsmails'],
    ['Klaar?', 0, 'Antwoord splitsen'],
    ['Afspraken wegschrijven', 0, 'Sheets: afspraken opslaan'],
    ['Gesprek voorbereiden', 0, 'Sheets: gesprek opslaan'],
    ['Bevestigingsmails', 0, 'Stuur bevestigingsmail'],
    ['Antwoord splitsen', 0, 'Twilio: stuur WhatsApp'],
  ];

  return werkstroom('AutoGarage – WhatsApp-bot', nodes, connecties,
    'Inkomende WhatsApp (Twilio) -> foto-analyse -> Claude met tools -> afspraken/gesprekken in Google Sheets -> antwoord via Twilio en bevestigingsmail via SMTP.');
}

/* ---------- Herinneringen: elke 30 minuten ---------- */

function bouwHerinneringen() {
  const nodes = [
    node('Elke 30 minuten', 'n8n-nodes-base.scheduleTrigger', 1.2, [0, 200], {
      rule: { interval: [{ field: 'minutes', minutesInterval: 30 }] },
    }),
    codeNode('Config', 'config.js', [220, 200], false),
    sheetsLees('Lees afspraken', [440, 200], 'Afspraken'),
    codeNode('Bepaal herinneringen', 'herinnering_bepaal.js', [660, 200]),
    twilioNode('Twilio: stuur herinnering', [880, 200]),
    codeNode('Markeer verzonden', 'herinnering_markeer.js', [1100, 200], false),
    sheetsUpsert('Sheets: afspraken bijwerken', [1320, 200], 'Afspraken', 'id'),
  ];
  const connecties = [
    ['Elke 30 minuten', 0, 'Config'],
    ['Config', 0, 'Lees afspraken'],
    ['Lees afspraken', 0, 'Bepaal herinneringen'],
    ['Bepaal herinneringen', 0, 'Twilio: stuur herinnering'],
    ['Twilio: stuur herinnering', 0, 'Markeer verzonden'],
    ['Markeer verzonden', 0, 'Sheets: afspraken bijwerken'],
  ];
  return werkstroom('AutoGarage – Herinneringen', nodes, connecties,
    'Elke 30 minuten: afspraken die over 24 uur of 1 uur beginnen krijgen een WhatsApp-herinnering via Twilio. Vlaggen worden in Google Sheets gezet.');
}

/* ---------- Schrijven en controle ---------- */

const uitvoer = {
  'autogarage-whatsapp-bot.json': bouwBot(),
  'autogarage-herinneringen.json': bouwHerinneringen(),
};

const map = path.join(HIER, 'workflows');
fs.mkdirSync(map, { recursive: true });
for (const [bestand, wf] of Object.entries(uitvoer)) {
  fs.writeFileSync(path.join(map, bestand), JSON.stringify(wf, null, 2) + '\n');
  console.log(`geschreven: n8n/workflows/${bestand} (${wf.nodes.length} nodes)`);
}

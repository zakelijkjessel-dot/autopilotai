// Bouwt per foto het Claude-verzoek (vision). Het binaire bestand is door de download-node gekomen.
const c = $('Config').first().json;
const media = $('Media-items').all().map(i => i.json);
const items = $input.all();
const uit = [];

for (let i = 0; i < items.length; i++) {
  let body = null;
  try {
    const buffer = await this.helpers.getBinaryDataBuffer(i, 'data');
    body = {
      model: c.CLAUDE_MODEL,
      max_tokens: 700,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: media[i].type, data: buffer.toString('base64') } },
          { type: 'text', text: BOT_FOTO_PROMPT },
        ],
      }],
    };
  } catch (e) {
    body = null; // foto kon niet worden opgehaald; de Claude-node levert dan een fout die we afvangen
  }
  uit.push({ json: { body } });
}
return uit;

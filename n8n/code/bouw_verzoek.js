// Loop-punt: bouwt het verzoek voor Claude uit de huidige staat.
const s = $input.first().json;
return [{ json: { ...s, anthropicBody: botClaudeVerzoek(s, s.model) } }];

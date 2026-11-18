// Verwerkt het Claude-antwoord: voert tool-calls uit en bepaalt of de loop klaar is.
const { anthropicBody, ...state } = $('Bouw verzoek').first().json;
const resp = $input.first().json;
return [{ json: botVerwerkAntwoord(state, resp) }];

// Voegt de vision-antwoorden samen tot één korte fotoanalyse-tekst.
const delen = $input.all().map(i => {
  const r = i.json;
  const tekst = Array.isArray(r.content)
    ? r.content.filter(b => b.type === 'text').map(b => b.text).join(' ').trim()
    : '';
  return tekst || 'foto kon niet worden geanalyseerd';
});
return [{ json: { fotoAnalyse: delen.join(' | ') } }];

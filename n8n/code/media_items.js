// Eén item per foto, zodat de download en de vision-analyse per foto lopen.
const basis = $input.first().json;
return basis.afbeeldingen.map(m => ({ json: m }));

// La recherche de ville de la supervision, commune aux onglets « Services » (supervision_services.js) et « Modifier »
// (supervision_modifier.js), comme à l'étape 1 (step1_city.js) : un nom ou le début d'un code postal, deux lettres
// ou deux chiffres, puis au plus 8 propositions dans l'ordre alphabétique.
// Les propositions : les villes de l'appli, et les communes des adresses des services qui n'en sont pas (Guilvinec).
// Un service se range par la commune de son adresse (utils/geo_utils.town_choices) ; les codes postaux viennent aussi
// des adresses.

const CITY_SEARCH_MAX = 8;

// options : inputId (le champ texte), boxId (la liste des propositions), cityValue(ville) : ce que la page envoie à l'API
// pour une ville (son identifiant, ou son nom), sources() : {cities: [{name, codes}], towns: [{nom, codes}]},
// onChoose({ville, commune}) : appelée au choix, et quand le champ est vidé.
function citySearch(options) {
    const input = document.getElementById(options.inputId);
    const box = document.getElementById(options.boxId);
    let chosen = false;

    const codesText = codes => codes && codes.length ? ` <small class="muted">${escapeHtml(codes.join(', '))}</small>` : '';

    function choose(ville, commune, label) {
        input.value = label;
        box.style.display = 'none';
        chosen = Boolean(ville || commune);
        options.onChoose({ ville, commune });
    }

    function suggest() {
        const typed = input.value.trim().toLowerCase();
        if (!typed) {
            // Le champ vidé : plus de ville choisie.
            box.style.display = 'none';
            if (chosen) choose('', '', '');
            return;
        }
        if (typed.length < 2) { box.style.display = 'none'; return; }
        const byCode = /^\d+$/.test(typed);
        const fits = (name, codes) => byCode ? (codes || []).some(code => code.startsWith(typed))
            : name.toLowerCase().includes(typed);
        const { cities, towns } = options.sources();
        const matches = [
            ...(cities || []).filter(city => fits(city.name, city.codes)).map(city => [city.name,
                `<div class="city-suggestion-item" data-ville="${escapeHtml(String(options.cityValue(city)))}"
                      data-label="${escapeHtml(city.name)}">${escapeHtml(city.name)}${codesText(city.codes)}</div>`]),
            ...(towns || []).filter(town => fits(town.nom, town.codes)).map(town => [town.nom,
                `<div class="city-suggestion-item" data-commune="${escapeHtml(town.nom)}"
                      data-label="${escapeHtml(town.nom)}">${escapeHtml(town.nom)}${codesText(town.codes)}</div>`]),
        ].sort((a, b) => a[0].localeCompare(b[0])).slice(0, CITY_SEARCH_MAX).map(([, html]) => html);
        box.innerHTML = matches.length ? matches.join('')
            : '<div class="city-suggestion-item muted">Aucune ville ni commune ne correspond.</div>';
        box.style.display = 'block';
    }

    input.addEventListener('input', suggest);
    box.addEventListener('click', event => {
        const item = event.target.closest('.city-suggestion-item[data-label]');
        if (item) choose(item.dataset.ville || '', item.dataset.commune || '', item.dataset.label);
    });
    document.addEventListener('click', event => {
        if (!event.target.closest(`#${options.inputId}`) && !event.target.closest(`#${options.boxId}`)) {
            box.style.display = 'none';
        }
    });
    // Oublier la ville choisie sans relancer de recherche (la page la relance elle-même).
    return { clear: () => { input.value = ''; chosen = false; box.style.display = 'none'; } };
}

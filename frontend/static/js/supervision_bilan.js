// Supervision (admin) : le bilan. Combien il reste à trancher, file par file, avec un lien
// vers chaque file. Les chiffres viennent de services/supervision/summary.py, qui
// compte avec les mêmes règles que les pages Spots et Services. Route : GET /api/supervision/reviews/summary.

const SHOWN_ROWS = 12;   // les lignes montrées d'un bloc long (villes, types), les autres sont repliées
let allCities = [];   // les villes de l'appli qui ont quelque chose à trancher, pour la recherche de ville
let allTowns = [];    // les communes qui n'en sont pas
let chosenPlace = null; // la ville ou la commune choisie : {id, name} ou {commune} ; null sans filtre

// Le filtre choisi, à mettre dans l'adresse de GET /reviews/summary.
function filterQuery() {
    const params = new URLSearchParams();
    const city = document.getElementById('filterCity').value;
    const town = document.getElementById('filterTown').value;
    if (city) params.set('ville', city);
    if (town) params.set('commune', town);
    return params.toString();
}

// Un lien vers une page de la supervision qui garde la ville choisie : la page s'ouvre déjà filtrée (placeFromUrl).
// Spots attend l'identifiant de la ville, Services son nom.
function withPlace(url, page) {
    const place = placeParams(chosenPlace, chosenPlace && (page === 'spots' ? chosenPlace.id : chosenPlace.name));
    if (!place) return url;
    return `${url}${url.includes('?') ? '&' : '?'}${place}`;
}

function plural(count, word) {
    return `${count} ${word}${count > 1 ? 's' : ''}`;
}

function totalCard(value, label, href) {
    const inner = `<strong>${value}</strong><span>${escapeHtml(label)}</span>`;
    return href ? `<a class="bilan-total" href="${href}">${inner}</a>` : `<div class="bilan-total">${inner}</div>`;
}

// Une ligne : libellé, barre proportionnelle au plus gros chiffre du bloc, nombre, lien éventuel.
function rows(items, href) {
    const max = Math.max(1, ...items.map(item => item.n));
    return items.map(item => {
        const label = escapeHtml(item.label);
        const link = href && href(item);
        return `
        <div class="bilan-row ${item.n === 0 ? 'is-empty' : ''}">
            <span class="bilan-row__label">${link ? `<a href="${link}">${label}</a>` : label}</span>
            <span class="bilan-row__bar"><span style="width:${(item.n / max) * 100}%"></span></span>
            <span class="bilan-row__n">${item.n}</span>
        </div>`;
    }).join('');
}

// Les SHOWN_ROWS premières lignes, puis les autres repliées sous « Voir les … autres … ». plural et single : la fin
// du lien, « autres villes » / « l'autre ville ».
function foldedRows(items, plural, single) {
    const others = items.slice(SHOWN_ROWS);
    return rows(items.slice(0, SHOWN_ROWS)) + (others.length ? `
        <details class="bilan-more">
            <summary>${others.length > 1 ? `Voir les ${others.length} ${plural}` : `Voir ${single}`}</summary>
            ${rows(others)}
        </details>` : '');
}

function showBlock(id, rowsId, html) {
    document.getElementById(rowsId).innerHTML = html;
    document.getElementById(id).style.display = html ? '' : 'none';
}

// Le tableau des notes des propositions (carte #201) : une ligne par catégorie, les trois pertinences en colonnes,
// les raisons d'erreur à la suite, de la plus fréquente à la plus rare. Rien de noté : le bloc reste caché.
function renderRatings(categories) {
    const block = document.getElementById('ratingsBlock');
    block.style.display = categories && categories.length ? '' : 'none';
    if (!categories || !categories.length) return;
    const head = categories[0].pertinences.map(item => `<th>${escapeHtml(item.label)}</th>`).join('');
    const lines = categories.map(category => `
        <tr>
            <th scope="row">${escapeHtml(category.label)}</th>
            <td>${category.n}</td>
            ${category.pertinences.map(item => `<td>${item.n}</td>`).join('')}
            <td>${category.raisons.map(item => `${escapeHtml(item.label)} (${item.n})`).join(' · ') || '—'}</td>
        </tr>`).join('');
    document.getElementById('ratingsTable').innerHTML = `
        <thead><tr><th>Catégorie</th><th>Notées</th>${head}<th>Raisons des erreurs</th></tr></thead>
        <tbody>${lines}</tbody>`;
}

// Ce qu'il y a : les spots et les services de toute la base, ou de la ville choisie, comptés comme dans « Modifier ».
function renderPlace(place) {
    document.getElementById('placeTitle').textContent =
        chosenPlace ? `Ce qu'il y a à ${place.lieu}` : `Ce qu'il y a dans ${place.lieu}`;
    const spots = place.spots;
    // Comme pour les services : ceux que le voyageur peut voir à l'étape 3, puis ceux qu'elle masque, par raison.
    document.getElementById('placeSpotsRows').innerHTML = rows([
        { label: 'Spots en tout', n: spots.total },
        { label: 'Proposés au voyageur', n: spots.proposes },
        ...spots.par_categorie,
        { label: 'Vérifiés', n: spots.verifies },
        { label: 'Non vérifiés', n: spots.non_verifies },
        { label: 'Masqués', n: spots.masques },
        ...spots.masques_par_raison,
    ]);
    const services = place.services;
    document.getElementById('placeServicesRows').innerHTML = rows([
        { label: 'Services en tout', n: services.total },
        { label: 'Affichés au voyageur', n: services.affiches },
        { label: 'Masqués', n: services.masques },
        { label: 'Saisonniers', n: services.saisonniers },
    ]) + rows(services.par_type);
}

// Le garde-fou (plan de #186, 5.2) : les services masqués sans décision ni signal, un par ligne, avec leur numéro
// pour les retrouver dans Modifier. Aucun : le bloc reste caché.
function renderUntraced(untraced) {
    const html = untraced.map(service =>
        `<p>${escapeHtml(service.nom)} <span class="muted">(n° ${service.id})</span></p>`).join('');
    showBlock('untracedBlock', 'untracedRows', html);
}

function render(data) {
    const urls = window.APP_URLS;
    allCities = data.cities;
    allTowns = data.towns;
    // Le total des décisions et les notes restent ceux de toutes les villes : on le dit quand une ville est choisie.
    const everywhere = chosenPlace ? ' (toutes villes)' : '';
    document.getElementById('reviewsCount').textContent =
        data.total === 0 ? 'Rien à trancher' : `${plural(data.total, 'décision')} en attente au total`;

    document.getElementById('bilanTotals').innerHTML = [
        totalCard(data.total, 'à trancher en tout'),
        totalCard(data.spots.a_relire + data.spots.non_verifies, 'spots à trancher', withPlace(urls.supervision, 'spots')),
        totalCard(data.services.a_relire, 'services à relire', withPlace(urls.supervisionServices, 'services')),
        totalCard(data.decisions, `décisions déjà prises${everywhere}`),
    ].join('');

    const spots = data.spots;
    showBlock('spotsBlock', 'spotsRows', rows([
        { label: 'Retraits proposés par l\'agent, à relire', n: spots.a_relire,
          href: withPlace(`${urls.supervision}?probleme=retrait`, 'spots') },
        { label: 'Non vérifiés, à confirmer', n: spots.non_verifies,
          href: withPlace(`${urls.supervision}?probleme=non_verifie`, 'spots') },
        { label: 'Gardés par l\'administrateur', n: spots.gardes },
        { label: 'Retirés par l\'administrateur', n: spots.retires },
        { label: 'Ouvertures tranchées par l\'administrateur', n: spots.ouvertures },
    ], item => item.href));

    showBlock('servicesBlock', 'servicesRows',
        rows(data.services.files, file => withPlace(`${urls.supervisionServices}?tab=${encodeURIComponent(file.tab)}`, 'services')));
    // Les villes et les types les plus chargés d'abord ; les autres restent repliés.
    showBlock('citiesBlock', 'citiesRows', foldedRows(data.par_ville, 'autres villes', 'l\'autre ville'));
    showBlock('typesBlock', 'typesRows', foldedRows(data.services.par_type, 'autres types de service', 'l\'autre type de service'));
    renderPlace(data.ville);
    renderUntraced(data.masques_sans_trace);
    renderRatings(data.notation);
    document.getElementById('ratingsScope').textContent = everywhere;
}

// Montre l'une des deux vues : « pending » (à trancher) ou « global » (données globales). Les deux sont dessinées à
// chaque chargement ; le bouton ne fait que choisir celle qu'on voit, la ville choisie vaut pour les deux.
function setView(view) {
    const pending = view === 'pending';
    document.getElementById('viewPending').style.display = pending ? '' : 'none';
    document.getElementById('viewGlobal').style.display = pending ? 'none' : '';
    document.getElementById('viewPendingButton').className = `btn ${pending ? 'btn--primary' : 'btn--outline'}`;
    document.getElementById('viewGlobalButton').className = `btn ${pending ? 'btn--outline' : 'btn--primary'}`;
    document.getElementById('viewPendingButton').setAttribute('aria-pressed', pending);
    document.getElementById('viewGlobalButton').setAttribute('aria-pressed', !pending);
}

// Redessine le bilan avec la ville choisie.
async function load() {
    try {
        showMessage('');
        render(await supervisionCall(`/reviews/summary?${filterQuery()}`));
    } catch (error) {
        showMessage(error.message);
    }
}

// Au choix d'une ville ou d'une commune (supervision_ville.js) : on garde aussi son nom, pour les liens vers Services.
function choosePlace({ ville, commune }) {
    const city = allCities.find(item => String(item.id) === String(ville));
    chosenPlace = city ? { id: city.id, name: city.name } : commune ? { commune } : null;
    chooseCity({ ville, commune });
}

document.addEventListener('DOMContentLoaded', () => {
    if (redirectIfLoggedOut()) return;
    citySearch({ inputId: 'filterCitySearch', boxId: 'filterCitySuggestions', cityValue: city => city.id,
                 sources: () => ({ cities: allCities, towns: allTowns }), onChoose: choosePlace });
    load();
});

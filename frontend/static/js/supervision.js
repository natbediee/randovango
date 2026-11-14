// Supervision (admin) : la file de relecture. L'agent propose de retirer un spot, avec ses
// preuves ; l'admin tranche (services/supervision/spots_review.py). La sécurité est côté API :
// cette page ne fait que renvoyer à la connexion quand l'API refuse. Les fonctions communes aux pages de la
// supervision (showMessage, supervisionCall…) sont dans supervision_common.js.

// La clé de la note d'un spot (supervision_notation.js) : distincte de celles des services.
function spotKey(spotId) {
    return `spot-${spotId}`;
}

// Deux liens sont la même page, à une barre finale près (« …/place/1368 » et « …/place/1368/ »).
function sameLink(first, second) {
    return first.replace(/\/+$/, '') === second.replace(/\/+$/, '');
}

// Les liens pour vérifier soi-même : la page du spot (« Voir plus de détails »), puis les autres pages que l'agent cite
// comme preuves (« Source 1 », « Source 2 »…). Le nom du site d'où viennent les spots n'est jamais écrit sur le site.
// L'agent cite souvent la page du spot elle-même : 80 spots sur 212 n'avaient qu'elle comme source, et la carte
// montrait deux liens vers la même page (14 novembre 2026). Elle n'est montrée qu'une fois.
function spotLinks(review) {
    const others = review.sources.filter(url => !review.url || !sameLink(url, review.url));
    return [
        review.url ? `<a href="${escapeHtml(review.url)}" target="_blank" rel="noopener">Voir plus de détails</a>` : '',
        ...others.map((url, i) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">Source ${i + 1}</a>`),
    ].filter(Boolean).join('');
}

// L'en-tête d'une carte selon son problème : un retrait proposé par l'agent, ou un spot non vérifié à confirmer.
function problemBadge(problem) {
    return problem === 'non_verifie'
        ? '<span class="status-badge services-tag--teal">Non vérifié : à confirmer</span>'
        : '<span class="status-badge review-card__remove">Proposé : retirer</span>';
}

// Pourquoi le spot attend une décision. Un spot non vérifié n'a pas de raison de retrait : on montre le résumé de
// l'agent, qui dit ce qu'il n'a pas pu confirmer.
function whyText(review) {
    if (review.probleme === 'non_verifie') {
        return review.resume ? `<p><strong>Ce que l'agent n'a pas pu confirmer :</strong> ${escapeHtml(review.resume)}</p>` : '';
    }
    return `<p><strong>Pourquoi :</strong> ${escapeHtml(review.raison)}</p>`;
}

function reviewCard(review) {
    const reopening = review.reouverture ? `<p><strong>Réouverture annoncée :</strong> ${escapeHtml(review.reouverture)}</p>` : '';
    const comments = review.commentaires.map(c =>
        `<li><strong>${escapeHtml(c.date)}</strong> : ${escapeHtml(c.texte)}</li>`).join('');
    const links = spotLinks(review);
    return `
        <article class="review-card" data-spot="${review.objet_id}">
            <div class="review-card__body">
                <div class="spot-tags">
                    <span class="spot-type">Spot n° ${review.objet_id}</span>
                    ${problemBadge(review.probleme)}
                </div>
                <h2>${escapeHtml(review.nom)}</h2>
                ${whyText(review)}
                ${reopening}
                ${comments ? `<div class="review-card__proofs"><span>Derniers commentaires en base</span><ul>${comments}</ul></div>` : ''}
                <div class="review-card__links">${links}</div>
                <label class="label review-card__text">« À savoir » affiché si le spot est gardé (une phrase par ligne)
                    <textarea class="review-card__a-savoir" rows="3" data-agent="${escapeHtml(review.a_savoir)}">${escapeHtml(review.a_savoir)}</textarea>
                </label>
            </div>
            <div class="review-card__actions">
                ${ratingHtml(spotKey(review.objet_id))}
                <button class="btn review-card__btn-remove" onclick="decide(${review.objet_id}, 'retirer')">Retirer</button>
                <button class="btn btn--outline" onclick="decide(${review.objet_id}, 'garder')">Garder</button>
                <label class="label">Note (facultative)
                    <input type="text" class="review-card__note" maxlength="255" placeholder="Vu sur Street View">
                </label>
            </div>
        </article>`;
}

// Une date que la fiche ne donne pas est signalée comme convention ; un texte changé attend une relecture.
function openingLine(opening) {
    const reading = opening.statut === 'periode' ? `ouvert du ${opening.debut} au ${opening.fin}`
        : opening.statut === 'saison' ? 'ouvert du 01/04 au 31/10'
        : opening.statut === 'toute_annee' ? 'ouvert toute l\'année' : 'jamais masqué selon la saison';
    const changed = opening.texte_change
        ? `<br><strong>À relire : le texte de la fiche a changé</strong> (« ${escapeHtml(opening.texte_decide)} » devenu « ${escapeHtml(opening.texte)} »)`
        : '';
    const name = opening.url
        ? `<a href="${escapeHtml(opening.url)}" target="_blank" rel="noopener">${escapeHtml(opening.nom)}</a>`
        : escapeHtml(opening.nom);
    return `
        <p>${name} (n° ${opening.objet_id}) : <strong>${reading}</strong>
           ${opening.convention ? '· dates par convention' : ''}
           ${opening.texte ? `· fiche : « ${escapeHtml(opening.texte)} »` : ''}
           ${opening.note ? `· « ${escapeHtml(opening.note)} »` : ''} · ${escapeHtml(opening.par)}, le ${escapeHtml(opening.le)}
           · <a href="#" onclick="cancelDecision(${opening.id}); return false;">annuler</a>${changed}</p>`;
}

// --- Les filtres : catégorie (gratuit, payant, autres, comme à l'étape 3) et ville ou commune ---

const CATEGORY_LABELS = { gratuit: 'Gratuit', payant: 'Payant', autres: 'Autres' };
let allCities = [];   // les villes de l'appli qui ont des spots à relire, pour la recherche de ville
let allTowns = [];    // les communes des spots qui ne sont pas des villes de l'appli

// Les filtres choisis, à mettre dans l'adresse de GET /reviews/spots (seuls ceux qui ont une valeur).
function filterQuery() {
    const params = new URLSearchParams();
    const values = { ville: document.getElementById('filterCity').value, commune: document.getElementById('filterTown').value,
                     categorie: document.getElementById('filterCategory').value,
                     probleme: document.getElementById('filterProblem').value };
    Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
    return params.toString();
}

// Le menu des catégories, avec le nombre de spots à relire dans la ville choisie ; le choix affiché reste.
function renderCategories(categories) {
    const select = document.getElementById('filterCategory');
    const chosen = select.value;
    const total = categories.reduce((sum, category) => sum + category.nombre, 0);
    select.innerHTML = `<option value="">Toutes (${total})</option>` + categories.map(category =>
        `<option value="${category.code}" ${category.code === chosen ? 'selected' : ''}>${CATEGORY_LABELS[category.code]} (${category.nombre})</option>`).join('');
}

// Le menu des problèmes (retrait proposé, non vérifié), avec leur nombre ; le choix affiché reste.
function renderProblems(problems) {
    const select = document.getElementById('filterProblem');
    const chosen = select.value;
    const total = problems.reduce((sum, problem) => sum + problem.nombre, 0);
    select.innerHTML = `<option value="">Tous (${total})</option>` + problems.map(problem =>
        `<option value="${problem.code}" ${problem.code === chosen ? 'selected' : ''}>${escapeHtml(problem.label)} (${problem.nombre})</option>`).join('');
}

function render(data) {
    setRatingLabels(data.notation);
    allCities = data.cities;
    allTowns = data.towns;
    renderCategories(data.categories);
    renderProblems(data.problemes);
    const count = data.reviews.length;
    document.getElementById('reviewsCount').textContent =
        count === 0 ? 'Rien à relire' : `${count} décision${count > 1 ? 's' : ''} en attente`;
    document.getElementById('reviewsList').innerHTML = data.reviews.map(reviewCard).join('');
    // Rien avec ces filtres, alors qu'il reste des spots ailleurs : on le dit, pour ne pas croire la file vide.
    document.getElementById('emptyNote').style.display = !count && filterQuery() ? '' : 'none';

    document.getElementById('recentSection').style.display = data.recent.length ? '' : 'none';
    document.getElementById('recentList').innerHTML = data.recent.map(d => `
        <p>${escapeHtml(d.nom)} : <strong>${d.decision === 'garder' ? 'gardé' : 'retiré'}</strong>
           ${d.note ? `· « ${escapeHtml(d.note)} »` : ''} · ${escapeHtml(d.par)}, le ${escapeHtml(d.le)}
           · <a href="#" onclick="cancelDecision(${d.id}); return false;">annuler</a></p>
        ${d.decision === 'garder' ? `
        <details class="supervision-recent__edit">
            <summary>Corriger le texte « À savoir »</summary>
            <textarea id="correct-${d.id}" rows="3">${escapeHtml(d.a_savoir)}</textarea>
            <button class="btn btn--outline btn--sm" onclick="correctText(${d.id})">Enregistrer</button>
        </details>` : ''}`).join('');

    document.getElementById('openingsSection').style.display = data.ouvertures.length ? '' : 'none';
    document.getElementById('openingsList').innerHTML = data.ouvertures.map(openingLine).join('');
}

async function decide(spotId, decision) {
    const card = document.querySelector(`[data-spot="${spotId}"]`);
    const note = card.querySelector('.review-card__note').value;
    const text = card.querySelector('.review-card__a-savoir');
    // Texte inchangé : rien à enregistrer, celui de l'agent reste.
    const aSavoir = text.value !== text.dataset.agent ? text.value : null;
    const recorded = await postDecision({ objet: 'spot', objet_id: spotId, decision, note, a_savoir: aSavoir,
                                          ...ratingOf(spotKey(spotId)) });
    if (recorded) forgetRating(spotKey(spotId));
}

// Le texte corrigé sous « Dernières décisions » (saveTextCorrection de supervision_common.js).
function correctText(decisionId) {
    return saveTextCorrection(decisionId, document.getElementById(`correct-${decisionId}`).value);
}

// Redessine la page avec la liste à jour et ses filtres (au chargement, après une décision ou une annulation).
async function refresh() {
    render(await supervisionCall(`/reviews/spots?${filterQuery()}`));
}

// Un filtre changé : la liste se recharge (chooseCity de supervision_common.js l'appelle aussi).
async function load() {
    try {
        showMessage('');
        await refresh();
    } catch (error) {
        showMessage(error.message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (redirectIfLoggedOut()) return;
    document.getElementById('filterCategory').addEventListener('change', load);
    document.getElementById('filterProblem').addEventListener('change', load);
    placeFromUrl();
    citySearch({ inputId: 'filterCitySearch', boxId: 'filterCitySuggestions', cityValue: city => city.id,
                 sources: () => ({ cities: allCities, towns: allTowns }), onChoose: chooseCity });
    load();
});

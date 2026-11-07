// Étape 5 : les pépites de Vany, des idées en plus de la journée (un lieu à ne pas
// rater, une expo, un concert ce soir-là...). L'API renvoie un état et des textes
// prêts à afficher (services/pepite_service.py, get_day_state) :
//   - 'recherche'    : aucune idée n'est encore prête, on redemande toutes les 5 s ;
//   - 'propositions' : des idées, chacune ajoutée ou non à la journée (plusieurs possibles),
//     en deux sections : les intemporels, puis ce qui dépend des dates du séjour. Tant que
//     "agenda_pending" est vrai, l'agenda peut encore en apporter : on continue de
//     redemander, sans bloquer le voyageur (il sera prévenu dans la barre du bas s'il part) ;
//   - 'rien'         : Vany a cherché sans rien trouver de bon ;
//   - 'vide'         : pas de recherche pour ce jour (pas de spot choisi).
// Avec les idées viennent les lieux à voir en chemin sur la rando ("trail_tips"), recommandés
// par Vany dès l'étape 2 : ici, seulement leurs pastilles sur la carte du jour.
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge → 3. Carte →
// 4. Chargement API (avec attente) → 5. Affichage → 6. Ajout/retrait et navigation.

const PEPITES_POLL_MS = 5000;
const PEPITES_MAX_POLLS = 132;  // 11 min, plus que le délai maximal de l'agent (find_pepites.py)

// --- 1. Contexte du séjour ---
const { planId, currentDay, selectedDays } = getTripContext();

let pepitesMap = null;
let ideaMarkers = [];   // marqueurs du spot, des idées et des lieux en chemin, redessinés à chaque état
let markersByIdea = {}; // id d'idée -> marqueur, pour le bouton « Voir »
// Cadrage : d'abord sur la journée (spot et rando) pendant que Vany cherche, puis
// une seconde fois à l'arrivée des idées. Jamais plus, pour ne pas ramener la carte
// toutes les 5 s si l'utilisateur l'a déplacée.
let framedOn = null;   // null, 'journee' ou 'idees'
let lastRendered = null; // dernier état affiché : on ne redessine pas s'il n'a pas changé (bulle ouverte, lecture...)

document.addEventListener('DOMContentLoaded', async function () {
    const cityId = requireCity();
    if (!cityId) return;

    // --- 2. Badge ---
    showDayBadge(currentDay, selectedDays);

    // --- 3. Carte : la rando du jour (tracé) ; le spot et les idées arrivent avec l'API ---
    pepitesMap = await createStepMap(48.4, -4.5, 12);
    await addChosenHikeToMap(pepitesMap, cityId, localStorage.getItem('selectedHiking'), currentDay);

    // Arrivé par le rappel de la barre du bas : la sortie ramène au jour en préparation.
    // Sinon, c'est le jour en préparation : le rappel pourra désormais le concerner.
    if (vanyNewsReturn()) showReturnFromNews();
    else markPepitesVisited(planId, currentDay);

    // --- 4. Chargement API ---
    loadPepites();
});

async function loadPepites(polls = 0) {
    try {
        const state = await apiGet(`/api/pepites/?plan_id=${planId}&day_number=${currentDay}`);
        const waiting = state.state === 'recherche' || state.agenda_pending;
        if (waiting && polls >= PEPITES_MAX_POLLS) {
            // L'agent a dépassé son délai maximal : on arrête d'annoncer une recherche.
            renderPepites(state.state === 'recherche' ? { state: 'vide' } : { ...state, agenda_pending: false });
            return;
        }
        renderPepites(state);
        if (waiting) setTimeout(() => loadPepites(polls + 1), PEPITES_POLL_MS);
    } catch (err) {
        console.error('Erreur pépites:', err);
        renderPepites({ state: 'vide' });
    }
}

function showReturnFromNews() {
    const saved = vanyNewsReturn();
    if (!saved) return;
    const toCarnet = saved.url === window.APP_URLS.results;
    document.getElementById('mainExitLabel').textContent =
        toCarnet ? 'Retour au carnet' : `Retour à ton jour ${saved.context.currentDay}`;
    document.getElementById('skipBtn').remove();
    document.querySelector('.step-nav__back').addEventListener('click', event => {
        event.preventDefault();
        goToNextDayOrResults();
    });
}

// --- 5. Affichage ---

// Fiche d'une idée, sur le modèle des fiches spot et service des étapes 3 et 4 :
// numéro (repris sur la carte), étiquettes et texte à gauche ; « Voir » et
// « Ajouter » / « Retirer » à droite.
function ideaCard(idea, number) {
    const top = idea.top ? '<span class="status-badge top">Le coup de cœur de Vany</span>' : '';
    const meteo = idea.meteo_a_verifier
        ? '<p class="pepite-meteo"><i class="fas fa-cloud-sun"></i> Météo à revérifier la veille</p>' : '';
    const why = idea.why
        ? `<p class="pepite-why"><i class="pepite-icon" aria-hidden="true"></i>${escapeHtml(idea.why)}</p>` : '';
    const approx = idea.position_approx
        ? '<p class="spot-address"><i class="fas fa-location-dot"></i> Emplacement approximatif sur la carte</p>' : '';
    const source = idea.source_url
        ? `<p class="spot-address"><a href="${escapeHtml(idea.source_url)}" target="_blank" rel="noopener">Source : ${escapeHtml(idea.source_label)}</a></p>` : '';
    return `
        <div class="spot-card${idea.added ? ' selected' : ''}">
            <div class="spot-content-grid">
                <div class="spot-center">
                    <div class="spot-tags">
                        <span class="pepite-num">${number}</span>
                        <span class="spot-type">${escapeHtml(idea.type_label)}</span>
                        ${top}
                    </div>
                    <h4>${escapeHtml(idea.nom)}</h4>
                    ${why}
                    <p class="spot-address">${escapeHtml(idea.meta_label)}</p>
                    <p class="spot-description">${escapeHtml(idea.description)}</p>
                    ${meteo}${approx}${source}
                </div>
                <div class="spot-right">
                    <button class="btn btn-outline btn-sm" onclick="showIdeaOnMap(${idea.id})">
                        <i class="fas fa-map"></i> Voir
                    </button>
                    <button class="btn ${idea.added ? 'btn-selected' : 'btn-primary'} btn-sm"
                        onclick="setAdded(${idea.id}, ${!idea.added})">
                        ${idea.added ? 'Retirer' : 'Ajouter'}
                    </button>
                </div>
            </div>
        </div>`;
}

// Les idées de la section, ou l'encadré d'attente tant que l'agenda peut en apporter.
function sectionHtml(title, css, ideas, firstNumber, pendingHtml = '') {
    if (!ideas.length && !pendingHtml) return '';
    return `<h2 class="pepites-section ${css}">${title}</h2>`
        + ideas.map((idea, i) => ideaCard(idea, firstNumber + i)).join('') + pendingHtml;
}

function renderPepites(state) {
    const fingerprint = JSON.stringify(state);
    if (fingerprint === lastRendered) return;
    lastRendered = fingerprint;

    const list = document.getElementById('pepitesList');
    const img = document.getElementById('pepitesImg');
    const ideas = state.ideas || [];

    if (state.title) document.getElementById('pepitesTitle').textContent = state.title;
    if (state.intro) document.getElementById('pepitesIntro').textContent = state.intro;
    img.src = ideas.length ? img.dataset.imgIdeas : img.dataset.imgSearching;

    if (state.state === 'recherche') {
        document.getElementById('pepitesIntro').textContent =
            'Vany cherche autour de ton spot et de ta rando. Tu peux aussi continuer sans attendre :'
            + ' il te préviendra dans la barre du bas.';
        list.innerHTML = '<div class="pepite-skeleton"><span></span><span></span><span></span></div>'.repeat(3);
    } else if (state.state === 'vide') {
        document.getElementById('pepitesIntro').textContent =
            'Pas d\'idée de Vany pour cette journée : choisis un spot pour la nuit pour qu\'il puisse chercher autour.';
        list.innerHTML = '';
    } else if (state.state === 'rien') {
        list.innerHTML = '';
    } else {
        const removed = state.removed
            ? `<div class="pepite-removed">« ${escapeHtml(state.removed)} » ne tient plus avec les changements de ce jour : elle est retirée de ton planning.</div>`
            : '';
        const always = ideas.filter(i => i.section === 'saison');
        const dated = ideas.filter(i => i.section === 'sejour');
        const pending = state.agenda_pending ? `
            <div class="pepites-pending">
                <i class="pepite-icon" aria-hidden="true"></i>
                <div>
                    <strong>Vany cherche ce qui se passe pendant ton séjour…</strong>
                    <p>Marchés, concerts, expositions, cinéma. Tu peux continuer : il te préviendra dans la barre du bas.</p>
                </div>
            </div>` : '';
        list.innerHTML = removed
            + sectionHtml('À voir en toute saison', 'pepites-section--saison', always, 1)
            + sectionHtml('Pendant ton séjour', 'pepites-section--sejour', dated, always.length + 1, pending);
        // Le voyageur a ces idées sous les yeux : pas de rappel dans la barre du bas.
        if (ideas.length) apiPut(`/api/pepites/seen/${planId}`, { day_number: currentDay }).catch(() => {});
    }

    renderCount(ideas.filter(i => i.added).length);
    drawMap(state, ideas);
}

// Compteur en bas de page ; « Continuer sans » n'a plus de sens dès qu'une idée est ajoutée.
function renderCount(addedCount) {
    document.getElementById('pepitesCount').textContent = addedCount === 0 ? ''
        : addedCount === 1 ? '1 pépite ajoutée' : `${addedCount} pépites ajoutées`;
    const skip = document.getElementById('skipBtn');
    if (skip) skip.style.display = addedCount === 0 ? '' : 'none';
}

// Spot, idées numérotées et lieux en chemin ; cadrage sur la journée puis sur les idées.
function drawMap(state, ideas) {
    if (!pepitesMap) return;
    ideaMarkers.forEach(m => pepitesMap.removeLayer(m));
    ideaMarkers = [];
    markersByIdea = {};
    const positions = [];

    if (state.spot && state.spot.latitude) {
        const pos = [state.spot.latitude, state.spot.longitude];
        ideaMarkers.push(L.marker(pos, { icon: buildSpotDivIcon(`J${currentDay}`), zIndexOffset: 500 })
            .bindPopup(`<b>${escapeHtml(state.spot.name)}</b>`));
        positions.push(pos);
    }
    ideas.forEach((idea, i) => {
        const pos = [idea.latitude, idea.longitude];
        const marker = L.marker(pos, { icon: buildPepiteIcon(i + 1), zIndexOffset: 800 })
            .bindPopup(`<b>${escapeHtml(idea.nom)}</b><br>${escapeHtml(idea.meta_label)}`
                       + (idea.position_approx ? '<br><i>Emplacement approximatif</i>' : ''));
        markersByIdea[idea.id] = marker;
        ideaMarkers.push(marker);
        positions.push(pos);
    });
    (state.trail_tips || []).forEach(tip => {
        ideaMarkers.push(L.marker([tip.latitude, tip.longitude], { icon: buildTrailTipIcon() })
            .bindPopup(`<b>${escapeHtml(tip.nom)}</b><br>En chemin sur ta rando`));
    });
    ideaMarkers.forEach(m => m.addTo(pepitesMap));

    const stage = ideas.length > 0 ? 'idees' : 'journee';
    if (positions.length > 0 && framedOn !== stage && framedOn !== 'idees') {
        const bounds = L.latLngBounds(positions);
        // Le tracé de la rando du jour (dessiné par addChosenHikeToMap) entre dans le cadre.
        pepitesMap.eachLayer(layer => {
            if (layer instanceof L.Polyline) bounds.extend(layer.getBounds());
        });
        pepitesMap.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        framedOn = stage;
    }
}

// --- 6. Ajout/retrait et navigation (appelés par les boutons de la page) ---

// Bouton « Voir » d'une idée : centre la carte sur elle et ouvre sa bulle.
function showIdeaOnMap(ideaId) {
    const marker = markersByIdea[ideaId];
    if (!pepitesMap || !marker) return;
    pepitesMap.setView(marker.getLatLng(), 15, { animate: true });
    marker.openPopup();
    document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Ajoute une idée à la journée ou l'en retire ; l'API renvoie l'état à jour.
async function setAdded(ideaId, added) {
    try {
        const response = await apiPut(`/api/pepites/choose/${planId}`,
                                      { day_number: currentDay, pepite_id: ideaId, added });
        renderPepites(await response.json());
    } catch (err) {
        console.error('Erreur ajout pépite:', err);
    }
}

// Fin de la journée : retour au carnet, qui propose de continuer sur la même ville
// ou d'en changer pour le jour suivant (voir stayInSameCity()/changeCityForNextDay()).
function goToNextDayOrResults() {
    // Visite d'un autre jour depuis le rappel de la barre du bas : retour à la page quittée.
    if (leaveVanyNews()) return;
    // Fin d'une édition de jour (lancée depuis le récap) : on restaure le jour de
    // progression réel et on nettoie les repères d'édition, pour revenir au récap
    // complet plutôt que de rester sur le jour édité (voir editDay dans results.js).
    const editingDay = localStorage.getItem('editingDay');
    if (editingDay) {
        const ret = localStorage.getItem('editReturnDay');
        if (ret) localStorage.setItem('currentDay', ret);
        localStorage.removeItem('editingDay');
        localStorage.removeItem('editReturnDay');
        localStorage.removeItem('editOriginalCity');
    }
    window.location.href = window.APP_URLS.results;
}

// Supervision, onglet « Modifier » (admin) : retrouver un service ou un spot vu dans l'appli et le corriger,
// même sans signal à relire (services/poi_edit_service.py, services/spot_edit_service.py).
// Chaque correction est une décision tracée : « Corrigé récemment » permet de l'annuler.
// La sécurité est côté API : le nom et les liens tapés y sont contrôlés.

const SERVICE_TABS = [['eau', 'Eau'], ['vidange', 'Vidange'], ['gasoil', 'Gasoil'], ['supermarche', 'Supermarché'],
                      ['commerce', 'Commerce'], ['restauration', 'Restauration'], ['cafe', 'Café, bar'], ['toilettes', 'Toilettes'],
                      ['hygiene', 'Hygiène'], ['laverie', 'Laverie'], ['culture', 'Culture & Loisirs'], ['urgence', 'Urgences'],
                      ['hors_etape4', 'Hors étape 4']];
const MONTHS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'];
const OPENINGS = [['toute_annee', "Toute l'année"], ['periode', 'Sur une période'], ['saison', 'Saisonnier, dates inconnues'],
                  ['inconnue', 'Inconnue']];

let mode = 'services';
let nameTimer = null;

function authToken() {
    return sessionStorage.getItem('jwtToken') || localStorage.getItem('userToken');
}

function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

function filters() {
    const values = { ville: document.getElementById('filterCity').value, nom: document.getElementById('filterName').value.trim() };
    if (mode === 'services') {
        values.service = document.getElementById('filterService').value;
        values.type = document.getElementById('filterType').value;
    }
    return values;
}

function filterQuery() {
    const params = new URLSearchParams();
    Object.entries(filters()).forEach(([key, value]) => { if (value) params.set(key, value); });
    return params.toString();
}

async function editFetch(path, options = {}) {
    const response = await fetch(`${window.API_BASE}/api/supervision/edit/${mode}${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken()}` },
    });
    if (response.status === 401) throw new Error('Ta session a expiré : reconnecte-toi, ta correction n\'a pas été enregistrée.');
    if (response.status === 403) throw new Error('Cette page est réservée aux comptes admin.');
    if (response.status === 422) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Correction refusée.');
    }
    if (!response.ok) throw new Error(`Erreur du serveur (HTTP ${response.status}) : correction non enregistrée.`);
    return response.json();
}

// Ce que la page envoie avec chaque correction : la recherche affichée, pour la renvoyer telle quelle.
function searchBody() {
    const values = filters();
    const city = values.ville ? Number(values.ville) : null;
    return mode === 'services' ? { ville: city, service: values.service, type: values.type, nom_recherche: values.nom }
                               : { ville: city, nom: values.nom };
}

function safeLink(url) {
    return /^https?:\/\//.test(url || '') ? escapeHtml(url) : null;
}

function mapsLink(saved, position) {
    if (safeLink(saved)) return safeLink(saved);
    return position ? `https://www.google.com/maps/search/?api=1&query=${position[0]},${position[1]}` : null;
}

function linkLine(label, url, text = url) {
    return url ? `<p><span class="muted">${label} :</span> <a href="${url}" target="_blank" rel="noopener">${escapeHtml(text)}</a></p>` : '';
}

function field(label, cls, button, placeholder, type = 'text', value = '') {
    return `<label class="label">${label}
        <span class="review-card__field">
            <input type="${type}" class="${cls}" maxlength="490" placeholder="${placeholder}" value="${escapeHtml(value)}">
            ${button}
        </span>
    </label>`;
}

// --- Services ---

function placeCard(card, buttons) {
    const has = action => card.actions.includes(action);
    const act = (action, label, style = 'btn--outline') =>
        `<button class="btn ${style} btn--sm" onclick="decidePlace(${card.poi_id}, '${action}')">${escapeHtml(label)}</button>`;
    const chips = MONTHS.map((label, index) => `
        <button type="button" class="services-chip ${card.months.includes(index) ? 'is-on' : ''}"
                aria-pressed="${card.months.includes(index)}" data-month="${index}" onclick="toggleMonth(this)">${label}</button>`).join('');
    const tab = (SERVICE_TABS.find(([key]) => key === card.onglet) || [, card.onglet])[1];
    const season = card.statut_saison === 'confirmee' ? 'Saisonnier' : card.statut_saison === 'probable' ? 'Saisonnier probable' : '';
    return `
        <article class="review-card review-card--wide" data-poi="${card.poi_id}">
            <div class="review-card__body">
                <div class="spot-tags">
                    <span class="spot-type">${escapeHtml(tab)}</span>
                    ${card.service ? `<span class="spot-type">${escapeHtml(card.service)}</span>` : ''}
                    ${card.masque ? '<span class="status-badge services-tag--red">Masqué</span>' : ''}
                    ${card.ferme_moment ? '<span class="status-badge services-tag--warn">Fermé pour le moment</span>' : ''}
                    ${season ? `<span class="status-badge services-tag--teal">${season}</span>` : ''}
                </div>
                <h2>${escapeHtml(card.nom)}</h2>
                <p class="muted">${escapeHtml(card.adresse || (card.commune ? `Commune : ${card.commune}` : 'Ni adresse ni commune connues'))}</p>
                <div class="review-card__links">
                    ${linkLine('Lien du lieu', safeLink(card.url_actuelle)) || '<p class="muted">Pas de lien.</p>'}
                    ${linkLine('Sur la carte', mapsLink(card.maps_actuel, card.position), card.maps_actuel ? 'Google Maps (saisi à la main)' : 'Google Maps')}
                </div>
                <div class="services-months"><span>Mois d'ouverture</span><div>${chips}</div></div>
            </div>
            <div class="review-card__actions">
                <div class="review-card__decisions">
                    ${has('retirer') ? `<button class="btn review-card__btn-remove" onclick="decidePlace(${card.poi_id}, 'retirer')">${buttons.retirer}</button>` : ''}
                    ${has('garder') ? act('garder', buttons.garder, 'btn--primary') : ''}
                    ${has('retirer_lien') ? act('retirer_lien', buttons.retirer_lien) : ''}
                    ${act('valider_saison', buttons.valider_saison)}
                    ${has('pas_saisonnier') ? act('pas_saisonnier', buttons.pas_saisonnier) : ''}
                </div>
                <div class="review-card__fields">
                    ${field('Autre nom', 'review-card__name', act('autre_nom', 'Renommer ainsi'), 'Le bon nom', 'text', card.nom)}
                    ${field('Autre lien', 'review-card__url', act('autre_lien', 'Mettre ce lien'), 'https://', 'url')}
                    ${field('Le bon lien Google Maps', 'review-card__maps', act('autre_maps', 'Mettre ce lien Google Maps'), 'https://maps.app.goo.gl/...', 'url')}
                    <label class="label">Note (facultative)
                        <input type="text" class="review-card__note" maxlength="255" placeholder="Vu sur place le 3 novembre">
                    </label>
                </div>
            </div>
        </article>`;
}

function renderServiceFilters(data) {
    const serviceSelect = document.getElementById('filterService');
    const chosen = serviceSelect.value;
    const counts = data.service_counts || {};
    const all = Object.values(counts).reduce((sum, count) => sum + count, 0);
    serviceSelect.innerHTML = `<option value="">Tous (${all})</option>` + SERVICE_TABS
        .filter(([key]) => counts[key] || key === chosen)
        .map(([key, label]) => `<option value="${key}" ${key === chosen ? 'selected' : ''}>${escapeHtml(label)} (${counts[key] || 0})</option>`).join('');
    const typeSelect = document.getElementById('filterType');
    const chosenType = typeSelect.value;
    const byType = data.type_counts || {};
    const types = Object.keys(byType).sort((a, b) => byType[b] - byType[a] || a.localeCompare(b));
    const typeLabel = document.getElementById('filterTypeLabel');
    if (chosen && (types.length > 1 || chosenType)) {
        const inTab = Object.values(byType).reduce((sum, count) => sum + count, 0);
        typeSelect.innerHTML = `<option value="">Tous (${inTab})</option>` + types.map(name =>
            `<option value="${escapeHtml(name)}" ${name === chosenType ? 'selected' : ''}>${escapeHtml(name || 'Sans type')} (${byType[name]})</option>`).join('');
        typeLabel.style.display = '';
    } else {
        typeSelect.innerHTML = '<option value="">Tous</option>';
        typeLabel.style.display = 'none';
    }
}

function decidePlace(poiId, action) {
    const card = document.querySelector(`[data-poi="${poiId}"]`);
    const months = [...card.querySelectorAll('.services-chip.is-on')].map(chip => Number(chip.dataset.month));
    const url = card.querySelector(action === 'autre_maps' ? '.review-card__maps' : '.review-card__url').value.trim();
    send('/decisions', 'POST', { poi_id: poiId, action, note: card.querySelector('.review-card__note').value, mois: months,
                                 url: url || null, nom: card.querySelector('.review-card__name').value.trim(), ...searchBody() });
}

function toggleMonth(button) {
    const on = button.classList.toggle('is-on');
    button.setAttribute('aria-pressed', on);
}

// --- Spots ---

function spotCard(card) {
    const opening = card.ouverture;
    const options = OPENINGS.map(([key, label]) =>
        `<option value="${key}" ${key === opening.statut ? 'selected' : ''}>${label}</option>`).join('');
    const badge = card.statut === 'retire' || card.statut === 'propose' ? 'red' : card.statut === 'garde' ? 'teal' : 'warn';
    const decided = card.decision_id
        ? `<p class="muted">Décision en vigueur : <strong>${card.decision === 'retirer' ? 'retiré' : 'gardé'}</strong>
             · <a href="#" onclick="cancelSpot(${card.decision_id}); return false;">annuler</a>
             · <a href="#" onclick="correctText(${card.spot_id}, ${card.decision_id}); return false;">corriger seulement le texte</a></p>`
        : '';
    return `
        <article class="review-card review-card--wide" data-spot="${card.spot_id}">
            <div class="review-card__body">
                <div class="spot-tags">
                    ${card.type ? `<span class="spot-type">${escapeHtml(card.type)}</span>` : ''}
                    <span class="status-badge services-tag--${badge}">${escapeHtml(card.statut_label)}</span>
                    ${card.verifie ? '<span class="status-badge services-tag--teal">Vérifié</span>' : ''}
                    ${card.nuit_interdite ? '<span class="status-badge services-tag--red">Nuit interdite</span>' : ''}
                </div>
                <h2>${escapeHtml(card.nom)}</h2>
                <div class="review-card__links">
                    ${linkLine('Fiche du spot', safeLink(card.url))}
                    ${linkLine('Sur la carte', mapsLink(null, card.position), 'Google Maps')}
                </div>
                ${decided}
                <label class="label">À savoir (une phrase par ligne, vide s'il n'y a rien à signaler)
                    <textarea class="review-card__text" rows="3" style="width:100%; font:inherit; font-size:13px;">${escapeHtml(card.a_savoir)}</textarea>
                </label>
                <p class="muted" style="font-size:13px;">Ouverture lue sur la fiche : ${escapeHtml(opening.texte || 'rien')}</p>
            </div>
            <div class="review-card__actions">
                <div class="review-card__decisions">
                    <button class="btn btn--primary" onclick="decideSpot(${card.spot_id}, 'garder')">Garder (vérifié)</button>
                    <button class="btn review-card__btn-remove" onclick="decideSpot(${card.spot_id}, 'retirer')">Retirer le spot</button>
                </div>
                <div class="review-card__fields">
                    <label class="label">Ouverture
                        <select class="spot-opening" style="min-height:34px;">${options}</select>
                    </label>
                    <label class="label">Du (JJ/MM)
                        <input type="text" class="spot-start" maxlength="5" placeholder="01/04" value="${escapeHtml(opening.debut)}">
                    </label>
                    <label class="label">Au (JJ/MM)
                        <input type="text" class="spot-end" maxlength="5" placeholder="31/10" value="${escapeHtml(opening.fin)}">
                    </label>
                    <label class="label"><span><input type="checkbox" class="spot-convention"> Dates choisies par moi, la fiche ne les donne pas</span></label>
                    <button class="btn btn--outline btn--sm" onclick="decideOpening(${card.spot_id})">Fixer l'ouverture</button>
                    ${opening.decision_id ? `<a href="#" onclick="cancelOpening(${opening.decision_id}); return false;">annuler l'ouverture fixée</a>` : ''}
                    <label class="label">Note (facultative)
                        <input type="text" class="review-card__note" maxlength="255" placeholder="Vu sur place le 3 novembre">
                    </label>
                </div>
            </div>
        </article>`;
}

function spotText(spotId) {
    return document.querySelector(`[data-spot="${spotId}"] .review-card__text`);
}

function decideSpot(spotId, decision) {
    const card = document.querySelector(`[data-spot="${spotId}"]`);
    const text = spotText(spotId);
    // Le texte n'est envoyé que s'il a été touché : sinon celui de l'agent reste.
    send('/decisions', 'POST', { spot_id: spotId, decision, note: card.querySelector('.review-card__note').value,
                                 a_savoir: text.value !== text.defaultValue ? text.value : null, ...searchBody() });
}

function correctText(spotId, decisionId) {
    send(`/decisions/${decisionId}`, 'PUT', { a_savoir: spotText(spotId).value, ...searchBody() });
}

function decideOpening(spotId) {
    const card = document.querySelector(`[data-spot="${spotId}"]`);
    send('/openings', 'POST', { spot_id: spotId, statut: card.querySelector('.spot-opening').value,
                                debut: card.querySelector('.spot-start').value, fin: card.querySelector('.spot-end').value,
                                convention: card.querySelector('.spot-convention').checked,
                                note: card.querySelector('.review-card__note').value, ...searchBody() });
}

function cancelSpot(decisionId) {
    send(`/decisions/${decisionId}?${filterQuery()}`, 'DELETE');
}

function cancelOpening(decisionId) {
    send(`/openings/${decisionId}?${filterQuery()}`, 'DELETE');
}

// --- Commun ---

function render(data) {
    const citySelect = document.getElementById('filterCity');
    const chosenCity = citySelect.value;
    citySelect.innerHTML = '<option value="">Choisir une ville</option>' + data.cities.map(city =>
        `<option value="${city.id}" ${String(city.id) === chosenCity ? 'selected' : ''}>${escapeHtml(city.name)}</option>`).join('');
    if (mode === 'services') renderServiceFilters(data);

    document.getElementById('cardsList').innerHTML = data.cards.map(card =>
        mode === 'services' ? placeCard(card, data.buttons) : spotCard(card)).join('');
    const empty = document.getElementById('emptyNote');
    empty.textContent = data.searched ? 'Aucun lieu ne correspond.' : 'Choisis une ville, ou tape au moins deux lettres du nom.';
    empty.style.display = data.cards.length ? 'none' : '';
    const more = document.getElementById('moreNote');
    more.textContent = `${data.cards.length} affichés sur ${data.total} : précise le nom ou le type pour voir les autres.`;
    more.style.display = data.total > data.cards.length ? '' : 'none';
    document.getElementById('reviewsCount').textContent = data.searched ? `${data.total} trouvé${data.total > 1 ? 's' : ''}` : '';

    document.getElementById('recentSection').style.display = data.recent.length ? '' : 'none';
    document.getElementById('recentList').innerHTML = data.recent.map(decision => {
        const cancel = mode === 'services' ? `cancelPlace(${decision.id})`
                     : decision.ouverture ? `cancelOpening(${decision.id})` : `cancelSpot(${decision.id})`;
        return `<p>${escapeHtml(decision.nom)} : <strong>${escapeHtml(decision.action)}</strong>
           ${decision.note ? `· « ${escapeHtml(decision.note)} »` : ''} · ${escapeHtml(decision.par)}, le ${escapeHtml(decision.le)}
           · <a href="#" onclick="${cancel}; return false;">annuler</a></p>`;
    }).join('');
}

function cancelPlace(decisionId) {
    send(`/decisions/${decisionId}?${filterQuery()}`, 'DELETE');
}

async function send(path, method, body = null) {
    try {
        showMessage('');
        render(await editFetch(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) }));
    } catch (error) {
        showMessage(error.message);
    }
}

async function load() {
    try {
        showMessage('');
        render(await editFetch(`?${filterQuery()}`));
    } catch (error) {
        showMessage(error.message);
    }
}

function setMode(next) {
    mode = next;
    document.getElementById('modeServices').className = `btn ${mode === 'services' ? 'btn--primary' : 'btn--outline'}`;
    document.getElementById('modeSpots').className = `btn ${mode === 'spots' ? 'btn--primary' : 'btn--outline'}`;
    document.getElementById('modeServices').setAttribute('aria-pressed', mode === 'services');
    document.getElementById('modeSpots').setAttribute('aria-pressed', mode === 'spots');
    document.getElementById('filterServiceLabel').style.display = mode === 'services' ? '' : 'none';
    document.getElementById('filterTypeLabel').style.display = 'none';
    document.getElementById('filterService').innerHTML = '<option value="">Tous</option>';
    document.getElementById('filterType').innerHTML = '<option value="">Tous</option>';
    load();
}

document.addEventListener('DOMContentLoaded', () => {
    if (!authToken()) {
        window.location.href = window.APP_URLS.contributorLogin;
        return;
    }
    document.getElementById('modeServices').addEventListener('click', () => setMode('services'));
    document.getElementById('modeSpots').addEventListener('click', () => setMode('spots'));
    document.getElementById('filterCity').addEventListener('change', load);
    document.getElementById('filterService').addEventListener('change', () => {
        document.getElementById('filterType').innerHTML = '<option value="">Tous</option>';
        load();
    });
    document.getElementById('filterType').addEventListener('change', load);
    // La recherche part quand on arrête de taper.
    document.getElementById('filterName').addEventListener('input', () => {
        clearTimeout(nameTimer);
        nameTimer = setTimeout(load, 350);
    });
    load();
});

// Supervision, onglet « Modifier » (admin) : retrouver un service ou un spot vu dans l'appli et le corriger,
// même sans signal à relire (services/poi_edit_service.py, services/spot_edit_service.py).
// Une liste compacte, une ligne par lieu ; un clic ouvre sa fiche complète (supervision_fiche.js pour les services).
// Chaque correction est une décision tracée : « Corrigé récemment » permet de l'annuler.
// La sécurité est côté API : tout ce qui est tapé y est contrôlé.

const SERVICE_TABS = [['eau', 'Eau'], ['vidange', 'Vidange'], ['gasoil', 'Gasoil'], ['supermarche', 'Supermarché'],
                      ['commerce', 'Commerce'], ['restauration', 'Restauration'], ['cafe', 'Café, bar'], ['toilettes', 'Toilettes'],
                      ['hygiene', 'Hygiène'], ['laverie', 'Laverie'], ['culture', 'Culture & Loisirs'], ['urgence', 'Urgences'],
                      ['hors_etape4', 'Hors étape 4']];
const OPENINGS = [['toute_annee', "Toute l'année"], ['periode', 'Sur une période'], ['saison', 'Saisonnier, dates inconnues'],
                  ['inconnue', 'Inconnue']];

let mode = 'services';
let nameTimer = null;
let openId = null;        // le lieu ou le spot dont la fiche est ouverte
let lastData = null;

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
    if (response.status === 422 || response.status === 404) {
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

// --- Services ---

function placeRow(card) {
    const tab = (SERVICE_TABS.find(([key]) => key === card.onglet) || [, card.onglet])[1];
    return `
        <button type="button" class="edit-row ${openId === card.poi_id ? 'is-open' : ''}" aria-expanded="${openId === card.poi_id}"
                onclick="togglePlace(${card.poi_id})">
            <span class="edit-row__name">${escapeHtml(card.nom)}</span>
            ${ficheId('poi', card.poi_id)}
            <span class="spot-type">${escapeHtml(card.service || tab)}</span>
            ${card.masque ? '<span class="status-badge services-tag--red">Masqué</span>' : ''}
            ${card.statut_saison ? '<span class="status-badge services-tag--teal">Saisonnier</span>' : ''}
            <span class="edit-row__place">${escapeHtml(card.commune || card.adresse)}</span>
            <i class="fas fa-chevron-${openId === card.poi_id ? 'up' : 'down'}" aria-hidden="true"></i>
        </button>
        ${openId === card.poi_id ? `<div class="edit-open" id="openSheet"><p class="muted">Chargement de la fiche…</p></div>` : ''}`;
}

function sheetBlock(view) {
    const key = `edit-${view.poi_id}`;
    return `
        ${ficheHtml(view, key)}
        <div class="fiche-actions">
            <button class="btn btn--primary" onclick="saveSheet(${view.poi_id})">Enregistrer</button>
            <button class="btn btn--outline" onclick="togglePlace(${view.poi_id})">Fermer</button>
            <span class="fiche-actions__spacer"></span>
            ${view.masque ? `<button class="btn btn--outline" onclick="decidePlace(${view.poi_id}, 'garder')">Remettre le lieu</button>`
                          : `<button class="btn review-card__btn-remove" onclick="decidePlace(${view.poi_id}, 'retirer')">Retirer le lieu</button>`}
        </div>`;
}

async function showSheet(poiId, view = null) {
    const box = document.getElementById('openSheet');
    if (!box) return;
    try {
        box.innerHTML = sheetBlock(view || await editFetch(`/fiche/${poiId}`));
    } catch (error) {
        box.innerHTML = `<p class="supervision-msg">${escapeHtml(error.message)}</p>`;
    }
}

function togglePlace(poiId) {
    openId = openId === poiId ? null : poiId;
    renderCards(lastData);
    if (openId) showSheet(openId);
}

async function saveSheet(poiId) {
    const key = `edit-${poiId}`;
    const changes = ficheChanges(key);
    if (!Object.keys(changes).length) {
        showMessage('Rien n\'a changé sur cette fiche.');
        return;
    }
    try {
        showMessage('');
        const data = await editFetch('/fiche', { method: 'POST', body: JSON.stringify({ poi_id: poiId, changes, note: ficheNote(key), ...searchBody() }) });
        render(data);
        showSheet(poiId, data.fiche);
    } catch (error) {
        showMessage(error.message);
    }
}

function decidePlace(poiId, action) {
    const key = `edit-${poiId}`;
    send('/decisions', 'POST', { poi_id: poiId, action, note: ficheElement(key) ? ficheNote(key) : '', ...searchBody() });
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

// --- Spots ---

function spotRow(card) {
    const badge = card.statut === 'retire' || card.statut === 'propose' ? 'red' : card.statut === 'garde' ? 'teal' : 'warn';
    return `
        <button type="button" class="edit-row ${openId === card.spot_id ? 'is-open' : ''}" aria-expanded="${openId === card.spot_id}"
                onclick="toggleSpot(${card.spot_id})">
            <span class="edit-row__name">${escapeHtml(card.nom)}</span>
            ${ficheId('spot', card.spot_id)}
            ${card.type ? `<span class="spot-type">${escapeHtml(card.type)}</span>` : ''}
            <span class="status-badge services-tag--${badge}">${escapeHtml(card.statut_label)}</span>
            <i class="fas fa-chevron-${openId === card.spot_id ? 'up' : 'down'}" aria-hidden="true" style="margin-left:auto;"></i>
        </button>
        ${openId === card.spot_id ? `<div class="edit-open">${spotSheet(card)}</div>` : ''}`;
}

function openingLabel(opening) {
    if (opening.statut === 'toute_annee') return "Ouvert toute l'année";
    if (opening.statut === 'periode') return `Ouvert du ${opening.debut} au ${opening.fin}`;
    if (opening.statut === 'saison') return "Saisonnier, vérifie l'ouverture";
    return '';
}

// À gauche ce que voit le voyageur à l'étape 3, à droite ce qui se corrige : garder ou retirer, l'« À savoir », l'ouverture.
function spotSheet(card) {
    const opening = card.ouverture;
    const options = OPENINGS.map(([key, label]) =>
        `<option value="${key}" ${key === opening.statut ? 'selected' : ''}>${label}</option>`).join('');
    const lines = card.a_savoir ? card.a_savoir.split('\n').filter(Boolean) : [];
    const link = safeLink(card.url);
    const decided = card.decision_id
        ? `<p class="muted">Décision en vigueur : <strong>${card.decision === 'retirer' ? 'retiré' : 'gardé'}</strong>
             · <a href="#" onclick="cancelSpot(${card.decision_id}); return false;">annuler</a>
             · <a href="#" onclick="correctText(${card.spot_id}, ${card.decision_id}); return false;">corriger seulement le texte</a></p>`
        : '';
    return `
        <div class="fiche" data-spot="${card.spot_id}">
            <div class="fiche__preview">
                <p class="fiche__caption"><span>Ce que voit le voyageur à l'étape 3 ${ficheId('spot', card.spot_id)}</span></p>
                <div class="fiche-preview">
                    <div class="spot-tags">
                        ${card.type ? `<span class="spot-type">${escapeHtml(card.type)}</span>` : ''}
                        ${card.verifie ? '<span class="status-badge services-tag--teal">Vérifié</span>' : ''}
                        ${card.statut === 'retire' || card.statut === 'propose' ? '<span class="status-badge services-tag--red">Masqué : le voyageur ne le voit pas</span>' : ''}
                        ${card.nuit_interdite ? '<span class="status-badge services-tag--red">Nuit interdite</span>' : ''}
                    </div>
                    <h4>${escapeHtml(card.nom)}</h4>
                    ${lines.length ? `<p class="fiche-preview__line"><strong>À savoir :</strong></p><ul>${lines.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>` : ''}
                    ${openingLabel(opening) ? `<p class="fiche-preview__line"><i class="fas fa-sun"></i> ${escapeHtml(openingLabel(opening))}</p>` : ''}
                    ${link ? `<p class="fiche-preview__line"><a href="${link}" target="_blank" rel="noopener">Fiche du spot</a></p>` : ''}
                    <a class="btn btn--outline btn--sm" href="https://www.google.com/maps/search/?api=1&query=${card.position[0]},${card.position[1]}" target="_blank" rel="noopener">Voir sur Google Maps ↗</a>
                </div>
                <p class="muted" style="font-size:13px; margin-top:6px;">Ouverture lue sur la fiche : ${escapeHtml(opening.texte || 'rien')}</p>
            </div>
            <div class="fiche__form">
                ${decided}
                <label class="label">À savoir (une phrase par ligne, vide s'il n'y a rien à signaler)
                    <textarea class="spot-text" rows="4">${escapeHtml(card.a_savoir)}</textarea>
                </label>
                <div class="fiche__pair">
                    <label class="label">Ouverture
                        <select class="spot-opening">${options}</select>
                    </label>
                    <span></span>
                    <label class="label">Du (JJ/MM)
                        <input type="text" class="spot-start" maxlength="5" placeholder="01/04" value="${escapeHtml(opening.debut)}">
                    </label>
                    <label class="label">Au (JJ/MM)
                        <input type="text" class="spot-end" maxlength="5" placeholder="31/10" value="${escapeHtml(opening.fin)}">
                    </label>
                </div>
                <label class="label" style="flex-direction:row; align-items:center; gap:6px;"><input type="checkbox" class="spot-convention" style="width:auto; height:auto;"> Dates choisies par moi, la fiche ne les donne pas</label>
                <div>
                    <button class="btn btn--outline btn--sm" onclick="decideOpening(${card.spot_id})">Fixer l'ouverture</button>
                    ${opening.decision_id ? `<a href="#" onclick="cancelOpening(${opening.decision_id}); return false;">annuler l'ouverture fixée</a>` : ''}
                </div>
                <label class="label">Note (facultative)
                    <input type="text" class="spot-note" maxlength="255" placeholder="Vu sur place le 3 novembre">
                </label>
            </div>
        </div>
        <div class="fiche-actions">
            <button class="btn btn--primary" onclick="decideSpot(${card.spot_id}, 'garder')">Garder (vérifié)</button>
            <button class="btn btn--outline" onclick="toggleSpot(${card.spot_id})">Fermer</button>
            <span class="fiche-actions__spacer"></span>
            <button class="btn review-card__btn-remove" onclick="decideSpot(${card.spot_id}, 'retirer')">Retirer le spot</button>
        </div>`;
}

function toggleSpot(spotId) {
    openId = openId === spotId ? null : spotId;
    renderCards(lastData);
}

function spotElement(spotId) {
    return document.querySelector(`[data-spot="${spotId}"]`);
}

function decideSpot(spotId, decision) {
    const card = spotElement(spotId);
    const text = card.querySelector('.spot-text');
    // Le texte n'est envoyé que s'il a été touché : sinon celui de l'agent reste.
    send('/decisions', 'POST', { spot_id: spotId, decision, note: card.querySelector('.spot-note').value,
                                 a_savoir: text.value !== text.defaultValue ? text.value : null, ...searchBody() });
}

function correctText(spotId, decisionId) {
    send(`/decisions/${decisionId}`, 'PUT', { a_savoir: spotElement(spotId).querySelector('.spot-text').value, ...searchBody() });
}

function decideOpening(spotId) {
    const card = spotElement(spotId);
    send('/openings', 'POST', { spot_id: spotId, statut: card.querySelector('.spot-opening').value,
                                debut: card.querySelector('.spot-start').value, fin: card.querySelector('.spot-end').value,
                                convention: card.querySelector('.spot-convention').checked,
                                note: card.querySelector('.spot-note').value, ...searchBody() });
}

function cancelSpot(decisionId) {
    send(`/decisions/${decisionId}?${filterQuery()}`, 'DELETE');
}

function cancelOpening(decisionId) {
    send(`/openings/${decisionId}?${filterQuery()}`, 'DELETE');
}

// --- Commun ---

function renderCards(data) {
    if (!data) return;
    const list = document.getElementById('cardsList');
    list.className = data.cards.length ? 'edit-list' : '';
    list.innerHTML = data.cards.map(card => mode === 'services' ? placeRow(card) : spotRow(card)).join('');
}

function render(data) {
    lastData = data;
    const citySelect = document.getElementById('filterCity');
    const chosenCity = citySelect.value;
    citySelect.innerHTML = '<option value="">Choisir une ville</option>' + data.cities.map(city =>
        `<option value="${city.id}" ${String(city.id) === chosenCity ? 'selected' : ''}>${escapeHtml(city.name)}</option>`).join('');
    if (mode === 'services') renderServiceFilters(data);

    renderCards(data);
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
           ${decision.champs ? `(${escapeHtml(decision.champs)})` : ''}
           ${decision.note ? `· « ${escapeHtml(decision.note)} »` : ''} · ${escapeHtml(decision.par)}, le ${escapeHtml(decision.le)}
           · <a href="#" onclick="${cancel}; return false;">annuler</a></p>`;
    }).join('');
}

function cancelPlace(decisionId) {
    send(`/decisions/${decisionId}?${filterQuery()}`, 'DELETE');
}

// Après une correction, la fiche ouverte se recharge : elle montre ce que voit maintenant le voyageur.
async function send(path, method, body = null) {
    try {
        showMessage('');
        render(await editFetch(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) }));
        if (mode === 'services' && openId) showSheet(openId);
    } catch (error) {
        showMessage(error.message);
    }
}

async function load() {
    try {
        showMessage('');
        openId = null;
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

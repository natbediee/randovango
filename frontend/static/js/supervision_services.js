// Supervision des services (admin) : les vérifications proposent, l'admin tranche
// (services/poi_review_service.py). La sécurité est côté API : le lien ou le nom appliqués
// viennent du signal enregistré, cette page n'envoie que le choix. Seule exception : la fiche complète
// (supervision_fiche.js), corrigée par l'admin et contrôlée par l'API (poi_edit_service.decide_sheet).

const TABS = { fermetures: 'Doute sur le nom', liens: 'Liens', saison: 'Saison', doublons: 'Doublons', confirmer: 'À confirmer' };
// Les onglets de l'étape 4 (CATEGORY_META de step4_services.js), dans le même ordre, puis les services sans onglet :
// le voyageur ne les voit jamais. Seuls les onglets qui ont des lieux à relire sont proposés.
const SERVICE_TABS = [['eau', 'Eau'], ['vidange', 'Vidange'], ['gasoil', 'Carburant'], ['supermarche', 'Supermarché'],
                      ['commerce', 'Commerce'], ['restauration', 'Restauration'], ['cafe', 'Café, bar'], ['toilettes', 'Toilettes'],
                      ['hygiene', 'Hygiène'], ['laverie', 'Laverie'], ['culture', 'Culture & Loisirs'], ['urgence', 'Urgences'],
                      ['hors_etape4', "Hors étape 4"]];
// Hors du filtre : la règle tranche tous les liens morts, seule une décision annulée en ramène un, visible dans « Tous ».
const HIDDEN_TABS = { morts: 'Liens morts' };

// La page du bilan ouvre directement une file : /supervision/services?tab=liens.
const requestedTab = new URLSearchParams(window.location.search).get('tab');
let currentTab = requestedTab in TABS ? requestedTab : 'tous';
let currentCards = [];

function authToken() {
    return sessionStorage.getItem('jwtToken') || localStorage.getItem('userToken');
}

function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

function filters() {
    return { service: document.getElementById('filterService').value, type: document.getElementById('filterType').value,
             ville: document.getElementById('filterCity').value };
}

function filterQuery() {
    const params = new URLSearchParams({ tab: currentTab, ...filters() });
    return params.toString();
}

async function servicesFetch(path, options = {}) {
    const response = await fetch(`${window.API_BASE}/api/supervision/services${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken()}` },
    });
    if (response.status === 401) throw new Error('Ta session a expiré : reconnecte-toi, ta décision n\'a pas été enregistrée.');
    if (response.status === 403) throw new Error('Cette page est réservée aux comptes admin.');
    if (response.status === 422) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Décision refusée.');
    }
    if (!response.ok) throw new Error(`Erreur du serveur (HTTP ${response.status}) : décision non enregistrée.`);
    return response.json();
}

function safeLink(url) {
    return /^https?:\/\//.test(url || '') ? escapeHtml(url) : null;
}

// Une recherche Google sur le nom et l'adresse : pour l'admin seulement, nos agents n'ouvrent jamais Google.
function searchUrl(name, address) {
    return `https://www.google.com/search?q=${encodeURIComponent(`${name} ${address || ''}`.trim())}`;
}

// L'adresse, sinon la commune : un objet OSM n'a souvent pas d'adresse.
function where(card) {
    if (card.adresse) return card.adresse;
    return card.commune ? `Commune : ${card.commune} (pas d'adresse)` : 'Ni adresse ni commune connues';
}

// Les liens pour vérifier soi-même : la page de la proposition, le lien que le lieu affiche aujourd'hui, et une recherche.
function cardLinks(card) {
    const links = [];
    const proposed = safeLink(card.link);
    const current = safeLink(card.url_actuelle);
    if (proposed) links.push(['Page proposée', proposed]);
    if (current && card.url_actuelle !== card.link) links.push(['Lien actuel du lieu', current]);
    // Le lien Google Maps saisi à la main, sinon la position : c'est celui que le voyageur verra.
    const savedMaps = safeLink(card.maps_actuel);
    if (savedMaps) {
        links.push(['Voir sur la carte', savedMaps]);
    } else if (card.position) {
        const [lat, lon] = card.position;
        links.push(['Voir sur la carte', `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`]);
    }
    links.push(['Rechercher sur le web', searchUrl(card.nom, card.adresse || card.commune)]);
    return `<div class="review-card__links">${links.map(([label, url]) =>
        `<p><span class="muted">${label} :</span> <a href="${url}" target="_blank" rel="noopener">${label === 'Rechercher sur le web' ? escapeHtml(`${card.nom} ${card.adresse || card.commune}`)
            : label === 'Voir sur la carte' ? 'Google Maps' : url}</a></p>`).join('')}</div>`;
}

// Une station déclarée deux fois : l'autre station, à côté, avec ses prix (poi_edit_service.attach_sheets).
function twinStation(card) {
    const twin = card.station_voisine;
    if (!twin) return '';
    return `
        <div class="review-card__twin">
            <p class="fiche__caption"><span>L'autre station, à côté ${ficheId('poi', twin.poi_id)}</span></p>
            <p><strong>${escapeHtml(twin.nom)}</strong> <span class="muted">· ${escapeHtml(twin.adresse_etat)} · identifiant ${escapeHtml(twin.pdv_id)}
                · dernière déclaration ${escapeHtml(twin.derniere_declaration || 'jamais')}</span></p>
            ${ficheStationPrices(twin)}
        </div>`;
}

// La fiche d'un lieu dans une file : un lieu peut être dans deux files, la clé les sépare.
function cardKey(card) {
    return `${card.tab}-${card.poi_id}`;
}

// Corriger ici le champ que la file met en doute la tranche (poi_edit_service.CLOSING_FIELDS).
// « Enregistrer mes corrections » corrige la fiche ; seuls les autres boutons tranchent la file, sauf quand on corrige
// le champ qu'elle met en doute (poi_edit_service.CLOSING_FIELDS).
const CLOSING_HINTS = { fermetures: 'Corriger le nom dans la fiche tranche aussi ce doute.',
                        liens: 'Corriger le lien dans la fiche tranche aussi ce signal.',
                        saison: 'Corriger la saison dans la fiche la valide aussi.',
                        confirmer: "« Enregistrer mes corrections » garde le lieu à confirmer, caché au voyageur. « Confirmer et afficher le lieu » le montre au voyageur, avec tes corrections.",
                        doublons: 'Enregistrer mes corrections ne tranche pas le doublon.' };

function sheetKey(card) {
    return `rev-${cardKey(card)}`;
}

// En haut, ce qu'il faut vérifier et ce que disent les sources ; dessous, la même fiche que l'onglet « Modifier »,
// les champs mis en doute encadrés ; en bas, les décisions de la file.
function reviewCard(card) {
    const buttons = card.boutons.filter(button => !['autre_lien', 'autre_nom', 'autre_maps'].includes(button.action)).map(button => `
        <button class="btn ${button.style === 'main' ? 'btn--primary' : button.style === 'remove' ? 'review-card__btn-remove' : 'btn--outline'}"
                onclick="decide('${cardKey(card)}', '${button.action}')">${escapeHtml(button.label)}</button>`).join('');
    return `
        <article class="review-card review-card--wide" data-key="${cardKey(card)}" data-poi="${card.poi_id}" data-tab="${card.tab}">
            <div class="fiche-banner">
                <div class="spot-tags">
                    ${ficheId('poi', card.poi_id)}
                    <span class="spot-type">${escapeHtml(card.service)}</span>
                    <span class="spot-type">${escapeHtml(TABS[card.tab] || HIDDEN_TABS[card.tab] || card.tab)}</span>
                    <span class="status-badge services-tag--${card.gravite}">${escapeHtml(card.signal)}</span>
                </div>
                <p><strong>À vérifier : ${escapeHtml(card.proposal)}</strong></p>
                <ul>${card.preuves.map(proof => `<li><strong>${escapeHtml(proof.source)} :</strong> ${escapeHtml(proof.texte)}</li>`).join('')}</ul>
                ${cardLinks(card)}
            </div>
            ${twinStation(card)}
            ${card.fiche ? ficheHtml(card.fiche, sheetKey(card), card.a_verifier || [], true) : `<h2>${escapeHtml(card.nom)}</h2><p class="muted">${escapeHtml(where(card))}</p>`}
            <p class="supervision-msg fiche-msg" role="alert" style="display:none;"></p>
            <div class="fiche-actions">
                ${buttons}
                ${card.fiche ? `<button class="btn btn--outline" onclick="saveReviewSheet('${cardKey(card)}')">Enregistrer mes corrections</button>` : ''}
                ${CLOSING_HINTS[card.tab] ? `<span class="muted" style="font-size:13px;">${CLOSING_HINTS[card.tab]}</span>` : ''}
            </div>
        </article>`;
}

function renderAudit(sample) {
    const section = document.getElementById('auditSection');
    section.style.display = sample.length ? '' : 'none';
    document.getElementById('auditList').innerHTML = sample.map(item => {
        const link = safeLink(item.url);
        return `
        <div class="services-auto__row">
            <div class="services-auto__name">
                <strong>${escapeHtml(item.nom)}</strong> <span class="muted">· ${escapeHtml(item.adresse)}</span>
                ${item.signal ? `<p class="muted">La règle a lu : ${escapeHtml(item.signal)}</p>` : ''}
                ${link ? `<p><span class="muted">Lien actuel du lieu :</span> <a href="${link}" target="_blank" rel="noopener">${link}</a></p>`
                       : `<p><span class="muted">Pas de lien :</span> <a href="${searchUrl(item.nom, item.adresse)}" target="_blank" rel="noopener">rechercher sur Google</a></p>`}
            </div>
            <span class="spot-type">${escapeHtml(item.action)}</span>
            <button class="btn btn--outline btn--sm" onclick="confirmAudit(${item.id})">C'est juste</button>
            <button class="btn btn--outline btn--sm" onclick="cancelDecision(${item.id})">Annuler</button>
        </div>`;
    }).join('');
}

function render(data) {
    currentCards = data.cards;
    // « tous » est déjà la somme des files : l'ajouter aux autres compterait tout deux fois.
    const waiting = data.counts.tous;
    document.getElementById('reviewsCount').textContent =
        waiting === 0 ? 'Rien à relire' : `${waiting} décision${waiting > 1 ? 's' : ''} en attente`;
    // Le nombre de lieux par type, dans le problème et la ville choisis.
    const serviceSelect = document.getElementById('filterService');
    const chosenService = serviceSelect.value;
    const byService = data.service_counts || {};
    const allServices = Object.values(byService).reduce((sum, count) => sum + count, 0);
    serviceSelect.innerHTML = `<option value="">Tous (${allServices})</option>` + SERVICE_TABS
        .filter(([key]) => byService[key] || key === chosenService)
        .map(([key, label]) =>
            `<option value="${key}" ${key === chosenService ? 'selected' : ''}>${escapeHtml(label)} (${byService[key] || 0})</option>`).join('');
    // Le sous-filtre : les types précis de l'onglet choisi (Boulangerie, Marché...), seulement s'il y en a plusieurs.
    const typeSelect = document.getElementById('filterType');
    const chosenType = typeSelect.value;
    const byType = data.type_counts || {};
    const types = Object.keys(byType).sort((a, b) => byType[b] - byType[a] || a.localeCompare(b));
    const typeLabel = document.getElementById('filterTypeLabel');
    if (chosenService && (types.length > 1 || chosenType)) {
        const inTab = Object.values(byType).reduce((sum, count) => sum + count, 0);
        typeSelect.innerHTML = `<option value="">Tous (${inTab})</option>` + types.map(name =>
            `<option value="${escapeHtml(name)}" ${name === chosenType ? 'selected' : ''}>${escapeHtml(name || 'Sans type')} (${byType[name]})</option>`).join('');
        typeLabel.style.display = '';
    } else {
        typeSelect.innerHTML = '<option value="">Tous</option>';
        typeLabel.style.display = 'none';
    }

    document.getElementById('filterProblem').innerHTML = [['tous', 'Tous'], ...Object.entries(TABS)].map(([tab, label]) =>
        `<option value="${tab}" ${tab === currentTab ? 'selected' : ''}>${label} (${data.counts[tab]})</option>`).join('');

    const citySelect = document.getElementById('filterCity');
    const chosenCity = citySelect.value;
    citySelect.innerHTML = '<option value="">Toutes</option>' + data.cities.map(city =>
        `<option ${city === chosenCity ? 'selected' : ''}>${escapeHtml(city)}</option>`).join('');

    // Un lien à la fois : chaque fiche a son bouton Valider (le lot « à valider d'un coup » est retiré, 7 novembre 2026).
    document.getElementById('cardsList').innerHTML = data.cards.map(reviewCard).join('');
    document.getElementById('emptyNote').style.display = data.cards.length ? 'none' : '';

    const more = document.getElementById('moreNote');
    more.textContent = `${data.cards.length} lieux affichés sur ${data.total} : les suivants apparaîtront une fois ceux-ci traités.`;
    more.style.display = data.total > data.cards.length ? '' : 'none';

    renderAudit(data.audit);
    document.getElementById('recentSection').style.display = data.recent.length ? '' : 'none';
    document.getElementById('recentList').innerHTML = data.recent.map(decision => `
        <p>${escapeHtml(decision.nom)} : <strong>${escapeHtml(decision.action)}</strong>
           ${decision.note ? `· « ${escapeHtml(decision.note)} »` : ''} · ${escapeHtml(decision.par)}, le ${escapeHtml(decision.le)}
           · <a href="#" onclick="cancelDecision(${decision.id}); return false;">annuler</a></p>`).join('');
}

async function load() {
    try {
        showMessage('');
        render(await servicesFetch(`?${filterQuery()}`));
    } catch (error) {
        showMessage(error.message);
    }
}

function selectTab(tab) {
    currentTab = tab || 'tous';
    load();
}

async function send(tab, poiIds, action, note, months, url = null, name = null) {
    const card = document.querySelector(`[data-key="${tab}-${poiIds[0]}"]`);
    try {
        cardMessage(card, '');
        render(await servicesFetch('/decisions', {
            method: 'POST',
            body: JSON.stringify({ tab, vue: currentTab, poi_ids: poiIds, action, note, mois: months, url, nom: name, ...filters() }),
        }));
    } catch (error) {
        cardMessage(card, error.message);
    }
}

// Les changements de la fiche encore à enregistrer. Valider la saison lit les mois cochés dans la fiche : ils n'en sont pas.
function pendingChanges(card, action) {
    if (!card.querySelector('[data-fiche]')) return {};
    const changes = ficheChanges(`rev-${card.dataset.key}`);
    if (['valider_saison', 'pas_saisonnier'].includes(action)) {
        delete changes.statut_saison;
        delete changes.mois;
    }
    return changes;
}

function cardNote(card) {
    return card.querySelector('[data-fiche]') ? ficheNote(`rev-${card.dataset.key}`) : '';
}

// Le message d'une décision refusée, sous les boutons de la carte : en haut de la page, on ne le voyait pas.
function cardMessage(card, text) {
    showMessage(text);
    const box = card && card.querySelector('.fiche-msg');
    if (!box) return;
    box.textContent = text;
    box.style.display = text ? '' : 'none';
    if (text) box.scrollIntoView({ block: 'nearest' });
}

const NOTHING_CHANGED = "Rien n'a changé";

async function saveSheetRequest(card, changes) {
    return servicesFetch('/fiche', {
        method: 'POST',
        body: JSON.stringify({ tab: card.dataset.tab, vue: currentTab, poi_id: Number(card.dataset.poi), changes,
                               note: cardNote(card), ...filters() }),
    });
}

async function saveReviewSheet(key) {
    const card = document.querySelector(`[data-key="${key}"]`);
    const changes = pendingChanges(card, null);
    if (!Object.keys(changes).length) {
        cardMessage(card, 'Rien n\'a changé sur cette fiche.');
        return;
    }
    try {
        cardMessage(card, '');
        render(await saveSheetRequest(card, changes));
    } catch (error) {
        cardMessage(card, error.message);
    }
}

async function decide(key, action) {
    const card = document.querySelector(`[data-key="${key}"]`);
    const months = [...card.querySelectorAll('.services-chip.is-on')].map(chip => Number(chip.dataset.month));
    const changes = pendingChanges(card, action);
    if (Object.keys(changes).length) {
        if (action === 'valider_pepite') {
            // Le lieu est affiché avec la fiche corrigée : on l'enregistre d'abord.
            // « Rien n'a changé » : la fiche en base est déjà celle de la saisie, on confirme quand même.
            try {
                await saveSheetRequest(card, changes);
            } catch (error) {
                if (!error.message.startsWith(NOTHING_CHANGED)) {
                    cardMessage(card, `Confirmation arrêtée : ${error.message}`);
                    return;
                }
            }
        } else if (!['retirer', 'fusionner'].includes(action)) {
            cardMessage(card, 'Tu as modifié la fiche : clique d\'abord « Enregistrer mes corrections », ou recharge la page pour oublier tes modifications.');
            return;
        }
    }
    send(card.dataset.tab, [Number(card.dataset.poi)], action, cardNote(card), months);
}

async function confirmAudit(decisionId) {
    try {
        showMessage('');
        render(await servicesFetch(`/audit/${decisionId}?${filterQuery()}`, { method: 'POST' }));
    } catch (error) {
        showMessage(error.message);
    }
}

async function cancelDecision(decisionId) {
    try {
        showMessage('');
        render(await servicesFetch(`/decisions/${decisionId}?${filterQuery()}`, { method: 'DELETE' }));
    } catch (error) {
        showMessage(error.message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!authToken()) {
        window.location.href = window.APP_URLS.contributorLogin;
        return;
    }
    document.getElementById('filterService').addEventListener('change', () => {
        // Un autre onglet n'a pas les mêmes types : le sous-filtre repart de « Tous ».
        document.getElementById('filterType').innerHTML = '<option value="">Tous</option>';
        load();
    });
    document.getElementById('filterType').addEventListener('change', load);
    document.getElementById('filterCity').addEventListener('change', load);
    document.getElementById('filterProblem').addEventListener('change', event => selectTab(event.target.value));
    load();
});

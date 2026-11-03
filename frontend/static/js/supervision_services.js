// Supervision des services (admin) : les vérifications proposent, l'admin tranche
// (services/poi_review_service.py). La sécurité est côté API : le lien ou le nom appliqués
// viennent du signal enregistré, cette page n'envoie que le choix.

const TABS = { fermetures: 'Fermetures et reprises', liens: 'Liens', saison: 'Saison', morts: 'Liens morts' };
const MONTHS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'];

let currentTab = 'fermetures';
let currentCards = [];
const removedFromBatch = new Set();

function authToken() {
    return sessionStorage.getItem('jwtToken') || localStorage.getItem('userToken');
}

function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

function filters() {
    return { service: document.getElementById('filterService').value, ville: document.getElementById('filterCity').value };
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

function proofs(card) {
    return `<div class="review-card__proofs"><span>Ce que disent les sources</span><ul>${card.preuves.map(proof =>
        `<li><strong>${escapeHtml(proof.source)} :</strong> ${escapeHtml(proof.texte)}</li>`).join('')}</ul></div>`;
}

function monthChips(card) {
    if (card.tab !== 'saison') return '';
    const chips = MONTHS.map((label, index) => `
        <button type="button" class="services-chip ${card.months.includes(index) ? 'is-on' : ''}"
                aria-pressed="${card.months.includes(index)}" data-month="${index}"
                onclick="toggleMonth(this)">${label}</button>`).join('');
    return `<div class="services-months"><span>Mois d'ouverture</span><div>${chips}</div></div>`;
}

function reviewCard(card) {
    const link = safeLink(card.link);
    const buttons = card.boutons.map(button => `
        <button class="btn ${button.style === 'main' ? 'btn--primary' : button.style === 'remove' ? 'review-card__btn-remove' : 'btn--outline'}"
                onclick="decide(${card.poi_id}, '${button.action}')">${escapeHtml(button.label)}</button>`).join('');
    return `
        <article class="review-card" data-poi="${card.poi_id}">
            <div class="review-card__body">
                <div class="spot-tags">
                    <span class="spot-type">${escapeHtml(card.service)}</span>
                    <span class="status-badge services-tag--${card.gravite}">${escapeHtml(card.signal)}</span>
                </div>
                <h2>${escapeHtml(card.nom)}</h2>
                <p class="muted">${escapeHtml(card.adresse)}</p>
                <p><strong>Proposition :</strong> ${escapeHtml(card.proposal)}</p>
                ${proofs(card)}
                ${link ? `<div class="review-card__links"><a href="${link}" target="_blank" rel="noopener">${link}</a></div>` : ''}
                ${monthChips(card)}
            </div>
            <div class="review-card__actions">
                ${buttons}
                <label class="label">Note (facultative)
                    <input type="text" class="review-card__note" maxlength="255" placeholder="Appelé le 3 novembre">
                </label>
            </div>
        </article>`;
}

function renderBatch(cards) {
    const section = document.getElementById('autoSection');
    const kept = cards.filter(card => !removedFromBatch.has(card.poi_id));
    if (!cards.length) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';
    section.innerHTML = `
        <div class="services-auto__head">
            <div>
                <h2 class="services-title">Liens à valider d'un coup</h2>
                <p class="muted">Contrôlés par le code, ou indiqués dans OSM. Ôte ceux qui ne te plaisent pas, puis valide le reste.</p>
            </div>
            <button class="btn btn--primary" onclick="validateBatch()" ${kept.length ? '' : 'disabled'}>Valider les ${kept.length} liens</button>
        </div>
        <div>${cards.map(card => {
            const removed = removedFromBatch.has(card.poi_id);
            const link = safeLink(card.url);
            return `
            <div class="services-auto__row ${removed ? 'is-removed' : ''}">
                <div class="services-auto__name">
                    <strong>${escapeHtml(card.nom)}</strong> <span class="muted">· ${escapeHtml(card.adresse)}</span>
                    ${link ? `<a href="${link}" target="_blank" rel="noopener">${link}</a>` : ''}
                </div>
                <span class="spot-type">${escapeHtml(card.type_page)}</span>
                <span class="services-auto__proof">${escapeHtml(card.preuves[0].texte)}</span>
                <button class="btn btn--outline btn--sm" onclick="toggleBatch(${card.poi_id})">${removed ? 'Remettre' : 'Ôter'}</button>
            </div>`;
        }).join('')}</div>`;
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
                ${link ? `<a href="${link}" target="_blank" rel="noopener">${link}</a>` : ''}
            </div>
            <span class="spot-type">${escapeHtml(item.action)}</span>
            <button class="btn btn--outline btn--sm" onclick="confirmAudit(${item.id})">C'est juste</button>
            <button class="btn btn--outline btn--sm" onclick="cancelDecision(${item.id})">Annuler</button>
        </div>`;
    }).join('');
}

function render(data) {
    currentCards = data.cards;
    const waiting = Object.values(data.counts).reduce((sum, count) => sum + count, 0);
    document.getElementById('reviewsCount').textContent =
        waiting === 0 ? 'Rien à relire' : `${waiting} décision${waiting > 1 ? 's' : ''} en attente`;
    document.getElementById('servicesTabs').innerHTML = Object.entries(TABS).map(([tab, label]) => `
        <button role="tab" aria-selected="${tab === currentTab}" class="services-tab ${tab === currentTab ? 'is-on' : ''}"
                onclick="selectTab('${tab}')">${label} · ${data.counts[tab]}</button>`).join('');

    const citySelect = document.getElementById('filterCity');
    const chosenCity = citySelect.value;
    citySelect.innerHTML = '<option value="">Toutes</option>' + data.cities.map(city =>
        `<option ${city === chosenCity ? 'selected' : ''}>${escapeHtml(city)}</option>`).join('');

    const batch = currentTab === 'liens' ? data.cards.filter(card => card.auto) : [];
    const single = currentTab === 'liens' ? data.cards.filter(card => !card.auto) : data.cards;
    renderBatch(batch);
    document.getElementById('cardsTitle').style.display = currentTab === 'liens' && single.length ? '' : 'none';
    document.getElementById('cardsList').innerHTML = single.map(reviewCard).join('');
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
    currentTab = tab;
    load();
}

function toggleMonth(button) {
    const on = button.classList.toggle('is-on');
    button.setAttribute('aria-pressed', on);
}

function toggleBatch(poiId) {
    if (removedFromBatch.has(poiId)) removedFromBatch.delete(poiId);
    else removedFromBatch.add(poiId);
    renderBatch(currentCards.filter(card => card.auto));
}

async function send(poiIds, action, note, months) {
    try {
        showMessage('');
        render(await servicesFetch('/decisions', {
            method: 'POST',
            body: JSON.stringify({ tab: currentTab, poi_ids: poiIds, action, note, mois: months, ...filters() }),
        }));
    } catch (error) {
        showMessage(error.message);
    }
}

function decide(poiId, action) {
    const card = document.querySelector(`[data-poi="${poiId}"]`);
    const months = [...card.querySelectorAll('.services-chip.is-on')].map(chip => Number(chip.dataset.month));
    send([poiId], action, card.querySelector('.review-card__note').value, months);
}

function validateBatch() {
    const poiIds = currentCards.filter(card => card.auto && !removedFromBatch.has(card.poi_id)).map(card => card.poi_id);
    if (poiIds.length) send(poiIds, 'valider_lien', '', []);
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
    document.getElementById('filterService').addEventListener('change', load);
    document.getElementById('filterCity').addEventListener('change', load);
    load();
});

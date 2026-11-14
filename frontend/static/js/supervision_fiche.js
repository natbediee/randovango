// La fiche complète d'un service dans la supervision (8 novembre 2026), commune à l'onglet « Modifier »
// (supervision_modifier.js) et à la relecture (supervision_services.js).
// À gauche, ce que voit le voyageur à l'étape 4 ; à droite, tout ce qui se corrige. L'aperçu suit la saisie.
// La page n'envoie que les champs changés (ficheChanges) : l'API les contrôle et les enregistre en une décision
// annulable (services/supervision/services_edit.py, decide_sheet).
// Une station-service a sa fiche à elle (view.station, station_selection_service.station_view) : la carte de l'étape 4
// avec ses prix, ce que dit l'État, et seulement le nom, l'adresse et le lien Google Maps à corriger.

const FICHE_MONTHS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'];
const FICHE_FRENCH_MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
                             'octobre', 'novembre', 'décembre'];
const FICHE_SEASONS = [['', "Toute l'année"], ['probable', 'Saisonnier, mois inconnus'], ['confirmee', 'Saisonnier : mois cochés']];
const FICHE_TEXT_FIELDS = ['name', 'address', 'url', 'maps_url', 'texte', 'genre', 'categorie', 'distinction', 'jours'];
const FICHES = {};
// Les fiches repliables ouvertes (la relecture) : elles le restent quand la page se redessine après une décision.
const FICHES_OPEN = new Set();

// Le numéro du lieu (poi.id) ou du spot (spots.id), à donner aux agents : un clic le sélectionne pour le copier.
function ficheId(kind, id) {
    return `<span class="fiche-id" title="Numéro à donner aux agents">${kind} ${id}</span>`;
}

// La même phrase que l'étape 4 (restaurant_selection_service.season_label).
function ficheSeasonLabel(status, months) {
    const listed = [...new Set(months)].sort((a, b) => a - b);
    if (status === 'confirmee' && listed.length) {
        if (listed.length >= 12) return '';
        const first = listed.find(month => !listed.includes((month + 11) % 12));
        const last = listed.find(month => !listed.includes((month + 1) % 12));
        const start = FICHE_FRENCH_MONTHS[first];
        return `Ouvert ${'aeiouéo'.includes(start[0]) ? "d'" : 'de '}${start} à ${FICHE_FRENCH_MONTHS[last]}`;
    }
    return status ? "Saisonnier, vérifie l'ouverture" : '';
}

function ficheSafeLink(url) {
    return /^https?:\/\//.test(url || '') ? escapeHtml(url) : null;
}

function ficheMapsLink(values) {
    if (ficheSafeLink(values.maps_url)) return ficheSafeLink(values.maps_url);
    // Une station : le lien construit avec sa marque, celui de l'étape 4 (station_selection_service.station_maps_url).
    if (values.station && ficheSafeLink(values.station.maps_url)) return ficheSafeLink(values.station.maps_url);
    return values.position ? `https://www.google.com/maps/search/?api=1&query=${values.position[0]},${values.position[1]}` : null;
}

// Les pastilles de prix d'une station, comme à l'étape 4 (step4_services.js, fuelPricesHtml) : une date en ocre au-delà
// de 7 jours, une rupture en pointillés.
function ficheStationPrices(station) {
    if (!station.prix.length) return '<p class="fiche-preview__line muted">Aucun prix déclaré.</p>';
    const badges = station.prix.map(badge => `
        <span class="fuel-price${badge.ancien ? ' fuel-price--old' : ''}${badge.rupture ? ' fuel-price--out' : ''}">
            <span>${escapeHtml(badge.label)}</span>
            ${badge.rupture ? '<span>en rupture</span>' : `<b>${badge.prix.toFixed(3).replace('.', ',')} €</b>`}
            ${badge.ancien ? `<span class="fuel-price__date">${escapeHtml(badge.date_label)}</span>` : ''}
        </span>`).join('');
    return `<div class="fuel-prices">${badges}</div>` +
        (station.prix_resume ? `<p class="fuel-prices__summary">${escapeHtml(station.prix_resume)}</p>` : '');
}

// Ce que dit l'État d'une station : de quoi juger une station douteuse (etl/transform/transform_carburants.py).
function ficheStationState(station) {
    const osm = ficheSafeLink(station.osm_url);
    const silence = station.jours_sans_nouvelles === null ? 'jamais'
        : `${station.derniere_declaration} (il y a ${station.jours_sans_nouvelles} jour${station.jours_sans_nouvelles > 1 ? 's' : ''})`;
    return `
        <div class="fiche-station">
            <p class="fiche__caption"><span>Ce que dit l'État</span></p>
            <p class="fiche-preview__line">Identifiant ${escapeHtml(station.pdv_id)} · ${escapeHtml(station.adresse_etat || 'sans adresse')}</p>
            <p class="fiche-preview__line">Dernière déclaration : ${escapeHtml(silence)}</p>
            <p class="fiche-preview__line">${osm ? `Station OSM : <a href="${osm}" target="_blank" rel="noopener">${escapeHtml(station.osm_element)} ↗</a>`
                : 'Aucune station OSM reliée : le voyageur voit « Station-service », sans marque.'}</p>
        </div>`;
}

// L'aperçu d'une station : sa carte à l'étape 4.
function ficheStationPreview(values) {
    const station = values.station;
    const maps = ficheMapsLink(values);
    return `
        <div class="spot-tags">
            <span class="spot-type">Station-service</span>
            ${station.automate_24_24 ? '<span class="status-badge fuel-open">24h/24</span>' : ''}
            ${station.autoroute ? '<span class="status-badge fuel-open">Autoroute</span>' : ''}
            ${values.masque ? '<span class="status-badge services-tag--red">Masquée : le voyageur ne la voit pas</span>' : ''}
        </div>
        <h4>${escapeHtml(values.nom || 'Sans nom')}</h4>
        ${values.adresse ? `<p class="fiche-preview__line"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(values.adresse)}</p>` : ''}
        ${ficheStationPrices(station)}
        ${maps ? `<a class="btn btn--outline btn--sm" href="${maps}" target="_blank" rel="noopener">Voir sur Google Maps ↗</a>` : ''}`;
}

// L'aperçu : la carte de l'étape 4 (step4_services.js, renderCategory), avec les valeurs de la saisie.
function fichePreview(values) {
    if (values.station) return ficheStationPreview(values);
    const type = values.fiche.categories[values.categorie] || values.type_label;
    const season = ficheSeasonLabel(values.statut_saison, values.months);
    const site = ficheSafeLink(values.url);
    const maps = ficheMapsLink(values);
    return `
        <div class="spot-tags">
            ${type ? `<span class="spot-type">${escapeHtml(type)}</span>` : ''}
            <span class="status-badge services-tag--${values.verifie ? 'teal' : 'warn'}">${values.verifie ? 'Vérifié' : 'Non vérifié'}</span>
            ${values.masque ? '<span class="status-badge services-tag--red">Masqué : le voyageur ne le voit pas</span>' : ''}
        </div>
        <h4>${escapeHtml(values.nom || 'Sans nom')}</h4>
        ${values.adresse && !values.maps_url ? `<p class="fiche-preview__line"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(values.adresse)}</p>` : ''}
        ${values.texte ? `<p class="fiche-preview__text">${escapeHtml(values.texte)}</p>` : '<p class="fiche-preview__line muted">Pas de texte.</p>'}
        ${values.distinction ? `<p class="fiche-preview__line"><i class="fas fa-star"></i> ${escapeHtml(values.distinction)}</p>` : ''}
        ${values.jours ? `<p class="fiche-preview__line"><i class="fas fa-calendar-day"></i> ${escapeHtml(values.jours)}</p>` : ''}
        ${season ? `<p class="fiche-preview__line"><i class="fas fa-sun"></i> ${escapeHtml(season)}</p>` : ''}
        ${site ? `<p class="fiche-preview__line"><a href="${site}" target="_blank" rel="noopener">Site : ${site}</a></p>` : ''}
        ${maps ? `<a class="btn btn--outline btn--sm" href="${maps}" target="_blank" rel="noopener">Voir sur Google Maps ↗</a>` : ''}`;
}

function ficheInput(key, field, label, value, doubt, attrs = '') {
    return `<label class="label${doubt.includes(field) ? ' fiche-doubt' : ''}">${label}
        <input type="text" data-field="${field}" value="${escapeHtml(value)}" ${attrs} oninput="ficheRefresh('${key}')">
    </label>`;
}

// La fiche d'un lieu : `key` la distingue dans la page, `doubt` liste les champs que le signal met en doute.
// `collapsible` (la relecture) : seul l'aperçu est montré ; un clic dessus ouvre le formulaire.
function ficheHtml(view, key, doubt = [], collapsible = false) {
    FICHES[key] = view;
    const has = field => view.champs.includes(field);
    const categories = Object.entries(view.fiche.categories || {});
    const chips = FICHE_MONTHS.map((label, index) => `
        <button type="button" class="services-chip ${view.months.includes(index) ? 'is-on' : ''}" data-month="${index}"
                aria-pressed="${view.months.includes(index)}" onclick="ficheToggleMonth(this, '${key}')">${label}</button>`).join('');
    const textLabel = view.texte_cible === 'description' ? 'Texte présenté (description du lieu)' : "Texte présenté (fiche de l'agent)";
    return `
        <div class="fiche${collapsible && !FICHES_OPEN.has(key) ? ' fiche--closed' : ''}" data-fiche="${key}">
            <div class="fiche__preview">
                <p class="fiche__caption"><span>Ce que voit le voyageur à l'étape 4 ${ficheId('poi', view.poi_id)}</span>
                    ${collapsible ? `<button type="button" class="btn btn--outline btn--sm fiche__toggle" aria-expanded="${FICHES_OPEN.has(key)}"
                        onclick="ficheToggle('${key}')">${FICHES_OPEN.has(key) ? 'Fermer la fiche' : 'Modifier la fiche'}</button>` : ''}
                </p>
                <div class="fiche-preview${collapsible ? ' fiche-preview--clickable' : ''}" data-preview
                     ${collapsible ? `onclick="ficheOpenFromPreview(event, '${key}')" title="Cliquer pour modifier la fiche"` : ''}>${fichePreview(view)}</div>
                ${view.station ? ficheStationState(view.station) : ''}
            </div>
            <div class="fiche__form">
                ${ficheInput(key, 'name', 'Nom', view.nom, doubt, 'maxlength="150"')}
                ${has('texte') ? `<label class="label${doubt.includes('texte') ? ' fiche-doubt' : ''}">${textLabel}
                    <textarea data-field="texte" rows="3" maxlength="1000" oninput="ficheRefresh('${key}')">${escapeHtml(view.texte)}</textarea>
                </label>` : ''}
                ${has('categorie') ? `<div class="fiche__pair">
                    <label class="label">Type affiché
                        <select data-field="categorie" onchange="ficheRefresh('${key}')">${view.fiche.categories[view.categorie] ? ''
                            : '<option value="" selected>À choisir</option>'}${categories.map(([code, label]) =>
                            `<option value="${escapeHtml(code)}" ${code === view.categorie ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}</select>
                    </label>
                    ${ficheInput(key, 'genre', 'Genre', view.genre, doubt, 'maxlength="100"')}
                </div>` : ''}
                ${ficheInput(key, 'address', 'Adresse', view.adresse, doubt, 'maxlength="255"')}
                <div class="fiche__pair">
                    ${has('url') ? ficheInput(key, 'url', 'Lien du site', view.url, doubt, 'maxlength="490" placeholder="https://"') : ''}
                    ${ficheInput(key, 'maps_url', 'Lien Google Maps', view.maps_url, doubt, 'maxlength="490" placeholder="https://maps.app.goo.gl/..."')}
                </div>
                ${has('distinction') ? ficheInput(key, 'distinction', 'Distinction (restaurant)', view.distinction, doubt, 'maxlength="100" placeholder="Guide Michelin"') : ''}
                ${has('jours') ? ficheInput(key, 'jours', 'Jours (marché)', view.jours, doubt, 'maxlength="150" placeholder="Dimanche matin"') : ''}
                ${has('saison') ? `<div class="label${doubt.includes('saison') ? ' fiche-doubt' : ''}">Saison
                    <select data-field="statut_saison" onchange="ficheRefresh('${key}')">${FICHE_SEASONS.map(([code, label]) =>
                        `<option value="${code}" ${code === view.statut_saison ? 'selected' : ''}>${label}</option>`).join('')}</select>
                    <div class="services-months"><div>${chips}</div></div>
                </div>` : ''}
                <label class="label">Note (facultative)
                    <input type="text" class="fiche__note" maxlength="255" placeholder="Vu sur place le 3 novembre">
                </label>
            </div>
        </div>`;
}

function ficheElement(key) {
    return document.querySelector(`[data-fiche="${key}"]`);
}

// Les valeurs de la saisie, sous la forme de la fiche reçue : l'aperçu les montre.
function ficheValues(key) {
    const view = FICHES[key];
    const element = ficheElement(key);
    // Comme l'API (services_edit._plain) : le texte est rogné, les autres champs ont leurs espaces regroupés.
    const read = field => {
        const input = element.querySelector(`[data-field="${field}"]`);
        if (!input) return view[field];
        return field === 'texte' ? input.value.trim() : input.value.split(/\s+/).filter(Boolean).join(' ');
    };
    return {
        ...view, nom: read('name'), adresse: read('address'), url: read('url'), maps_url: read('maps_url'),
        texte: read('texte'), genre: read('genre'), categorie: read('categorie'), distinction: read('distinction'),
        jours: read('jours'), statut_saison: read('statut_saison'),
        months: [...element.querySelectorAll('.services-chip.is-on')].map(chip => Number(chip.dataset.month)),
    };
}

// Les seuls champs changés, sous les noms que l'API attend.
function ficheChanges(key) {
    const view = FICHES[key];
    const values = ficheValues(key);
    const before = { name: view.nom, address: view.adresse, url: view.url, maps_url: view.maps_url, texte: view.texte,
                     genre: view.genre, categorie: view.categorie, distinction: view.distinction, jours: view.jours };
    const after = { name: values.nom, address: values.adresse, url: values.url, maps_url: values.maps_url, texte: values.texte,
                    genre: values.genre, categorie: values.categorie, distinction: values.distinction, jours: values.jours };
    const changes = {};
    const same = (field, a, b) => field === 'texte' ? (a || '').trim() === (b || '').trim()
        : (a || '').split(/\s+/).filter(Boolean).join(' ') === (b || '').split(/\s+/).filter(Boolean).join(' ');
    FICHE_TEXT_FIELDS.filter(field => view.champs.includes(field))
        // Un type « À choisir » laissé tel quel n'est pas une correction.
        .filter(field => !(field === 'categorie' && !after.categorie))
        .forEach(field => { if (!same(field, after[field], before[field])) changes[field] = after[field]; });
    const sameMonths = [...values.months].sort().join() === [...view.months].sort().join();
    // Une fiche sans saison (une station) n'a rien à changer de ce côté.
    if (view.champs.includes('saison') && (values.statut_saison !== (view.statut_saison || '') || !sameMonths)) {
        changes.statut_saison = values.statut_saison;
        changes.mois = values.months;
    }
    return changes;
}

function ficheNote(key) {
    return ficheElement(key).querySelector('.fiche__note').value;
}

function ficheRefresh(key) {
    ficheElement(key).querySelector('[data-preview]').innerHTML = fichePreview(ficheValues(key));
}

function ficheToggleMonth(button, key) {
    const on = button.classList.toggle('is-on');
    button.setAttribute('aria-pressed', on);
    // Cocher un mois, c'est dire que le lieu est saisonnier sur ces mois.
    const status = ficheElement(key).querySelector('[data-field="statut_saison"]');
    if (on && status.value !== 'confirmee') status.value = 'confirmee';
    ficheRefresh(key);
}

// Ouvrir ou replier le formulaire d'une fiche repliable.
function ficheToggle(key) {
    const element = ficheElement(key);
    const open = element.classList.toggle('fiche--closed') === false;
    if (open) FICHES_OPEN.add(key); else FICHES_OPEN.delete(key);
    const button = element.querySelector('.fiche__toggle');
    button.textContent = open ? 'Fermer la fiche' : 'Modifier la fiche';
    button.setAttribute('aria-expanded', open);
    if (open) element.querySelector('[data-field="name"]').focus();
}

// Un clic sur ce que voit le voyageur ouvre la fiche ; un lien de l'aperçu (site, Google Maps) s'ouvre normalement.
function ficheOpenFromPreview(event, key) {
    if (event.target.closest('a')) return;
    if (ficheElement(key).classList.contains('fiche--closed')) ficheToggle(key);
}

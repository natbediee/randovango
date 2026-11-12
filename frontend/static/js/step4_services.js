// Étape 4 : choix des services (POI) utiles pour la journée en cours - eau,
// vidange, carburant, commerces... Les textes des cartes et les phrases de
// sous-titre par catégorie arrivent prêts à afficher depuis l'API (champs badge,
// distance_label, subtitles... préparés par display_utils.py).
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Filtres (onglets) →
// 7. Sélection et sauvegarde → 8. Fonctions exposées aux popups de la carte.

// Toutes les catégories de services, dans l'ordre d'affichage des tuiles.
const POI_CATEGORIES = ['eau', 'vidange', 'gasoil', 'supermarche', 'commerce',
                        'restauration', 'cafe', 'toilettes', 'hygiene', 'laverie', 'culture', 'urgence'];

// Icône (Font Awesome) et libellé de chaque catégorie, pour les tuiles de la vue 1
// et le titre de la sous-liste (vue 2).
const CATEGORY_META = {
    eau:          { icon: 'fa-tint',            label: 'Eau' },
    vidange:      { icon: 'fa-recycle',         label: 'Vidange' },
    gasoil:       { icon: 'fa-gas-pump',        label: 'Carburant' },
    supermarche:  { icon: 'fa-cart-arrow-down', label: 'Supermarché' },
    commerce:     { icon: 'fa-shopping-basket', label: 'Commerce' },
    restauration: { icon: 'fa-utensils',        label: 'Restauration' },
    cafe:         { icon: 'fa-mug-hot',         label: 'Café, bar' },
    toilettes:    { icon: 'fa-toilet',          label: 'Toilettes' },
    hygiene:      { icon: 'fa-shower',          label: 'Hygiène' },
    laverie:      { icon: 'fa-shirt',           label: 'Laverie' },
    culture:      { icon: 'fa-camera',          label: 'Culture & Loisirs' },
    urgence:      { icon: 'fa-first-aid',       label: 'Urgences' }
};

// --- 1. Contexte du séjour ---
// Lu au niveau du fichier : les fonctions de sélection (toggleService...) appelées
// par les popups Leaflet et les boutons de la page en ont aussi besoin.
const { currentDay, selectedDays } = getTripContext();

// État de l'étape accessible depuis ces mêmes fonctions globales.
let selectedPoiIds = new Set();
let serviceMap = null;
let poiMarkers = []; // { marker, category, poi }
// Phrases "X services disponibles pour cette journée" par catégorie, reçues de l'API.
let subtitlesByCategory = {};
// Listes de POI par catégorie (réponse API), pour les compteurs des tuiles.
let poisByCategory = {};
// Catégorie ouverte dans la sous-liste (null = vue tuiles = tous les marqueurs).
let activeCategory = null;
// Type choisi dans le filtre de la sous-liste (« Boulangerie », « Marché »...), null = tous.
let activeType = null;
// Les onglets dont les agents écrivent les fiches, avec une catégorie par lieu : le filtre par type n'y apparaît
// que s'il y a au moins deux types à choisir.
const TYPE_FILTER_CATEGORIES = ['commerce', 'restauration', 'cafe'];
// L'onglet carburant a son propre filtre : par carburant vendu (le gazole par défaut, celui des vans), qui ne laisse que
// le prix de ce carburant sur chaque station, puis le tri par prix de ce carburant ou par distance du spot (du centre de
// la commune sans spot choisi). Les pastilles de prix arrivent prêtes de l'API (poi.prix).
const FUEL_CATEGORY = 'gasoil';
const DEFAULT_FUEL = 'Gazole';
let activeFuel = DEFAULT_FUEL;      // null = « Tout »
let fuelSort = 'prix';              // 'prix' ou 'distance'
// Services retenus les jours précédents, pour le rappel lecture seule (vue tuiles).
// Purement informatif : ces POI ne sont JAMAIS ajoutés à selectedPoiIds.
let previousDaysServices = [];
// poiId -> numéro du 1er jour où ce service a déjà été planifié. Sert à signaler
// « déjà planifié Jx » sur la carte de la liste quand un point du jour en cours a
// déjà été retenu un jour précédent (cohérence avec le marqueur/popup de la carte).
let previousPoiDay = new Map();

// N'affiche sur la carte que les marqueurs de la catégorie ouverte. En vue tuiles
// (activeCategory === null), tous les marqueurs sont visibles (vue d'ensemble).
function updateMapMarkersVisibility() {
    if (!serviceMap) return;
    poiMarkers.forEach(({ marker, category, poi }) => {
        const matches = (activeCategory === null || category === activeCategory)
            && (activeType === null || poi.service_type_label === activeType)
            && (category !== FUEL_CATEGORY || activeCategory !== FUEL_CATEGORY || sellsFuel(poi, activeFuel));
        if (matches && !serviceMap.hasLayer(marker)) {
            marker.addTo(serviceMap);
        } else if (!matches && serviceMap.hasLayer(marker)) {
            serviceMap.removeLayer(marker);
        }
    });
}

document.addEventListener('DOMContentLoaded', async function () {
    const cityId = requireCity();
    if (!cityId) return;

    // --- 2. Badge et titres ---
    showDayBadge(currentDay, selectedDays);

    const isDetente = localStorage.getItem('selectedHiking') === 'no-hiking';
    document.getElementById('step4Title').textContent =
        `🛠️ Jour ${currentDay} : Services pour ${isDetente ? 'votre journée détente' : 'compléter votre journée'}`;

    // Label jour dans la section sélectionnés
    const dayLabelEl = document.getElementById('selectedDayLabel');
    if (dayLabelEl) dayLabelEl.textContent = currentDay;

    // Label du bouton suivant
    const nextLabel = document.getElementById('nextStepLabel');
    if (nextLabel) nextLabel.textContent = 'Voir les pépites de Vany';

    // --- 3. Carte ---
    serviceMap = await createStepMap(48.4, -4.5, 12);

    // Centrer la page sur la carte à l'arrivée sur l'étape
    document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });

    // Afficher la randonnée et le spot déjà choisis, pour garder le contexte du jour.
    // Leurs positions servent ensuite à centrer la carte.
    const referencePositions = [];
    const hikeId = localStorage.getItem('selectedHiking');
    const hikePosition = await addChosenHikeToMap(serviceMap, cityId, hikeId, currentDay);
    if (hikePosition) referencePositions.push(hikePosition);

    const spotId = localStorage.getItem('selectedSpot');
    let chosenSpotCoords = null;
    if (spotId && spotId !== 'autre_hebergement') {
        try {
            const spots = await apiGet(`/api/step3/spots?city_id=${cityId}`);
            const chosenSpot = spots.find(s => String(s.id) === String(spotId));
            if (chosenSpot && chosenSpot.latitude && chosenSpot.longitude) {
                chosenSpotCoords = { lat: chosenSpot.latitude, lon: chosenSpot.longitude };
                if (serviceMap) {
                    const pos = [chosenSpot.latitude, chosenSpot.longitude];
                    L.marker(pos, { icon: buildSpotDivIcon(`J${currentDay}`), zIndexOffset: 500 })
                        .addTo(serviceMap)
                        .bindPopup(`<b>${chosenSpot.name}</b><br>${chosenSpot.type}`);
                    referencePositions.push(pos);
                }
            }
        } catch (err) {
            console.error('Erreur chargement spot choisi:', err);
        }
    }

    // Afficher les jours déjà planifiés sur la carte (rando, spot ET services), et
    // récupérer leurs positions pour les inclure dans le cadrage plus bas.
    const { planId } = getTripContext();
    const { previousPositions = [] } =
        await loadPreviousDaysOnMap(serviceMap, currentDay, planId, { showPois: true });

    // Restaurer les POI déjà sauvegardés pour ce jour (retour depuis results)
    if (planId) {
        try {
            const plan = await apiGet(`/api/result/?plan_id=${planId}`);
            const savedDay = (plan.days || []).find(d => d.day_number === currentDay);
            if (savedDay && savedDay.pois) {
                savedDay.pois.forEach(p => selectedPoiIds.add(p.id));
            }
            // Services des jours précédents → rappel lecture seule. On ne les met pas
            // dans selectedPoiIds : ils ne comptent pas dans la sélection du jour en cours.
            previousDaysServices = (plan.days || [])
                .filter(d => d.day_number < currentDay && (d.pois || []).length > 0)
                .map(d => ({ day: d.day_number, pois: d.pois }));
            previousPoiDay = new Map();
            previousDaysServices.forEach(d => (d.pois || []).forEach(p => {
                if (!previousPoiDay.has(p.id)) previousPoiDay.set(p.id, d.day);
            }));
            renderPreviousServices();
        } catch (e) { /* pas bloquant */ }
    }

    // --- 4. Chargement API : POI au plus près du spot choisi si disponible ---
    try {
        let poiUrl = `/api/step4/poi?city_id=${cityId}&distance_km=5`;
        // La date du jour préparé : un lieu fermé en cette saison n'est pas proposé (Kervouroc en novembre).
        const dayDate = tripDayDate(currentDay);
        if (dayDate) poiUrl += `&day_date=${dayDate}`;        if (chosenSpotCoords) {
            poiUrl += `&spot_lat=${chosenSpotCoords.lat}&spot_lon=${chosenSpotCoords.lon}`;
        }
        const data = await apiGet(poiUrl);

        // --- 5. Affichage : une grille de cartes par catégorie (masquée), puis les
        // tuiles de choix du type (vue 1). La sous-liste ne s'affiche qu'au clic. ---
        subtitlesByCategory = data.subtitles || {};
        poisByCategory = data;
        POI_CATEGORIES.forEach(category => renderCategory(category, data[category] || []));
        renderCategoryTiles();

        // Message d'accueil de la vue tuiles
        const subtitleEl = document.getElementById('step4Subtitle');
        if (subtitleEl) subtitleEl.textContent = 'Choisis un type de service pour voir les points disponibles.';

        // Mettre à jour les marqueurs des POI déjà sélectionnés (restauration depuis DB)
        selectedPoiIds.forEach(id => updatePoiMarker(id));
        showNextOrSkip(selectedPoiIds.size > 0);

        // Vue d'ensemble au départ : tous les marqueurs visibles (activeCategory = null)
        updateMapMarkersVisibility();

        // Positions à cadrer : rando/spot du jour + repères des jours précédents
        // (services J-1 inclus) PROCHES (≤ 30 km), pour qu'on les voie sans dézoomer à
        // l'extrême quand le jour suivant est dans une autre ville.
        const framePositions = [...referencePositions];
        if (serviceMap && referencePositions.length > 0) {
            const anchor = referencePositions[0];
            previousPositions.forEach(pos => {
                if (serviceMap.distance(anchor, pos) <= 30000) framePositions.push(pos);
            });
        } else {
            framePositions.push(...previousPositions);
        }

        // Centrer la carte sur la rando/le spot du jour et les repères précédents proches
        // (les POI du jour restent affichés mais n'influencent pas le zoom).
        if (serviceMap && framePositions.length === 1) {
            serviceMap.setView(framePositions[0], 15);
        } else if (serviceMap && framePositions.length > 1) {
            serviceMap.fitBounds(framePositions, { padding: [60, 60], maxZoom: 16 });
        } else if (serviceMap) {
            // Repli si ni rando ni spot n'est sélectionné (ex. jour libre, hébergement hors liste)
            const poiPositions = POI_CATEGORIES
                .flatMap(category => data[category] || [])
                .filter(p => p.latitude && p.longitude)
                .map(p => [p.latitude, p.longitude]);
            if (poiPositions.length === 1) {
                serviceMap.setView(poiPositions[0], 13);
            } else if (poiPositions.length > 1) {
                serviceMap.fitBounds(poiPositions, { padding: [40, 40], maxZoom: 14 });
            }
        }
    } catch (err) {
        console.error('Erreur chargement POI:', err);
        document.getElementById('eau').innerHTML =
            '<p style="padding:1rem;color:red;">Erreur lors du chargement des services.</p>';
    }
});

// --- 5. Affichage : cartes d'une catégorie + marqueurs correspondants ---

function renderCategory(categoryId, poiList) {
    const grid = document.getElementById(categoryId);
    if (!grid) return;
    grid.innerHTML = '';

    if (poiList.length === 0) {
        grid.style.display = 'none';
        return;
    }

    poiList.forEach(poi => {
        const safeName = poi.name.replace(/'/g, "\\'");
        const card = document.createElement('div');
        // .selected : la carte du service ajouté reste en teal (comme spot/rando)
        // .service-card--near-spot : à pied du spot, la carte est entourée comme un spot sur la rando
        card.className = 'service-card' + (poi.near_spot ? ' service-card--near-spot' : '') + (selectedPoiIds.has(poi.id) ? ' selected' : '');
        card.id = `poi-card-${poi.id}`;
        card.dataset.type = poi.service_type_label;
        card.innerHTML = `
            <div class="service-content-grid">
                <!-- Comme la fiche spot : catégorie et vérifié sur une ligne, puis le nom, le texte et le lien -->
                <div class="service-center">
                    <div class="spot-tags">
                        ${poi.reference_distance_label ? `<span class="hike-distance${poi.near_spot ? ' hike-distance--on' : ''}">${poi.reference_distance_label}</span>` : ''}
                        <span class="spot-type">${poi.service_type_label}</span>
                        <span class="status-badge ${poi.badge.css}">${poi.badge.text}</span>
                        ${poi.nouveau ? '<span class="status-badge top">Nouveau</span>' : ''}
                        ${poi.automate_24_24 ? '<span class="status-badge fuel-open">24h/24</span>' : ''}
                        ${poi.autoroute ? '<span class="status-badge fuel-open">Autoroute</span>' : ''}
                        ${poi.fermeture_label ? `<span class="status-badge pending">${escapeHtml(poi.fermeture_label)}</span>` : ''}
                        ${previousPoiDay.has(poi.id) ? `<span class="status-badge planned"><i class="fas fa-check"></i> J${previousPoiDay.get(poi.id)} déjà planifié</span>` : ''}                    </div>
                    <h4>${poi.name}</h4>
                    ${poi.address && !poi.maps_url ? `<p class="service-address"><i class="fas fa-map-marker-alt"></i> ${poi.address}</p>` : ''}
                    ${poi.prix ? fuelPricesHtml(poi) : ''}
                    ${poi.description ? `<p class="service-description">${escapeHtml(poi.description)}</p>` : ''}
                    ${poi.distinction ? `<p class="service-address"><i class="fas fa-star"></i> ${escapeHtml(poi.distinction)}</p>` : ''}
                    ${poi.jours ? `<p class="service-address"><i class="fas fa-calendar-day"></i> ${escapeHtml(poi.jours)}</p>` : ''}
                    ${poi.saison_label ? `<p class="service-address"><i class="fas fa-sun"></i> ${escapeHtml(poi.saison_label)}</p>` : ''}
                    <!-- Le lien du lieu (son site, ou la page qui le prouve) reste à côté du bouton Google Maps : c'est le recours du voyageur. -->
                    ${poi.url ? `<p class="service-address"><a href="${escapeHtml(poi.url)}" target="_blank" rel="noopener">Site : ${escapeHtml(poi.url_label)}</a></p>` : ''}                </div>
                <div class="service-right">
                    <!-- Essai de mise en page : pour un restaurant, le bouton Voir ouvre Google Maps -->
                    ${poi.maps_url ? `<a href="${escapeHtml(poi.maps_url)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm btn-external">Voir sur Google Maps ↗
                    </a>` : `<button class="btn btn-outline btn-sm"
                        onclick="showPoiOnMap(${poi.latitude}, ${poi.longitude}, '${safeName}')">
                        <i class="fas fa-map"></i> Voir
                    </button>`}
                    <button class="${selectedPoiIds.has(poi.id) ? 'btn btn-selected btn-sm' : 'btn btn-primary btn-sm'}" id="btn-poi-${poi.id}"
                        onclick="toggleService(${poi.id}, '${safeName}')">
                        ${selectedPoiIds.has(poi.id) ? 'Retirer' : 'Ajouter'}
                    </button>
                </div>
            </div>`;
        grid.appendChild(card);

        // Marqueur sur la carte (affiché/masqué selon l'onglet actif via updateMapMarkersVisibility)
        if (serviceMap && poi.latitude && poi.longitude) {
            // Tooltip d'aperçu au survol : nom + infos de base (type, distance si dispo).
            const poiTipHtml =
                `<span class="map-tip__name">${poi.name}</span>` +
                `<span class="map-tip__stats">${poi.service_type_label || ''}${poi.distance_label ? ' · ' + poi.distance_label : ''}</span>`;
            const TIP_OPTS = { direction: 'top', offset: [0, -30], className: 'map-tip', opacity: 1 };
            const marker = L.marker([poi.latitude, poi.longitude], {
                icon: buildPoiDivIcon(categoryId)
            }).bindPopup(buildPoiPopupContent(poi, selectedPoiIds.has(poi.id)))
              .bindTooltip(poiTipHtml, TIP_OPTS)
              // Popup ouvert ⇒ tooltip masqué (pas de doublon), rétabli à la fermeture.
              .on('popupopen', function () { this.closeTooltip(); this.unbindTooltip(); })
              .on('popupclose', function () { if (!this.getTooltip()) this.bindTooltip(poiTipHtml, TIP_OPTS); });
            poiMarkers.push({ marker, category: categoryId, poi });

            // Survol de la fiche → aperçu de son marqueur sur la carte.
            const poiBtn = document.getElementById(`btn-poi-${poi.id}`);
            const poiCard = poiBtn ? poiBtn.closest('.service-card') : null;
            if (poiCard) {
                poiCard.addEventListener('mouseenter', () => marker.openTooltip());
                poiCard.addEventListener('mouseleave', () => marker.closeTooltip());
            }
        }
    });
}

// --- 6. Vues : tuiles de catégories (vue 1) ⇄ sous-liste d'un type (vue 2) ---

// Vue 1 : une tuile par catégorie ayant au moins un service, avec son nombre de
// points et, le cas échéant, une pastille du nombre déjà ajouté.
function renderCategoryTiles() {
    const container = document.getElementById('categoryTiles');
    if (!container) return;

    const available = POI_CATEGORIES.filter(cat => (poisByCategory[cat] || []).length > 0);
    if (available.length === 0) {
        container.innerHTML = '<p class="muted" style="padding:1rem;text-align:center;grid-column:1/-1;">Aucun service trouvé autour de ce spot.</p>';
        return;
    }

    container.innerHTML = available.map(cat => {
        const meta = CATEGORY_META[cat] || { icon: 'fa-map-marker-alt', label: cat };
        const list = poisByCategory[cat] || [];
        const count = list.length;
        const selectedCount = list.filter(p => selectedPoiIds.has(p.id)).length;
        return `
            <button type="button" class="category-tile" onclick="openCategory('${cat}')" aria-label="${meta.label} - ${count} points">
                ${selectedCount ? `<span class="category-tile__selected">✓ ${selectedCount}</span>` : ''}
                <span class="category-tile__icon"><i class="fas ${meta.icon}"></i></span>
                <span class="category-tile__label">${meta.label}</span>
                <span class="category-tile__count">${count} ${count > 1 ? 'points' : 'point'}</span>
            </button>`;
    }).join('');
}

// Rappel lecture seule (vue tuiles) des services retenus les jours précédents,
// groupés par jour. Aucun bouton Ajouter/Retirer : c'est un repère, pas une sélection.
function renderPreviousServices() {
    const el = document.getElementById('previousServices');
    if (!el) return;
    if (previousDaysServices.length === 0) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    el.innerHTML =
        '<p class="previous-services__title">Services déjà planifiés les jours précédents</p>' +
        previousDaysServices.map(d => {
            const chips = d.pois.map(p => {
                const meta = CATEGORY_META[p.category] || { icon: 'fa-map-marker-alt', label: '' };
                // Type précis ("Restaurant", "Plage") s'il n'est pas une simple reprise du
                // nom, sinon le libellé de catégorie ("Restauration") : un nom seul comme
                // « Glenn » ne dit pas de quel type de service il s'agit.
                const rawType = (p.service_type || '').trim();
                const kind = rawType && rawType.toLowerCase() !== (p.name || '').toLowerCase()
                    ? rawType : (meta.label || '');
                return `<span class="previous-chip"><i class="fas ${meta.icon}"></i>${p.name}` +
                       `${kind ? ` <small class="previous-chip__type">· ${kind}</small>` : ''}</span>`;
            }).join('');
            return `<div class="previous-day">
                        <div class="previous-day__label">Jour ${d.day}</div>
                        <div class="previous-chips">${chips}</div>
                    </div>`;
        }).join('');
}

// Vue 2 : ouvrir la sous-liste d'un type de service.
function openCategory(category) {
    activeCategory = category;
    activeType = null;
    // L'onglet carburant rouvert repart sur le gazole, trié par prix.
    if (category === FUEL_CATEGORY) {
        activeFuel = DEFAULT_FUEL;
        fuelSort = 'prix';
    }
    document.getElementById('categoryTilesView').style.display = 'none';
    const sublist = document.getElementById('serviceSublistView');
    sublist.style.display = 'block';

    // N'afficher que la grille de cette catégorie. IMPORTANT : 'flex' (pas 'block'),
    // sinon le display inline écrase le `display:flex` de .services-grid et son `gap`
    // ne s'applique plus → cartes collées.
    document.querySelectorAll('.services-grid').forEach(grid => {
        grid.style.display = grid.id === category ? 'flex' : 'none';
    });

    // Titre + sous-titre
    const meta = CATEGORY_META[category] || { label: category };
    const titleEl = document.getElementById('sublistTitle');
    if (titleEl) titleEl.textContent = meta.label;
    const subtitleEl = document.getElementById('step4Subtitle');
    if (subtitleEl) subtitleEl.textContent = subtitlesByCategory[category] || '';

    // Un onglet rouvert repart sur « Tout » : ses cartes filtrées la fois d'avant réapparaissent.
    filterByType(category, null);

    // Marqueurs de la catégorie seulement
    updateMapMarkersVisibility();

    // Recadrer la carte sur les points de cette catégorie, sinon ils restent hors
    // champ (la carte était centrée sur la rando/le spot) et « on ne les voit pas ».
    const catMarkers = poiMarkers.filter(m => m.category === category);
    if (serviceMap && catMarkers.length > 0) {
        const bounds = L.latLngBounds(catMarkers.map(m => m.marker.getLatLng()));
        serviceMap.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
    }

    // Cadrer sur le bloc carte+liste, pas sur la sous-liste seule : en mobile la carte
    // est au-dessus de la liste (.map-col order:-1) et un scroll sur la sous-liste la
    // pousserait hors écran, juste après l'avoir recadrée sur la catégorie.
    document.querySelector('.map-list-layout')
        .scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Filtre par type de la sous-liste : « Tout », puis un bouton par type présent (« Boulangerie (3) »).
// Les types viennent des cartes elles-mêmes : seul ce qui est affiché peut être choisi.
function renderTypeFilter(category) {
    const filter = document.getElementById('typeFilter');
    if (!filter) return;
    if (category === FUEL_CATEGORY) {
        renderFuelFilter(filter);
        return;
    }
    filter.style.flexDirection = '';    // l'onglet carburant met ses deux rangées l'une sous l'autre
    const counts = new Map();
    (poisByCategory[category] || []).forEach(poi => {
        counts.set(poi.service_type_label, (counts.get(poi.service_type_label) || 0) + 1);
    });
    if (!TYPE_FILTER_CATEGORIES.includes(category) || counts.size < 2) {
        filter.style.display = 'none';
        filter.innerHTML = '';
        return;
    }
    const total = (poisByCategory[category] || []).length;
    const chips = [[null, `Tout (${total})`],
                   ...[...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                                            .map(([type, count]) => [type, `${type} (${count})`])];
    filter.innerHTML = chips.map(([type, label], index) =>
        `<button type="button" class="chip${type === activeType ? ' is-active' : ''}" data-index="${index}">${escapeHtml(label)}</button>`
    ).join('');
    filter.querySelectorAll('button').forEach(button => {
        button.addEventListener('click', () => filterByType(category, chips[Number(button.dataset.index)][0]));
    });
    filter.style.display = 'flex';
}

function filterByType(category, type) {
    activeType = type;
    const grid = document.getElementById(category);
    if (grid) {
        grid.querySelectorAll('.service-card').forEach(card => {
            card.style.display = type === null || card.dataset.type === type ? '' : 'none';
        });
    }
    renderTypeFilter(category);
    if (category === FUEL_CATEGORY) applyFuelView();
    updateMapMarkersVisibility();
}

// --- Onglet carburant : pastilles de prix, filtre par carburant, tri ---

// Le prix vendu d'un carburant dans une station (une pastille en rupture ne compte pas), ou null.
function fuelPrice(poi, fuel) {
    const badge = (poi.prix || []).find(b => b.carburant === fuel && !b.rupture && b.prix !== null);
    return badge ? badge.prix : null;
}

function sellsFuel(poi, fuel) {
    return fuel === null || fuelPrice(poi, fuel) !== null;
}

function formatFuelPrice(price) {
    return `${price.toFixed(3).replace('.', ',')} €`;
}

// La ligne des prix : une pastille par carburant (ordre de l'API), puis la phrase des dates.
// Le carburant choisi passe devant et « le moins cher » s'y affiche : c'est applyFuelView qui le fait.
function fuelPricesHtml(poi) {
    const badges = poi.prix.map((b, rank) => `
        <span class="fuel-price${b.ancien ? ' fuel-price--old' : ''}${b.rupture ? ' fuel-price--out' : ''}"
              data-fuel="${escapeHtml(b.carburant)}" data-rank="${rank}">
            <span>${escapeHtml(b.label)}</span>
            ${b.rupture ? '<span>en rupture</span>' : `<b>${formatFuelPrice(b.prix)}</b>`}
            ${b.ancien ? `<span class="fuel-price__date">${escapeHtml(b.date_label)}</span>` : ''}
            <span class="fuel-price__cheapest">le moins cher</span>
        </span>`).join('');
    return `<div class="fuel-prices">${badges}</div>` +
        (poi.prix_resume ? `<p class="fuel-prices__summary">${escapeHtml(poi.prix_resume)}</p>` : '');
}

// Les carburants vendus dans l'onglet, dans l'ordre des pastilles, avec le nombre de stations qui les vendent.
function fuelsOnSale(stations) {
    const fuels = new Map();
    stations.forEach(poi => (poi.prix || []).forEach(b => {
        if (!fuels.has(b.carburant)) fuels.set(b.carburant, { label: b.label, count: 0 });
        if (fuelPrice(poi, b.carburant) !== null) fuels.get(b.carburant).count += 1;
    }));
    return [...fuels.entries()].filter(([, info]) => info.count > 0);
}

function renderFuelFilter(filter) {
    const stations = poisByCategory[FUEL_CATEGORY] || [];
    const fuels = fuelsOnSale(stations);
    if (activeFuel !== null && !fuels.some(([fuel]) => fuel === activeFuel)) activeFuel = null;
    const chip = (active, label, attrs) =>
        `<button type="button" class="chip${active ? ' is-active' : ''}" aria-pressed="${active}" ${attrs}>${escapeHtml(label)}</button>`;
    const sortLabel = `Prix ${activeFuel === null ? 'du gazole' : 'du ' + fuels.find(([fuel]) => fuel === activeFuel)[1].label}`;
    filter.innerHTML =
        `<div class="fuel-filter" role="group" aria-label="Filtrer par carburant">
            <span class="fuel-filter__label">Carburant</span>
            ${chip(activeFuel === null, `Tout (${stations.length})`, 'data-fuel=""')}
            ${fuels.map(([fuel, info]) => chip(fuel === activeFuel, `${info.label} (${info.count})`, `data-fuel="${escapeHtml(fuel)}"`)).join('')}
        </div>
        <div class="fuel-filter" role="group" aria-label="Trier les stations">
            <span class="fuel-filter__label">Trier par</span>
            ${chip(fuelSort === 'prix', sortLabel, 'data-sort="prix"')}
            ${chip(fuelSort === 'distance', stations.some(poi => poi.from_spot) ? 'Distance du spot' : 'Distance du centre', 'data-sort="distance"')}
        </div>`;
    filter.querySelectorAll('[data-fuel]').forEach(button => button.addEventListener('click', () => {
        activeFuel = button.dataset.fuel || null;
        filterByType(FUEL_CATEGORY, null);
    }));
    filter.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
        fuelSort = button.dataset.sort;
        filterByType(FUEL_CATEGORY, null);
    }));
    filter.style.display = stations.length ? 'flex' : 'none';
    filter.style.flexDirection = 'column';
}

// Range les cartes (prix du carburant choisi, ou distance), cache celles qui ne le vendent pas, met ce carburant
// devant sur chaque carte et marque le moins cher. Les cartes ne sont pas refaites : leurs marqueurs restent liés.
function applyFuelView() {
    const grid = document.getElementById(FUEL_CATEGORY);
    const stations = poisByCategory[FUEL_CATEGORY] || [];
    if (!grid) return;
    const priceFuel = activeFuel || DEFAULT_FUEL;
    const shown = stations.filter(poi => sellsFuel(poi, activeFuel));
    const prices = shown.map(poi => fuelPrice(poi, priceFuel)).filter(price => price !== null);
    const cheapest = prices.length > 1 ? Math.min(...prices) : null;
    const byDistance = (a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity);
    const byPrice = (a, b) => (fuelPrice(a, priceFuel) ?? Infinity) - (fuelPrice(b, priceFuel) ?? Infinity) || byDistance(a, b);
    [...stations].sort(fuelSort === 'prix' ? byPrice : byDistance).forEach(poi => {
        const card = document.getElementById(`poi-card-${poi.id}`);
        if (!card) return;
        grid.appendChild(card);
        card.style.display = shown.includes(poi) ? '' : 'none';
        const line = card.querySelector('.fuel-prices');
        if (!line) return;
        const pills = [...line.querySelectorAll('.fuel-price')].sort((a, b) => a.dataset.rank - b.dataset.rank);
        pills.forEach(pill => {
            const chosen = pill.dataset.fuel === priceFuel;
            // Un carburant choisi (Gazole...) : seul son prix reste sur la carte ; « Tout » remontre les autres.
            pill.hidden = activeFuel !== null && !chosen;
            pill.classList.toggle('is-chosen', chosen);
            pill.classList.toggle('is-cheapest', chosen && cheapest !== null && fuelPrice(poi, priceFuel) === cheapest);
            line.appendChild(pill);
        });
        const chosenPill = pills.find(pill => pill.dataset.fuel === priceFuel);
        if (chosenPill) line.prepend(chosenPill);
    });
}

// Date (AAAA-MM-JJ) du jour préparé : la date de départ choisie au début, plus le numéro du jour moins un.
// Sans date de départ, null : l'API prend alors la date d'aujourd'hui.
function tripDayDate(dayNumber) {
    const start = localStorage.getItem('selectedStartDate');
    if (!start) return null;
    const day = new Date(start + 'T12:00:00');
    if (isNaN(day)) return null;
    day.setDate(day.getDate() + (dayNumber || 1) - 1);
    return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
}

// Retour à la vue tuiles (recalcule les pastilles « déjà ajouté »).
function showCategoryTiles() {
    activeCategory = null;
    activeType = null;
    document.getElementById('serviceSublistView').style.display = 'none';
    document.getElementById('categoryTilesView').style.display = 'block';
    renderCategoryTiles();

    const subtitleEl = document.getElementById('step4Subtitle');
    if (subtitleEl) subtitleEl.textContent = 'Choisis un type de service pour voir les points disponibles.';

    updateMapMarkersVisibility();
}

// --- 7. Sélection et sauvegarde ---

// Met à jour le popup et l'icône du marqueur d'un POI selon son état de sélection
function updatePoiMarker(poiId) {
    const markerData = poiMarkers.find(m => m.poi.id === poiId);
    if (!markerData) return;
    const isSelected = selectedPoiIds.has(poiId);
    markerData.marker.setPopupContent(buildPoiPopupContent(markerData.poi, isSelected));
    markerData.marker.setIcon(isSelected
        ? buildPoiSelectedDivIcon(markerData.category)
        : buildPoiDivIcon(markerData.category));
}

// Sauvegarde en base la liste des services sélectionnés pour le jour en cours
function saveToDB() {
    return saveDayChoice('step4', {
        services: Array.from(selectedPoiIds),
        day_number: currentDay
    }, 'services');
}

// --- 8. Fonctions exposées aux popups Leaflet et aux boutons de la page ---
// Déclarées au niveau du fichier (et donc accessibles via window.*) : les popups
// les appellent par leur nom dans des attributs onclick.

function toggleService(poiId, poiName) {
    const btn = document.getElementById(`btn-poi-${poiId}`);
    const card = document.getElementById(`poi-card-${poiId}`);
    if (selectedPoiIds.has(poiId)) {
        selectedPoiIds.delete(poiId);
        if (btn) { btn.textContent = 'Ajouter'; btn.className = 'btn btn-primary btn-sm'; }
        if (card) card.classList.remove('selected');
    } else {
        selectedPoiIds.add(poiId);
        if (btn) { btn.textContent = 'Retirer'; btn.className = 'btn btn-selected btn-sm'; }
        if (card) card.classList.add('selected');
    }

    updatePoiMarker(poiId);
    showNextOrSkip(selectedPoiIds.size > 0);
    // Concept unifié : après l'action, le popup se ferme.
    if (serviceMap) serviceMap.closePopup();
    saveToDB();
}

// Bouton « Continuer sans service » de la barre du bas : aucun service ce jour-là,
// on passe directement aux pépites de Vany.
function skipServices() {
    selectedPoiIds.clear();
    goToPepites();
}

// Bouton "Voir les pépites de Vany" : sauvegarde les services puis passe à l'étape 5.
// On ATTEND la fin de la sauvegarde avant de quitter la page : naviguer tout de
// suite interrompait la requête en cours ("Failed to fetch" dans la console).
async function goToPepites() {
    await saveToDB();
    window.location.href = window.APP_URLS.step5;
}

// Bouton "Voir" d'un service : centre la carte sur le service
function showPoiOnMap(lat, lon, name) {
    if (serviceMap) {
        document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
        serviceMap.setView([lat, lon], 15);
        L.popup().setLatLng([lat, lon]).setContent(`<b>${name}</b>`).openOn(serviceMap);
    }
}

// Bouton "Détail" du popup carte : amène à la carte du service dans la liste et l'encadre
function showPoiDetail(poiId) {
    // Le popup peut être cliqué depuis la vue tuiles ou une autre catégorie : ouvrir
    // d'abord la sous-liste de ce service, sinon sa carte est masquée (display:none).
    const md = poiMarkers.find(m => m.poi.id === poiId);
    if (md && activeCategory !== md.category) openCategory(md.category);

    const card = document.getElementById(`poi-card-${poiId}`);
    if (!card) return;
    document.querySelectorAll('.service-card.highlight-frame').forEach(c => c.classList.remove('highlight-frame'));
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('highlight-flash', 'highlight-frame');
    setTimeout(() => card.classList.remove('highlight-flash'), 1400);
}

// Contenu du popup d'un POI, avec le bouton "Ajouter"/"Retirer" qui reflète l'état sélectionné
function buildPoiPopupContent(poi, isSelected) {
    const safeName = poi.name.replace(/'/g, "\\'");
    return `<b>${poi.name}</b><br>${poi.service_type || ''}
        ${poi.address ? `<br><small>📍 ${poi.address}</small>` : ''}
        <div style="margin-top:6px;display:flex;gap:6px;">
            <button class="btn btn-outline btn-sm" onclick="showPoiDetail(${poi.id})">Détail</button>
            <button class="btn btn-sm ${isSelected ? 'btn-selected' : 'btn-primary'}" onclick="toggleService(${poi.id}, '${safeName}')">
                ${isSelected ? 'Retirer' : 'Ajouter'}
            </button>
        </div>`;
}

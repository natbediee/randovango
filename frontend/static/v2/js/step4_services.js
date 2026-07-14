// Étape 4 : choix des services (POI) utiles pour la journée en cours — eau,
// vidange, carburant, commerces... Les textes des cartes et les phrases de
// sous-titre par catégorie arrivent prêts à afficher depuis l'API (champs badge,
// distance_label, subtitles... préparés par display_utils.py).
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Filtres (onglets) →
// 7. Sélection et sauvegarde → 8. Fonctions exposées aux popups de la carte.

// Toutes les catégories de services, dans l'ordre d'affichage des tuiles.
const POI_CATEGORIES = ['eau', 'vidange', 'gasoil', 'supermarche', 'commerce',
                        'restauration', 'toilettes', 'hygiene', 'culture', 'urgence'];

// Icône (Font Awesome) et libellé de chaque catégorie, pour les tuiles de la vue 1
// et le titre de la sous-liste (vue 2).
const CATEGORY_META = {
    eau:          { icon: 'fa-tint',            label: 'Eau' },
    vidange:      { icon: 'fa-recycle',         label: 'Vidange' },
    gasoil:       { icon: 'fa-gas-pump',        label: 'Gasoil' },
    supermarche:  { icon: 'fa-cart-arrow-down', label: 'Supermarché' },
    commerce:     { icon: 'fa-shopping-basket', label: 'Commerce' },
    restauration: { icon: 'fa-utensils',        label: 'Restauration' },
    toilettes:    { icon: 'fa-toilet',          label: 'Toilettes' },
    hygiene:      { icon: 'fa-shower',          label: 'Hygiène' },
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

// N'affiche sur la carte que les marqueurs de la catégorie ouverte. En vue tuiles
// (activeCategory === null), tous les marqueurs sont visibles (vue d'ensemble).
function updateMapMarkersVisibility() {
    if (!serviceMap) return;
    poiMarkers.forEach(({ marker, category }) => {
        const matches = activeCategory === null || category === activeCategory;
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
    if (nextLabel) nextLabel.textContent = 'Récapitulatif';

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

    // Afficher les jours déjà planifiés sur la carte
    const { planId } = getTripContext();
    loadPreviousDaysOnMap(serviceMap, currentDay, planId);

    // Restaurer les POI déjà sauvegardés pour ce jour (retour depuis results)
    if (planId) {
        try {
            const plan = await apiGet(`/api/result/?plan_id=${planId}`);
            const savedDay = (plan.days || []).find(d => d.day_number === currentDay);
            if (savedDay && savedDay.pois) {
                savedDay.pois.forEach(p => selectedPoiIds.add(p.id));
            }
        } catch (e) { /* pas bloquant */ }
    }

    // --- 4. Chargement API : POI au plus près du spot choisi si disponible ---
    try {
        let poiUrl = `/api/step4/poi?city_id=${cityId}&distance_km=5`;
        if (chosenSpotCoords) {
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
        if (selectedPoiIds.size > 0) document.getElementById('nextStepBtn').style.display = 'block';

        // Vue d'ensemble au départ : tous les marqueurs visibles (activeCategory = null)
        updateMapMarkersVisibility();

        // Centrer la carte sur la rando et le spot du jour (les POI restent affichés
        // mais n'influencent plus le zoom : à l'utilisateur de se déplacer pour en voir plus)
        if (serviceMap && referencePositions.length === 1) {
            serviceMap.setView(referencePositions[0], 15);
        } else if (serviceMap && referencePositions.length > 1) {
            serviceMap.fitBounds(referencePositions, { padding: [60, 60], maxZoom: 16 });
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
        card.className = 'service-card' + (selectedPoiIds.has(poi.id) ? ' selected' : '');
        card.id = `poi-card-${poi.id}`;
        card.innerHTML = `
            <div class="service-content-grid">
                <div class="service-left">
                    <span class="hiking-stats"><span class="stat">${poi.service_type_label}</span></span>
                    <span class="status-badge ${poi.badge.css}">${poi.badge.text}</span>
                </div>
                <div class="service-center">
                    <h4>${poi.name}</h4>
                    ${poi.address ? `<p class="service-address"><i class="fas fa-map-marker-alt"></i> ${poi.address}</p>` : ''}
                    ${poi.distance_label ? `<p class="service-distance"><i class="fas fa-route"></i> ${poi.distance_label}</p>` : ''}
                    <p>${poi.description || ''}</p>
                </div>
                <div class="service-right">
                    <button class="btn btn-outline btn-sm"
                        onclick="showPoiOnMap(${poi.latitude}, ${poi.longitude}, '${safeName}')">
                        <i class="fas fa-map"></i> Voir
                    </button>
                    ${poi.url ? `
                    <a href="${poi.url}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">
                        <i class="fas fa-external-link-alt"></i> Site
                    </a>` : ''}
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
            <button type="button" class="category-tile" onclick="openCategory('${cat}')" aria-label="${meta.label} — ${count} points">
                ${selectedCount ? `<span class="category-tile__selected">✓ ${selectedCount}</span>` : ''}
                <span class="category-tile__icon"><i class="fas ${meta.icon}"></i></span>
                <span class="category-tile__label">${meta.label}</span>
                <span class="category-tile__count">${count} ${count > 1 ? 'points' : 'point'}</span>
            </button>`;
    }).join('');
}

// Vue 2 : ouvrir la sous-liste d'un type de service.
function openCategory(category) {
    activeCategory = category;
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

    // Marqueurs de la catégorie seulement
    updateMapMarkersVisibility();

    // Recadrer la carte sur les points de cette catégorie, sinon ils restent hors
    // champ (la carte était centrée sur la rando/le spot) et « on ne les voit pas ».
    const catMarkers = poiMarkers.filter(m => m.category === category);
    if (serviceMap && catMarkers.length > 0) {
        const bounds = L.latLngBounds(catMarkers.map(m => m.marker.getLatLng()));
        serviceMap.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
    }

    sublist.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Retour à la vue tuiles (recalcule les pastilles « déjà ajouté »).
function showCategoryTiles() {
    activeCategory = null;
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
    const noServiceOption = document.querySelector('.no-service-option');
    if (noServiceOption) noServiceOption.classList.remove('selected');

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
    document.getElementById('nextStepBtn').style.display = 'block';
    // Concept unifié : après l'action, le popup se ferme.
    if (serviceMap) serviceMap.closePopup();
    saveToDB();
}

function selectNoService() {
    const previouslySelected = Array.from(selectedPoiIds);
    selectedPoiIds.clear();
    previouslySelected.forEach(poiId => {
        const btn = document.getElementById(`btn-poi-${poiId}`);
        if (btn) { btn.textContent = 'Ajouter'; btn.className = 'btn btn-primary btn-sm'; }
    });
    previouslySelected.forEach(updatePoiMarker);

    document.querySelector('.no-service-option').classList.add('selected');
    document.getElementById('nextStepBtn').style.display = 'block';

    saveToDB();
}

// Bouton "Récapitulatif" : sauvegarde les services puis affiche le récapitulatif.
// On ATTEND la fin de la sauvegarde avant de quitter la page : naviguer tout de
// suite interrompait la requête en cours ("Failed to fetch" dans la console).
// C'est ensuite /results qui propose de continuer sur la même ville ou d'en
// changer pour le jour suivant (voir stayInSameCity()/changeCityForNextDay()).
async function goToNextDayOrResults() {
    await saveToDB();
    window.location.href = window.APP_URLS.results;
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

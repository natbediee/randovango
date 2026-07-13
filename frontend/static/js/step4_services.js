// Étape 4 : choix des services (POI) utiles pour la journée en cours — eau,
// vidange, carburant, commerces... Les textes des cartes et les phrases de
// sous-titre par catégorie arrivent prêts à afficher depuis l'API (champs badge,
// distance_label, subtitles... préparés par display_utils.py).
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Filtres (onglets) →
// 7. Sélection et sauvegarde → 8. Fonctions exposées aux popups de la carte.

// Toutes les catégories de services, dans l'ordre d'affichage des onglets.
const POI_CATEGORIES = ['eau', 'vidange', 'gasoil', 'supermarche', 'commerce',
                        'restauration', 'toilettes', 'hygiene', 'culture', 'urgence'];

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

// Affiche la phrase de sous-titre correspondant à l'onglet actif.
function updateStep4Subtitle(category) {
    const subtitleEl = document.getElementById('step4Subtitle');
    if (subtitleEl && subtitlesByCategory[category]) {
        subtitleEl.textContent = subtitlesByCategory[category];
    }
}

// N'affiche sur la carte que les marqueurs de l'onglet actif ("Tout" affiche toutes les catégories)
function updateMapMarkersVisibility() {
    if (!serviceMap) return;
    const activeTab = document.querySelector('.category-tab.active');
    const activeCategory = activeTab ? activeTab.dataset.category : 'tout';

    poiMarkers.forEach(({ marker, category }) => {
        const matches = activeCategory === 'tout' || category === activeCategory;
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

    // --- 6. Filtres : onglets de catégories ("Tout" affiche toutes les catégories) ---
    document.querySelectorAll('.category-tab').forEach(tab => {
        tab.addEventListener('click', function () {
            document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            const category = this.dataset.category;
            document.querySelectorAll('.services-grid').forEach(grid => {
                grid.style.display = (category === 'tout' || grid.id === category) ? 'block' : 'none';
            });
            updateMapMarkersVisibility();
            updateStep4Subtitle(category);
        });
    });

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

        // --- 5. Affichage : une grille de cartes par catégorie ---
        subtitlesByCategory = data.subtitles || {};
        POI_CATEGORIES.forEach(category => renderCategory(category, data[category] || []));

        // Phrase dynamique pour l'onglet actif par défaut ("Tout")
        updateStep4Subtitle('tout');

        // Mettre à jour les marqueurs des POI déjà sélectionnés (restauration depuis DB)
        selectedPoiIds.forEach(id => updatePoiMarker(id));
        if (selectedPoiIds.size > 0) document.getElementById('nextStepBtn').style.display = 'block';

        // Afficher les marqueurs correspondant à l'onglet actif par défaut ("Tout")
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
        card.className = 'service-card';
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
            const marker = L.marker([poi.latitude, poi.longitude], {
                icon: buildPoiDivIcon(categoryId)
            }).bindPopup(buildPoiPopupContent(poi, selectedPoiIds.has(poi.id)));
            poiMarkers.push({ marker, category: categoryId, poi });
        }
    });
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
    if (selectedPoiIds.has(poiId)) {
        selectedPoiIds.delete(poiId);
        if (btn) { btn.textContent = 'Ajouter'; btn.className = 'btn btn-primary btn-sm'; }
    } else {
        selectedPoiIds.add(poiId);
        if (btn) { btn.textContent = 'Retirer'; btn.className = 'btn btn-selected btn-sm'; }
    }

    updatePoiMarker(poiId);
    document.getElementById('nextStepBtn').style.display = 'block';
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

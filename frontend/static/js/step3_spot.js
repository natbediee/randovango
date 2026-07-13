// Étape 3 : choix du spot nuit (bivouac, aire, camping...) pour la journée en cours.
// Les textes des cartes arrivent prêts à afficher depuis l'API (catégorie prix,
// badge de vérification, icônes des services... préparés par display_utils.py).
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Filtres → 7. Sélection et
// sauvegarde → 8. Fonctions exposées aux popups de la carte.

// --- 1. Contexte du séjour ---
// Lu au niveau du fichier : les fonctions de sélection (selectSpot...) appelées
// par les popups Leaflet et les boutons de la page en ont aussi besoin.
const { currentDay, selectedDays } = getTripContext();

// État de la carte accessible depuis ces mêmes fonctions globales.
let spotMap = null;
let spotMarkers = []; // { marker, spot }
// Spots déjà utilisés sur un jour précédent du même séjour (Map<spotId, dayNumber>) :
// un spot ne peut être choisi qu'une seule fois par séjour, il devient donc non sélectionnable.
let plannedSpotIds = new Map();

document.addEventListener('DOMContentLoaded', async function() {
    // --- 2. Badge et titres ---
    showDayBadge(currentDay, selectedDays);

    const hikeId = localStorage.getItem('selectedHiking');
    document.getElementById('step3Title').textContent = hikeId === 'no-hiking'
        ? `🌙 Jour ${currentDay} : Où dormir après cette journée détente ?`
        : `🌙 Jour ${currentDay} : Où dormir cette nuit ?`;
    document.getElementById('step3Subtitle').textContent =
        'Choisissez votre spot pour terminer parfaitement cette journée';

    const cityId = requireCity();
    if (!cityId) return;

    // --- 3. Carte ---
    spotMap = await createStepMap(48.4, -4.5, 12);

    // Centrer la page sur la carte à l'arrivée sur l'étape
    document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });

    // Randonnée choisie à l'étape 2 : marqueur "Jx" + tracé GPX, pour situer les
    // spots par rapport à la journée. Sa position sert aussi à centrer la carte.
    const hikeMarkerPosition = await addChosenHikeToMap(spotMap, cityId, hikeId, currentDay);

    // --- 4. Chargement API ---
    let spotsLoadFailed = false;
    try {
        const spots = await apiGet(`/api/step3/spots?city_id=${cityId}`);

        if (spots && spots.length > 0) {
            // --- 5. Affichage ---
            const { planId } = getTripContext();
            ({ plannedSpotIds } = await loadPreviousDaysOnMap(spotMap, currentDay, planId));
            displaySpots(spots, spotMap, hikeMarkerPosition, plannedSpotIds);
        } else {
            document.getElementById('spotsSection').innerHTML = '<p>Aucun spot disponible pour cette zone.</p>';
            if (spotMap && hikeMarkerPosition) {
                spotMap.setView(hikeMarkerPosition, 13);
            }
        }
    } catch (error) {
        console.error('Erreur lors du chargement des spots:', error);
        document.getElementById('spotsSection').innerHTML = '<p>Erreur lors du chargement des spots.</p>';
        document.getElementById('step3Subtitle').textContent = 'Erreur lors du chargement des spots';
        spotsLoadFailed = true;
    }

    // --- 6. Filtres (gratuit / payant / autres) ---
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const group = this.parentElement;
            group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            filterSpotsByType(this.getAttribute('data-filter'));
        });
    });

    // Phrase dynamique initiale indiquant le nombre d'hébergements disponibles
    // (sauf en cas d'erreur de chargement : on garde le message d'erreur affiché)
    if (!spotsLoadFailed) filterSpotsByType('all');

    // Auto-afficher les spots
    document.getElementById('spotsSection').style.display = 'block';
});

// --- 5. Affichage : liste des cartes de spots + marqueurs correspondants ---

function displaySpots(spots, map, hikeMarkerPosition, plannedSpotIds = new Map()) {
    const spotsSection = document.getElementById('spotsSection');
    const spotsList = spotsSection.querySelector('.spots-list');

    spotsList.innerHTML = '';
    spotsSection.style.display = 'block';

    // Créer les marqueurs et les cartes pour chaque spot
    const markerPositions = hikeMarkerPosition ? [hikeMarkerPosition] : [];
    spots.forEach(spot => {
        const plannedDay = plannedSpotIds.get(spot.id);
        spotsList.appendChild(createSpotCard(spot, plannedDay));

        // Ajouter un marqueur sur la carte si disponible
        // zIndexOffset > 500 : passe au-dessus du marqueur "déjà planifié" (sans bouton)
        // dessiné par loadPreviousDaysOnMap pour ce même spot, sinon ce dernier
        // intercepte le clic et empêche de re-choisir le spot pour le jour courant.
        if (map && spot.latitude && spot.longitude) {
            const marker = L.marker([spot.latitude, spot.longitude], { icon: buildSpotDivIcon(), zIndexOffset: 600 })
                .addTo(map)
                .bindPopup(buildSpotPopupContent(spot, false))
                .on('mouseover', function () {
                    const isSelected = localStorage.getItem('selectedSpot') == spot.id;
                    if (!isSelected) this.setIcon(buildSpotHoveredDivIcon());
                    const btn = document.getElementById(`select-spot-btn-${spot.id}`);
                    if (btn) {
                        const card = btn.closest('.spot-card');
                        if (card && !card.classList.contains('selected')) {
                            card.classList.add('map-hover');
                        }
                    }
                })
                .on('mouseout', function () {
                    const isSelected = localStorage.getItem('selectedSpot') == spot.id;
                    if (!isSelected) this.setIcon(buildSpotDivIcon());
                    const btn = document.getElementById(`select-spot-btn-${spot.id}`);
                    if (btn) btn.closest('.spot-card')?.classList.remove('map-hover');
                });
            spotMarkers.push({ marker, spot });

            markerPositions.push([spot.latitude, spot.longitude]);
        }
    });

    // Centrer la carte : priorité à la rando, sinon fitBounds sur tous les spots
    if (map) {
        if (hikeMarkerPosition) {
            map.setView(hikeMarkerPosition, 13);
        } else if (markerPositions.length === 1) {
            map.setView(markerPositions[0], 12);
        } else if (markerPositions.length > 1) {
            map.fitBounds(markerPositions, { padding: [40, 40] });
        }
    }

    // Refléter sur la carte et les boutons une éventuelle sélection déjà faite
    const previouslySelected = localStorage.getItem('selectedSpot');
    if (previouslySelected && previouslySelected !== 'autre_hebergement') {
        updateSpotSelectionUI(previouslySelected);
    }
}

function createSpotCard(spot, plannedDay) {
    const card = document.createElement('div');
    card.className = 'spot-card';
    // Catégorie prix calculée côté Python (display_utils.spot_category), utilisée
    // par le filtre gratuit/payant/autres.
    card.setAttribute('data-type', spot.category);
    card.setAttribute('data-timing', 'same-day');

    const plannedBadge = plannedDay
        ? `<span class="status-badge planned">📌 Planifié J${plannedDay}</span>` : '';

    // Liste des services du spot (icône + nom, préparés côté Python)
    const servicesHTML = spot.services_display.length > 0
        ? spot.services_display.map(s => `<span class="feature">${s.icon} ${s.name}</span>`).join('')
        : '<span class="feature">❌ Aucun service disponible</span>';

    card.innerHTML = `
        <div class="spot-content-grid">
            <!-- Colonne gauche : Type + Vérifié + Planifié -->
            <div class="spot-left">
                <span class="hiking-stats"><span class="stat">${spot.type_label}</span></span>
                <span class="status-badge ${spot.badge.css}">${spot.badge.text}</span>
                ${plannedBadge}
            </div>

            <!-- Colonne centre : Infos bivouac -->
            <div class="spot-center">
                <h4>${spot.name}</h4>
                ${spot.address ? `<p class="spot-address"><i class="fas fa-map-marker-alt"></i> ${spot.address}</p>` : ''}
                <p class="spot-description">${spot.description_label}</p>
                <div class="spot-features">
                    ${servicesHTML}
                </div>
                <div class="spot-details">
                    ${spot.rating_label ? `<span class="rating">${spot.rating_label}</span>` : ''}
                </div>
            </div>

            <!-- Colonne droite : Boutons -->
            <div class="spot-right">
                ${spot.url
                    ? `<a href="${spot.url}" target="_blank" class="btn btn-outline btn-sm">
                        <i class="fas fa-external-link-alt"></i> Voir
                       </a>`
                    : `<button class="btn btn-outline btn-sm" onclick="showSpotOnMap(${spot.latitude}, ${spot.longitude}, '${spot.name}')">
                        <i class="fas fa-map"></i> Carte
                       </button>`
                }
                <button class="btn btn-primary btn-sm" id="select-spot-btn-${spot.id}" onclick="selectSpot(${spot.id})">
                    ${plannedDay ? `Choisir aussi` : 'Choisir'}
                </button>
            </div>
        </div>
    `;

    // Survol de la carte de liste → met en évidence le marqueur correspondant sur la carte
    card.addEventListener('mouseenter', () => {
        const isSelected = localStorage.getItem('selectedSpot') == spot.id;
        if (isSelected) return;
        const markerData = spotMarkers.find(m => m.spot.id === spot.id);
        if (!markerData) return;
        markerData.marker.setIcon(buildSpotHoveredDivIcon());
        if (spotMap && !spotMap.getBounds().contains(markerData.marker.getLatLng())) {
            spotMap.panTo(markerData.marker.getLatLng(), { animate: true });
        }
    });
    card.addEventListener('mouseleave', () => {
        const isSelected = localStorage.getItem('selectedSpot') == spot.id;
        if (isSelected) return;
        const markerData = spotMarkers.find(m => m.spot.id === spot.id);
        if (markerData) markerData.marker.setIcon(buildSpotDivIcon());
    });

    return card;
}

// --- 6. Filtres : liste et marqueurs suivent le même filtre prix ---

function filterSpotsByType(filter) {
    let matchCount = 0;
    document.querySelectorAll('.spot-card').forEach(card => {
        const cardType = card.getAttribute('data-type');
        const matches = filter === 'all' || cardType === filter;
        card.style.display = matches ? '' : 'none';
        if (matches) matchCount++;
    });

    // Appliquer le même filtre aux marqueurs de la carte
    spotMarkers.forEach(({ marker, spot }) => {
        const matches = filter === 'all' || spot.category === filter;
        if (!spotMap) return;
        if (matches && !spotMap.hasLayer(marker)) {
            marker.addTo(spotMap);
        } else if (!matches && spotMap.hasLayer(marker)) {
            spotMap.removeLayer(marker);
        }
    });

    // Phrase dynamique indiquant le nombre de spots correspondant au filtre actif
    const subtitleEl = document.getElementById('step3Subtitle');
    if (subtitleEl) subtitleEl.textContent = matchCountSubtitle(matchCount, 'spot', 'm');
}

// --- 7. Sélection et sauvegarde ---

// Met à jour l'icône des marqueurs, le contenu des popups et les boutons des cartes
function updateSpotSelectionUI(spotId) {
    spotMarkers.forEach(({ marker, spot }) => {
        const isSelected = spot.id == spotId;
        marker.setIcon(isSelected ? buildSpotSelectedDivIcon() : buildSpotDivIcon());
        marker.setPopupContent(buildSpotPopupContent(spot, isSelected));

        const cardBtn = document.getElementById(`select-spot-btn-${spot.id}`);
        if (cardBtn) {
            cardBtn.textContent = isSelected ? '✅ Sélectionné' : 'Choisir';
            cardBtn.classList.toggle('btn-selected', isSelected);
            cardBtn.classList.toggle('btn-primary', !isSelected);
        }
    });
}

// --- 8. Fonctions exposées aux popups Leaflet et aux boutons de la page ---
// Déclarées au niveau du fichier (et donc accessibles via window.*) : les popups
// les appellent par leur nom dans des attributs onclick.

function selectSpot(spotId) {
    document.querySelectorAll('.spot-card').forEach(card => card.classList.remove('selected'));
    const cardBtn = document.getElementById(`select-spot-btn-${spotId}`);
    if (cardBtn) {
        const card = cardBtn.closest('.spot-card');
        card.classList.add('selected');
        card.classList.remove('highlight-frame');
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    const noSpotOption = document.querySelector('.no-spot-option');
    if (noSpotOption) noSpotOption.classList.remove('selected');

    localStorage.setItem('selectedSpot', spotId);
    updateSpotSelectionUI(spotId);

    const nightWeather = document.getElementById('nightWeather');
    if (nightWeather) nightWeather.style.display = 'block';

    const nextBtn = document.getElementById('nextStepBtn');
    if (nextBtn) nextBtn.style.display = 'block';

    saveDayChoice('step3', { spot_id: spotId, day_number: currentDay }, 'spot');
}

function selectNoSpot() {
    document.querySelectorAll('.spot-card').forEach(card => card.classList.remove('selected'));

    const noSpotOption = document.querySelector('.no-spot-option');
    if (noSpotOption) noSpotOption.classList.add('selected');

    localStorage.setItem('selectedSpot', 'autre_hebergement');
    updateSpotSelectionUI(null);

    const nightWeather = document.getElementById('nightWeather');
    if (nightWeather) nightWeather.style.display = 'none';

    const nextBtn = document.getElementById('nextStepBtn');
    if (nextBtn) nextBtn.style.display = 'block';

    // Réinitialise spot_id en base
    saveDayChoice('step3', { spot_id: null, day_number: currentDay }, 'spot');
}

// Bouton "Détail" du popup carte : amène à la carte du spot dans la liste et l'encadre
function showSpotDetail(spotId) {
    const btn = document.getElementById(`select-spot-btn-${spotId}`);
    if (!btn) return;
    const card = btn.closest('.spot-card');
    document.querySelectorAll('.spot-card.highlight-frame').forEach(c => c.classList.remove('highlight-frame'));
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('highlight-flash', 'highlight-frame');
    setTimeout(() => card.classList.remove('highlight-flash'), 1400);
}

// Contenu du popup d'un spot, avec le bouton "Choisir" qui reflète l'état sélectionné
function buildSpotPopupContent(spot, isSelected) {
    return `<b>${spot.name}</b><br>${spot.type}
        ${spot.address ? `<br><small>📍 ${spot.address}</small>` : ''}
        <div style="margin-top:6px;display:flex;gap:6px;">
            <button class="btn btn-outline btn-sm" onclick="showSpotDetail(${spot.id})">Détail</button>
            <button class="btn btn-sm ${isSelected ? 'btn-selected' : 'btn-primary'}" onclick="selectSpot(${spot.id})">
                ${isSelected ? '✅ Sélectionné' : 'Choisir'}
            </button>
        </div>`;
}

// Bouton "Carte" d'un spot sans site web : centre la carte sur le spot
function showSpotOnMap(lat, lon, name) {
    if (spotMap) {
        document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
        spotMap.setView([lat, lon], 14);
        L.popup().setLatLng([lat, lon]).setContent(`<b>${name}</b>`).openOn(spotMap);
    }
}

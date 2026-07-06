    // ========================================
    // INITIALISATION ET CHARGEMENT DES SPOTS
    // ========================================

const currentDay = parseInt(localStorage.getItem('currentDay') || '1');

// État de la carte accessible depuis les fonctions globales de sélection (selectSpot, etc.)
let spotMap = null;
let spotMarkers = []; // { marker, spot }
// Spots déjà utilisés sur un jour précédent du même séjour (Map<spotId, dayNumber>) :
// un spot ne peut être choisi qu'une seule fois par séjour, il devient donc non sélectionnable.
let plannedSpotIds = new Map();

document.addEventListener('DOMContentLoaded', async function() {
    const selectedDays = parseInt(localStorage.getItem('selectedDays') || '1');

    // Badge "Jour X/N" en haut à gauche du stepper (dynamique, depuis localStorage)
    const dayBadge = document.getElementById('dayBadge');
    if (dayBadge) dayBadge.textContent = `Jour ${currentDay}/${selectedDays}`;

    document.getElementById('step3Title').textContent =
        `🌙 Jour ${currentDay} : Où dormir cette nuit ?`;
    document.getElementById('step3Subtitle').textContent =
        'Choisissez votre spot pour terminer parfaitement cette journée';

    // Récupérer l'ID de la ville et de la randonnée depuis localStorage
    const cityId = localStorage.getItem('selectedCityId');
    const hikeId = localStorage.getItem('selectedHiking');
    
    // Validation : vérifier qu'une ville a été sélectionnée
    if (!cityId) {
        alert('Aucune ville sélectionnée. Retour à l\'étape 1.');
        window.location.href = window.APP_URLS.step1;
        return;
    }
    
    // ========================================
    // INITIALISATION DE LA CARTE LEAFLET
    // ========================================
    
    const mapElement = document.getElementById('map');

    if (mapElement && window.L && !mapElement._leaflet_id) {
        // Créer la carte Leaflet avec position par défaut (sera mise à jour)
        const boundsOptions = await getCityBoundsOptions();
        spotMap = L.map('map', { minZoom: 3, ...boundsOptions }).setView([48.4, -4.5], 12);

        // Ajouter les tuiles OpenStreetMap
        L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(spotMap);
        fixMapSizeOnLoad(spotMap);
    }

    // Centrer la page sur la carte à l'arrivée sur l'étape
    mapElement.scrollIntoView({ behavior: 'smooth', block: 'center' });

    // ========================================
    // MARQUEUR DE LA RANDONNÉE CHOISIE (même logo que la page résultat)
    // ========================================
    let hikeMarkerPosition = null;
    if (spotMap && hikeId && hikeId !== 'no-hiking') {
        try {
            const hikesResponse = await fetch(`${window.API_BASE}/api/step2/hikes?city_id=${cityId}&distance_km=5`);
            if (hikesResponse.ok) {
                const hikes = await hikesResponse.json();
                const chosenHike = hikes.find(h => String(h.id) === String(hikeId));
                if (chosenHike && chosenHike.start_latitude && chosenHike.start_longitude) {
                    hikeMarkerPosition = [chosenHike.start_latitude, chosenHike.start_longitude];
                    L.marker(hikeMarkerPosition, { icon: buildHikeDivIcon(`J${currentDay}`), zIndexOffset: 1000 })
                        .addTo(spotMap)
                        .bindPopup(`<b>🥾 ${chosenHike.name}</b><br>${chosenHike.distance_km} km - ${chosenHike.duration}h`);
                }
            }
        } catch (err) {
            console.error('Erreur chargement randonnée choisie:', err);
        }

        // Tracé GPX de la randonnée sélectionnée
        try {
            const traceRes = await fetch(`${window.API_BASE}/api/step2/hike/${hikeId}/trace`);
            if (traceRes.ok) {
                const traceData = await traceRes.json();
                if (traceData.points && traceData.points.length > 0) {
                    const latlngs = traceData.points.map(p => [p.lat, p.lon]);
                    L.polyline(latlngs, { color: '#339af0', weight: 3, opacity: 0.8 }).addTo(spotMap);
                }
            }
        } catch (err) {
            console.error('Erreur chargement tracé GPX:', err);
        }
    }

    // ========================================
    // CHARGEMENT DES SPOTS
    // ========================================

    let spotsLoadFailed = false;
    try {
        // Appel direct à l'API FastAPI (pas d'authentification requise sur cette route)
        const response = await fetch(`${window.API_BASE}/api/step3/spots?city_id=${cityId}&hike_id=${hikeId || 0}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Erreur lors du chargement des spots');
        }
        
        const spots = await response.json();
        console.log('Spots récupérés:', spots);
        
        // Afficher les spots dynamiquement
        if (spots && spots.length > 0) {
            const planId = localStorage.getItem('planId');
            ({ plannedSpotIds } = await loadPreviousDaysOnMap(spotMap, currentDay, planId));
            displaySpots(spots, spotMap, hikeMarkerPosition, plannedSpotIds);
        } else {
            console.log('Aucun spot trouvé pour cette ville');
            document.getElementById('spotsSection').innerHTML = '<p>Aucun spot disponible pour cette zone.</p>';
            if (spotMap && hikeMarkerPosition) {
                spotMap.setView(hikeMarkerPosition, 13);
            }
        }
        
    } catch (error) {
        console.error('Erreur lors du chargement des spots:', error);
        document.getElementById('spotsSection').innerHTML = '<p>Erreur lors du chargement des spots.</p>';
        const subtitleEl = document.getElementById('step3Subtitle');
        if (subtitleEl) subtitleEl.textContent = 'Erreur lors du chargement des spots';
        spotsLoadFailed = true;
    }

    // Adapter le titre si pas de randonnée
    const selectedHiking = localStorage.getItem('selectedHiking');
    if (selectedHiking === 'no-hiking') {
        document.getElementById('step3Title').textContent =
            `🌙 Jour ${currentDay} : Où dormir après cette journée détente ?`;
    }

    // Gestion des filtres type
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

    // Sauvegarde en base de données
    const planId = localStorage.getItem('planId');
    if (planId) {
        fetch(`${window.API_BASE}/api/step3/update_plan/${planId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ spot_id: spotId, day_number: currentDay })
        }).catch(err => console.error('Erreur sauvegarde spot:', err));
    }
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
    const planId = localStorage.getItem('planId');
    if (planId) {
        fetch(`${window.API_BASE}/api/step3/update_plan/${planId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ spot_id: null, day_number: currentDay })
        }).catch(err => console.error('Erreur reset spot:', err));
    }
}

function showSpotMap(spotId) {
    // Ouvrir la vue cartographique avec la randonnée choisie + l'emplacement du bivouac
    const selectedHiking = localStorage.getItem('selectedHiking') || '1';
    const mapUrl = `/map/spot/${spotId}?hiking=${selectedHiking}`;
    window.open(mapUrl, '_blank', 'width=1200,height=800');
}


// ========================================
// FONCTION D'AFFICHAGE DYNAMIQUE DES SPOTS
// ========================================

function displaySpots(spots, map, hikeMarkerPosition, plannedSpotIds = new Map()) {
    const spotsSection = document.getElementById('spotsSection');
    const spotsList = spotsSection.querySelector('.spots-list');

    // Vider la liste existante
    spotsList.innerHTML = '';

    // Afficher la section
    spotsSection.style.display = 'block';

    // Créer les marqueurs et les cards pour chaque spot
    const markerPositions = hikeMarkerPosition ? [hikeMarkerPosition] : [];
    spots.forEach((spot, index) => {
        const plannedDay = plannedSpotIds.get(spot.id);
        const spotCard = createSpotCard(spot, index, plannedDay);
        spotsList.appendChild(spotCard);

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

function createSpotCard(spot, index, plannedDay) {
    const card = document.createElement('div');
    card.className = 'spot-card';
    card.setAttribute('data-type', normalizeType(spot.type));
    card.setAttribute('data-timing', 'same-day');

    // Déterminer le badge de vérification
    const verifiedBadge = spot.verifie === 1
        ? '<span class="status-badge verified">✅ Vérifié</span>'
        : '<span class="status-badge pending">⚠️ En attente</span>';
    const plannedBadge = plannedDay
        ? `<span class="status-badge planned">📌 Planifié J${plannedDay}</span>` : '';
    
    // Construire la liste des services (features)
    let servicesHTML = '';
    if (spot.services && spot.services.length > 0) {
        servicesHTML = spot.services.map(service => 
            `<span class="feature">${getServiceIcon(service)} ${service}</span>`
        ).join('');
    } else {
        servicesHTML = '<span class="feature">❌ Aucun service disponible</span>';
    }
    
    // Construire le HTML de la card
    card.innerHTML = `
        <div class="spot-content-grid">
            <!-- Colonne gauche : Type + Vérifié + Planifié -->
            <div class="spot-left">
                <span class="hiking-stats"><span class="stat">${spot.type || 'Bivouac'}</span></span>
                ${verifiedBadge}
                ${plannedBadge}
            </div>
            
            <!-- Colonne centre : Infos bivouac -->
            <div class="spot-center">
                <h4>${spot.name}</h4>
                ${spot.address ? `<p class="spot-address"><i class="fas fa-map-marker-alt"></i> ${spot.address}</p>` : ''}
                <p class="spot-description">${spot.description || 'Aucune description disponible'}</p>
                <div class="spot-features">
                    ${servicesHTML}
                </div>
                <div class="spot-details">
                    ${spot.rating ? `<span class="rating">⭐ ${spot.rating}/5</span>` : ''}
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

    // Survol de la carte → met en évidence le marqueur correspondant sur la carte
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

function normalizeType(type) {
    if (!type) return 'autres';
    const GRATUIT = [
        'AIRE CC STAT. GRATUIT',
        'PARKING CC SANS SERVICES',
        'PARKING JOUR ET NUIT',
        'AIRE DE REPOS'
    ];
    const PAYANT = [
        'AIRE CC STAT. PAYANT',
        'CAMPING',
        'AIRE CC PRIVÉE',
        'ACCUEIL ENTRE PARTICULIERS',
        'A LA FERME (FERME, VIGNOBLE ...)'
    ];
    const t = type.toUpperCase().trim();
    if (GRATUIT.some(v => v.toUpperCase() === t)) return 'gratuit';
    if (PAYANT.some(v => v.toUpperCase() === t)) return 'payant';
    return 'autres';
}

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
        const matches = filter === 'all' || normalizeType(spot.type) === filter;
        if (!spotMap) return;
        if (matches && !spotMap.hasLayer(marker)) {
            marker.addTo(spotMap);
        } else if (!matches && spotMap.hasLayer(marker)) {
            spotMap.removeLayer(marker);
        }
    });

    // Phrase dynamique indiquant le nombre de spots correspondant au filtre actif
    const subtitleEl = document.getElementById('step3Subtitle');
    if (subtitleEl) {
        subtitleEl.textContent = matchCount === 0
            ? 'Aucun spot ne correspond à vos critères'
            : `${matchCount} spot${matchCount > 1 ? 's' : ''} correspond${matchCount > 1 ? 'ent' : ''} à vos critères`;
    }
}

function getServiceIcon(serviceName) {
    // Mapper les noms de services à des icônes
    const iconMap = {
        'Eau': '💧',
        'WC': '🚽',
        'Douche': '🚿',
        'Électricité': '⚡',
        'WiFi': '📶',
        'Restaurant': '🍽️',
        'Supermarché': '🛒',
        'Boulangerie': '🥐',
        'Parking': '🅿️',
        'Plage': '🏖️',
        'Vue mer': '🌅'
    };
    
    // Rechercher l'icône correspondante
    for (const [key, icon] of Object.entries(iconMap)) {
        if (serviceName.toLowerCase().includes(key.toLowerCase())) {
            return icon;
        }
    }
    
    return '✓'; // Icône par défaut
}

function showSpotOnMap(lat, lon, name) {
    const mapElement = document.getElementById('map');
    if (mapElement && window.L) {
        // Récupérer l'instance de la carte depuis l'élément
        let map;
        if (mapElement._leaflet_id) {
            map = mapElement._leaflet || L.map(mapElement);
        }
        
        if (map) {
            map.setView([lat, lon], 14);
            L.popup()
                .setLatLng([lat, lon])
                .setContent(`<b>${name}</b>`)
                .openOn(map);
        }
    }
}


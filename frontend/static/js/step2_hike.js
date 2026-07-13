// Étape 2 : choix de la randonnée de la journée. Les textes des cartes arrivent
// prêts à afficher depuis l'API (badge, catégorie de durée, couleur du tracé...
// préparés par display_utils.py) ; le JS affiche la liste, la carte et les tracés
// GPX, et applique les filtres difficulté/durée.
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Filtres → 7. Sélection et
// sauvegarde → 8. Fonctions exposées aux popups de la carte.

document.addEventListener('DOMContentLoaded', async function () {
    // --- 1. Contexte du séjour ---
    const { currentDay, selectedDays, planId } = getTripContext();

    // --- 2. Badge et titres ---
    showDayBadge(currentDay, selectedDays);
    document.getElementById('step2Title').textContent =
        `🥾 Jour ${currentDay} : Choisissez votre randonnée`;
    document.getElementById('step2Subtitle').textContent =
        'Sélectionnez l\'activité principale qui rythmera votre journée';

    const cityId = requireCity();
    if (!cityId) return;

    // --- 3. Carte ---
    let hikingMarkers = [];  // { marker, hike, polyline }

    // Filtres actifs (doivent être initialisés avant le premier appel à applyFilters(),
    // déclenché dès le chargement initial des randonnées)
    let activeDifficultyFilter = 'all';
    let activeDurationFilter = 'all';

    const hikeMap = await createStepMap(48.4, -4.5, 12);

    // Centrer la page sur la carte à l'arrivée sur l'étape
    document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });

    // Marqueur bleu de la ville (centre de recherche des randonnées)
    try {
        const cities = await apiGet('/api/step1/cities');
        const selectedCity = cities.find(c => c.id == cityId);
        if (selectedCity && hikeMap) {
            const cityIcon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style="background-color: #339af0; width: 24px; height: 24px; border-radius: 50%; border: 3px solid white; box-shadow: 0 3px 8px rgba(0,0,0,0.4);"></div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12]
            });
            L.marker([selectedCity.latitude, selectedCity.longitude], { icon: cityIcon })
                .addTo(hikeMap)
                .bindPopup(`<b>📍 ${selectedCity.name}</b><br>Centre de recherche`);
            hikeMap.setView([selectedCity.latitude, selectedCity.longitude], 12);
        }
    } catch (error) {
        console.error('Erreur lors de la récupération de la ville:', error);
    }

    // --- 4. Chargement API ---
    // Charger les randonnées (et leurs tracés GPX) depuis l'API, ou depuis le cache
    // de session si elles ont déjà été chargées pour cette ville lors d'un jour
    // précédent du même séjour. Le "v2" de la clé invalide les caches d'avant la
    // refonte : ils n'ont pas les champs prêts à afficher ajoutés par l'API.
    try {
        const cacheKey = `hikesCache_v2_${cityId}`;
        let hikes, tracesByHikeId;
        try {
            const cached = JSON.parse(sessionStorage.getItem(cacheKey));
            if (cached && Array.isArray(cached.hikes)) {
                hikes = cached.hikes;
                tracesByHikeId = cached.traces || {};
            }
        } catch { /* cache absent ou corrompu : on ignore et on recharge depuis l'API */ }

        if (!hikes) {
            // Randonnées dans un rayon de 5 km autour de la ville
            hikes = await apiGet(`/api/step2/hikes?city_id=${cityId}&distance_km=5`);

            // Charger le tracé GPX de chaque randonnée
            tracesByHikeId = {};
            await Promise.all(hikes.map(async (hike) => {
                try {
                    const traceData = await apiGet(`/api/step2/hike/${hike.id}/trace`);
                    if (traceData.points && traceData.points.length > 0) {
                        tracesByHikeId[hike.id] = traceData.points.map(p => [p.lat, p.lon]);
                    }
                } catch (err) {
                    console.error(`Erreur chargement tracé GPX pour la randonnée ${hike.id}:`, err);
                }
            }));

            try {
                sessionStorage.setItem(cacheKey, JSON.stringify({ hikes, traces: tracesByHikeId }));
            } catch (e) {
                console.warn('Cache des randonnées non sauvegardé (sessionStorage plein ?)', e);
            }
        }

        // --- 5. Affichage : jours déjà planifiés, liste des cartes, marqueurs, tracés ---
        const { plannedHikeIds } = await loadPreviousDaysOnMap(hikeMap, currentDay, planId);
        displayHikes(hikes, plannedHikeIds);
        applyFilters();

        if (hikeMap && hikes.length > 0) {
            hikes.forEach(hike => {
                const marker = L.marker([hike.start_latitude, hike.start_longitude], { icon: buildHikeDivIcon() })
                    .addTo(hikeMap)
                    .bindPopup(buildHikePopupContent(hike, false))
                    .on('mouseover', function () {
                        const isSelected = localStorage.getItem('selectedHiking') == hike.id;
                        if (!isSelected) this.setIcon(buildHikeHoveredDivIcon());
                        highlightHikeTrace(hike.id, true);
                        const btn = document.getElementById(`select-hike-btn-${hike.id}`);
                        if (btn) {
                            const card = btn.closest('.hiking-card');
                            if (card && !card.classList.contains('selected')) {
                                card.classList.add('map-hover');
                            }
                        }
                    })
                    .on('mouseout', function () {
                        const isSelected = localStorage.getItem('selectedHiking') == hike.id;
                        if (!isSelected) this.setIcon(buildHikeDivIcon());
                        highlightHikeTrace(hike.id, false);
                        const btn = document.getElementById(`select-hike-btn-${hike.id}`);
                        if (btn) btn.closest('.hiking-card')?.classList.remove('map-hover');
                    });
                hikingMarkers.push({ marker, hike, polyline: null });

                // Survol de la carte liste → marqueur orange (handler attaché ici pour capturer marker directement)
                const btn = document.getElementById(`select-hike-btn-${hike.id}`);
                if (btn) {
                    const card = btn.closest('.hiking-card');
                    if (card) {
                        card.addEventListener('mouseenter', () => {
                            const isSelected = localStorage.getItem('selectedHiking') == hike.id;
                            highlightHikeTrace(hike.id, true);
                            if (isSelected) return;
                            marker.setIcon(buildHikeHoveredDivIcon());
                            if (!hikeMap.getBounds().contains(marker.getLatLng())) {
                                hikeMap.panTo(marker.getLatLng(), { animate: true });
                            }
                        });
                        card.addEventListener('mouseleave', () => {
                            const isSelected = localStorage.getItem('selectedHiking') == hike.id;
                            highlightHikeTrace(hike.id, false);
                            if (!isSelected) marker.setIcon(buildHikeDivIcon());
                        });
                    }
                }
            });

            // Dessiner le tracé GPX de chaque randonnée sur la carte (déjà en mémoire :
            // venant du réseau ou du cache de session). La couleur de chaque tracé est
            // calculée côté Python (hike.color, dégradé de bleus).
            hikes.forEach(hike => {
                const latlngs = tracesByHikeId[hike.id];
                if (!latlngs || latlngs.length === 0) return;
                const entry = hikingMarkers.find(m => m.hike.id === hike.id);
                const polyline = L.polyline(latlngs, { color: hike.color, weight: 3, opacity: 0.8 })
                    .addTo(hikeMap)
                    .bindPopup(buildHikePopupContent(hike, localStorage.getItem('selectedHiking') == hike.id))
                    .on('mouseover', function () { highlightHikeTrace(hike.id, true); })
                    .on('mouseout', function () { highlightHikeTrace(hike.id, false); });
                if (entry) entry.polyline = polyline;
            });

            // Refléter sur la carte et les boutons une éventuelle sélection déjà faite
            const previouslySelected = localStorage.getItem('selectedHiking');
            if (previouslySelected && previouslySelected !== 'no-hiking') {
                updateSelectionUI(previouslySelected);
                // Centrer la carte sur la rando déjà sélectionnée
                const selectedMarkerData = hikingMarkers.find(m => m.hike.id == previouslySelected);
                if (selectedMarkerData) {
                    hikeMap.setView(
                        [selectedMarkerData.hike.start_latitude, selectedMarkerData.hike.start_longitude],
                        14
                    );
                    selectedMarkerData.marker.openPopup();
                }
            } else {
                // Aucune sélection : recadrer pour montrer tous les marqueurs et tracés
                const allLayers = hikingMarkers.flatMap(m => m.polyline ? [m.marker, m.polyline] : [m.marker]);
                const group = L.featureGroup(allLayers);
                hikeMap.fitBounds(group.getBounds(), { padding: [40, 40] });
            }
        }
    } catch (error) {
        console.error('Erreur:', error);
        document.getElementById('hikingList').innerHTML = '<p style="text-align: center; color: red;">Erreur lors du chargement des randonnées</p>';
        document.getElementById('step2Subtitle').textContent = 'Erreur lors du chargement des randonnées';
    }

    // --- 5. Affichage : liste des cartes de randonnées ---
    // plannedDays : Map<hikeId → dayNumber> pour les randos déjà planifiées
    function displayHikes(hikes, plannedDays = new Map()) {
        const hikingList = document.getElementById('hikingList');
        hikingList.innerHTML = '';

        if (hikes.length === 0) {
            hikingList.innerHTML = '<p style="text-align: center;">Aucune randonnée disponible pour cette ville</p>';
            return;
        }

        hikes.forEach(hike => {
            const selectedHiking = localStorage.getItem('selectedHiking');
            const isSelected = selectedHiking && selectedHiking == hike.id;
            const plannedDay = plannedDays.get(hike.id);
            const plannedBadge = plannedDay
                ? `<span class="status-badge planned">📌 Planifié J${plannedDay}</span>` : '';

            const card = document.createElement('div');
            card.className = 'hiking-card' + (isSelected ? ' selected' : '');
            // Attributs lus par les filtres difficulté/durée (applyFilters)
            card.setAttribute('data-difficulty', hike.difficulty_css);
            card.setAttribute('data-duration', hike.duration_category);

            card.innerHTML = `
                <div class="hiking-status">
                    <span class="status-badge ${hike.badge.css}">${hike.badge.text}</span>
                    ${plannedBadge}
                </div>
                <div class="hiking-info">
                    <h3>${hike.name}</h3>
                    <p class="hiking-description">${hike.description_label}</p>
                    <div class="hiking-stats">
                        <span class="stat"><i class="fas fa-clock"></i>${hike.duration}h</span>
                        <span class="stat"><i class="fas fa-route"></i>${hike.distance_km} km</span>
                        <span class="stat"><i class="fas fa-mountain"></i>+${hike.elevation_gain_m}m</span>
                        <span class="stat difficulty-${hike.difficulty_css}">
                            <i class="fas fa-signal"></i>${hike.difficulty_label}
                        </span>
                    </div>
                </div>
                <div class="hiking-actions">
                    <button class="btn ${isSelected ? 'btn-selected' : 'btn-primary'}" id="select-hike-btn-${hike.id}" onclick="selectHiking(${hike.id})">
                        ${isSelected ? '✅ Sélectionné' : (plannedDay ? `Choisir aussi` : 'Choisir')}
                    </button>
                </div>
            `;

            hikingList.appendChild(card);
        });
    }

    // --- 6. Filtres difficulté/durée : liste et carte suivent les mêmes filtres ---
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const group = this.parentElement;
            const filterType = group.querySelector('label').textContent.includes('Difficulté') ? 'difficulty' : 'duration';
            const filterValue = this.getAttribute('data-filter');

            // Mettre à jour le bouton actif dans le groupe
            group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');

            if (filterType === 'difficulty') {
                activeDifficultyFilter = filterValue;
            } else {
                activeDurationFilter = filterValue;
            }

            applyFilters();
        });
    });

    function applyFilters() {
        const hikingCards = document.querySelectorAll('.hiking-card');
        let matchCount = 0;

        hikingCards.forEach(card => {
            const matchesDifficulty = activeDifficultyFilter === 'all'
                || card.getAttribute('data-difficulty') === activeDifficultyFilter;
            const matchesDuration = activeDurationFilter === 'all'
                || card.getAttribute('data-duration') === activeDurationFilter;

            if (matchesDifficulty && matchesDuration) {
                card.style.display = 'flex';
                matchCount++;
            } else {
                card.style.display = 'none';
            }
        });

        // Phrase dynamique indiquant le nombre de randonnées correspondant aux filtres actifs
        const subtitleEl = document.getElementById('step2Subtitle');
        if (subtitleEl) subtitleEl.textContent = matchCountSubtitle(matchCount, 'randonnée', 'f');

        // Répercuter le même filtre sur la carte : masquer marqueurs et tracés
        // des randonnées qui ne correspondent pas (sinon la carte continue d'afficher
        // toutes les randos même quand la liste est filtrée).
        if (hikeMap) {
            hikingMarkers.forEach(({ marker, hike, polyline }) => {
                const matches = (activeDifficultyFilter === 'all' || hike.difficulty_css === activeDifficultyFilter)
                    && (activeDurationFilter === 'all' || hike.duration_category === activeDurationFilter);

                if (matches) {
                    if (!hikeMap.hasLayer(marker)) marker.addTo(hikeMap);
                    if (polyline && !hikeMap.hasLayer(polyline)) polyline.addTo(hikeMap);
                } else {
                    if (hikeMap.hasLayer(marker)) hikeMap.removeLayer(marker);
                    if (polyline && hikeMap.hasLayer(polyline)) hikeMap.removeLayer(polyline);
                }
            });
        }
    }

    // Contenu du popup d'une randonnée, avec le bouton "Choisir" qui reflète l'état sélectionné
    function buildHikePopupContent(hike, isSelected) {
        return `<b>🥾 ${hike.name}</b><br>${hike.summary_label}
            <div style="margin-top:6px;display:flex;gap:6px;">
                <button class="btn btn-outline btn-sm" onclick="showHikeDetail(${hike.id})">Détail</button>
                <button class="btn btn-sm ${isSelected ? 'btn-selected' : 'btn-primary'}" onclick="selectHiking(${hike.id})">
                    ${isSelected ? '✅ Sélectionné' : 'Choisir'}
                </button>
            </div>`;
    }

    // Survol d'un tracé (marqueur ou carte de liste) : le met en évidence sur la carte
    function highlightHikeTrace(hikeId, hovered) {
        const entry = hikingMarkers.find(m => m.hike.id == hikeId);
        if (!entry || !entry.polyline) return;
        const isSelected = localStorage.getItem('selectedHiking') == hikeId;
        if (isSelected) return; // le tracé sélectionné garde son style vert
        entry.polyline.setStyle(hovered
            ? { color: '#ff9800', weight: 5, opacity: 0.95 }
            : { color: entry.hike.color, weight: 3, opacity: 0.8 });
        if (hovered) entry.polyline.bringToFront();
    }

    // --- 7. Sélection : met à jour marqueurs, tracés, popups et boutons des cartes ---
    function updateSelectionUI(hikingId) {
        hikingMarkers.forEach(({ marker, hike, polyline }) => {
            const isSelected = hike.id == hikingId;
            marker.setIcon(isSelected ? buildHikeSelectedDivIcon() : buildHikeDivIcon());
            marker.setPopupContent(buildHikePopupContent(hike, isSelected));
            if (polyline) {
                polyline.setPopupContent(buildHikePopupContent(hike, isSelected));
                polyline.setStyle(isSelected
                    ? { color: '#4CAF50', weight: 5, opacity: 0.9 }
                    : { color: hike.color, weight: 3, opacity: 0.8 });
                if (isSelected) polyline.bringToFront();
            }

            const cardBtn = document.getElementById(`select-hike-btn-${hike.id}`);
            if (cardBtn) {
                cardBtn.textContent = isSelected ? '✅ Sélectionné' : 'Choisir';
                cardBtn.classList.toggle('btn-selected', isSelected);
                cardBtn.classList.toggle('btn-primary', !isSelected);
            }
        });
    }

    // --- 8. Fonctions exposées aux popups Leaflet et aux boutons de la page ---
    // Attachées explicitement à window : les popups les appellent par leur nom
    // dans des attributs onclick.

    // Bouton "Détail" du popup carte : amène à la carte de la randonnée dans la liste
    window.showHikeDetail = function (hikeId) {
        const btn = document.getElementById(`select-hike-btn-${hikeId}`);
        if (!btn) return;
        const card = btn.closest('.hiking-card');
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('highlight-flash');
        setTimeout(() => card.classList.remove('highlight-flash'), 1400);
    };

    // Clic sur un marqueur de la carte : centrer et ouvrir le popup
    window.showHikingMap = function (hikeId, lat, lon) {
        if (hikeMap) {
            hikeMap.setView([lat, lon], 14);
            const markerData = hikingMarkers.find(m => m.hike.id === hikeId);
            if (markerData) markerData.marker.openPopup();
        }
    };

    // Sélection d'une randonnée (depuis une carte de la liste ou un popup)
    window.selectHiking = function (hikingId) {
        localStorage.setItem('selectedHiking', hikingId);
        document.querySelectorAll('.hiking-card').forEach(card => card.classList.remove('selected'));
        document.getElementById('noHikingCard').classList.remove('selected');
        const selectedBtn = document.getElementById(`select-hike-btn-${hikingId}`);
        if (selectedBtn) {
            const card = selectedBtn.closest('.hiking-card');
            card.classList.add('selected');
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        document.getElementById('nextStepBtn').style.display = 'flex';
        updateSelectionUI(hikingId);

        // Centrer la carte sur la randonnée sélectionnée et ouvrir son popup
        const selectedMarkerData = hikingMarkers.find(m => m.hike.id == hikingId);
        if (hikeMap && selectedMarkerData) {
            hikeMap.setView(
                [selectedMarkerData.hike.start_latitude, selectedMarkerData.hike.start_longitude],
                14,
                { animate: true }
            );
            selectedMarkerData.marker.openPopup();
        }

        saveDayChoice('step2', { hike_id: hikingId, day_number: currentDay }, 'randonnée');
    };

    // Option "Pas de randonnée aujourd'hui" : journée détente
    window.selectNoHiking = function () {
        localStorage.setItem('selectedHiking', 'no-hiking');
        document.querySelectorAll('.hiking-card').forEach(card => card.classList.remove('selected'));
        document.getElementById('noHikingCard').classList.add('selected');
        document.getElementById('nextStepBtn').style.display = 'flex';
        updateSelectionUI(null);

        // Réinitialise hike_id en base
        saveDayChoice('step2', { hike_id: null, day_number: currentDay }, 'randonnée');
    };
});

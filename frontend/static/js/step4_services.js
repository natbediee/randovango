    // État global de l'étape 4
    let selectedPoiIds = new Set();
    let serviceMap = null;
    let poiMarkers = []; // { marker, category }
    let categoryCounts = {}; // nombre de résultats par catégorie, rempli après chargement des POI

    // Libellés pour la phrase dynamique "X service(s) disponible(s) pour cette journée"
    const CATEGORY_LABELS = {
        tout:         { singular: 'service',           plural: 'services',            gender: 'm' },
        eau:          { singular: "point d'eau",        plural: "points d'eau",        gender: 'm' },
        vidange:      { singular: 'station de vidange', plural: 'stations de vidange', gender: 'f' },
        gasoil:       { singular: 'point carburant',    plural: 'points carburant',    gender: 'm' },
        supermarche:  { singular: 'supermarché',        plural: 'supermarchés',        gender: 'm' },
        commerce:     { singular: 'commerce',           plural: 'commerces',           gender: 'm' },
        restauration: { singular: 'restaurant',         plural: 'restaurants',         gender: 'm' },
        toilettes:    { singular: 'point toilettes',    plural: 'points toilettes',    gender: 'm' },
        hygiene:      { singular: 'point hygiène',      plural: 'points hygiène',      gender: 'm' },
        culture:      { singular: 'site culturel',      plural: 'sites culturels',     gender: 'm' },
        urgence:      { singular: "service d'urgence",  plural: "services d'urgence",  gender: 'm' }
    };

    // Phrase dynamique indiquant le nombre de résultats pour la catégorie active
    function updateStep4Subtitle(category) {
        const subtitleEl = document.getElementById('step4Subtitle');
        if (!subtitleEl) return;
        const labels = CATEGORY_LABELS[category] || CATEGORY_LABELS.tout;
        const count = categoryCounts[category] || 0;
        if (count === 0) {
            subtitleEl.textContent = `${labels.gender === 'f' ? 'Aucune' : 'Aucun'} ${labels.singular} disponible pour cette journée`;
        } else {
            const noun = count > 1 ? labels.plural : labels.singular;
            subtitleEl.textContent = `${count} ${noun} disponible${count > 1 ? 's' : ''} pour cette journée`;
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

    const currentDay = parseInt(localStorage.getItem('currentDay') || '1');
    const selectedDays = parseInt(localStorage.getItem('selectedDays') || '1');

    // Bouton "suivant" : sauvegarde les services puis affiche le récapitulatif.
    // C'est désormais /results qui propose de continuer sur la même ville ou d'en
    // changer pour le jour suivant (voir stayInSameCity()/changeCityForNextDay()).
    function goToNextDayOrResults() {
        const planId = localStorage.getItem('planId');
        if (planId) {
            fetch(`${window.API_BASE}/api/step4/update_plan/${planId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ services: Array.from(selectedPoiIds), day_number: currentDay })
            }).catch(err => console.error('Erreur sauvegarde services:', err));
        }
        window.location.href = window.APP_URLS.results;
    }

    document.addEventListener('DOMContentLoaded', async function () {
        const cityId = localStorage.getItem('selectedCityId');
        if (!cityId) {
            alert('Aucune ville sélectionnée. Retour à l\'étape 1.');
            window.location.href = window.APP_URLS.step1;
            return;
        }

        // Badge "Jour X/N" en haut à gauche du stepper (dynamique, depuis localStorage)
        const dayBadge = document.getElementById('dayBadge');
        if (dayBadge) dayBadge.textContent = `Jour ${currentDay}/${selectedDays}`;

        // Titre dynamique selon le jour en cours
        const isDetente = localStorage.getItem('selectedHiking') === 'no-hiking';
        document.getElementById('step4Title').textContent =
            `🛠️ Jour ${currentDay} : Services pour ${isDetente ? 'votre journée détente' : 'compléter votre journée'}`;

        // Label jour dans la section sélectionnés
        const dayLabelEl = document.getElementById('selectedDayLabel');
        if (dayLabelEl) dayLabelEl.textContent = currentDay;

        // Label du bouton suivant
        const nextLabel = document.getElementById('nextStepLabel');
        if (nextLabel) nextLabel.textContent = 'Récapitulatif';

        // Initialiser la carte Leaflet
        const mapElement = document.getElementById('map');
        if (mapElement && window.L && !mapElement._leaflet_id) {
            const boundsOptions = await getCityBoundsOptions();
            serviceMap = L.map('map', { minZoom: 3, ...boundsOptions }).setView([48.4, -4.5], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors'
            }).addTo(serviceMap);
            fixMapSizeOnLoad(serviceMap);
        }

        // Centrer la page sur la carte à l'arrivée sur l'étape
        mapElement.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Afficher la randonnée et le spot déjà choisis, pour garder le contexte du Jour 1
        const referencePositions = [];
        const hikeId = localStorage.getItem('selectedHiking');
        if (serviceMap && hikeId && hikeId !== 'no-hiking') {
            try {
                const hikesResponse = await fetch(`${window.API_BASE}/api/step2/hikes?city_id=${cityId}&distance_km=5`);
                if (hikesResponse.ok) {
                    const hikes = await hikesResponse.json();
                    const chosenHike = hikes.find(h => String(h.id) === String(hikeId));
                    if (chosenHike && chosenHike.start_latitude && chosenHike.start_longitude) {
                        const pos = [chosenHike.start_latitude, chosenHike.start_longitude];
                        L.marker(pos, { icon: buildHikeDivIcon(`J${currentDay}`), zIndexOffset: 1000 })
                            .addTo(serviceMap)
                            .bindPopup(`<b>🥾 ${chosenHike.name}</b><br>${chosenHike.distance_km} km - ${chosenHike.duration}h`);
                        referencePositions.push(pos);
                    }
                }
            } catch (err) {
                console.error('Erreur chargement randonnée choisie:', err);
            }
        }

        // Tracé GPX de la randonnée sélectionnée
        if (serviceMap && hikeId && hikeId !== 'no-hiking') {
            try {
                const traceRes = await fetch(`${window.API_BASE}/api/step2/hike/${hikeId}/trace`);
                if (traceRes.ok) {
                    const traceData = await traceRes.json();
                    if (traceData.points && traceData.points.length > 0) {
                        const latlngs = traceData.points.map(p => [p.lat, p.lon]);
                        L.polyline(latlngs, { color: '#339af0', weight: 3, opacity: 0.8 }).addTo(serviceMap);
                    }
                }
            } catch (err) {
                console.error('Erreur chargement tracé GPX:', err);
            }
        }

        const spotId = localStorage.getItem('selectedSpot');
        let chosenSpotCoords = null;
        if (spotId && spotId !== 'autre_hebergement') {
            try {
                const spotsResponse = await fetch(`${window.API_BASE}/api/step3/spots?city_id=${cityId}&hike_id=${hikeId || 0}`);
                if (spotsResponse.ok) {
                    const spots = await spotsResponse.json();
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
                }
            } catch (err) {
                console.error('Erreur chargement spot choisi:', err);
            }
        }

        // Gestion des onglets ("Tout" affiche toutes les catégories)
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
        const planId = localStorage.getItem('planId');
        loadPreviousDaysOnMap(serviceMap, currentDay, planId);

        // Restaurer les POI déjà sauvegardés pour ce jour (retour depuis results)
        if (planId) {
            try {
                const savedPlan = await fetch(`${window.API_BASE}/api/result/?plan_id=${planId}`);
                if (savedPlan.ok) {
                    const plan = await savedPlan.json();
                    const savedDay = (plan.days || []).find(d => d.day_number === currentDay);
                    if (savedDay && savedDay.pois) {
                        savedDay.pois.forEach(p => selectedPoiIds.add(p.id));
                    }
                }
            } catch (e) { /* pas bloquant */ }
        }

        // Charger les POI depuis l'API, au plus près du spot choisi si disponible
        try {
            let poiUrl = `${window.API_BASE}/api/step4/poi?city_id=${cityId}&distance_km=5`;
            if (chosenSpotCoords) {
                poiUrl += `&spot_lat=${chosenSpotCoords.lat}&spot_lon=${chosenSpotCoords.lon}`;
            }
            const response = await fetch(poiUrl);
            if (!response.ok) throw new Error('Erreur API step4/poi');
            const data = await response.json();

            renderCategory('eau',          data.eau          || []);
            renderCategory('vidange',      data.vidange      || []);
            renderCategory('gasoil',       data.gasoil       || []);
            renderCategory('supermarche',  data.supermarche  || []);
            renderCategory('commerce',     data.commerce     || []);
            renderCategory('restauration', data.restauration || []);
            renderCategory('toilettes',    data.toilettes    || []);
            renderCategory('hygiene',      data.hygiene      || []);
            renderCategory('culture',      data.culture      || []);
            renderCategory('urgence',      data.urgence      || []);

            // Total tous services confondus + phrase dynamique pour l'onglet actif par défaut ("Tout")
            categoryCounts.tout = Object.keys(CATEGORY_LABELS)
                .filter(c => c !== 'tout')
                .reduce((sum, c) => sum + (categoryCounts[c] || 0), 0);
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
                const allPoi = [
                    ...(data.eau          || []),
                    ...(data.vidange      || []),
                    ...(data.gasoil       || []),
                    ...(data.supermarche  || []),
                    ...(data.commerce     || []),
                    ...(data.restauration || []),
                    ...(data.toilettes    || []),
                    ...(data.hygiene      || []),
                    ...(data.culture      || []),
                    ...(data.urgence      || [])
                ];
                const poiPositions = allPoi
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

    function renderCategory(categoryId, poiList) {
        const grid = document.getElementById(categoryId);
        if (!grid) return;
        grid.innerHTML = '';
        categoryCounts[categoryId] = poiList.length;

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
                        <span class="hiking-stats"><span class="stat">${poi.service_type || 'Service'}</span></span>
                        <span class="status-badge ${poi.verifie ? 'verified' : 'pending'}">
                            ${poi.verifie ? '✅ Vérifié' : '⚠️ En attente'}
                        </span>
                    </div>
                    <div class="service-center">
                        <h4>${poi.name}</h4>
                        ${poi.address ? `<p class="service-address"><i class="fas fa-map-marker-alt"></i> ${poi.address}</p>` : ''}
                        ${typeof poi.distance_km === 'number' ? `<p class="service-distance"><i class="fas fa-route"></i> ${poi.distance_km < 1 ? Math.round(poi.distance_km * 1000) + ' m' : poi.distance_km + ' km'}</p>` : ''}
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
        updateStickyBar();

        saveToDB();
    }


    function saveToDB() {
        const planId = localStorage.getItem('planId');
        if (!planId) return;

        fetch(`${window.API_BASE}/api/step4/update_plan/${planId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ services: Array.from(selectedPoiIds), day_number: currentDay })
        }).catch(err => console.error('Erreur sauvegarde services:', err));
    }

    function showPoiOnMap(lat, lon, name) {
        if (serviceMap) {
            document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
            serviceMap.setView([lat, lon], 15);
            L.popup().setLatLng([lat, lon]).setContent(`<b>${name}</b>`).openOn(serviceMap);
        }
    }

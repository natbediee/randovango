// Étape 1 : choix de la ville de départ (carte interactive + recherche), affichage
// de la météo, puis création du plan de séjour. Les textes des cartes météo et de
// la fiche ville arrivent prêts à afficher depuis l'API (day_label, css, advice,
// stats_labels... préparés par display_utils.py).
//
// Squelette commun aux étapes : 1. Contexte du séjour → 2. Badge et titres →
// 3. Carte → 4. Chargement API → 5. Affichage → 6. Recherche (tient lieu de
// filtres) → 7. Sélection et création du plan.

document.addEventListener('DOMContentLoaded', async function() {
    // --- 1. Contexte du séjour ---
    // Mode "changement de ville mi-séjour" : l'utilisateur a déjà un plan en cours
    // (déclenché depuis /results, bouton "Changer de ville") et vient simplement
    // choisir la ville du jour suivant, sans redéfinir la durée du séjour.
    const changingCityForNextDay = localStorage.getItem('changingCityForNextDay') === '1';

    const select = document.getElementById('citySelect');
    if (!select) return;

    // La durée est fixée sur /duration ; si elle est absente (accès direct à
    // cette page), on renvoie l'utilisateur la choisir avant de continuer.
    const selectedDaysRaw = localStorage.getItem('selectedDays');
    if (!changingCityForNextDay && !selectedDaysRaw) {
        window.location.href = window.APP_URLS.duration;
        return;
    }
    const selectedDays = parseInt(selectedDaysRaw || '1');

    // --- 2. Badge "Jour X/N" ---
    // En mode "changer de ville", currentDay est encore le dernier jour complété
    // (pas encore incrémenté par continueWithNewCity()) : le jour en cours de
    // planification est donc +1.
    const currentDay = parseInt(localStorage.getItem('currentDay') || '1');
    const displayDay = changingCityForNextDay ? currentDay + 1 : currentDay;
    if (selectedDaysRaw) showDayBadge(displayDay, selectedDays);

    // --- 3. Carte des villes disponibles ---
    let allCities = [];
    const cityMarkers = {};

    // Marqueur violet d'une ville, ou vert avec une coche pour la ville choisie.
    function buildCityDivIcon(selected) {
        if (selected) {
            return L.divIcon({
                className: 'custom-map-marker',
                html: `<div style="background:#28a745;width:34px;height:34px;border-radius:50% 50% 50% 0;
                            transform:rotate(-45deg);box-shadow:0 2px 6px #0006;
                            display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                          <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:13px;"></i>
                       </div>`,
                iconSize: [34, 34],
                iconAnchor: [17, 34],
                popupAnchor: [0, -36]
            });
        }
        return L.divIcon({
            className: 'custom-map-marker',
            html: `<div style="background:#5C3D99;width:30px;height:30px;border-radius:50% 50% 50% 0;
                        transform:rotate(-45deg);box-shadow:0 2px 5px #0005;
                        display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                      <i class="fas fa-van-shuttle" style="color:#fff;transform:rotate(45deg);font-size:11px;"></i>
                   </div>`,
            iconSize: [30, 30],
            iconAnchor: [15, 30],
            popupAnchor: [0, -32]
        });
    }

    // Initialiser la carte tout de suite (tuiles visibles immédiatement), sans
    // attendre le chargement des villes : les marqueurs sont ajoutés dès que
    // l'API a répondu, mais la carte elle-même ne doit pas rester vide/blanche
    // pendant ce temps. Vue par défaut : la France entière.
    const cityMap = await createStepMap(46.5, 2.5, 6);
    let clusterGroup = null;
    if (cityMap) {
        clusterGroup = L.markerClusterGroup({
            maxClusterRadius: 40,
            disableClusteringAtZoom: 11,
            spiderfyOnMaxZoom: true
        });
        cityMap.addLayer(clusterGroup);
    }

    // Centrer la page sur la carte à l'arrivée sur l'étape
    document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });

    // --- 4. Chargement API ---
    // Charger les villes et remplir le <select> caché (une <option> par ville, avec
    // les attributs data-* que lisent la carte, la recherche et la fiche ville).
    try {
        const citiesData = await apiGet('/api/step1/cities');
        citiesData.forEach(city => {
            const opt = document.createElement('option');
            opt.value = city.id;
            opt.textContent = city.name;
            opt.dataset.lat = city.latitude;
            opt.dataset.lon = city.longitude;
            opt.dataset.name = city.name;
            opt.dataset.dept = city.department || '';
            opt.dataset.country = city.country || '';
            opt.dataset.hikes = city.stats.hikes;
            opt.dataset.spots = city.stats.spots;
            opt.dataset.poi = city.stats.poi;
            // Libellés prêts à afficher de la fiche ville ("12 randonnées", ...)
            opt.dataset.hikesLabel = city.stats_labels.hikes;
            opt.dataset.spotsLabel = city.stats_labels.spots;
            opt.dataset.poiLabel = city.stats_labels.poi;
            opt.dataset.meteo = JSON.stringify(city.meteo || []);
            select.appendChild(opt);
        });
    } catch (err) {
        console.error('Erreur lors du chargement des villes:', err);
    }

    // Extraire toutes les villes depuis le select caché
    allCities = Array.from(select.options).map(opt => ({
        id: opt.value,
        name: opt.getAttribute('data-name'),
        lat: parseFloat(opt.getAttribute('data-lat')),
        lon: parseFloat(opt.getAttribute('data-lon')),
        dept: opt.getAttribute('data-dept') || '',
        country: opt.getAttribute('data-country') || '',
        hikes: opt.getAttribute('data-hikes'),
        spots: opt.getAttribute('data-spots'),
        poi: opt.getAttribute('data-poi'),
        option: opt
    }));

    // --- 5. Affichage : marqueurs des villes, regroupés en grappes ---
    if (clusterGroup) {
        allCities.forEach(city => {
            if (isNaN(city.lat) || isNaN(city.lon)) return;
            const marker = L.marker([city.lat, city.lon], { icon: buildCityDivIcon(false) })
                .bindPopup(`<b>${city.name}</b><br><small>${city.dept}</small><br>
                            <small>${city.hikes} randonnées · ${city.spots} spots nuit</small>`)
                .on('click', () => selectCity(city.id));
            cityMarkers[city.id] = marker;
            clusterGroup.addLayer(marker);
        });

        // Centrer sur le cluster de villes (maxZoom évite de trop dézoomer si villes éparpillées)
        if (Object.keys(cityMarkers).length > 0) {
            cityMap.fitBounds(clusterGroup.getBounds(), { padding: [40, 40], maxZoom: 10 });
        }
    }

    // --- 7. Sélection d'une ville (depuis carte ou recherche) ---
    async function selectCity(cityId) {
        const city = allCities.find(c => c.id == cityId);
        if (!city) return;

        // Synchroniser le select caché (utilisé par le bouton Planifier et l'upload GPX)
        for (let i = 0; i < select.options.length; i++) {
            if (select.options[i].value == cityId) { select.selectedIndex = i; break; }
        }

        // Mettre à jour le champ de recherche
        const citySearch = document.getElementById('citySearch');
        if (citySearch) citySearch.value = city.name;

        // Mettre à jour les icônes des marqueurs
        Object.entries(cityMarkers).forEach(([id, marker]) => {
            marker.setIcon(buildCityDivIcon(id == cityId));
        });

        // Zoomer sur la ville et ouvrir le popup
        if (cityMap) {
            cityMap.setView([city.lat, city.lon], 12, { animate: true });
            if (cityMarkers[cityId]) cityMarkers[cityId].openPopup();
        }

        // Mémoriser la ville dans sessionStorage (survit au retour arrière, pas aux nouvelles sessions)
        sessionStorage.setItem('step1_cityId', cityId);

        // Révéler la fiche ville, la météo et le bouton au premier choix
        // (la durée est déjà fixée, choisie sur la page précédente).
        document.getElementById('selectedCity').style.display = '';
        document.getElementById('weatherSection').style.display = '';
        const planBtn = document.getElementById('planButton');
        if (planBtn) planBtn.style.display = '';

        // Remplir la fiche ville (libellés préparés côté Python)
        document.getElementById('cityName').textContent = city.name;
        document.getElementById('cityDept').textContent =
            city.dept + (city.country ? ' - ' + city.country : '');
        document.getElementById('cityHikes').textContent = city.option.dataset.hikesLabel;
        document.getElementById('citySpots').textContent = city.option.dataset.spotsLabel;
        document.getElementById('cityServices').textContent = city.option.dataset.poiLabel;
        document.getElementById('weatherTitle').textContent = '🌤️ Météo à ' + city.name + ' - Prochains jours';

        // Charger la météo si nécessaire (villes dont la météo en base est périmée :
        // /refresh-meteo la réactualise et renvoie la même forme enrichie que /cities)
        let meteoData = [];
        try { meteoData = JSON.parse(city.option.getAttribute('data-meteo')) || []; } catch(e) {}

        if (!meteoData || meteoData.length === 0) {
            const weatherGrid = document.getElementById('weatherGrid');
            weatherGrid.innerHTML = '<p style="grid-column:1/-1;text-align:center;"><i class="fas fa-spinner fa-spin"></i> Chargement météo...</p>';
            try {
                const data = await apiGet(`/api/step1/refresh-meteo/${cityId}`);
                city.option.setAttribute('data-meteo', JSON.stringify(data.meteo));
            } catch(err) {
                weatherGrid.innerHTML = '<p style="grid-column:1/-1;text-align:center;">⚠️ Météo indisponible</p>';
                return;
            }
        }
        updateWeatherDisplay(city.option);
    }

    // Compatibilité : upload GPX déclenche un change sur le select caché
    select.addEventListener('change', () => selectCity(select.value));

    // --- 6. Recherche textuelle ---
    const citySearch = document.getElementById('citySearch');
    const citySuggestions = document.getElementById('citySuggestions');
    const cityNotFound = document.getElementById('cityNotFound');

    citySearch.addEventListener('input', () => {
        const q = citySearch.value.trim().toLowerCase();
        cityNotFound.style.display = 'none';
        if (q.length < 2) { citySuggestions.style.display = 'none'; return; }

        const matches = allCities.filter(c =>
            c.name.toLowerCase().includes(q) || c.dept.toLowerCase().includes(q)
        ).slice(0, 8);

        if (matches.length === 0) {
            citySuggestions.style.display = 'none';
            cityNotFound.style.display = 'block';
            return;
        }

        citySuggestions.innerHTML = matches.map(c =>
            `<div class="city-suggestion-item" data-id="${c.id}" style="
                padding:0.65rem 1rem;cursor:pointer;border-bottom:1px solid #f5f5f5;
                display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:0.95rem;"><b>${c.name}</b> <small style="color:#999;">${c.dept}</small></span>
                <small style="color:#bbb;">${c.hikes} randos</small>
            </div>`
        ).join('');
        citySuggestions.style.display = 'block';
    });

    citySuggestions.addEventListener('click', e => {
        const item = e.target.closest('.city-suggestion-item');
        if (!item) return;
        citySuggestions.style.display = 'none';
        cityNotFound.style.display = 'none';
        selectCity(item.dataset.id);
    });

    // Hover sur les suggestions
    citySuggestions.addEventListener('mouseover', e => {
        const item = e.target.closest('.city-suggestion-item');
        if (item) item.style.background = '#f0f7ff';
    });
    citySuggestions.addEventListener('mouseout', e => {
        const item = e.target.closest('.city-suggestion-item');
        if (item) item.style.background = '';
    });

    document.addEventListener('click', e => {
        if (!e.target.closest('#citySearch') && !e.target.closest('#citySuggestions')) {
            citySuggestions.style.display = 'none';
        }
    });

    // Initialisation : restaurer la ville si retour arrière depuis step2 (sessionStorage)
    (async () => {
        await new Promise(r => setTimeout(r, 100));
        const savedCityId = sessionStorage.getItem('step1_cityId');
        if (savedCityId && allCities.find(c => c.id == savedCityId)) {
            await selectCity(savedCityId);
        }
    })();

    // --- 5. Affichage : grille des cartes météo de la ville sélectionnée ---
    // Tous les textes (entête du jour, températures, pluie, vent, conseil) et la
    // classe CSS de fond arrivent prêts à afficher de l'API : on ne fait qu'insérer.
    function updateWeatherDisplay(option) {
        let meteoData = [];
        try {
            meteoData = JSON.parse(option.getAttribute('data-meteo'));
        } catch (e) {
            console.error('Erreur parsing météo:', e.message);
        }

        const weatherGrid = document.getElementById('weatherGrid');
        weatherGrid.innerHTML = '';

        if (!meteoData || meteoData.length === 0) {
            weatherGrid.innerHTML = '<p>Aucune donnée météo disponible</p>';
            return;
        }

        meteoData.forEach(forecast => {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'weather-day ' + forecast.css;
            dayDiv.innerHTML = `
                <div class="day-name">${forecast.day_label}</div>
                <div class="weather-icon">
                    <img src="/static/images/wheather/${forecast.picto}.png" alt="${forecast.picto}"
                         style="width: 100%; max-width: 80px; height: auto;">
                </div>
                <div class="temperatures">
                    <span class="temp-max">${forecast.temp_max_label}</span>
                    <span class="temp-min">${forecast.temp_min_label}</span>
                </div>
                <div class="weather-details">
                    ${forecast.precipitation_label ?
                        `<div class="weather-info"><i class="fas fa-tint"></i> ${forecast.precipitation_label}</div>` : ''}
                    ${forecast.wind_label ?
                        `<div class="weather-info"><i class="fas fa-wind"></i> ${forecast.wind_label}</div>` : ''}
                </div>
                <div class="weather-advice">
                    <i class="fas ${forecast.advice.icon}"></i> ${forecast.advice.text}
                </div>
            `;
            weatherGrid.appendChild(dayDiv);
        });
    }

    // --- 7. Création du plan et navigation vers l'étape 2 ---

    const planButton = document.getElementById('planButton');

    function updatePlanButton() {
        if (!planButton) return;
        planButton.innerHTML = changingCityForNextDay
            ? `Continuer avec cette ville <i class="fas fa-arrow-right"></i>`
            : `Planifier ce séjour <i class="fas fa-arrow-right"></i>`;
    }
    updatePlanButton();

    // Si la page est restaurée depuis le cache navigateur (retour arrière après
    // avoir cliqué "Planifier"/"Continuer"), le bouton peut rester bloqué en
    // désactivé avec son spinner : on le réinitialise dans ce cas.
    window.addEventListener('pageshow', function (event) {
        if (event.persisted && planButton) {
            planButton.disabled = false;
            updatePlanButton();
        }
    });

    if (planButton) {
        planButton.addEventListener('click', function(e) {
            e.preventDefault();

            // Récupérer l'ID de la ville sélectionnée
            const selectedOption = select.options[select.selectedIndex];
            const cityId = selectedOption.value;

            if (changingCityForNextDay) {
                // Changement de ville mi-séjour : plan existant conservé, pas de nouvelle durée
                continueWithNewCity(cityId);
                return;
            }

            // Stocker la ville dans localStorage pour les étapes suivantes
            // (la durée est déjà en localStorage depuis /duration)
            localStorage.setItem('selectedCityId', cityId);

            // Lancer la création du plan via API
            createPlan(cityId, selectedDays);
        });
    }

    /**
     * Change la ville du jour suivant pour un plan déjà en cours (mi-séjour).
     * Met à jour trip_days.city_id via l'API, puis redirige vers l'étape 2.
     * @param {number} cityId - L'ID de la nouvelle ville sélectionnée
     */
    async function continueWithNewCity(cityId) {
        const planId = localStorage.getItem('planId');
        const currentDay = parseInt(localStorage.getItem('currentDay') || '1');
        const nextDay = currentDay + 1;
        try {
            planButton.disabled = true;
            planButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Changement de ville...';
            const resp = await fetch(`${window.API_BASE}/api/step1/update_day_city/${planId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ day_number: nextDay, city_id: parseInt(cityId) })
            });
            if (!resp.ok) throw new Error('Erreur mise à jour de la ville du jour');
            localStorage.setItem('selectedCityId', cityId);
            localStorage.setItem('currentDay', nextDay);
            localStorage.removeItem('selectedHiking');
            localStorage.removeItem('selectedSpot');
            localStorage.removeItem('changingCityForNextDay');
            window.location.href = window.APP_URLS.step2;
        } catch (e) {
            console.error('Erreur lors du changement de ville:', e);
            alert('Le changement de ville a échoué. Veuillez réessayer.');
            planButton.disabled = false;
            updatePlanButton();
        }
    }

    /**
     * Appelle l'API create_plan pour créer un nouveau plan de voyage, puis
     * redirige vers l'étape 2. Pour un invité sans jeton, c'est le serveur qui
     * génère le user_token (renvoyé dans la réponse) : on le mémorise ici.
     * @param {number} cityId - L'ID de la ville sélectionnée
     * @param {number} days - La durée du séjour en jours
     */
    async function createPlan(cityId, days) {
        try {
            // Désactiver le bouton et afficher un indicateur de chargement
            planButton.disabled = true;
            planButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Création du plan...';

            // Jeton invité éventuel des séjours précédents ; userId si connecté
            const userToken = localStorage.getItem('userToken');
            const userId = localStorage.getItem('userId') ? parseInt(localStorage.getItem('userId')) : null;

            const response = await fetch(`${window.API_BASE}/api/step1/create_plan`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    city_id: parseInt(cityId),
                    duration_days: days,
                    user_token: userToken,
                    user_id: userId,
                    start_date: localStorage.getItem('selectedStartDate') || new Date().toISOString().slice(0, 10)
                })
            });

            if (!response.ok) {
                const text = await response.text();
                console.error('create_plan response not ok', response.status, text);
                throw new Error('Erreur lors de la création du plan: ' + response.status);
            }

            const data = await response.json();

            // Validation : vérifier que l'API a retourné un plan_id
            if (!data || !data.plan_id) {
                console.error('Aucun plan_id retourné par create_plan:', data);
                alert('La création du plan a échoué : réponse inattendue du serveur.');
                planButton.disabled = false;
                updatePlanButton();
                return;
            }

            // Mémoriser le jeton invité généré par le serveur (réutilisé aux séjours suivants)
            if (data.user_token) localStorage.setItem('userToken', data.user_token);

            // Stocker le plan_id dans localStorage pour les étapes suivantes
            localStorage.setItem('planId', data.plan_id);
            localStorage.setItem('currentDay', 1);

            // Réinitialiser les sélections des étapes suivantes (nouveau plan = nouveau départ)
            localStorage.removeItem('selectedHiking');
            localStorage.removeItem('selectedSpot');
            localStorage.removeItem('selectedServices');

            // Rediriger vers l'étape 2 (sélection des randonnées)
            window.location.href = window.APP_URLS.step2;

        } catch (error) {
            // Gestion des erreurs : afficher un message d'alerte et réactiver le bouton
            console.error('Erreur:', error);
            alert('Erreur lors de la création du plan: ' + error.message);
            planButton.disabled = false;
            updatePlanButton();
        }
    }
});

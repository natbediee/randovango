// Icônes et helpers Leaflet partagés entre les étapes 1, 2, 3, 4 et le récapitulatif
// (mêmes marqueurs rando/spot/POI et même logique d'affichage des jours déjà planifiés).

// NE PAS réintroduire de patch agrandissant les tuiles de 1px (_initTile → 257px) :
// l'étirement 256→257 fait ré-échantillonner l'image par le navigateur, ce qui crée
// un bord semi-transparent sur chaque tuile et dessine un quadrillage blanc sur toute
// la carte (vérifié par comparaison avec/sans patch, en densité de pixels 1.0 et 1.25).

// Emprise géographique des villes disponibles, à passer en option `maxBounds` DÈS LA
// CRÉATION de la carte (et non via setMaxBounds() après coup, qui interrompt le
// chargement des tuiles en cours et laisse des carrés blancs). Mise en cache le temps
// de la page pour ne faire l'appel qu'une seule fois même si plusieurs cartes existent.
let _cityBoundsPromise = null;
function getCityBoundsOptions(padDegrees = 1.5) {
    if (!_cityBoundsPromise) {
        _cityBoundsPromise = fetch(`${window.API_BASE}/api/step1/cities/bounds`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null);
    }
    return _cityBoundsPromise.then(b => {
        if (!b || b.min_lat == null) return {};
        return {
            maxBounds: [
                [b.min_lat - padDegrees, b.min_lon - padDegrees],
                [b.max_lat + padDegrees, b.max_lon + padDegrees]
            ]
        };
    });
}

// Si le conteneur de la carte n'a pas encore sa taille finale au moment de l'init
// (image hero au-dessus pas encore chargée, flex/grid pas encore recalculé), Leaflet
// mémorise une taille obsolète et certaines tuiles restent blanches/décalées tant
// qu'aucun recalcul n'est déclenché. On force ce recalcul une fois toutes les
// ressources de la page chargées (images comprises), avec un filet de sécurité
// (setTimeout) si l'évènement 'load' est déjà passé ou si un dernier reflow survient.
function fixMapSizeOnLoad(map) {
    if (!map) return;
    const invalidate = () => map.invalidateSize();
    window.addEventListener('load', invalidate);
    setTimeout(invalidate, 300);
    setTimeout(invalidate, 1000);
}

// ---------------------------------------------------------------------------
// Helpers partagés entre les étapes (contexte du séjour, appels API, carte)
// ---------------------------------------------------------------------------

// Lit d'un coup toutes les informations du séjour en cours stockées dans le
// navigateur (localStorage). Chaque étape en déstructure ce dont elle a besoin :
//   const { planId, cityId, currentDay } = getTripContext();
function getTripContext() {
    return {
        planId: localStorage.getItem('planId'),
        cityId: localStorage.getItem('selectedCityId'),
        currentDay: parseInt(localStorage.getItem('currentDay') || '1'),
        selectedDays: parseInt(localStorage.getItem('selectedDays') || '1'),
        hikeId: localStorage.getItem('selectedHiking'),
        spotId: localStorage.getItem('selectedSpot'),
    };
}

// Badge "Jour X/N" en haut à gauche du stepper.
function showDayBadge(currentDay, selectedDays) {
    const dayBadge = document.getElementById('dayBadge');
    if (dayBadge) dayBadge.textContent = `Jour ${currentDay}/${selectedDays}`;
}

// Vérifie qu'une ville a été choisie à l'étape 1, sinon y renvoie l'utilisateur.
// Renvoie l'identifiant de la ville (ou null : l'appelant doit alors s'arrêter).
function requireCity() {
    const cityId = localStorage.getItem('selectedCityId');
    if (!cityId) {
        alert('Aucune ville sélectionnée. Retour à l\'étape 1.');
        window.location.href = window.APP_URLS.step1;
        return null;
    }
    return cityId;
}

// Appel GET vers l'API FastAPI ; renvoie le JSON de la réponse, ou lève une
// erreur si le serveur a répondu autre chose que 200 (à attraper par l'appelant).
async function apiGet(path) {
    const response = await fetch(`${window.API_BASE}${path}`);
    if (!response.ok) throw new Error(`Erreur API ${path} (HTTP ${response.status})`);
    return response.json();
}

// Appel PUT vers l'API FastAPI avec un corps JSON.
// keepalive : la requête se termine même si l'utilisateur quitte la page juste
// après (clic "Choisir" immédiatement suivi de "Étape suivante") ; sans cela le
// navigateur l'interrompt et la sauvegarde du choix peut être perdue.
function apiPut(path, body) {
    return fetch(`${window.API_BASE}${path}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        keepalive: true
    });
}

// Sauvegarde le choix du jour (rando, spot ou services) dans le plan en cours.
// `step` est le routeur concerné ("step2", "step3", "step4"), `payload` le corps
// envoyé (ex. { hike_id: 12, day_number: 1 }). La sauvegarde se fait en arrière-plan :
// on ne bloque pas l'interface, on trace juste un éventuel échec dans la console.
function saveDayChoice(step, payload, errorLabel) {
    const planId = localStorage.getItem('planId');
    if (!planId) return Promise.resolve();
    return apiPut(`/api/${step}/update_plan/${planId}`, payload)
        .catch(err => console.error(`Erreur sauvegarde ${errorLabel}:`, err));
}

// Crée la carte Leaflet d'une étape dans l'élément #map : emprise limitée aux
// villes disponibles, tuiles OpenStreetMap France, recalcul de taille au
// chargement. Renvoie la carte, ou null si l'élément est absent ou déjà initialisé.
async function createStepMap(centerLat, centerLon, zoom) {
    const mapElement = document.getElementById('map');
    if (!mapElement || !window.L || mapElement._leaflet_id) return null;
    const boundsOptions = await getCityBoundsOptions();
    const map = L.map('map', { minZoom: 3, ...boundsOptions }).setView([centerLat, centerLon], zoom);
    L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    fixMapSizeOnLoad(map);
    return map;
}

// Affiche sur la carte la randonnée choisie à l'étape 2 (marqueur "Jx" + tracé GPX),
// pour garder le contexte de la journée aux étapes 3 et 4. Renvoie la position
// [lat, lon] du départ de la randonnée (utile pour centrer la carte), ou null.
async function addChosenHikeToMap(map, cityId, hikeId, currentDay) {
    if (!map || !hikeId || hikeId === 'no-hiking') return null;
    let position = null;
    try {
        const hikes = await apiGet(`/api/step2/hikes?city_id=${cityId}&distance_km=5`);
        const chosenHike = hikes.find(h => String(h.id) === String(hikeId));
        if (chosenHike && chosenHike.start_latitude && chosenHike.start_longitude) {
            position = [chosenHike.start_latitude, chosenHike.start_longitude];
            L.marker(position, { icon: buildHikeDivIcon(`J${currentDay}`), zIndexOffset: 1000 })
                .addTo(map)
                .bindPopup(`<b>🥾 ${chosenHike.name}</b><br>${chosenHike.summary_label}`);
        }
    } catch (err) {
        console.error('Erreur chargement randonnée choisie:', err);
    }
    try {
        const traceData = await apiGet(`/api/step2/hike/${hikeId}/trace`);
        if (traceData.points && traceData.points.length > 0) {
            const latlngs = traceData.points.map(p => [p.lat, p.lon]);
            L.polyline(latlngs, { color: '#339af0', weight: 3, opacity: 0.8 }).addTo(map);
        }
    } catch (err) {
        console.error('Erreur chargement tracé GPX:', err);
    }
    return position;
}

// Phrase "X randonnées correspondent à vos critères" des filtres des étapes 2 et 3.
// Seul texte encore accordé en JavaScript : le nombre dépend du filtrage fait en
// direct dans le navigateur, le serveur ne peut donc pas préparer la phrase.
// `noun` est le nom au singulier ("randonnée", "spot"), `gender` 'f' ou 'm'.
function matchCountSubtitle(count, noun, gender) {
    if (count === 0) {
        return `${gender === 'f' ? 'Aucune' : 'Aucun'} ${noun} ne correspond à vos critères`;
    }
    const s = count > 1 ? 's' : '';
    return `${count} ${noun}${s} correspond${count > 1 ? 'ent' : ''} à vos critères`;
}

const POI_MARKER_STYLES = {
    eau:          { color: '#E91E63', icon: 'fa-tint' },
    vidange:      { color: '#EE3575', icon: 'fa-recycle' },
    gasoil:       { color: '#F24D89', icon: 'fa-gas-pump' },
    supermarche:  { color: '#F5659C', icon: 'fa-cart-arrow-down' },
    commerce:     { color: '#F77DB0', icon: 'fa-shopping-basket' },
    restauration: { color: '#F990C1', icon: 'fa-utensils' },
    toilettes:    { color: '#FAA5CE', icon: 'fa-toilet' },
    hygiene:      { color: '#FBBAD9', icon: 'fa-shower' },
    culture:      { color: '#FCCFE5', icon: 'fa-camera' },
    urgence:      { color: '#FDE3F0', icon: 'fa-first-aid' }
};

function buildHikeDivIcon(dayLabel) {
    const label = dayLabel
        ? `<span style="position:absolute;left:50%;transform:translateX(-50%);top:32px;
                        background:var(--blue);color:#fff;font-size:9px;font-weight:700;
                        padding:1px 5px;border-radius:3px;white-space:nowrap;box-shadow:0 1px 3px #0004;">
               ${dayLabel}
           </span>` : '';
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="position:relative;width:30px;">
                  <div style="background:var(--blue);width:30px;height:30px;border-radius:50% 50% 50% 0;
                              transform:rotate(-45deg);box-shadow:0 1px 4px #0006;display:flex;align-items:center;justify-content:center;">
                    <i class="fas fa-hiking" style="color:#fff;transform:rotate(45deg);font-size:14px;"></i>
                  </div>${label}
               </div>`,
        iconSize: [30, dayLabel ? 48 : 30],
        iconAnchor: [15, 30],
        popupAnchor: [0, -28]
    });
}

function buildSpotDivIcon(dayLabel) {
    // Couleur du spot alignée sur la page récapitulatif (results.js SPOT_STYLE = #26C6A6).
    const label = dayLabel
        ? `<span style="position:absolute;left:50%;transform:translateX(-50%);top:30px;
                        background:#26C6A6;color:#fff;font-size:9px;font-weight:700;
                        padding:1px 5px;border-radius:3px;white-space:nowrap;box-shadow:0 1px 3px #0004;">
               ${dayLabel}
           </span>` : '';
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="position:relative;width:28px;">
                  <div style="background:#26C6A6;width:28px;height:28px;border-radius:50% 50% 50% 0;
                              transform:rotate(-45deg);box-shadow:0 1px 4px #0006;display:flex;align-items:center;justify-content:center;">
                    <i class="fas fa-bed" style="color:#fff;transform:rotate(45deg);font-size:13px;"></i>
                  </div>${label}
               </div>`,
        iconSize: [28, dayLabel ? 46 : 28],
        iconAnchor: [14, 28],
        popupAnchor: [0, -26]
    });
}

// Icône de survol d'une randonnée : teal clair (accent de la palette), icône encre
// pour le contraste. Se distingue du teal foncé par défaut et du sélectionné.
function buildHikeHoveredDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#7FC4CC;width:36px;height:36px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 8px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-hiking" style="color:#22424B;transform:rotate(45deg);font-size:16px;"></i>
               </div>`,
        iconSize: [36, 36],
        iconAnchor: [18, 36],
        popupAnchor: [0, -34]
    });
}

// Marqueur de la randonnée sélectionnée : teal, PLUS GRAND que les autres, avec un ✓.
function buildHikeSelectedDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#2E7D86;width:42px;height:42px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 3px 10px #0009;display:flex;align-items:center;justify-content:center;border:3px solid #fff;">
                  <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:18px;"></i>
               </div>`,
        iconSize: [42, 42],
        iconAnchor: [21, 42],
        popupAnchor: [0, -40]
    });
}

// Icône de survol d'un spot : teal clair (accent), icône encre pour le contraste.
function buildSpotHoveredDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#7FC4CC;width:34px;height:34px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 8px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-bed" style="color:#22424B;transform:rotate(45deg);font-size:15px;"></i>
               </div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

// Marqueur du spot sélectionné : couleur du spot (#26C6A6, comme le récapitulatif),
// plus grand, avec un ✓.
function buildSpotSelectedDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#26C6A6;width:40px;height:40px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 3px 10px #0009;display:flex;align-items:center;justify-content:center;border:3px solid #fff;">
                  <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:16px;"></i>
               </div>`,
        iconSize: [40, 40],
        iconAnchor: [20, 40],
        popupAnchor: [0, -38]
    });
}

function buildPoiDivIcon(category) {
    const style = POI_MARKER_STYLES[category] || POI_MARKER_STYLES.commerce;
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:${style.color};width:28px;height:28px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 1px 4px #0006;display:flex;align-items:center;justify-content:center;">
                  <i class="fas ${style.icon}" style="color:#fff;transform:rotate(45deg);font-size:13px;"></i>
               </div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 28],
        popupAnchor: [0, -26]
    });
}

// POI sélectionné : fond teal + contour blanc + un peu plus grand (même code visuel de
// sélection que la rando et le spot, pas de vert). On GARDE l'icône de la catégorie
// (eau, gasoil…) au lieu d'une coche, pour que l'utilisateur voie toujours le type de
// service et ne soit pas perdu.
function buildPoiSelectedDivIcon(category) {
    const style = POI_MARKER_STYLES[category] || POI_MARKER_STYLES.commerce;
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#2E7D86;width:34px;height:34px;border-radius:50% 50% 50% 0;
                   transform:rotate(-45deg);box-shadow:0 2px 6px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                 <i class="fas ${style.icon}" style="color:#fff;transform:rotate(45deg);font-size:14px;"></i>
               </div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

// Affiche sur la carte les jours déjà planifiés (badges Jx) et renvoie les randos/spots
// déjà utilisés, pour que les étapes 2 et 3 puissent afficher un badge "Planifié Jx"
// sur les cartes correspondantes.
async function loadPreviousDaysOnMap(map, currentDay, planId) {
    const plannedHikeIds = new Map();
    const plannedSpotIds = new Map();
    if (!map || currentDay <= 1 || !planId) return { plannedHikeIds, plannedSpotIds };
    try {
        const res = await fetch(`${window.API_BASE}/api/result/?plan_id=${planId}`);
        if (!res.ok) return { plannedHikeIds, plannedSpotIds };
        const plan = await res.json();
        (plan.days || []).forEach(day => {
            if (day.day_number >= currentDay) return;
            const jLabel = `J${day.day_number}`;
            if (day.hike_latitude && day.hike_longitude) {
                L.marker([day.hike_latitude, day.hike_longitude], { icon: buildHikeDivIcon(jLabel), zIndexOffset: 1000 })
                    .addTo(map)
                    .bindPopup(`<b>🥾 ${day.hike_name || 'Randonnée'}</b><br>${jLabel} — déjà planifié`);
            }
            if (day.spot_latitude && day.spot_longitude) {
                L.marker([day.spot_latitude, day.spot_longitude], { icon: buildSpotDivIcon(jLabel), zIndexOffset: 500 })
                    .addTo(map)
                    .bindPopup(`<b>🛏️ ${day.spot_name || 'Spot'}</b><br>${jLabel} — déjà planifié`);
            }
            if (day.hike_id) plannedHikeIds.set(day.hike_id, day.day_number);
            if (day.spot_id) plannedSpotIds.set(day.spot_id, day.day_number);
        });
        return { plannedHikeIds, plannedSpotIds };
    } catch {
        return { plannedHikeIds, plannedSpotIds };
    }
}

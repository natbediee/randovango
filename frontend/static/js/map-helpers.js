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

// Icône orange affichée au survol d'une carte de randonnée dans la liste
function buildHikeHoveredDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#ff9800;width:36px;height:36px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 8px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-hiking" style="color:#fff;transform:rotate(45deg);font-size:16px;"></i>
               </div>`,
        iconSize: [36, 36],
        iconAnchor: [18, 36],
        popupAnchor: [0, -34]
    });
}

// Icône verte affichée sur le marqueur de la randonnée sélectionnée
function buildHikeSelectedDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:var(--green);width:34px;height:34px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 6px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:14px;"></i>
               </div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

// Icône orange affichée au survol d'un spot (carte liste ↔ marqueur)
function buildSpotHoveredDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:#ff9800;width:34px;height:34px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 8px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-bed" style="color:#fff;transform:rotate(45deg);font-size:15px;"></i>
               </div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

// Icône verte affichée sur le marqueur du spot sélectionné
function buildSpotSelectedDivIcon() {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:var(--green);width:32px;height:32px;border-radius:50% 50% 50% 0;
                    transform:rotate(-45deg);box-shadow:0 2px 6px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                  <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:13px;"></i>
               </div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 32],
        popupAnchor: [0, -30]
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

function buildPoiSelectedDivIcon(category) {
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="background:var(--green);width:34px;height:34px;border-radius:50% 50% 50% 0;
                   transform:rotate(-45deg);box-shadow:0 2px 6px #0008;display:flex;align-items:center;justify-content:center;border:2px solid #fff;">
                 <i class="fas fa-check" style="color:#fff;transform:rotate(45deg);font-size:14px;"></i>
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

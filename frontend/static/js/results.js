// Icônes alignées sur celles des étapes 2/3 (rando, spot) et 4 (poi par catégorie).
// POI_MARKER_STYLES vient de map-helpers.js (partagé avec l'étape 4).
const HIKE_STYLE = { color: 'var(--blue)', icon: 'fa-hiking' };
const SPOT_STYLE  = { color: '#26C6A6',    icon: 'fa-bed' };

function buildDivIcon(type, category, dayNumber) {
    const style = type === 'hike' ? HIKE_STYLE
        : type === 'spot' ? SPOT_STYLE
        : (POI_MARKER_STYLES[category] || POI_MARKER_STYLES.commerce);
    const size = type === 'hike' ? 30 : 28;
    const showLabel = !!dayNumber;
    const labelHtml = showLabel
        ? `<span style="position:absolute;left:50%;transform:translateX(-50%);top:${size + 2}px;
                        background:${style.color};color:#fff;font-size:9px;font-weight:700;
                        padding:1px 5px;border-radius:3px;white-space:nowrap;box-shadow:0 1px 3px #0004;">
               J${dayNumber}
           </span>`
        : '';
    return L.divIcon({
        className: 'custom-map-marker',
        html: `<div style="position:relative;width:${size}px;">
                  <div style="background:${style.color};width:${size}px;height:${size}px;border-radius:50% 50% 50% 0;
                              transform:rotate(-45deg);box-shadow:0 1px 4px #0006;display:flex;align-items:center;justify-content:center;">
                    <i class="fas ${style.icon}" style="color:#fff;transform:rotate(45deg);font-size:13px;"></i>
                  </div>
                  ${labelHtml}
               </div>`,
        iconSize: [size, showLabel ? size + 18 : size],
        iconAnchor: [size / 2, size],
        popupAnchor: [0, -size + 2]
    });
}

document.addEventListener('DOMContentLoaded', async function () {
    const planId = localStorage.getItem('planId');
    const tableBody = document.getElementById('days-table-body');

    if (!planId) {
        tableBody.innerHTML = '<tr><td colspan="5">Aucun plan trouvé. Retour à l\'étape 1.</td></tr>';
        window.location.href = window.APP_URLS.step1;
        return;
    }

    // Initialiser la carte Leaflet
    const mapElement = document.getElementById('map');
    let resultMap = null;
    if (mapElement && window.L && !mapElement._leaflet_id) {
        const boundsOptions = await getCityBoundsOptions();
        resultMap = L.map('map', { minZoom: 3, ...boundsOptions }).setView([48.4, -4.5], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(resultMap);
        fixMapSizeOnLoad(resultMap);
    }

    try {
        const response = await fetch(`${window.API_BASE}/api/result/?plan_id=${planId}`);
        if (!response.ok) throw new Error('Erreur API result');
        const plan = await response.json();

        if (!plan || !plan.days) {
            tableBody.innerHTML = '<tr><td colspan="5">Aucune donnée pour ce plan.</td></tr>';
            return;
        }

        tableBody.innerHTML = '';
        const markerPositions = [];

        // create_plan pré-crée tous les jours du séjour (vides) dès le départ : on
        // n'affiche que les jours réellement complétés jusqu'ici, pas ceux à venir.
        const currentDay = parseInt(localStorage.getItem('currentDay') || '1');
        const completedDays = plan.days.filter(d => d.day_number <= currentDay);

        completedDays.forEach(day => {
            const activity = day.hike_id
                ? `${day.hike_name} (${day.distance_km ?? '?'} km, ${day.difficulte || ''})`
                : 'Pas de randonnée - Détente';
            const accommodation = day.spot_id
                ? `${day.spot_name}${day.spot_address ? `<br><small>📍 ${day.spot_address}</small>` : ''}`
                : 'Aucun spot sélectionné';
            const services = (day.pois && day.pois.length > 0)
                ? day.pois.map(p => `${p.name}${p.address ? ` <small>📍 ${p.address}</small>` : ''}`).join('<br>')
                : 'Aucun service';

            const row = document.createElement('tr');
            row.innerHTML = `
                <td><strong>Jour ${day.day_number}</strong></td>
                <td>${day.city_name || '?'}</td>
                <td>${activity}</td>
                <td>${accommodation}</td>
                <td>${services}</td>
            `;
            tableBody.appendChild(row);

            // Marqueur randonnée
            if (resultMap && day.hike_latitude && day.hike_longitude) {
                L.marker([day.hike_latitude, day.hike_longitude], { icon: buildDivIcon('hike', null, day.day_number), zIndexOffset: 1000 })
                    .addTo(resultMap)
                    .bindPopup(`<b>🥾 ${day.hike_name}</b><br>Jour ${day.day_number}`);
                markerPositions.push([day.hike_latitude, day.hike_longitude]);
            }

            // Marqueur spot (hébergement)
            if (resultMap && day.spot_latitude && day.spot_longitude) {
                L.marker([day.spot_latitude, day.spot_longitude], { icon: buildDivIcon('spot', null, day.day_number) })
                    .addTo(resultMap)
                    .bindPopup(`<b>🏕️ ${day.spot_name}</b><br>Jour ${day.day_number}${day.spot_address ? `<br><small>📍 ${day.spot_address}</small>` : ''}`);
                markerPositions.push([day.spot_latitude, day.spot_longitude]);
            }

            // Marqueurs POI/services
            (day.pois || []).forEach(poi => {
                if (resultMap && poi.latitude && poi.longitude) {
                    L.marker([poi.latitude, poi.longitude], { icon: buildDivIcon('poi', poi.category, day.day_number) })
                        .addTo(resultMap)
                        .bindPopup(`<b>🛠️ ${poi.name}</b><br>${poi.service_type || ''}${poi.address ? `<br><small>📍 ${poi.address}</small>` : ''}`);
                    markerPositions.push([poi.latitude, poi.longitude]);
                }
            });
        });

        if (resultMap && markerPositions.length > 0) {
            if (markerPositions.length === 1) {
                resultMap.setView(markerPositions[0], 13);
            } else {
                resultMap.fitBounds(markerPositions, { padding: [40, 40] });
            }
        }

        // Le jour qui vient d'être complété est le dernier jour affiché dans le récap
        // (currentDay n'est incrémenté qu'au moment où l'utilisateur choisit de continuer,
        // voir stayInSameCity()/changeCityForNextDay() ci-dessous).
        const selectedDays = parseInt(localStorage.getItem('selectedDays') || '1');
        const lastDay = completedDays.find(d => d.day_number === currentDay) || completedDays[completedDays.length - 1];

        // Badge "Jour X/N" en haut à gauche du stepper (dynamique, depuis localStorage)
        const dayBadge = document.getElementById('dayBadge');
        if (dayBadge) dayBadge.textContent = `Jour ${currentDay}/${selectedDays}`;

        if (currentDay < selectedDays) {
            document.getElementById('nextDayTitle').textContent = `Planifier jour ${currentDay + 1}`;
            document.getElementById('stayButtonLabel').textContent =
                `Rester à ${lastDay && lastDay.city_name ? lastDay.city_name : 'cette ville'}`;
            document.getElementById('nextDaySection').style.display = '';
        } else {
            document.getElementById('downloadPdfBtn').href = `${window.API_BASE}/api/result/pdf?plan_id=${planId}`;
            document.getElementById('tripEndSection').style.display = '';
        }

        // Centrer la page sur la carte une fois le tableau rempli (sinon la mise en
        // page grandit après le scroll et la carte ne se retrouve plus centrée)
        mapElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (err) {
        console.error('Erreur chargement plan:', err);
        tableBody.innerHTML = '<tr><td colspan="5">Erreur lors du chargement du plan.</td></tr>';
    }
});

// Continue le séjour dans la même ville : le jour suivant hérite explicitement de la
// ville du jour qui vient d'être complété (au cas où celle-ci aurait changé en cours de route).
async function stayInSameCity() {
    const planId = localStorage.getItem('planId');
    const currentDay = parseInt(localStorage.getItem('currentDay') || '1');
    const cityId = localStorage.getItem('selectedCityId');
    const nextDay = currentDay + 1;
    try {
        await fetch(`${window.API_BASE}/api/step1/update_day_city/${planId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ day_number: nextDay, city_id: parseInt(cityId) })
        });
    } catch (err) {
        console.error('Erreur lors de la propagation de la ville:', err);
    }
    localStorage.setItem('currentDay', nextDay);
    localStorage.removeItem('selectedHiking');
    localStorage.removeItem('selectedSpot');
    window.location.href = window.APP_URLS.step2;
}

// Change de ville pour le jour suivant : redirige vers l'étape 1 en mode "changement
// de ville mi-séjour" (durée déjà fixée, plan existant conservé).
function changeCityForNextDay() {
    localStorage.setItem('changingCityForNextDay', '1');
    window.location.href = window.APP_URLS.step1;
}

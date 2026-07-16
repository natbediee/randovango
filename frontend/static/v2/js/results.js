// Page récapitulatif : tableau des journées complétées + carte de tous les choix
// (randonnées, spots nuit, services), puis navigation vers le jour suivant ou la
// fin du séjour. Les textes du tableau arrivent prêts à afficher depuis l'API
// (champ day.display, préparé par backend/utils/display_utils.py).

// ---------------------------------------------------------------------------
// Icônes de la carte : mêmes pastilles que les étapes 2/3 (rando, spot) et 4
// (services par catégorie), avec une étiquette "Jx" sous la pastille.
// POI_MARKER_STYLES vient de map-helpers.js (partagé avec l'étape 4).
// ---------------------------------------------------------------------------
const HIKE_STYLE = { color: 'var(--blue)', icon: 'fa-hiking' };
// Spot en encre (#22424B), distinct du teal de la rando (cf. SPOT_COLOR dans map-helpers.js).
const SPOT_STYLE  = { color: '#22424B',    icon: 'fa-bed' };

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

// Date d'une journée du séjour = date de départ du plan + (numéro du jour - 1).
// Rendu court en français, ex. « Lun. 14 juil. ». Renvoie null si la date de départ
// est absente/invalide (on retombe alors sur « Jour N »).
function formatDayDate(startDateStr, dayNumber) {
    if (!startDateStr) return null;
    const d = new Date(startDateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return null;
    d.setDate(d.getDate() + (dayNumber - 1));
    const label = d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' });
    return label.charAt(0).toUpperCase() + label.slice(1);
}

document.addEventListener('DOMContentLoaded', async function () {
    // --- 1. Contexte du séjour ---
    const { planId, currentDay, selectedDays } = getTripContext();
    const tableBody = document.getElementById('days-table-body');
    if (!planId) {
        tableBody.innerHTML = '<tr><td colspan="5">Aucun plan trouvé. Retour à l\'étape 1.</td></tr>';
        window.location.href = window.APP_URLS.step1;
        return;
    }

    // --- 2. Badge "Jour X/N" ---
    showDayBadge(currentDay, selectedDays);

    // --- 3. Carte ---
    const resultMap = await createStepMap(48.4, -4.5, 11);

    try {
        // --- 4. Chargement API ---
        // create_plan pré-crée tous les jours du séjour (vides) dès le départ :
        // up_to_day fait filtrer côté serveur les jours réellement complétés
        // jusqu'ici (currentDay n'est incrémenté qu'en continuant le séjour).
        const plan = await apiGet(`/api/result/?plan_id=${planId}&up_to_day=${currentDay}`);
        if (!plan || !plan.days) {
            tableBody.innerHTML = '<tr><td colspan="5">Aucune donnée pour ce plan.</td></tr>';
            return;
        }

        // --- 5. Affichage : une ligne de tableau et des marqueurs par journée ---
        tableBody.innerHTML = '';
        const markerPositions = [];

        plan.days.forEach(day => {
            const row = document.createElement('tr');
            // Date de la journée (repli sur « Jour N » si la date de départ manque)
            const dateLabel = formatDayDate(plan.start_date, day.day_number) || day.display.day_title;
            // data-label : en mobile le tableau est déplié en blocs (un par jour) et ces
            // libellés sont réaffichés devant chaque cellule, l'en-tête étant masqué.
            row.innerHTML = `
                <td data-label="Date"><strong>${dateLabel}</strong></td>
                <td data-label="Ville">${day.city_name || '?'}</td>
                <td data-label="Rando">${day.display.activity_html}</td>
                <td data-label="Spot">${day.display.accommodation_html}</td>
                <td data-label="Services">${day.display.services_html}</td>
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

        // --- 7. Navigation : jour suivant ou fin du séjour ---
        // Le jour qui vient d'être complété est le dernier jour affiché dans le récap.
        const lastDay = plan.days.find(d => d.day_number === currentDay) || plan.days[plan.days.length - 1];

        if (currentDay < selectedDays) {
            document.getElementById('nextDayTitle').textContent = `Planifier jour ${currentDay + 1}`;
            document.getElementById('stayButtonLabel').textContent =
                `Rester à ${lastDay && lastDay.city_name ? lastDay.city_name : 'cette ville'}`;
            document.getElementById('nextDaySection').style.display = '';
        } else {
            document.getElementById('downloadPdfBtn').href = `${window.API_BASE}/api/result/pdf?plan_id=${planId}`;
            document.getElementById('tripEndSection').style.display = '';
        }
        // Pas de scroll automatique ici : cet écran est une relecture avant PDF, on doit
        // arriver en haut sur le récapitulatif. La carte reste accessible plus bas.
    } catch (err) {
        console.error('Erreur chargement plan:', err);
        tableBody.innerHTML = '<tr><td colspan="5">Erreur lors du chargement du plan.</td></tr>';
    }
});

// --- 8. Fonctions appelées par les boutons de la page (attributs onclick) ---

// Continue le séjour dans la même ville : le jour suivant hérite explicitement de la
// ville du jour qui vient d'être complété (au cas où celle-ci aurait changé en cours de route).
async function stayInSameCity() {
    const { planId, cityId, currentDay } = getTripContext();
    const nextDay = currentDay + 1;
    try {
        await apiPut(`/api/step1/update_day_city/${planId}`, {
            day_number: nextDay,
            city_id: parseInt(cityId)
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

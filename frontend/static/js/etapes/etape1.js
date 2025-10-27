// =============================
// JS ÉTAPE 1 - CHOIX DE LA VILLE
// =============================

console.log('📦 Fichier etape1.js en cours de chargement...');

document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Étape 1 JS chargé');
    const select = document.getElementById('citySelect');
    if (!select) {
        console.error('❌ Element citySelect non trouvé');
        return;
    }
    console.log('✅ Element citySelect trouvé');
    
    // Initialisation de la carte Leaflet sur la première ville
    if (window.L && document.getElementById('map')) {
        const opt = select.options[select.selectedIndex];
        const lat = parseFloat(opt.getAttribute('data-lat'));
        const lon = parseFloat(opt.getAttribute('data-lon'));
        window.map = L.map('map').setView([lat, lon], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(window.map);
        // Ajoute le marker initial
        window.cityMarker = L.marker([lat, lon]).addTo(window.map);
    }
    
    // Gestion du changement de ville
    select.addEventListener('change', function() {
        console.log('🔄 Changement de ville détecté');
        const opt = select.options[select.selectedIndex];
        const cityName = opt.getAttribute('data-name');
        console.log('📍 Nouvelle ville:', cityName);
        
        // Mise à jour des informations de la ville
        document.getElementById('cityName').textContent = cityName;
        let dept = opt.getAttribute('data-dept') || '';
        let country = opt.getAttribute('data-country') || '';
        document.getElementById('cityDept').textContent = dept + (country ? ' - ' + country : '');
        document.getElementById('cityRando').textContent = opt.getAttribute('data-rando') + ' randonnées';
        document.getElementById('citySpots').textContent = opt.getAttribute('data-spots') + ' spots nuit';
        document.getElementById('cityServices').textContent = opt.getAttribute('data-poi') + " points d'intérêt";
        
        // Mise à jour du titre météo
        document.getElementById('weatherTitle').textContent = '🌤️ Météo à ' + cityName + ' - Prochains jours';
        
        // Mise à jour des prévisions météo
        updateWeatherDisplay(opt);
        
        // Centrer la carte sur la nouvelle ville et déplacer le marker
        updateMap(opt);
    });
});

/**
 * Met à jour l'affichage de la météo pour la ville sélectionnée
 */
function updateWeatherDisplay(option) {
    console.log('☁️ Mise à jour de la météo');
    const meteoData = JSON.parse(option.getAttribute('data-meteo'));
    console.log('📊 Données météo:', meteoData);
    const weatherGrid = document.getElementById('weatherGrid');
    weatherGrid.innerHTML = '';
    
    if (!meteoData || meteoData.length === 0) {
        console.warn('⚠️ Aucune donnée météo disponible');
        weatherGrid.innerHTML = '<p>Aucune donnée météo disponible</p>';
        return;
    }
    
    console.log(`✅ ${meteoData.length} jours de météo à afficher`);
    
    const daysOfWeek = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
    const months = ['janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc'];
    
    meteoData.forEach((forecast, index) => {
        const date = new Date(forecast.date);
        const dayOfWeek = daysOfWeek[date.getDay()];
        const dayNum = date.getDate();
        const month = months[date.getMonth()];
        const dayName = index === 0 ? "Aujourd'hui" : `${dayOfWeek} ${dayNum} ${month}`;
        
        // Application des classes CSS selon le weather_code
        let weatherClass = '';
        if (forecast.weather_code < 45) {
            weatherClass = 'good-weather';
        } else if (forecast.weather_code <= 65) {
            weatherClass = 'acceptable-weather';
        } else {
            weatherClass = 'bad-weather';
        }
        
        const dayDiv = document.createElement('div');
        dayDiv.className = 'weather-day ' + weatherClass;
        
        // Message de conseil selon le picto
        const advice = getWeatherAdvice(forecast.picto);
        
        dayDiv.innerHTML = `
            <div class="day-name">${dayName}</div>
            <div class="weather-icon">
                <img src="/static/images/wheather/${forecast.picto}.png" alt="${forecast.picto}" style="width: 100%; max-width: 80px; height: auto;">
            </div>
            <div class="temperatures">
                <span class="temp-max">${Math.round(forecast.temp_max)}°</span>
                <span class="temp-min">${Math.round(forecast.temp_min)}°</span>
            </div>
            <div class="weather-details">
                ${forecast.precipitation_sum > 0 ? `<div class="weather-info"><i class="fas fa-tint"></i> ${forecast.precipitation_sum.toFixed(1)} mm</div>` : ''}
                ${forecast.wind_speed_max > 0 ? `<div class="weather-info"><i class="fas fa-wind"></i> ${Math.round(forecast.wind_speed_max)} km/h</div>` : ''}
            </div>
            <div class="weather-advice">
                ${advice.icon} ${advice.message}
            </div>
        `;
        weatherGrid.appendChild(dayDiv);
    });
}

/**
 * Retourne le message de conseil selon le type de météo
 */
function getWeatherAdvice(picto) {
    const adviceMap = {
        'sun': {
            icon: '<i class="fas fa-check-circle"></i>',
            message: 'Parfait pour randonner'
        },
        'storm': {
            icon: '<i class="fas fa-exclamation-triangle"></i>',
            message: 'Éviter les randos'
        },
        'rain': {
            icon: '<i class="fas fa-info-circle"></i>',
            message: 'Équipements conseillés'
        },
        'snow': {
            icon: '<i class="fas fa-info-circle"></i>',
            message: 'Équipements conseillés'
        },
        'fog': {
            icon: '<i class="fas fa-eye-slash"></i>',
            message: 'Avec prudence'
        },
        'cloud': {
            icon: '<i class="fas fa-cloud"></i>',
            message: 'Conditions correctes'
        },
        'indisponible': {
            icon: '<i class="fas fa-question-circle"></i>',
            message: 'Météo indisponible'
        }
    };
    
    return adviceMap[picto] || adviceMap['indisponible'];
}

/**
 * Met à jour la carte avec la nouvelle position
 */
function updateMap(option) {
    if (!window.map || !window.L) return;
    
    const lat = parseFloat(option.getAttribute('data-lat'));
    const lon = parseFloat(option.getAttribute('data-lon'));
    
    if (isNaN(lat) || isNaN(lon)) return;
    
    window.map.setView([lat, lon], 12);
    
    // Supprime l'ancien marker s'il existe
    if (window.cityMarker) {
        window.map.removeLayer(window.cityMarker);
    }
    
    // Ajoute le nouveau marker
    window.cityMarker = L.marker([lat, lon]).addTo(window.map);
}

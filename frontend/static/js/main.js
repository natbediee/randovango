// Fonctions mutualisées pour la gestion des services (étape 4)
document.addEventListener('DOMContentLoaded', function() {
    // Gestion des onglets de catégories
    document.querySelectorAll('.category-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            const category = this.dataset.category;
            document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            document.querySelectorAll('.services-grid').forEach(grid => {
                grid.style.display = grid.id === category ? 'block' : 'none';
            });
        });
    });

    // Sélection d'un service
    window.selectService = function(serviceId) {
        const noServiceOption = document.querySelector('.no-service-option');
        if (noServiceOption) noServiceOption.classList.remove('selected');
        const selectedServices = document.getElementById('selectedServices');
        const selectedList = document.getElementById('selectedList');
        const nextBtn = document.getElementById('nextStepBtn');
        // Créer l'élément service sélectionné
        const serviceElement = document.createElement('div');
        serviceElement.className = 'selected-service-item';
        serviceElement.innerHTML = `
            <span class="service-name">✅ ${serviceId}</span>
            <button class="btn btn-outline btn-sm" onclick="removeService('${serviceId}')">Retirer</button>
        `;
        if (selectedList) selectedList.appendChild(serviceElement);
        if (selectedServices) selectedServices.style.display = 'block';
        if (nextBtn) nextBtn.style.display = 'block';
    };

    // Retirer un service sélectionné
    window.removeService = function(serviceId) {
        const selectedList = document.getElementById('selectedList');
        if (selectedList) {
            const items = selectedList.querySelectorAll('.selected-service-item');
            items.forEach(item => {
                if (item.textContent.includes(serviceId)) {
                    item.remove();
                }
            });
        }
    };

    // Sélection "aucun service"
    window.selectNoService = function() {
        const noServiceOption = document.querySelector('.no-service-option');
        if (noServiceOption) noServiceOption.classList.add('selected');
        const selectedList = document.getElementById('selectedList');
        const selectedServices = document.getElementById('selectedServices');
        if (selectedList) selectedList.innerHTML = '';
        if (selectedServices) selectedServices.style.display = 'none';
        localStorage.setItem('selectedServices', 'aucun_service');
        const nextBtn = document.getElementById('nextStepBtn');
        if (nextBtn) nextBtn.style.display = 'block';
    };

    // Affichage des détails d'un service
    window.showServiceDetails = function(serviceId) {
        alert('Détails du service: ' + serviceId + ' (Modal à implémenter)');
    };
});
// Fonctions mutualisées pour la sélection de spots (hébergement)
document.addEventListener('DOMContentLoaded', function() {
    // Gestion des filtres pour spots (hébergement)
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const group = this.parentElement;
            group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            // Afficher la section des spots si un filtre spécifique est sélectionné
            const filterValue = this.getAttribute('data-filter');
            if (filterValue && filterValue !== 'all' && document.getElementById('spotsSection')) {
                document.getElementById('spotsSection').style.display = 'block';
            }
        });
    });

    // Auto-afficher les spots si la section existe
    if (document.getElementById('spotsSection')) {
        document.getElementById('spotsSection').style.display = 'block';
    }

    // Sélection d'un spot (hébergement)
    window.selectSpot = function(spotId) {
        document.querySelectorAll('.spot-card').forEach(card => card.classList.remove('selected'));
        const spotCard = document.querySelector(`[onclick="selectSpot(${spotId})"]`);
        if (spotCard) spotCard.closest('.spot-card').classList.add('selected');
        const noSpotOption = document.querySelector('.no-spot-option');
        if (noSpotOption) noSpotOption.classList.remove('selected');
        localStorage.setItem('selectedSpot', spotId);
        const nightWeather = document.getElementById('nightWeather');
        if (nightWeather) nightWeather.style.display = 'block';
        const nextBtn = document.getElementById('nextStepBtn');
        if (nextBtn) nextBtn.style.display = 'block';
    };

    // Sélection "autre hébergement"
    window.selectNoSpot = function() {
        document.querySelectorAll('.spot-card').forEach(card => card.classList.remove('selected'));
        const noSpotOption = document.querySelector('.no-spot-option');
        if (noSpotOption) noSpotOption.classList.add('selected');
        localStorage.setItem('selectedSpot', 'autre_hebergement');
        const nightWeather = document.getElementById('nightWeather');
        if (nightWeather) nightWeather.style.display = 'none';
        const nextBtn = document.getElementById('nextStepBtn');
        if (nextBtn) nextBtn.style.display = 'block';
    };

    // Affichage de la carte détaillée spot
    window.showSpotMap = function(spotId) {
        const selectedHiking = localStorage.getItem('selectedHiking') || '1';
        const mapUrl = `/map/spot/${spotId}?hiking=${selectedHiking}`;
        window.open(mapUrl, '_blank', 'width=1200,height=800');
    };

});
// Fonction générique pour la sélection d'une carte (card)
function selectCard({
    cardSelector,
    cardId,
    noOptionSelector = null,
    storageKey,
    storageValue,
    nextBtnId = 'nextStepBtn',
    extra = null
}) {
    document.querySelectorAll(cardSelector).forEach(card => card.classList.remove('selected'));
    const cardElem = document.querySelector(`[onclick*='${cardId}']`);
    if (cardElem) cardElem.closest(cardSelector).classList.add('selected');
    if (noOptionSelector) {
        const noOption = document.querySelector(noOptionSelector);
        if (noOption) noOption.classList.remove('selected');
    }
    if (storageKey) localStorage.setItem(storageKey, storageValue);
    const nextBtn = document.getElementById(nextBtnId);
    if (nextBtn) nextBtn.style.display = 'block';
    if (typeof extra === 'function') extra();
}

// Spécifique randonnée
window.selectHiking = function(id) {
    selectCard({
        cardSelector: '.hiking-card',
        cardId: id,
        noOptionSelector: '#noHikingCard',
        storageKey: 'selectedHiking',
        storageValue: id
    });
};
window.selectNoHiking = function() {
    document.querySelectorAll('.hiking-card').forEach(card => card.classList.remove('selected'));
    const noHiking = document.getElementById('noHikingCard');
    if (noHiking) noHiking.classList.add('selected');
    localStorage.setItem('selectedHiking', 'no-hiking');
    const nextBtn = document.getElementById('nextStepBtn');
    if (nextBtn) nextBtn.style.display = 'block';
};
window.showHikingMap = function(id) {
    const mapUrl = `/map/randonnee/${id}`;
    window.open(mapUrl, '_blank', 'width=1200,height=800');
};

// Spécifique spot
window.selectSpot = function(spotId) {
    selectCard({
        cardSelector: '.spot-card',
        cardId: spotId,
        noOptionSelector: '.no-spot-option',
        storageKey: 'selectedSpot',
        storageValue: spotId,
        extra: function() {
            const nightWeather = document.getElementById('nightWeather');
            if (nightWeather) nightWeather.style.display = 'block';
        }
    });
};
window.selectNoSpot = function() {
    document.querySelectorAll('.spot-card').forEach(card => card.classList.remove('selected'));
    const noSpotOption = document.querySelector('.no-spot-option');
    if (noSpotOption) noSpotOption.classList.add('selected');
    localStorage.setItem('selectedSpot', 'autre_hebergement');
    const nightWeather = document.getElementById('nightWeather');
    if (nightWeather) nightWeather.style.display = 'none';
    const nextBtn = document.getElementById('nextStepBtn');
    if (nextBtn) nextBtn.style.display = 'block';
};
window.showSpotMap = function(spotId) {
    const selectedHiking = localStorage.getItem('selectedHiking') || '1';
    const mapUrl = `/map/spot/${spotId}?hiking=${selectedHiking}`;
    window.open(mapUrl, '_blank', 'width=1200,height=800');
};
// Initialisation Leaflet sur toutes les pages avec une div #map
// SAUF sur étape1 qui gère sa propre carte
document.addEventListener('DOMContentLoaded', function() {
    const citySelect = document.getElementById('citySelect');
    // Ne pas initialiser si on est sur la page étape1 (qui a un citySelect)
    if (typeof L !== 'undefined' && document.getElementById('map') && !citySelect) {
        var map = L.map('map').setView([48.3833, -4.7708], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 18,
            attribution: '© OpenStreetMap'
        }).addTo(map);
        L.marker([48.349998,  -4.71667]).addTo(map)
            .bindPopup('Plougonvelin');
    }
});
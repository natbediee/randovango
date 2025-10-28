// =============================
// JS ÉTAPE 3 - CHOIX SPOT / HÉBERGEMENT
// =============================

// Sélection d'un spot (hébergement)
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

// Affichage de la carte spot
window.showSpotMap = function(spotId) {
    const selectedHiking = localStorage.getItem('selectedHiking') || '1';
    const mapUrl = `/map/spot/${spotId}?hiking=${selectedHiking}`;
    window.open(mapUrl, '_blank', 'width=1200,height=800');
};

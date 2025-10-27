// JS commun : Leaflet, filtres, cards génériques, etc.

// =============================
// FONCTIONS COMMUNES / UTILITAIRES
// =============================

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

// Initialisation Leaflet sur toutes les pages avec une div #map
// (affichage de la carte OpenStreetMap si présent)
// NOTE: DÉSACTIVÉ - Chaque page gère sa propre carte
/*
document.addEventListener('DOMContentLoaded', function() {
    // Ne pas initialiser la carte si on est sur une page du planificateur (etape1, etape2, etc.)
    const isPlanningPage = window.location.pathname.match(/\/etape[1-4]/);
    
    if (typeof L !== 'undefined' && document.getElementById('map') && !isPlanningPage) {
        var map = L.map('map').setView([48.3833, -4.7708], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 18,
            attribution: '© OpenStreetMap'
        }).addTo(map);
        L.marker([48.349998,  -4.71667]).addTo(map)
            .bindPopup('Plougonvelin');
    }
});
*/

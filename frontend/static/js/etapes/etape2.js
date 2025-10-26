// =============================
// JS ÉTAPE 2 - CHOIX RANDONNÉE
// =============================

// Sélection d'une randonnée
window.selectHiking = function(id) {
    selectCard({
        cardSelector: '.hiking-card',
        cardId: id,
        noOptionSelector: '#noHikingCard',
        storageKey: 'selectedHiking',
        storageValue: id
    });
};

// Sélection "pas de randonnée"
window.selectNoHiking = function() {
    document.querySelectorAll('.hiking-card').forEach(card => card.classList.remove('selected'));
    const noHiking = document.getElementById('noHikingCard');
    if (noHiking) noHiking.classList.add('selected');
    localStorage.setItem('selectedHiking', 'no-hiking');
    const nextBtn = document.getElementById('nextStepBtn');
    if (nextBtn) nextBtn.style.display = 'block';
};

// Affichage de la carte randonnée
window.showHikingMap = function(id) {
    const mapUrl = `/map/randonnee/${id}`;
    window.open(mapUrl, '_blank', 'width=1200,height=800');
};

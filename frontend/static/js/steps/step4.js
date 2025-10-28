// =============================
// JS ÉTAPE 4 - CHOIX SERVICES
// =============================

document.addEventListener('DOMContentLoaded', function() {
    // Adapter le contenu selon les choix précédents (spécifique étape 4)
    const selectedHiking = localStorage.getItem('selectedHiking');
    const selectedSpot = localStorage.getItem('selectedSpot');
    if (selectedHiking === 'no-hiking') {
        const stepTitle = document.querySelector('.step-header h2');
        if (stepTitle) stepTitle.textContent = '🛠️ Jour 1 : Services pour votre journée détente';
    }
    if (selectedSpot === 'autre_hebergement') {
        const stepSubtitle = document.querySelector('.step-header p');
        if (stepSubtitle) stepSubtitle.textContent = 'Ajoutez les services utiles pendant votre séjour';
    }

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

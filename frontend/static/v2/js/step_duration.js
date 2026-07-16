/* Front v2 - Accueil / choix de la durée (écran 01).
   Reprend la logique métier du legacy step_duration.js : purge de l'état d'un séjour
   précédent, sélection de durée (cartes data-days), date de départ, navigation vers step1.
   Le widget de connexion/upload GPX du legacy n'est PAS repris ici : il vit désormais dans
   les pages contributeur dédiées (/contributor/login, /contributor/add-hike). */
document.addEventListener('DOMContentLoaded', function () {
  // /duration = tout début d'une nouvelle planification. On efface l'état d'un séjour
  // précédent (même abandonné en cours), sinon l'utilisateur reste coincé dessus.
  ['changingCityForNextDay', 'planId', 'currentDay', 'selectedCityId',
   'selectedHiking', 'selectedSpot', 'selectedServices'].forEach(function (k) {
    localStorage.removeItem(k);
  });
  sessionStorage.removeItem('step1_cityId');

  let selectedDays = null;
  const durationCards = document.querySelectorAll('.duration-card');
  const nextButton = document.getElementById('nextButton');

  // Date du premier jour : par défaut aujourd'hui, jamais dans le passé.
  const startDateInput = document.getElementById('startDate');
  if (startDateInput) {
    const todayStr = new Date().toISOString().slice(0, 10);
    startDateInput.value = todayStr;
    startDateInput.min = todayStr;
  }

  function updateNextButton() {
    if (!selectedDays) {
      nextButton.innerHTML = 'Choisissez une durée <i class="fas fa-arrow-right"></i>';
      nextButton.disabled = true;
      return;
    }
    const dayText = selectedDays === 1 ? 'jour' : 'jours';
    nextButton.innerHTML = `Planifier ces ${selectedDays} ${dayText} <i class="fas fa-arrow-right"></i>`;
    nextButton.disabled = false;
  }

  durationCards.forEach(function (card) {
    card.addEventListener('click', function () {
      durationCards.forEach(function (c) { c.classList.remove('is-selected'); });
      this.classList.add('is-selected');

      const days = this.getAttribute('data-days');
      if (days === 'custom') {
        const customInput = document.getElementById('customDays');
        customInput.focus();
        selectedDays = parseInt(customInput.value) || null;
        updateNextButton();
        customInput.addEventListener('input', function () {
          selectedDays = parseInt(this.value) || null;
          updateNextButton();
        });
      } else {
        selectedDays = parseInt(days);
        updateNextButton();
      }
    });
  });

  nextButton.addEventListener('click', function (e) {
    e.preventDefault();
    if (!selectedDays) return;
    localStorage.setItem('selectedDays', selectedDays);
    const startDate = (startDateInput && startDateInput.value) || new Date().toISOString().slice(0, 10);
    localStorage.setItem('selectedStartDate', startDate);
    window.location.href = window.APP_URLS.step1;
  });
});

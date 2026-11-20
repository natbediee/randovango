/* Front RandoVanGo - Accueil / choix de la durée (écran 01).
   Sélection de durée (cartes data-days), date de départ, navigation vers step1.
   Voyage en cours (issue #262) : treize liens mènent ici (logo, retours, « Créer mon voyage »…).
   Avant, la page effaçait le voyage en cours à chaque visite, et le plafond d'un voyage par jour
   empêchait d'en créer un autre : la journée de préparation était perdue. Elle propose maintenant
   de le reprendre ou d'en commencer un nouveau, et ne l'oublie que sur ce second choix.
   Le widget de connexion/upload GPX du legacy n'est PAS repris ici : il vit désormais dans
   les pages contributeur dédiées (/contributor/login, /contributor/add-hike). */
document.addEventListener('DOMContentLoaded', function () {
  const durationSection = document.getElementById('durationSection');
  offerCurrentTrip();

  // Grise (ou dégrise) le choix de la durée. inert le rend aussi inaccessible au clavier.
  function lockDuration(locked) {
    durationSection.inert = locked;
    durationSection.classList.toggle('is-locked', locked);
  }

  // Propose de reprendre le voyage en cours, s'il y en a un que l'API rend encore au voyageur.
  // Les durées sont grisées tout de suite, avant même la réponse de l'API : un clic pendant
  // l'attente ne doit pas lancer un nouveau voyage sans que le voyageur ait choisi.
  async function offerCurrentTrip() {
    const trip = window.RVG.trip.toOffer();
    if (!trip || trip.fromBackup) return; // le secours ne se reprend que depuis la page « voyage gratuit du jour »
    lockDuration(true);
    const plan = await window.RVG.trip.fetch(trip);
    if (!plan) {
      // Voyage introuvable ou plus à ce voyageur (déconnexion, jeton expiré) : rien à proposer.
      lockDuration(false);
      return;
    }
    document.getElementById('tripResumeSummary').textContent = window.RVG.trip.describe(plan, trip.currentDay);
    document.getElementById('tripResume').hidden = false;
    document.getElementById('tripResumeButton').addEventListener('click', function () {
      window.RVG.trip.resume(trip);
    });
    document.getElementById('tripNewButton').addEventListener('click', startNewTrip);
  }

  // « Commencer un nouveau voyage » : le voyage en cours est oublié (rangé en secours), l'encadré
  // disparaît et le voyageur choisit sa durée.
  function startNewTrip() {
    window.RVG.trip.forget();
    document.getElementById('tripResume').hidden = true;
    lockDuration(false);
    durationSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

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
    // Plus de 7 jours tapés dans la case « Personnalisée » (son max="7" n'empêche pas de les taper) :
    // la page de l'offre explique que les séjours plus longs viendront avec l'offre payante (issue #263).
    if (window.RVG.isTripTooLong(selectedDays)) {
      window.RVG.showTripTooLong();
      return;
    }
    // Ici, le voyageur part sur un nouveau voyage : soit il l'a choisi dans l'encadré, soit aucun
    // voyage ne lui était proposé (l'API ne le rendait plus). Un planId resté dans le navigateur
    // ferait croire à l'étape 1 qu'un voyage est en cours, et elle n'en créerait pas : on l'oublie.
    window.RVG.trip.forget();
    localStorage.setItem('selectedDays', selectedDays);
    const startDate = (startDateInput && startDateInput.value) || new Date().toISOString().slice(0, 10);
    localStorage.setItem('selectedStartDate', startDate);
    window.location.href = window.APP_URLS.step1;
  });
});

/* Front RandoVanGo - reprendre ou oublier le voyage en cours (issue #262).
   Le voyage en cours vit dans le navigateur (localStorage) : son numéro (planId), le jour en cours,
   la ville, la rando et le spot du jour. Deux pages s'en servent :
     - « Durée » (step_duration.js) propose de le reprendre ou d'en commencer un nouveau ;
     - « voyage gratuit du jour » (free_limit.js) propose de reprendre le voyage du jour.
   Pourquoi un secours : un voyageur qui choisit « nouveau voyage » peut ensuite tomber sur le plafond
   d'un voyage par jour. Si son voyage avait été effacé, il serait perdu. On le range donc dans une clé
   de secours (previousTrip), effacée seulement quand le nouveau voyage est vraiment créé (step1_city.js). */
(function () {
  'use strict';

  // Les clés du voyage en cours. Les effacer, c'est oublier le voyage (choix « nouveau voyage »).
  // selectedDays et selectedStartDate n'y sont pas : la page « Durée » les réécrit de toute façon.
  var TRIP_KEYS = ['changingCityForNextDay', 'planId', 'currentDay', 'selectedCityId',
    'selectedHiking', 'selectedSpot', 'selectedServices',
    'editingDay', 'editReturnDay', 'editOriginalCity', 'vanyNewsReturn', 'lastTripPage'];
  // Clés gardées dans le secours en plus : sans elles, la reprise ne saurait plus la durée du voyage.
  var BACKUP_KEYS = TRIP_KEYS.concat(['selectedDays', 'selectedStartDate']);
  var BACKUP_KEY = 'previousTrip';

  // Le navigateur garde-t-il un voyage en cours ?
  function hasCurrentTrip() {
    return !!localStorage.getItem('planId');
  }

  // Le voyage rangé en secours, sous forme d'objet { clé: valeur }, ou null s'il n'y en a pas.
  function backupTrip() {
    try {
      var saved = JSON.parse(localStorage.getItem(BACKUP_KEY));
      return saved && saved.planId ? saved : null;
    } catch (e) {
      return null; // secours illisible : comme s'il n'y en avait pas
    }
  }

  // « Nouveau voyage » : on range le voyage en cours dans le secours, puis on efface ses clés.
  function forgetTrip() {
    if (hasCurrentTrip()) {
      var saved = {};
      BACKUP_KEYS.forEach(function (k) { saved[k] = localStorage.getItem(k); });
      localStorage.setItem(BACKUP_KEY, JSON.stringify(saved));
    }
    TRIP_KEYS.forEach(function (k) { localStorage.removeItem(k); });
    sessionStorage.removeItem('step1_cityId');
  }

  // Remet le voyage du secours en voyage en cours (reprise depuis la page « voyage gratuit du jour »).
  function restoreBackup() {
    var saved = backupTrip();
    if (!saved) return;
    Object.keys(saved).forEach(function (k) {
      if (saved[k] === null) localStorage.removeItem(k);
      else localStorage.setItem(k, saved[k]);
    });
    localStorage.removeItem(BACKUP_KEY);
  }

  // Le nouveau voyage est créé : le secours ne sert plus à rien.
  function dropBackup() {
    localStorage.removeItem(BACKUP_KEY);
  }

  // Le voyage à proposer : celui en cours, sinon celui du secours. Renvoie { planId, currentDay, fromBackup }.
  function tripToOffer() {
    if (hasCurrentTrip()) {
      return {
        planId: localStorage.getItem('planId'),
        currentDay: parseInt(localStorage.getItem('currentDay') || '1', 10),
        fromBackup: false
      };
    }
    var saved = backupTrip();
    if (!saved) return null;
    return { planId: saved.planId, currentDay: parseInt(saved.currentDay || '1', 10), fromBackup: true };
  }

  // Demande le voyage à l'API. Elle ne le rend qu'à son propriétaire (compte ou invité) :
  // après une déconnexion ou un jeton invité expiré, elle refuse, et on ne propose pas la reprise.
  // Renvoie le voyage (ville, durée, date de départ…) ou null.
  async function fetchTrip(trip) {
    try {
      var response = await window.RVG.apiFetch('/api/result/?plan_id=' + encodeURIComponent(trip.planId)
        + '&up_to_day=' + trip.currentDay);
      if (!response.ok) return null;
      return await response.json();
    } catch (e) {
      return null; // API injoignable : on ne propose rien plutôt qu'une reprise qui échouerait
    }
  }

  // La phrase qui décrit le voyage, ex. « Le Conquet · 3 jours à partir du jeu. 19 nov. · jour 2 sur 3 ».
  function describeTrip(plan, currentDay) {
    var days = plan.duration_days;
    // La ville du jour en cours : celle du dernier jour renvoyé, sinon celle du départ.
    var lastDay = (plan.days || [])[(plan.days || []).length - 1];
    var city = (lastDay && lastDay.city_name) || plan.city_name || 'Ville à choisir';
    var parts = [city, days + (days > 1 ? ' jours' : ' jour')];
    var start = new Date(plan.start_date + 'T00:00:00');
    if (!isNaN(start.getTime())) {
      parts[1] += ' à partir du ' + start.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' });
    }
    parts.push('jour ' + Math.min(currentDay, days) + ' sur ' + days);
    return parts.join(' · ');
  }

  // Reprend le voyage : remet le secours si besoin, puis ouvre la dernière page du parcours visitée.
  // Sans page notée (voyage commencé avant cette version), on repart à la rando du jour en cours.
  function resumeTrip(trip) {
    if (trip.fromBackup) restoreBackup();
    window.location.href = localStorage.getItem('lastTripPage') || window.APP_URLS.step2;
  }

  window.RVG = window.RVG || {};
  window.RVG.trip = {
    forget: forgetTrip,
    dropBackup: dropBackup,
    toOffer: tripToOffer,
    fetch: fetchTrip,
    describe: describeTrip,
    resume: resumeTrip
  };
})();

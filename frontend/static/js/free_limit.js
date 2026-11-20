/* Front RandoVanGo - page « voyage gratuit du jour déjà composé » (issue #262).
   Elle sert aussi aux séjours de plus de 7 jours (issue #263) : ce cas n'a rien à reprendre.
   Le voyageur arrive ici quand l'API refuse un deuxième voyage dans la journée. Son voyage du jour
   existe déjà : on lui propose de le reprendre, plutôt que de le laisser sans issue jusqu'à demain.
   Le voyage peut être en cours dans le navigateur, ou rangé en secours s'il avait choisi « nouveau
   voyage » sur la page « Durée » (voir trip_resume.js). */
document.addEventListener('DOMContentLoaded', async function () {
  const resumeButton = document.getElementById('tripResumeButton');
  const missingText = document.getElementById('tripResumeMissing');
  // Séjour de plus de 7 jours (issue #263) : le voyageur n'a pas encore de voyage, la page ne montre
  // pas le bouton de reprise mais celui du retour au choix de la durée. Rien à chercher.
  if (!resumeButton) return;

  // Pas de voyage dans ce navigateur (autre appareil, données effacées), ou l'API ne le rend plus
  // à ce voyageur : on le dit, au lieu d'un bouton qui mènerait à une page vide.
  const trip = window.RVG.trip.toOffer();
  const plan = trip ? await window.RVG.trip.fetch(trip) : null;
  if (!plan) {
    missingText.hidden = false;
    return;
  }
  resumeButton.hidden = false;
  resumeButton.addEventListener('click', function () {
    window.RVG.trip.resume(trip);
  });
});

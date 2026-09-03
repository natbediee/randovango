/* Front v2 - comportements communs (chargé sur toutes les pages via base.html). */
(function () {
  'use strict';

  // ===== Menu burger mobile =====
  // Ouvre/ferme le panneau de nav sous le header ; l'icône passe en croix (via .is-open).
  function initBurger() {
    var burger = document.querySelector('[data-burger]');
    var panel = document.querySelector('[data-nav-panel]');
    if (!burger || !panel) return;

    function close() {
      panel.classList.remove('is-open');
      burger.classList.remove('is-open');
      burger.setAttribute('aria-expanded', 'false');
    }
    function toggle(e) {
      e.stopPropagation();
      var open = panel.classList.toggle('is-open');
      burger.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    burger.addEventListener('click', toggle);
    // Fermeture au clic sur un lien ou en dehors du panneau.
    panel.addEventListener('click', function (e) {
      if (e.target.closest('a')) close();
    });
    document.addEventListener('click', function (e) {
      if (!panel.contains(e.target) && !burger.contains(e.target)) close();
    });
  }

  // ===== État de session dans le header (accueil / planificateur) =====
  // Le header est rendu par le serveur sans connaître l'état d'auth (côté client :
  // localStorage). Quand un contributeur est connecté, le lien « Contributeur ?
  // Connexion » cède la place au lien « Espace contributeur », à l'avatar et au
  // bouton de déconnexion.
  function getUsername() {
    return localStorage.getItem('username') || sessionStorage.getItem('username');
  }
  function isLoggedIn() {
    return !!(localStorage.getItem('userId') || getUsername());
  }
  function logout() {
    // Self-contained (contrib.js n'est pas chargé sur ces pages) : on vide les deux
    // emplacements utilisés par le login (voir contrib.js storeSession/logoutContrib).
    ['jwtToken', 'username'].forEach(function (k) { sessionStorage.removeItem(k); });
    ['userToken', 'userId', 'username'].forEach(function (k) { localStorage.removeItem(k); });
  }

  function initAccountMenu() {
    var account = document.querySelector('[data-account]');
    if (!account || !isLoggedIn()) return;

    var name = getUsername() || 'mon compte';
    account.querySelectorAll('[data-account-initials]').forEach(function (el) {
      el.textContent = name.slice(0, 2).toUpperCase();
    });
    account.style.display = 'flex';

    var logoutLink = account.querySelector('[data-account-logout]');
    if (logoutLink) {
      logoutLink.addEventListener('click', function (e) {
        e.preventDefault();
        logout();
        // Retour à l'accueil plutôt qu'un simple reload : la page courante peut
        // être réservée aux contributeurs (dashboard, ajout de spot/rando).
        window.location.href = window.APP_URLS.duration;
      });
    }
  }

  // ===== Timeline du séjour (header du wizard) =====
  // Le serveur rend le jour courant déplié en ses quatre étapes ; le nombre de jours
  // et le rang de ce jour ne sont connus que du navigateur (localStorage), d'où les
  // pastilles des autres jours insérées ici, de part et d'autre du jour déplié.
  function initDayTimeline() {
    var timeline = document.querySelector('[data-timeline]');
    if (!timeline) return;

    function num(key, fallback) {
      var v = parseInt(localStorage.getItem(key), 10);
      return isNaN(v) || v < 1 ? fallback : v;
    }
    var total = num('selectedDays', 1);
    var current = num('currentDay', 1);
    if (current > total) current = total;

    // Le carnet n'est pas que la fin du séjour : on y repasse après CHAQUE
    // journée pour lancer la suivante. Le serveur n'y rend donc pas de jour déplié,
    // mais tout ce qui suit currentDay reste à composer.
    var expanded = timeline.querySelector('.timeline__current');
    var lastDone = expanded ? current - 1 : current;

    // Édition d'un jour déjà planifié (bouton « Modifier » du récap) : currentDay
    // vaut le jour rouvert, la progression réelle est dans editReturnDay. Le récap
    // la restaure lui aussi (results.js), mais après nous.
    if (localStorage.getItem('editingDay')) {
      lastDone = Math.max(lastDone, num('editReturnDay', 1));
    }

    var dayLabel = timeline.querySelector('[data-timeline-day]');
    if (dayLabel) dayLabel.textContent = 'Jour ' + current;

    function chips(from, to) {
      var html = '';
      for (var d = from; d <= to; d++) {
        var done = d <= lastDone;
        html += '<span class="timeline__chip' + (done ? ' is-done' : '') + '">'
          + (done ? '<i class="fas fa-check" aria-hidden="true"></i> ' : '')
          + 'Jour ' + d + '</span>';
      }
      return html;
    }

    var book = timeline.querySelector('.timeline__chip--book');
    var html = chips(1, expanded ? current - 1 : total);
    if (html) (expanded || book).insertAdjacentHTML('beforebegin', html);

    // Jours restant à composer, entre le jour déplié et le carnet.
    if (expanded) {
      html = chips(current + 1, total);
      if (html) book.insertAdjacentHTML('beforebegin', html);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initBurger();
    initAccountMenu();
    initDayTimeline();
  });

  // ===== Helpers exposés =====
  // Déblocage du chat Vany (payé ou code contributeur validé) - mock front-only pour l'instant.
  window.RVG = window.RVG || {};
  window.RVG.isVanyUnlocked = function () {
    return localStorage.getItem('vanyUnlocked') === '1';
  };
  window.RVG.unlockVany = function () {
    localStorage.setItem('vanyUnlocked', '1');
  };
})();

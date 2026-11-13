/* Front RandoVanGo - comportements communs (chargé sur toutes les pages via base.html). */
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

  // ===== Appels à l'API =====
  // Le jeton de connexion est dans un cookie httpOnly posé par l'API (carte #24) : le JavaScript
  // ne le voit pas et ne l'envoie pas lui-même. credentials: 'include' demande au navigateur de
  // joindre ce cookie, y compris quand le front et l'API ne sont pas sur le même port.
  // Tous les appels à l'API passent par ici, pour qu'aucun n'oublie le cookie.
  // Les routes du voyage exigent un jeton (carte #103) : un visiteur sans compte reçoit d'abord un
  // jeton invité (ensureSession), puis l'appel part. Les routes /api/auth/ n'en ont pas besoin.
  async function apiFetch(path, options) {
    if (path.indexOf('/api/auth/') !== 0) await ensureSession();
    return fetch(window.API_BASE + path, Object.assign({}, options, { credentials: 'include' }));
  }

  // Plusieurs appels partent en même temps au chargement d'une page : ils attendent tous la même
  // demande de jeton invité, au lieu d'en demander un chacun.
  var guestRequest = null;
  function ensureSession() {
    if (isLoggedIn() || hasGuestSession()) return Promise.resolve();
    if (!guestRequest) {
      guestRequest = requestGuestSession().finally(function () { guestRequest = null; });
    }
    return guestRequest;
  }
  // L'API pose le jeton invité dans le cookie ; le front ne garde que son heure de fin.
  async function requestGuestSession() {
    try {
      var response = await fetch(window.API_BASE + '/api/auth/guest', { method: 'POST', credentials: 'include' });
      if (response.ok) localStorage.setItem('guestExpiresAt', (await response.json()).expires_at);
    } catch (err) { /* API injoignable : l'appel qui suit échouera de lui-même, avec son propre message */ }
  }

  // ===== Session affichée =====
  // Ce que le front garde de la connexion, pour l'affichage seulement : nom, rôles et heure de fin.
  // Rien de secret : c'est l'API qui décide des droits, en lisant le cookie.
  var SESSION_KEYS = ['userId', 'username', 'userRoles', 'sessionExpiresAt', 'guestExpiresAt'];

  function storeSession(user, expiresAt) {
    localStorage.setItem('userId', user.id);
    localStorage.setItem('username', user.username);
    localStorage.setItem('userRoles', (user.roles || []).join(','));
    localStorage.setItem('sessionExpiresAt', expiresAt);
    // Le cookie du compte a remplacé celui de l'invité : à la fin de la session, il en faudra un nouveau.
    localStorage.removeItem('guestExpiresAt');
  }
  // Une heure de fin (texte ISO) pas encore passée ? Le cookie expire au même moment.
  function isStillValid(expiresAt) {
    var time = Date.parse(expiresAt || '');
    return !isNaN(time) && time > Date.now();
  }
  function isLoggedIn() {
    return isStillValid(localStorage.getItem('sessionExpiresAt'));
  }
  function hasGuestSession() {
    return isStillValid(localStorage.getItem('guestExpiresAt'));
  }
  function getUsername() {
    return localStorage.getItem('username');
  }
  // Seule l'API peut effacer le cookie httpOnly : on le lui demande, puis on oublie la session affichée.
  async function logout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (err) { /* API injoignable : la session affichée est quand même oubliée */ }
    SESSION_KEYS.forEach(function (k) { localStorage.removeItem(k); });
  }

  // ===== État de session dans le header (accueil / planificateur) =====
  // Le header est rendu par le serveur dans l'état déconnecté. Connecté, le lien
  // « Contributeur ? Connexion » disparaît au profit de l'avatar, dont le menu déroulant
  // porte l'espace contributeur, la création de voyage et la déconnexion.

  function initAccountMenu() {
    var account = document.querySelector('[data-account]');
    if (!account || !isLoggedIn()) return;

    // Le lien de connexion est rendu deux fois (nav desktop + panneau burger).
    document.querySelectorAll('[data-nav-anon]').forEach(function (el) {
      el.remove();
    });

    // Le burger ferait un second menu à côté de celui du compte, qui reprend les
    // liens publics (.account__menu-public) : on le retire, panneau compris.
    var burger = document.querySelector('[data-burger]');
    var panel = document.querySelector('[data-nav-panel]');
    if (burger) burger.style.display = 'none';
    if (panel) panel.remove();

    if ((localStorage.getItem('userRoles') || '').split(',').indexOf('admin') !== -1) {
      document.querySelectorAll('[data-admin-only]').forEach(function (el) { el.style.display = ''; });
    }

    var name = getUsername() || 'mon compte';
    account.querySelectorAll('[data-account-initials]').forEach(function (el) {
      el.textContent = name.slice(0, 2).toUpperCase();
    });
    account.style.display = 'flex';

    var toggle = account.querySelector('[data-account-toggle]');
    var menu = account.querySelector('[data-account-menu]');
    if (toggle && menu) {
      function close() {
        menu.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
      }
      toggle.addEventListener('click', function (e) {
        e.stopPropagation();
        var open = menu.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      // Fermeture au clic en dehors (le clic sur le burger passe aussi par là).
      document.addEventListener('click', function (e) {
        if (!account.contains(e.target)) close();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') close();
      });
    }

    var logoutLink = account.querySelector('[data-account-logout]');
    if (logoutLink) {
      logoutLink.addEventListener('click', async function (e) {
        e.preventDefault();
        await logout();
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

    // Nom de la ville du jour, tiré de la liste gardée par l'étape 1 (step1_city.js) :
    // le serveur ne connaît pas la ville choisie, elle vit dans localStorage.
    var cityLabel = timeline.querySelector('[data-timeline-city]');
    if (cityLabel) {
      try {
        var names = JSON.parse(localStorage.getItem('cityNames')) || {};
        var name = names[localStorage.getItem('selectedCityId')];
        if (name) {
          cityLabel.textContent = name;
          cityLabel.title = name;
        }
      } catch (e) { /* liste illisible : on garde « Ville » */ }
    }

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

    // Séjour complet (toutes les journées composées) : le carnet devient une étape
    // franchie, coche comprise, comme les jours terminés. Vrai sur le carnet final,
    // mais aussi si on revient éditer un jour d'un séjour déjà bouclé. Sur les
    // carnets intermédiaires (on y repasse après chaque journée), lastDone < total :
    // le carnet reste à venir.
    if (book && lastDone >= total) {
      book.classList.add('is-done');
      var bookIcon = book.querySelector('i');
      if (bookIcon) bookIcon.className = 'fas fa-check';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initBurger();
    initAccountMenu();
    initDayTimeline();
  });

  // ===== Helpers exposés =====
  window.RVG = window.RVG || {};
  window.RVG.apiFetch = apiFetch;
  window.RVG.storeSession = storeSession;
  window.RVG.isLoggedIn = isLoggedIn;
  window.RVG.logout = logout;

  // Déblocage du chat Vany (payé ou code contributeur validé) - mock front-only pour l'instant.
  window.RVG.isVanyUnlocked = function () {
    return localStorage.getItem('vanyUnlocked') === '1';
  };
  window.RVG.unlockVany = function () {
    localStorage.setItem('vanyUnlocked', '1');
  };
})();

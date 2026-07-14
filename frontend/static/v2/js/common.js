/* Front v2 — comportements communs (chargé sur toutes les pages via base.html). */
(function () {
  'use strict';

  // ===== Menu burger mobile =====
  // Ouvre/ferme le panneau de nav sous le header ; l'icône passe en croix (via .is-open).
  function initBurger() {
    var burger = document.querySelector('[data-burger]');
    var panel = document.querySelector('[data-mobile-nav]');
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
  // localStorage). Quand un contributeur est connecté, on remplace le lien
  // « Contributeur ? Connexion » par « Bonjour, <username> » + « Déconnexion ».
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

  function initAuthNav() {
    if (!isLoggedIn()) return;
    var name = getUsername() || 'mon compte';
    // Les liens « Connexion » (desktop + mobile) portent la classe .nav-cta.
    document.querySelectorAll('.rvg-nav .nav-cta').forEach(function (cta) {
      var greeting = document.createElement('span');
      greeting.className = 'rvg-greeting';
      greeting.textContent = 'Bonjour, ' + name;
      cta.parentNode.insertBefore(greeting, cta);

      cta.textContent = 'Déconnexion';
      cta.setAttribute('href', '#');
      cta.addEventListener('click', function (e) {
        e.preventDefault();
        logout();
        window.location.reload();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initBurger();
    initAuthNav();
  });

  // ===== Helpers exposés =====
  // Déblocage du chat Vany (payé ou code contributeur validé) — mock front-only pour l'instant.
  window.RVG = window.RVG || {};
  window.RVG.isVanyUnlocked = function () {
    return localStorage.getItem('vanyUnlocked') === '1';
  };
  window.RVG.unlockVany = function () {
    localStorage.setItem('vanyUnlocked', '1');
  };
})();

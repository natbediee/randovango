/* Front RandoVanGo - espace contributeur (connexion + garde du dashboard).
   Login branché sur le vrai endpoint FastAPI POST /api/auth/login (JWT).
   NB: l'API attend `username` ; on envoie la saisie telle quelle (le passage à
   l'email se fera côté backend plus tard). Le jeton n'est jamais vu par cette page :
   l'API le pose dans un cookie httpOnly (carte #24), voir common.js apiFetch. */
(function () {
  'use strict';

  // ===== Page connexion =====
  function initLogin() {
    var form = document.getElementById('contribLoginForm');
    if (!form) return;

    var toggle = document.getElementById('togglePass');
    var pass = document.getElementById('loginPass');
    if (toggle && pass) {
      toggle.addEventListener('click', function () {
        var show = pass.type === 'password';
        pass.type = show ? 'text' : 'password';
        toggle.textContent = show ? 'Masquer' : 'Afficher';
      });
    }

    var errorBox = document.getElementById('loginError');
    var submit = document.getElementById('loginSubmit');

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      errorBox.style.display = 'none';
      var username = document.getElementById('loginUser').value.trim();
      var password = document.getElementById('loginPass').value;
      if (!username || !password) return;

      submit.disabled = true;
      var original = submit.innerHTML;
      submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Connexion…';

      try {
        var res = await window.RVG.apiFetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: username, password: password })
        });
        var data = await res.json();
        if (res.ok && data.success) {
          // Le jeton est déjà dans le cookie posé par l'API : on ne garde que ce qui s'affiche.
          window.RVG.storeSession(data.user, data.expires_at);
          window.location.href = window.APP_URLS.contributor;
        } else {
          // 401 : la raison est dans message. 429 (trop d'essais manqués, issue #264) : elle est dans detail,
          // comme pour tous les plafonds ; sans cela, la page dirait « mot de passe incorrect » à tort.
          errorBox.textContent = data.message || data.detail || 'Identifiant ou mot de passe incorrect.';
          errorBox.style.display = 'block';
          submit.disabled = false;
          submit.innerHTML = original;
        }
      } catch (err) {
        errorBox.textContent = 'Impossible de joindre le serveur. Réessaie plus tard.';
        errorBox.style.display = 'block';
        submit.disabled = false;
        submit.innerHTML = original;
      }
    });
  }

  // ===== Salutation du dashboard =====
  // Salutation du dashboard (« Bonjour <nom>. »). L'avatar et la déconnexion du
  // header sont, eux, communs à toutes les pages (common.js initAccountMenu).
  function initDashboardGreeting() {
    var nameEl = document.getElementById('contribName');
    if (!nameEl) return;
    nameEl.textContent = localStorage.getItem('username') || 'contributeur';
  }

  // ===== Garde du dashboard : redirige vers la connexion si non authentifié =====
  function initDashboardGuard() {
    var el = document.querySelector('[data-contrib-dashboard]');
    if (!el) return;
    if (!window.RVG.isLoggedIn()) {
      window.location.href = window.APP_URLS.contributorLogin;
      return;
    }
  }

  // ===== Page ajout de randonnée : upload GPX réel (/api/etl/upload_gpx) =====
  function initAddHike() {
    var root = document.querySelector('[data-add-hike]');
    if (!root) return;

    // Garde : réservé aux contributeurs connectés.
    if (!window.RVG.isLoggedIn()) {
      window.location.href = window.APP_URLS.contributorLogin;
      return;
    }

    var dropzone = document.getElementById('gpxDropzone');
    var input = document.getElementById('gpxFileInput');
    var label = document.getElementById('gpxDropLabel');
    var msg = document.getElementById('gpxMsg');
    var submit = document.getElementById('submitHike');
    var loadAnyway = document.getElementById('loadAnyway');
    var selectedFile = null;

    function showMsg(text, ok) {
      msg.textContent = text;
      msg.className = 'addhike-msg ' + (ok ? 'is-ok' : 'is-error');
      msg.style.display = 'block';
    }

    if (dropzone && input) {
      dropzone.addEventListener('click', function () { input.click(); });
      ['dragover', 'dragenter'].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add('is-drag'); });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove('is-drag'); });
      });
      dropzone.addEventListener('drop', function (e) {
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
          selectedFile = e.dataTransfer.files[0];
          label.textContent = selectedFile.name;
          hideLoadAnyway();
        }
      });
      input.addEventListener('change', function () {
        if (input.files && input.files[0]) {
          selectedFile = input.files[0];
          label.textContent = selectedFile.name;
          hideLoadAnyway();
        }
      });
    }

    // Le bouton « Charger quand même » ne vaut que pour le fichier qui vient d'être refusé : il disparaît dès qu'un
    // autre fichier est choisi ou qu'un nouvel envoi part.
    function hideLoadAnyway() {
      if (loadAnyway) loadAnyway.style.display = 'none';
    }

    // Envoie le fichier choisi à l'API et affiche ce qui s'est passé. loadAnywayAsked : l'admin confirme le
    // chargement d'un tracé qui suit le chemin d'une rando déjà en base (issue #271) ; l'API ne l'accepte que d'un admin.
    async function sendFile(loadAnywayAsked) {
      msg.style.display = 'none';
      hideLoadAnyway();
      if (!selectedFile) { showMsg('Ajoute d\'abord ton fichier .gpx.', false); return; }

      if (!window.RVG.isLoggedIn()) { window.location.href = window.APP_URLS.contributorLogin; return; }
      var formData = new FormData();
      formData.append('file', selectedFile);
      if (loadAnywayAsked) formData.append('load_anyway', 'true');

      submit.disabled = true;
      var original = submit.innerHTML;
      submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Envoi…';
      try {
        var res = await window.RVG.apiFetch('/api/etl/upload_gpx', {
          method: 'POST',
          body: formData
        });
        if (res.status === 401) { window.location.href = window.APP_URLS.contributorLogin; return; }
        var ct = res.headers.get('content-type') || '';
        var data = ct.includes('application/json') ? await res.json() : { message: await res.text() };
        if (res.ok && (data.success === undefined || data.success)) {
          var city = data.city ? ' Ville détectée : ' + data.city + '.' : '';
          showMsg((data.message || 'Tracé envoyé en relecture.') + city, true);
        } else {
          showMsg(data.message || ('Erreur lors de l\'envoi (' + res.status + ').'), false);
          // L'API dit si la personne (un admin) peut charger quand même ce tracé qui suit une rando en base.
          if (data.can_load_anyway && loadAnyway) loadAnyway.style.display = 'inline-flex';
        }
      } catch (err) {
        showMsg('Impossible de joindre le serveur. Réessaie plus tard.', false);
      } finally {
        submit.disabled = false;
        submit.innerHTML = original;
      }
    }

    if (submit) {
      submit.addEventListener('click', function () { sendFile(false); });
    }
    if (loadAnyway) {
      loadAnyway.addEventListener('click', function () { sendFile(true); });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initLogin();
    initDashboardGreeting();
    initDashboardGuard();
    initAddHike();
  });
})();

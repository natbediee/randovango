/* Front v2 - espace contributeur (connexion + garde du dashboard).
   Login branché sur le vrai endpoint FastAPI POST /api/auth/login (JWT).
   NB: l'API attend `username` ; on envoie la saisie telle quelle (le passage à
   l'email se fera côté backend plus tard). Le token est stocké de façon unifiée
   pour lever l'incohérence historique localStorage.userToken / sessionStorage.jwtToken. */
(function () {
  'use strict';

  function storeSession(token, user) {
    // Deux emplacements, pour rester compatible avec l'existant :
    // - sessionStorage (utilisé par le widget legacy / durée)
    // - localStorage (lu par step1_city.js : userToken / userId)
    sessionStorage.setItem('jwtToken', token);
    sessionStorage.setItem('username', user.username);
    localStorage.setItem('userToken', token);
    localStorage.setItem('userId', user.id);
    localStorage.setItem('username', user.username);
  }

  window.RVG = window.RVG || {};
  window.RVG.getContribToken = function () {
    return sessionStorage.getItem('jwtToken') || localStorage.getItem('userToken');
  };
  window.RVG.logoutContrib = function () {
    ['jwtToken', 'username'].forEach(function (k) { sessionStorage.removeItem(k); });
    ['userToken', 'userId', 'username'].forEach(function (k) { localStorage.removeItem(k); });
  };

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
        var res = await fetch(window.API_BASE + '/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: username, password: password })
        });
        var data = await res.json();
        if (res.ok && data.success) {
          storeSession(data.token, data.user);
          window.location.href = window.APP_URLS.contributor;
        } else {
          errorBox.textContent = data.message || 'Identifiant ou mot de passe incorrect.';
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

  // ===== Entête contributeur (avatar + déconnexion), commun aux pages contrib =====
  function initContribHeader() {
    var name = sessionStorage.getItem('username') || localStorage.getItem('username') || 'contributeur';
    var nameEl = document.getElementById('contribName');
    if (nameEl) nameEl.textContent = name;
    var initialsEl = document.getElementById('contribInitials');
    if (initialsEl) initialsEl.textContent = name.slice(0, 2).toUpperCase();
    var logout = document.getElementById('contribLogout');
    if (logout) {
      logout.addEventListener('click', function (e) {
        e.preventDefault();
        window.RVG.logoutContrib();
        window.location.href = window.APP_URLS.duration;
      });
    }
  }

  // ===== Garde du dashboard : redirige vers la connexion si non authentifié =====
  function initDashboardGuard() {
    var el = document.querySelector('[data-contrib-dashboard]');
    if (!el) return;
    if (!window.RVG.getContribToken()) {
      window.location.href = window.APP_URLS.contributorLogin;
      return;
    }
  }

  // ===== Tags cliquables (équipements, difficulté, type…) =====
  function initPickTags() {
    // .equip-tag isolés ou groupés dans .pick-tags (data-single = un seul actif)
    document.querySelectorAll('.pick-tags').forEach(function (group) {
      var single = group.hasAttribute('data-single');
      group.querySelectorAll('.equip-tag').forEach(function (tag) {
        tag.addEventListener('click', function () {
          if (single) {
            group.querySelectorAll('.equip-tag').forEach(function (t) { t.classList.remove('is-on'); });
            tag.classList.add('is-on');
          } else {
            tag.classList.toggle('is-on');
          }
        });
      });
    });
  }

  // ===== Page ajout de randonnée : upload GPX réel (/api/etl/upload_gpx) =====
  function initAddHike() {
    var root = document.querySelector('[data-add-hike]');
    if (!root) return;

    // Garde : réservé aux contributeurs connectés.
    if (!window.RVG.getContribToken()) {
      window.location.href = window.APP_URLS.contributorLogin;
      return;
    }

    var dropzone = document.getElementById('gpxDropzone');
    var input = document.getElementById('gpxFileInput');
    var label = document.getElementById('gpxDropLabel');
    var msg = document.getElementById('gpxMsg');
    var submit = document.getElementById('submitHike');
    var draft = document.getElementById('saveDraft');
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
        }
      });
      input.addEventListener('change', function () {
        if (input.files && input.files[0]) {
          selectedFile = input.files[0];
          label.textContent = selectedFile.name;
        }
      });
    }

    if (submit) {
      submit.addEventListener('click', async function () {
        msg.style.display = 'none';
        if (!selectedFile) { showMsg('Ajoute d\'abord ton fichier .gpx.', false); return; }

        var token = window.RVG.getContribToken();
        var formData = new FormData();
        formData.append('file', selectedFile);

        submit.disabled = true;
        var original = submit.innerHTML;
        submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Envoi…';
        try {
          var res = await fetch(window.API_BASE + '/api/etl/upload_gpx', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
          });
          var ct = res.headers.get('content-type') || '';
          var data = ct.includes('application/json') ? await res.json() : { message: await res.text() };
          if (res.ok && (data.success === undefined || data.success)) {
            var city = data.city ? ' Ville détectée : ' + data.city + '.' : '';
            showMsg((data.message || 'Tracé envoyé en relecture.') + city, true);
          } else {
            showMsg(data.message || ('Erreur lors de l\'envoi (' + res.status + ').'), false);
          }
        } catch (err) {
          showMsg('Impossible de joindre le serveur. Réessaie plus tard.', false);
        } finally {
          submit.disabled = false;
          submit.innerHTML = original;
        }
      });
    }

    if (draft) {
      draft.addEventListener('click', function () { showMsg('Brouillon enregistré (démo).', true); });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initLogin();
    initContribHeader();
    initDashboardGuard();
    initPickTags();
    initAddHike();
  });
})();

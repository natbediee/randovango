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

  // ===== Codes Vany du dashboard (démo : liste rendue par le template) =====
  function initVanyCodes() {
    document.querySelectorAll('.code-copy').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var code = btn.getAttribute('data-code');
        var original = btn.textContent;
        function done(ok) {
          btn.textContent = ok ? 'Copié !' : 'Échec';
          setTimeout(function () { btn.textContent = original; }, 1600);
        }
        // navigator.clipboard n'existe qu'en contexte sécurisé (https ou localhost)
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(function () { done(true); }, function () { done(false); });
        } else {
          done(false);
        }
      });
    });

    // Démo : le code disponible est appliqué directement, comme le fera le backend
    // au moment de composer le voyage (cf. unlock.js pour le parcours payant).
    var useBtn = document.getElementById('useVanyCode');
    if (useBtn) {
      useBtn.addEventListener('click', function () {
        if (window.RVG && window.RVG.unlockVany) window.RVG.unlockVany();
        else localStorage.setItem('vanyUnlocked', '1');
        window.location.href = window.APP_URLS.chat;
      });
    }
  }

  // ===== Page ajout de spot (démo : aucun endpoint spot n'existe encore) =====
  function initAddSpot() {
    var root = document.querySelector('[data-add-spot]');
    if (!root) return;

    // Garde : réservé aux contributeurs connectés.
    if (!window.RVG.isLoggedIn()) {
      window.location.href = window.APP_URLS.contributorLogin;
      return;
    }

    var msg = document.getElementById('spotMsg');
    function showMsg(text, ok) {
      msg.textContent = text;
      msg.className = 'addspot-msg ' + (ok ? 'is-ok' : 'is-error');
      msg.style.display = 'block';
    }

    var submit = document.getElementById('submitSpot');
    if (submit) {
      submit.addEventListener('click', function () {
        var name = document.getElementById('spotName').value.trim();
        var city = document.getElementById('spotCity').value.trim();
        if (!name || !city) { showMsg('Renseigne au moins le nom du spot et la commune.', false); return; }
        showMsg('Merci ! Ton spot part en relecture (démo).', true);
      });
    }

    var draft = document.getElementById('saveSpotDraft');
    if (draft) {
      draft.addEventListener('click', function () { showMsg('Brouillon enregistré (démo).', true); });
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

        if (!window.RVG.isLoggedIn()) { window.location.href = window.APP_URLS.contributorLogin; return; }
        var formData = new FormData();
        formData.append('file', selectedFile);

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
    initDashboardGreeting();
    initDashboardGuard();
    initPickTags();
    initVanyCodes();
    initAddSpot();
    initAddHike();
  });
})();

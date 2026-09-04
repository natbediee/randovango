/* Front v2 - Accès à Vany (déblocage du chat).
   Démo front-only : le paiement et la validation du code sont factices ; on pose le flag
   localStorage.vanyUnlocked puis on redirige vers le chat. Le vrai paiement (prestataire)
   et la vérification serveur du code contributeur viendront plus tard. */
(function () {
  'use strict';
  var root = document.querySelector('[data-unlock]');
  if (!root) return;

  function unlockAndGo() {
    if (window.RVG && window.RVG.unlockVany) window.RVG.unlockVany();
    else localStorage.setItem('vanyUnlocked', '1');
    window.location.href = window.APP_URLS.chat;
  }

  var payBtn = document.getElementById('payBtn');
  if (payBtn) {
    payBtn.addEventListener('click', function () {
      payBtn.disabled = true;
      payBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Paiement…';
      setTimeout(unlockAndGo, 900); // simulation du prestataire de paiement
    });
  }

  var codeBtn = document.getElementById('codeBtn');
  var codeInput = document.getElementById('codeInput');
  var codeMsg = document.getElementById('codeMsg');
  if (codeBtn && codeInput) {
    codeBtn.addEventListener('click', function () {
      var code = codeInput.value.trim();
      // Démo : tout code au format VANY-XXX est accepté.
      if (/^VANY-.+/i.test(code)) {
        unlockAndGo();
      } else {
        codeMsg.textContent = 'Code invalide. Format attendu : VANY-XXXX-XXXX.';
        codeMsg.style.display = 'block';
      }
    });
  }
})();

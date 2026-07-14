/* Front v2 — Chat « Voyage 100% IA » avec Vany.
   Démo scriptée front-only (aucun appel LLM) : bulles, indicateur de saisie,
   quick-replies, carte de proposition jour par jour. Le vrai service IA viendra plus tard.
   Accès conditionné au déverrouillage (paiement / code) : sinon redirection vers /unlock-vany. */
(function () {
  'use strict';
  var root = document.querySelector('[data-chat]');
  if (!root) return;

  // Garde : le chat est la fonctionnalité payante.
  if (!(window.RVG && window.RVG.isVanyUnlocked && window.RVG.isVanyUnlocked())) {
    window.location.href = window.APP_URLS.unlockVany;
    return;
  }

  var thread = document.getElementById('chatThread');
  var quick = document.getElementById('chatQuick');
  var form = document.getElementById('chatForm');
  var input = document.getElementById('chatInput');
  var AVATAR = document.querySelector('.chat-badge img').src;

  var day = 0;

  function scrollDown() { thread.scrollTop = thread.scrollHeight; }

  function addUser(text) {
    var el = document.createElement('div');
    el.className = 'bubble bubble--user';
    el.textContent = text;
    thread.appendChild(el);
    scrollDown();
  }

  function addVany(html) {
    var row = document.createElement('div');
    row.className = 'chat-row';
    row.innerHTML = '<img class="chat-avatar" src="' + AVATAR + '" alt="Vany">' +
                    '<div class="bubble bubble--vany">' + html + '</div>';
    thread.appendChild(row);
    scrollDown();
  }

  function addProposalCard(n) {
    var row = document.createElement('div');
    row.className = 'chat-row';
    row.innerHTML =
      '<img class="chat-avatar" src="' + AVATAR + '" alt="Vany">' +
      '<div class="chat-proposal-wrap">' +
        '<div class="bubble bubble--vany">Voici ma proposition pour le jour ' + n + ' — chaque élément se change d\'un mot.</div>' +
        '<div class="proposal">' +
          '<div class="proposal__head"><span class="proposal__title">Jour ' + n + ' — Saint-Jean-Trolimon</span>' +
          '<span class="tag tag--verified">Proposition de Vany</span></div>' +
          '<div class="proposal__body">' +
            '<div class="proposal__line"><span class="proposal__k">Randonnée</span><span><strong>Circuit de Tréminou</strong> <span class="muted">· 14 km · moyen · 4h</span></span></div>' +
            '<div class="proposal__line"><span class="proposal__k">Spot nuit</span><span>Allée de Brémillec, Plomeur <span class="muted">· gratuit · calme · ★ 3,75</span></span></div>' +
            '<div class="proposal__line"><span class="proposal__k">Services</span><span class="muted">Carrefour Market · Bistrot de la Torche · toilettes publiques</span></div>' +
          '</div>' +
          '<div class="proposal__actions">' +
            '<button class="btn btn--primary btn--sm" data-validate>Valider le jour ' + n + '</button>' +
            '<button class="btn btn--outline btn--sm" data-change>Changer la rando</button>' +
            '<button class="btn btn--outline btn--sm" data-change>Changer le spot</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    thread.appendChild(row);
    scrollDown();
    row.querySelectorAll('[data-validate]').forEach(function (b) {
      b.addEventListener('click', function () { validateDay(n); });
    });
    row.querySelectorAll('[data-change]').forEach(function (b) {
      b.addEventListener('click', function () {
        addUser(b.textContent);
        vanyThink(function () { addVany('Bonne idée, je te réajuste ça tout de suite 👇'); setTimeout(function () { addProposalCard(n); }, 400); });
      });
    });
  }

  function setQuick(options) {
    quick.innerHTML = '';
    options.forEach(function (opt) {
      var b = document.createElement('button');
      b.className = 'quick-reply';
      b.textContent = opt;
      b.addEventListener('click', function () { handleUser(opt); });
      quick.appendChild(b);
    });
  }

  // Indicateur de saisie (3 points) puis exécute cb.
  function vanyThink(cb, label) {
    var row = document.createElement('div');
    row.className = 'chat-row chat-typing';
    row.innerHTML = '<img class="chat-avatar" src="' + AVATAR + '" alt="Vany">' +
      '<div class="bubble bubble--vany typing"><span class="dots"><i></i><i></i><i></i></span>' +
      '<span class="muted" style="font-size:13px;">' + (label || 'Vany réfléchit…') + '</span></div>';
    thread.appendChild(row);
    scrollDown();
    setTimeout(function () { row.remove(); cb(); }, 1200);
  }

  function validateDay(n) {
    addUser('Valide, passe au jour ' + (n + 1));
    if (n >= 2) {
      vanyThink(function () {
        addVany('Ton week-end est complet ! 🎉 Tu peux le retrouver dans ton carnet de voyage.');
        setQuick([]);
      }, 'Vany finalise ton carnet…');
      return;
    }
    vanyThink(function () {
      addVany('Super. Voici le jour ' + (n + 1) + ' dans le même esprit.');
      setTimeout(function () { addProposalCard(n + 1); day = n + 1; setQuick(['Plutôt une rando facile', 'Un spot avec vue mer', 'Valide, passe au jour ' + (n + 2)]); }, 400);
    }, 'Vany prépare le jour ' + (n + 1) + '…');
  }

  // Aiguillage d'un message utilisateur (saisie libre ou quick-reply).
  function handleUser(text) {
    addUser(text);
    setQuick([]);
    if (/valide/i.test(text)) { validateDay(day || 1); return; }
    if (day === 0) {
      vanyThink(function () {
        addVany('Parfait pour le Pays Bigouden. Voici ma proposition pour le jour 1 — chaque élément se change d\'un mot.');
        setTimeout(function () { addProposalCard(1); day = 1; setQuick(['Plutôt une rando facile', 'Un spot avec vue mer', 'Valide, passe au jour 2']); }, 400);
      }, 'Vany compose ton voyage…');
    } else {
      vanyThink(function () {
        addVany('C\'est noté, je réajuste la proposition en conséquence 👇');
        setTimeout(function () { addProposalCard(day); }, 400);
      });
    }
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    handleUser(text);
  });

  // Amorce de la conversation
  addVany('Salut ! Dis-moi où tu veux partir, combien de temps, et ce que tu aimes — je compose ton voyage, tu valides chaque étape.');
  setQuick(['Un week-end dans le Finistère sud, 2 jours', 'Une semaine sur la côte atlantique', 'Surprends-moi !']);
})();

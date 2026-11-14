// Supervision (admin) : ce que les quatre pages (Spots, Services, Modifier, Bilan) font de la même façon.
// Chargé avant le script de chaque page. Avant ce fichier, chaque page avait sa copie de ces fonctions,
// avec des messages d'erreur un peu différents d'une page à l'autre (carte #186).
// La sécurité est côté API : ces pages ne font que renvoyer à la connexion quand l'API refuse.

// Le bandeau de message en haut de la page : une erreur, ou rien (texte vide = bandeau caché).
function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

// Sans connexion, la page n'a rien à montrer : on envoie vers la page de connexion. Rend true dans ce cas.
function redirectIfLoggedOut() {
    if (window.RVG.isLoggedIn()) return false;
    window.location.href = window.APP_URLS.contributorLogin;
    return true;
}

// Le message d'un refus de l'API (404, 422) : le texte du serveur quand il en donne un, sinon un message général.
async function refusalMessage(response) {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : 'Demande refusée.';
}

// Un appel à l'API de la supervision (path commence après /api/supervision). Rend la réponse lue en JSON,
// ou lève une erreur dont le message est prêt à afficher avec showMessage.
// Session expirée : ce qui est à l'écran reste, rien n'est perdu ; on se reconnecte et on recommence.
async function supervisionCall(path, options = {}) {
    const response = await window.RVG.apiFetch(`/api/supervision${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json' },
    });
    if (response.status === 401) throw new Error('Ta session a expiré : reconnecte-toi, rien n\'a été enregistré.');
    if (response.status === 403) throw new Error('Cette page est réservée aux comptes admin.');
    // 404 : le lieu ou la décision n'existe plus ; 422 : demande refusée (par exemple une décision déjà annulée).
    if (response.status === 404 || response.status === 422) throw new Error(await refusalMessage(response));
    if (!response.ok) throw new Error(`Erreur du serveur (HTTP ${response.status}) : rien n'a été enregistré.`);
    return response.json();
}

// Un lien venu de la base, sûr à mettre dans un href : http ou https seulement (jamais « javascript: »), échappé.
// Rend null pour un lien absent ou douteux : la page n'affiche alors pas de lien.
function safeLink(url) {
    return /^https?:\/\//.test(url || '') ? escapeHtml(url) : null;
}

// La ville choisie dans la recherche de ville (supervision_ville.js) : l'identifiant d'une ville de l'étape 1,
// ou une commune d'adresse. Les pages Services et Modifier ont les mêmes deux champs cachés ; load() est celle
// de la page.
function chooseCity({ ville, commune }) {
    document.getElementById('filterCity').value = ville;
    document.getElementById('filterTown').value = commune;
    load();
}

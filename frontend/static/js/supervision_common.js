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

// La ville venue d'un lien du Bilan (?ville=…&lieu=…, ou ?commune=…&lieu=…) : elle remplit les champs de la recherche
// de ville avant le premier chargement, pour que la page s'ouvre déjà filtrée. lieu est le nom affiché dans le champ.
function placeFromUrl() {
    const params = new URLSearchParams(window.location.search);
    document.getElementById('filterCity').value = params.get('ville') || '';
    document.getElementById('filterTown').value = params.get('commune') || '';
    document.getElementById('filterCitySearch').value = params.get('lieu') || '';
}

// La partie d'un lien qui garde la ville choisie (placeFromUrl la relit) : ville est ce que la page visée attend
// (l'identifiant pour Spots, le nom pour Services). Rien de choisi : rien à ajouter.
function placeParams(place, ville) {
    if (!place) return '';
    const params = place.commune ? { commune: place.commune, lieu: place.commune } : { ville, lieu: place.name };
    return new URLSearchParams(params).toString();
}

// Un geste de décision (décider, annuler, corriger un texte, dire juste une décision de la règle), puis la page se
// redessine par refresh(), que chaque page définit. La route répond par la décision, pas par la page (plan de #186, 2.1).
// Si le geste passe mais pas le rechargement, on le dit : le geste est bien enregistré.
// Rend true quand le geste est enregistré, false quand il est refusé (le message est alors affiché).
async function decisionGesture(path, options) {
    showMessage('');
    try {
        await supervisionCall(path, options);
    } catch (error) {
        showMessage(error.message);
        return false;
    }
    try {
        await refresh();
    } catch (error) {
        showMessage('C\'est enregistré, mais la liste n\'a pas pu être rechargée : recharge la page.');
    }
    return true;
}

// Une nouvelle décision, sur un spot, ses dates d'ouverture ou un service : body.objet dit sur quoi (POST /decisions).
function postDecision(body) {
    return decisionGesture('/decisions', { method: 'POST', body: JSON.stringify(body) });
}

// Annule une décision, quelle qu'elle soit (spot, ouverture, service) : une seule route, DELETE /decisions/{id},
// qui lit elle-même ce que vise la décision.
function cancelDecision(decisionId) {
    return decisionGesture(`/decisions/${decisionId}`, { method: 'DELETE' });
}

// Corrige le texte « À savoir » d'une décision sur un spot, sans refaire la décision (PUT /decisions/{id}).
function saveTextCorrection(decisionId, text) {
    return decisionGesture(`/decisions/${decisionId}`, { method: 'PUT', body: JSON.stringify({ a_savoir: text }) });
}

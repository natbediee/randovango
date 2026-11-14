// Supervision (admin) : noter la proposition de l'agent à côté de la décision (carte #201).
// Une ligne sous chaque carte : « La proposition de l'agent : juste · à corriger · fausse », puis la raison d'une
// erreur, proposée seulement pour « à corriger » ou « fausse ». C'est facultatif : sans note, la décision vaut comme avant.
// Les notes forment le jeu d'évaluation des agents (#114). Utilisé par supervision.js (spots) et
// supervision_services.js (services) ; les valeurs permises viennent du serveur (services/decision_rating.py).

// Les libellés reçus de l'API (data.notation) : { pertinences: {valeur: libellé}, raisons: {...}, avec_raison: [...] }.
let ratingLabels = null;
// La note en cours de chaque carte, par clé de carte. Gardée hors de la page : une carte redessinée (cocher un lieu
// dans « Doublons ») ne perd pas sa note.
const ratings = {};

// Retient les libellés de la dernière réponse de l'API.
function setRatingLabels(notation) {
    if (notation) ratingLabels = notation;
}

// La ligne de notation d'une carte. Vide tant que les libellés ne sont pas arrivés.
function ratingHtml(key) {
    if (!ratingLabels) return '';
    const rating = ratings[key] || {};
    const chips = Object.entries(ratingLabels.pertinences).map(([value, label]) => `
        <button type="button" class="rating-chip${rating.pertinence === value ? ' is-on' : ''}" aria-pressed="${rating.pertinence === value}"
                onclick="chooseRating('${key}', '${value}')">${escapeHtml(label)}</button>`).join('');
    // La raison n'a de sens que si l'agent s'est trompé.
    const reason = ratingLabels.avec_raison.includes(rating.pertinence) ? `
        <label class="rating__reason">Raison
            <select onchange="chooseReason('${key}', this.value)">
                <option value="">—</option>
                ${Object.entries(ratingLabels.raisons).map(([value, label]) =>
                    `<option value="${value}" ${rating.raison === value ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}
            </select>
        </label>` : '';
    return `
        <div class="rating" id="rating-${key}">
            <span>La proposition de l'agent (facultatif) :</span>
            ${chips}
            ${reason}
        </div>`;
}

// Redessine la seule ligne de notation : le reste de la carte (fiche en cours de correction) ne bouge pas.
function redrawRating(key) {
    const line = document.getElementById(`rating-${key}`);
    if (line) line.outerHTML = ratingHtml(key);
}

// Un clic sur une pastille la choisit ; un second clic sur la même retire la note. Changer de pastille efface la
// raison si la nouvelle pertinence n'en demande pas (« juste »).
function chooseRating(key, value) {
    const rating = ratings[key] || {};
    const pertinence = rating.pertinence === value ? null : value;
    const raison = ratingLabels.avec_raison.includes(pertinence) ? rating.raison : null;
    ratings[key] = { pertinence, raison };
    redrawRating(key);
}

// Le choix de la raison dans la liste ; « — » la retire.
function chooseReason(key, value) {
    ratings[key] = { ...(ratings[key] || {}), raison: value || null };
}

// Ce que la décision envoie à l'API : { pertinence, raison }, null pour ce qui n'est pas noté.
function ratingOf(key) {
    const rating = ratings[key] || {};
    return { pertinence: rating.pertinence || null, raison: rating.raison || null };
}

// Une fois la décision enregistrée, sa note est oubliée : si la décision est annulée, la carte revient sans note.
function forgetRating(key) {
    delete ratings[key];
}

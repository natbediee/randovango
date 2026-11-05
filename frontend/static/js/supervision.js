// Supervision (admin) : la file de relecture. L'agent propose de retirer un spot, avec ses
// preuves ; l'admin tranche (services/supervision_service.py). La sécurité est côté API :
// cette page ne fait que renvoyer à la connexion quand l'API refuse.

function authToken() {
    return sessionStorage.getItem('jwtToken') || localStorage.getItem('userToken');
}

function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

// Session expirée : la fiche reste à l'écran, rien n'est perdu ; on se reconnecte et on recommence.
async function supervisionFetch(path, options = {}) {
    const response = await fetch(`${window.API_BASE}/api/supervision${path}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken()}` },
    });
    if (response.status === 401) throw new Error('Ta session a expiré : reconnecte-toi, ta décision n\'a pas été enregistrée.');
    if (response.status === 403) throw new Error('Cette page est réservée aux comptes admin.');
    if (!response.ok) throw new Error(`Erreur du serveur (HTTP ${response.status}) : décision non enregistrée.`);
    return response.json();
}

function reviewCard(review) {
    const reopening = review.reouverture ? `<p><strong>Réouverture annoncée :</strong> ${escapeHtml(review.reouverture)}</p>` : '';
    const comments = review.commentaires.map(c =>
        `<li><strong>${escapeHtml(c.date)}</strong> : ${escapeHtml(c.texte)}</li>`).join('');
    const links = [
        review.url ? `<a href="${escapeHtml(review.url)}" target="_blank" rel="noopener">Voir plus de détails</a>` : '',
        ...review.sources.map((url, i) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">Source ${i + 1}</a>`),
    ].filter(Boolean).join('');
    return `
        <article class="review-card" data-spot="${review.objet_id}">
            <div class="review-card__body">
                <div class="spot-tags">
                    <span class="spot-type">Spot n° ${review.objet_id}</span>
                    <span class="status-badge review-card__remove">Proposé : retirer</span>
                </div>
                <h2>${escapeHtml(review.nom)}</h2>
                <p><strong>Pourquoi :</strong> ${escapeHtml(review.raison)}</p>
                ${reopening}
                ${comments ? `<div class="review-card__proofs"><span>Derniers commentaires en base</span><ul>${comments}</ul></div>` : ''}
                <div class="review-card__links">${links}</div>
                <label class="label review-card__text">« À savoir » affiché si le spot est gardé (une phrase par ligne)
                    <textarea class="review-card__a-savoir" rows="3" data-agent="${escapeHtml(review.a_savoir)}">${escapeHtml(review.a_savoir)}</textarea>
                </label>
            </div>
            <div class="review-card__actions">
                <button class="btn review-card__btn-remove" onclick="decide(${review.objet_id}, 'retirer')">Retirer</button>
                <button class="btn btn--outline" onclick="decide(${review.objet_id}, 'garder')">Garder</button>
                <label class="label">Note (facultative)
                    <input type="text" class="review-card__note" maxlength="255" placeholder="Vu sur Street View">
                </label>
            </div>
        </article>`;
}

// Une date que la fiche ne donne pas est signalée comme convention ; un texte changé attend une relecture.
function openingLine(opening) {
    const reading = opening.statut === 'periode' ? `ouvert du ${opening.debut} au ${opening.fin}`
        : opening.statut === 'saison' ? 'ouvert du 01/04 au 31/10'
        : opening.statut === 'toute_annee' ? 'ouvert toute l\'année' : 'jamais masqué selon la saison';
    const changed = opening.texte_change
        ? `<br><strong>À relire : le texte de la fiche a changé</strong> (« ${escapeHtml(opening.texte_decide)} » devenu « ${escapeHtml(opening.texte)} »)`
        : '';
    const name = opening.url
        ? `<a href="${escapeHtml(opening.url)}" target="_blank" rel="noopener">${escapeHtml(opening.nom)}</a>`
        : escapeHtml(opening.nom);
    return `
        <p>${name} (n° ${opening.objet_id}) : <strong>${reading}</strong>
           ${opening.convention ? '· dates par convention' : ''}
           ${opening.texte ? `· fiche : « ${escapeHtml(opening.texte)} »` : ''}
           ${opening.note ? `· « ${escapeHtml(opening.note)} »` : ''} · ${escapeHtml(opening.par)}, le ${escapeHtml(opening.le)}
           · <a href="#" onclick="cancelOpening(${opening.id}); return false;">annuler</a>${changed}</p>`;
}

function render(data) {
    const count = data.reviews.length;
    document.getElementById('reviewsCount').textContent =
        count === 0 ? 'Rien à relire' : `${count} décision${count > 1 ? 's' : ''} en attente`;
    document.getElementById('reviewsList').innerHTML = data.reviews.map(reviewCard).join('');

    document.getElementById('recentSection').style.display = data.recent.length ? '' : 'none';
    document.getElementById('recentList').innerHTML = data.recent.map(d => `
        <p>${escapeHtml(d.nom)} : <strong>${d.decision === 'garder' ? 'gardé' : 'retiré'}</strong>
           ${d.note ? `· « ${escapeHtml(d.note)} »` : ''} · ${escapeHtml(d.par)}, le ${escapeHtml(d.le)}
           · <a href="#" onclick="cancelDecision(${d.id}); return false;">annuler</a></p>
        ${d.decision === 'garder' ? `
        <details class="supervision-recent__edit">
            <summary>Corriger le texte « À savoir »</summary>
            <textarea id="correct-${d.id}" rows="3">${escapeHtml(d.a_savoir)}</textarea>
            <button class="btn btn--outline btn--sm" onclick="correctText(${d.id})">Enregistrer</button>
        </details>` : ''}`).join('');

    document.getElementById('openingsSection').style.display = data.ouvertures.length ? '' : 'none';
    document.getElementById('openingsList').innerHTML = data.ouvertures.map(openingLine).join('');
}

async function decide(spotId, decision) {
    const card = document.querySelector(`[data-spot="${spotId}"]`);
    const note = card.querySelector('.review-card__note').value;
    const text = card.querySelector('.review-card__a-savoir');
    // Texte inchangé : rien à enregistrer, celui de l'agent reste.
    const aSavoir = text.value !== text.dataset.agent ? text.value : null;
    try {
        showMessage('');
        render(await supervisionFetch('/decisions', {
            method: 'POST', body: JSON.stringify({ objet_id: spotId, decision, note, a_savoir: aSavoir }),
        }));
    } catch (error) {
        showMessage(error.message);
    }
}

async function correctText(decisionId) {
    const text = document.getElementById(`correct-${decisionId}`).value;
    try {
        showMessage('');
        render(await supervisionFetch(`/decisions/${decisionId}`, {
            method: 'PUT', body: JSON.stringify({ a_savoir: text }),
        }));
    } catch (error) {
        showMessage(error.message);
    }
}

async function cancelDecision(decisionId) {
    try {
        showMessage('');
        render(await supervisionFetch(`/decisions/${decisionId}`, { method: 'DELETE' }));
    } catch (error) {
        showMessage(error.message);
    }
}

async function cancelOpening(decisionId) {
    try {
        showMessage('');
        render(await supervisionFetch(`/openings/${decisionId}`, { method: 'DELETE' }));
    } catch (error) {
        showMessage(error.message);
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken()) {
        window.location.href = window.APP_URLS.contributorLogin;
        return;
    }
    try {
        render(await supervisionFetch('/reviews'));
    } catch (error) {
        showMessage(error.message);
    }
});

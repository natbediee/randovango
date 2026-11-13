// Supervision (admin) : le bilan. Combien il reste à trancher, file par file, avec un lien
// vers chaque file. Les chiffres viennent de services/supervision_summary_service.py, qui
// compte avec les mêmes règles que les pages Spots et Services.

const CITIES_SHOWN = 12;

function showMessage(text) {
    const box = document.getElementById('supervisionMsg');
    box.textContent = text;
    box.style.display = text ? '' : 'none';
}

async function summaryFetch() {
    const response = await window.RVG.apiFetch('/api/supervision/bilan');
    if (response.status === 401) throw new Error('Ta session a expiré : reconnecte-toi.');
    if (response.status === 403) throw new Error('Cette page est réservée aux comptes admin.');
    if (!response.ok) throw new Error(`Erreur du serveur (HTTP ${response.status}) : bilan indisponible.`);
    return response.json();
}

function plural(count, word) {
    return `${count} ${word}${count > 1 ? 's' : ''}`;
}

function totalCard(value, label, href) {
    const inner = `<strong>${value}</strong><span>${escapeHtml(label)}</span>`;
    return href ? `<a class="bilan-total" href="${href}">${inner}</a>` : `<div class="bilan-total">${inner}</div>`;
}

// Une ligne : libellé, barre proportionnelle au plus gros chiffre du bloc, nombre, lien éventuel.
function rows(items, href) {
    const max = Math.max(1, ...items.map(item => item.n));
    return items.map(item => {
        const label = escapeHtml(item.label);
        const link = href && href(item);
        return `
        <div class="bilan-row ${item.n === 0 ? 'is-empty' : ''}">
            <span class="bilan-row__label">${link ? `<a href="${link}">${label}</a>` : label}</span>
            <span class="bilan-row__bar"><span style="width:${(item.n / max) * 100}%"></span></span>
            <span class="bilan-row__n">${item.n}</span>
        </div>`;
    }).join('');
}

function showBlock(id, rowsId, html) {
    document.getElementById(rowsId).innerHTML = html;
    document.getElementById(id).style.display = html ? '' : 'none';
}

function render(data) {
    const urls = window.APP_URLS;
    document.getElementById('reviewsCount').textContent =
        data.total === 0 ? 'Rien à trancher' : `${plural(data.total, 'décision')} en attente au total`;

    document.getElementById('bilanTotals').innerHTML = [
        totalCard(data.total, 'à trancher en tout'),
        totalCard(data.spots.a_relire, 'spots à relire', urls.supervision),
        totalCard(data.services.a_relire, 'services à relire', urls.supervisionServices),
        totalCard(data.decisions, 'décisions déjà prises'),
    ].join('');

    const spots = data.spots;
    showBlock('spotsBlock', 'spotsRows', rows([
        { label: 'Retraits proposés par l\'agent, à relire', n: spots.a_relire, href: urls.supervision },
        { label: 'Gardés par l\'administrateur', n: spots.gardes },
        { label: 'Retirés par l\'administrateur', n: spots.retires },
        { label: 'Ouvertures tranchées par l\'administrateur', n: spots.ouvertures },
    ], item => item.href));

    showBlock('servicesBlock', 'servicesRows',
        rows(data.services.files, file => `${urls.supervisionServices}?tab=${encodeURIComponent(file.tab)}`));
    // Les villes les plus chargées d'abord ; les autres restent repliées.
    const cities = data.par_ville;
    const others = cities.slice(CITIES_SHOWN);
    showBlock('citiesBlock', 'citiesRows', rows(cities.slice(0, CITIES_SHOWN)) + (others.length ? `
        <details class="bilan-more">
            <summary>${others.length > 1 ? `Voir les ${others.length} autres villes` : 'Voir l\'autre ville'}</summary>
            ${rows(others)}
        </details>` : ''));
    showBlock('typesBlock', 'typesRows', rows(data.services.par_type));
}

document.addEventListener('DOMContentLoaded', async () => {
    if (!window.RVG.isLoggedIn()) {
        window.location.href = window.APP_URLS.contributorLogin;
        return;
    }
    try {
        render(await summaryFetch());
    } catch (error) {
        showMessage(error.message);
    }
});

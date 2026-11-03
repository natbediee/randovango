// Rappel de Vany dans la barre du bas, la seule affichée en permanence : le voyageur peut
// quitter l'étape 5 sans attendre l'agenda ; quand des idées arrivent, on le lui dit ici,
// quelle que soit la page (services/pepite_service.py, day_news).

const VANY_NEWS_POLL_MS = 15000;

// Le contexte du jour en cours de préparation, mis de côté pendant la visite d'un autre
// jour à l'étape 5. Revenir au carnet ne suffirait pas : pour lui, le jour courant est
// terminé, et il proposerait le suivant alors que celui-ci n'a ni rando ni spot.
const VANY_NEWS_RETURN_KEY = 'vanyNewsReturn';
const DAY_CONTEXT_KEYS = ['currentDay', 'selectedCityId', 'selectedHiking', 'selectedSpot',
                          'editingDay', 'editReturnDay', 'editOriginalCity'];

function vanyNewsReturn() {
    try {
        return JSON.parse(localStorage.getItem(VANY_NEWS_RETURN_KEY));
    } catch {
        return null;
    }
}

// Remet le jour en cours de préparation et renvoie la page d'où le voyageur est parti.
function restoreDayInProgress() {
    const saved = vanyNewsReturn();
    if (!saved) return null;
    DAY_CONTEXT_KEYS.forEach(key => {
        if (saved.context[key] === null) localStorage.removeItem(key);
        else localStorage.setItem(key, saved.context[key]);
    });
    localStorage.removeItem(VANY_NEWS_RETURN_KEY);
    return saved.url;
}

// Sortie de l'étape 5 après la visite d'un autre jour : retour là où en était le voyageur.
function leaveVanyNews() {
    const url = restoreDayInProgress();
    if (url) window.location.href = url;
    return Boolean(url);
}

// Ouvre l'étape 5 du jour concerné. Si ce n'est pas le jour en cours, on met son contexte
// de côté (sauf s'il l'est déjà : le voyageur passe d'un rappel à l'autre), puis on
// réutilise la mécanique de modification d'un jour (editDay dans results.js).
function openVanyNews(news) {
    const shownDay = parseInt(localStorage.getItem('currentDay') || '1');
    if (news.day_number !== shownDay) {
        if (!vanyNewsReturn()) {
            const context = {};
            DAY_CONTEXT_KEYS.forEach(key => { context[key] = localStorage.getItem(key); });
            localStorage.setItem(VANY_NEWS_RETURN_KEY, JSON.stringify({ url: window.location.pathname, context }));
        }
        localStorage.setItem('editReturnDay', vanyNewsReturn().context.currentDay);
        localStorage.setItem('editingDay', news.day_number);
        localStorage.setItem('editOriginalCity', news.city_id != null ? news.city_id : '');
        localStorage.setItem('currentDay', news.day_number);
        if (news.city_id != null) localStorage.setItem('selectedCityId', news.city_id);
        localStorage.setItem('selectedHiking', news.hike_id != null ? news.hike_id : 'no-hiking');
        if (news.spot_id != null) localStorage.setItem('selectedSpot', news.spot_id);
        else localStorage.removeItem('selectedSpot');
    }
    window.location.href = window.APP_URLS.step5;
}

async function refreshVanyNews() {
    const nav = document.querySelector('.step-nav');
    const planId = localStorage.getItem('planId');
    if (!nav || !planId) return;
    let news = [];
    try {
        news = await apiGet(`/api/pepites/news?plan_id=${planId}`);
    } catch {
        return;   // un simple rappel : son échec ne doit rien perturber
    }
    // À l'étape 5, les idées du jour affiché sont déjà sous les yeux du voyageur.
    if (window.location.pathname.endsWith('/step5')) {
        const shown = parseInt(localStorage.getItem('currentDay') || '1');
        news = news.filter(item => item.day_number !== shown);
    }

    let box = document.getElementById('vanyNews');
    if (!news.length) {
        if (box) box.remove();
        return;
    }
    if (!box) {
        box = document.createElement('div');
        box.id = 'vanyNews';
        box.className = 'vany-news';
        box.innerHTML = `<i class="pepite-icon" aria-hidden="true"></i>
            <span class="vany-news__text"></span>
            <button type="button" class="btn btn--outline btn--sm vany-news__btn">Les découvrir</button>`;
        const back = nav.querySelector('.step-nav__back');
        if (back) back.after(box); else nav.prepend(box);
    }
    box.querySelector('.vany-news__text').textContent = news[0].text;
    box.querySelector('.vany-news__btn').onclick = () => openVanyNews(news[0]);
}

// Le voyageur a quitté l'étape 5 autrement (menu, précédent du navigateur) : on remet son
// jour avant que la page ne lise son contexte (à l'ouverture de la page, DOMContentLoaded).
if (!window.location.pathname.endsWith('/step5')) restoreDayInProgress();

document.addEventListener('DOMContentLoaded', () => {
    if (typeof apiGet !== 'function') return;   // page sans parcours (pas de map-helpers.js)
    refreshVanyNews();
    setInterval(refreshVanyNews, VANY_NEWS_POLL_MS);
});

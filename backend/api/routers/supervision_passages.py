"""
Les passages des chaînes d'agents, lancés et suivis depuis la supervision (issue #204, section « Passages » de /docs).

Une chaîne (la chaîne des services : restaurants, commerces, supermarchés, laveries ; et, depuis #276, les chaînes
gratuites de l'ajout d'une ville : OSM, pharmacies FINESS, carburants) se lance sur une ville sans ouvrir le conteneur. Le lancement répond tout de suite (202) : le passage tourne ensuite en tâche de fond,
parfois des heures pour une grande ville, et l'écran relit son état. Les règles sont dans services/passage_service.py.

Un lancement fait toujours une vraie mise à jour, payante : l'essai et le rejeu des règles restent des outils de la
ligne de commande. Le budget des agents (issue #211, services/budget_service.py) se règle ici aussi, et un lancement
est refusé quand il est atteint. Toutes les routes sont réservées aux admins (require_admin).
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.dependencies import require_admin
from api.models.supervision import AgentSettingsRequest, PassageRequest
from services import budget_service, passage_service
from services.exchange_rate_service import RateUnavailable
from services.passage_service import PassageConflict

router = APIRouter()

# Les champs du réglage, tels que la page les envoie (en français), et la colonne de agent_settings de chacun.
SETTING_COLUMNS = {"services_apres_etl": "services_after_etl", "enveloppe_du_mois_eur": "monthly_budget_eur",
                   "plafond_du_jour_eur": "daily_budget_eur", "reserve_vany_eur": "vany_reserve_eur"}

CONFLICT = {409: {"description": "Un passage de la chaîne tourne déjà, ou ce passage ne se reprend pas : le message dit pourquoi."}}
NOT_FOUND = {404: {"description": "Ce passage n'existe pas."}}


@router.post("/passages", status_code=202, responses=CONFLICT,
             summary="Lance un passage d'une chaîne d'agents sur une ville, en tâche de fond.")
def post_passage(body: PassageRequest, background: BackgroundTasks, _admin=Depends(require_admin)):
    """
    Écrit le passage demandé et le lance en tâche de fond ; répond tout de suite par son état (« en_file »), avec son
    identifiant (passage_id), à relire ensuite avec GET /passages/{passage_id}.
    {"chaine": "services", "ville_id": 12, "categories": ["restaurants", "laveries"]}
    Les chaînes et leurs catégories se lisent dans GET /passages/chaines : {"chaine": "osm", "ville_id": 12} relance OSM.
    Une chaîne, une ville ou une catégorie inconnue est refusée (422). Si un passage de la chaîne tourne déjà, le
    lancement est refusé (409) avec un message qui le nomme : un seul passage à la fois.
    """
    try:
        passage_id = passage_service.create_passage(body.chaine, body.ville_id, body.categories, origin="supervision")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except PassageConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    background.add_task(passage_service.run_passage, passage_id)
    return passage_service.read_passage(passage_id)


@router.get("/passages", responses={422: {"description": "Un objet d'un type inconnu, ou sans son objet_id."}},
            summary="Les passages en cours, en file d'attente, et les derniers finis ou en échec.")
def get_passages(limite: int = 20, objet: str | None = None, objet_id: int | None = None, _admin=Depends(require_admin)):
    """
    Ce que montre le panneau « En cours et file d'attente » de l'espace Agents, la liste des derniers passages, et le
    tableau des villes non faites avec leur raison (budget atteint, attend la fin du passage en cours, mise à jour
    automatique coupée, échec) : {"en_cours": [...], "en_file": [...], "derniers": [...], "villes_en_attente": [...]},
    chacun au format de GET /passages/{passage_id}, avec son origine (supervision, etl) ; une ville non faite y ajoute
    sa « raison ». Les villes ajoutées par l'ETL entrent dans la file et partent seules, l'une après l'autre.
    Chaque passage donne le nombre de ses trouvailles (nombre_trouvailles) ; leur détail est dans GET /passages/{passage_id}.

    Pour une information, le passage qui l'a apportée : ?objet=spot&objet_id=3893 (objet : service, spot ou pepite).
    La réponse garde la même forme, réduite aux passages qui ont ajouté ou modifié cet objet, du plus récent au plus
    ancien ; chacun donne ses trouvailles sur cet objet seul (la partie qui l'a fait, ajout ou modification, quand).
    Un lancement en ligne de commande ou une action d'un voyageur y figure aussi, dans « derniers », sans chaîne ni ville.
    """
    try:
        return passage_service.list_passages(limite, objet, objet_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


# Les routes des chaînes et du réglage sont déclarées avant /passages/{passage_id} : sinon « chaines » ou « reglage »
# serait lu comme l'identifiant d'un passage.
@router.get("/passages/chaines", summary="Les chaînes qu'on peut lancer sur une ville, gratuites ou payantes.")
def get_chains(_admin=Depends(require_admin)):
    """
    Chaque chaîne, avec sa clé à envoyer dans « chaine » de POST /passages, son libellé, si elle est payante (des agents,
    retenue par le budget du jour) ou gratuite (OSM, fichiers de l'État), et ses parties, à envoyer dans « categories ».
    [{"chaine": "osm", "libelle": "Lieux d'OpenStreetMap", "payant": false, "categories": [{"cle": "osm", ...}]}, ...]
    """
    return passage_service.list_chains()


@router.get("/passages/reglage", summary="Le réglage des agents et le budget : réglé, dépensé, restant.")
def get_settings(_admin=Depends(require_admin)):
    """
    Ce que montre le panneau « Budget du jour » de l'espace Agents : la mise à jour automatique à la fin de l'ETL
    (activée ou coupée), l'enveloppe du mois, le plafond du jour, la part gardée pour Vany, ce qui est dépensé et ce
    qui reste le jour et le mois, et, si le budget est atteint, la raison (budget_atteint), sinon null.
    Les montants sont en euros TTC estimés ; la dépense est aussi donnée en dollars, la monnaie du fournisseur, avec le
    taux de la BCE utilisé (taux). Sans aucun taux connu, les montants en euros sont null et budget_atteint le dit.
    budget_actif vaut false quand AGENT_BUDGET_ENABLED=0 coupe le budget (poste de développement) : les dépenses sont
    toujours données, mais rien ne retient la file, et budget_atteint vaut null.
    """
    return budget_service.budget_state()


@router.put("/passages/reglage", responses={422: {"description": "Un montant négatif, ou des montants qui ne vont pas ensemble."},
                                            503: {"description": "Aucun taux de la BCE connu : les euros ne peuvent pas être convertis."}},
            summary="Change le réglage des agents : mise à jour automatique, enveloppe, plafond, part de Vany.")
def put_settings(body: AgentSettingsRequest, admin=Depends(require_admin)):
    """
    Seuls les champs envoyés changent ; le changement vaut tout de suite, sans redémarrer l'application. L'ancien
    réglage reste en base, avec le nom de l'admin qui l'a changé. Répond par le nouvel état, comme GET /passages/reglage.
    {"services_apres_etl": false} ou {"plafond_du_jour_eur": 5, "raison": "test du budget atteint"}
    Les montants sont en euros TTC. Un plafond du jour ou une part de Vany plus grands que l'enveloppe du mois sont
    refusés (422). Sans aucun taux de la BCE connu, rien n'est écrit (503).
    """
    sent = body.model_dump(exclude_none=True)
    reason = sent.pop("raison", None)
    changes = {SETTING_COLUMNS[field]: value for field, value in sent.items()}
    try:
        return budget_service.save_settings(changes, admin["username"], reason)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except RateUnavailable as error:
        raise HTTPException(status_code=503, detail=f"Taux du dollar inconnu : {error}.")


@router.get("/passages/{passage_id}", responses=NOT_FOUND, summary="L'état d'un passage, catégorie par catégorie.")
def get_passage(passage_id: str, _admin=Depends(require_admin)):
    """
    Où en est un passage : la ville, l'origine (supervision, etl), l'état (en_file, en_cours, fini, echec), le coût et
    les appels lus dans llm_calls, la raison d'un échec, et pour chaque catégorie son état, son étape (recherches,
    analyse, preuves, enregistrement), son coût et le bilan de son enregistrement.
    Ce qu'il a trouvé (trouvailles) : chaque service, spot ou pépite qu'il a ajouté ou modifié, avec son nom, la partie
    qui l'a fait et l'heure.
    """
    passage = passage_service.read_passage(passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage introuvable")
    return passage


@router.post("/passages/{passage_id}/reprise", status_code=202, responses=NOT_FOUND | CONFLICT,
             summary="Relance une ville non faite : reprend un échec sans repayer, ou lance une ville en attente.")
def post_resume(passage_id: str, background: BackgroundTasks, _admin=Depends(require_admin)):
    """
    Un passage en échec : crée un nouveau passage qui ne refait que ses catégories non finies (reprise_de le relie à
    lui), et le lance en tâche de fond. Une grande ville cherchée par zones reprend aussi ses zones finies sans les
    repayer. Un échec n'est jamais relancé tout seul : c'est cette route qui le reprend.
    Un passage en attente (l'ETL l'a gardé quand la mise à jour automatique était coupée) : il part lui-même.
    Refusé (409), avec le motif : un passage ni en échec ni en attente, un autre passage en cours, un budget atteint.
    """
    try:
        resumed = passage_service.resume_passage(passage_id, origin="supervision")
    except PassageConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    if resumed is None:
        raise HTTPException(status_code=404, detail="Passage introuvable")
    background.add_task(passage_service.run_passage, resumed)
    return passage_service.read_passage(resumed)

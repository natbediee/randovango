"""
Les passages des chaînes d'agents, lancés et suivis depuis la supervision (issue #204, section « Passages » de /docs).

Une chaîne d'agents (aujourd'hui, la chaîne des services : restaurants, commerces, supermarchés, laveries) se lance sur
une ville sans ouvrir le conteneur. Le lancement répond tout de suite (202) : le passage tourne ensuite en tâche de fond,
parfois des heures pour une grande ville, et l'écran relit son état. Les règles sont dans services/passage_service.py.

Un lancement fait toujours une vraie mise à jour, payante : l'essai et le rejeu des règles restent des outils de la
ligne de commande. Le budget des agents (issue #211, services/budget_service.py) se règle ici aussi, et un lancement
est refusé quand il est atteint. Toutes les routes sont réservées aux admins (require_admin).
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.dependencies import require_admin
from api.models.supervision import AgentSettingsRequest, PassageRequest
from services import budget_service, passage_service
from services.passage_service import PassageConflict

router = APIRouter()

# Les champs du réglage, tels que la page les envoie (en français), et la colonne de agent_settings de chacun.
SETTING_COLUMNS = {"services_apres_etl": "services_after_etl", "enveloppe_du_mois_usd": "monthly_budget_usd",
                   "plafond_du_jour_usd": "daily_budget_usd", "reserve_vany_usd": "vany_reserve_usd"}

CONFLICT = {409: {"description": "Un passage de la chaîne tourne déjà, ou ce passage ne se reprend pas : le message dit pourquoi."}}
NOT_FOUND = {404: {"description": "Ce passage n'existe pas."}}


@router.post("/passages", status_code=202, responses=CONFLICT,
             summary="Lance un passage d'une chaîne d'agents sur une ville, en tâche de fond.")
def post_passage(body: PassageRequest, background: BackgroundTasks, _admin=Depends(require_admin)):
    """
    Écrit le passage demandé et le lance en tâche de fond ; répond tout de suite par son état (« en_file »), avec son
    identifiant (passage_id), à relire ensuite avec GET /passages/{passage_id}.
    {"chaine": "services", "ville_id": 12, "categories": ["restaurants", "laveries"]}
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


@router.get("/passages", summary="Les passages en cours, en file d'attente, et les derniers finis ou en échec.")
def get_passages(limite: int = 20, _admin=Depends(require_admin)):
    """
    Ce que montre le panneau « En cours et file d'attente » de l'espace Agents, et la liste des derniers passages :
    {"en_cours": [...], "en_file": [...], "derniers": [...]}, chacun au format de GET /passages/{passage_id}.
    La file reste vide tant que #211 n'y met pas les villes ajoutées par l'ETL.
    """
    return passage_service.list_passages(limite)


# Les deux routes du réglage sont déclarées avant /passages/{passage_id} : sinon « reglage » serait lu comme
# l'identifiant d'un passage.
@router.get("/passages/reglage", summary="Le réglage des agents et le budget : réglé, dépensé, restant.")
def get_settings(_admin=Depends(require_admin)):
    """
    Ce que montre le panneau « Budget du jour » de l'espace Agents : la mise à jour automatique à la fin de l'ETL
    (activée ou coupée), l'enveloppe du mois, le plafond du jour, la part gardée pour Vany, ce qui est dépensé et ce
    qui reste le jour et le mois, et, si le budget est atteint, la raison (budget_atteint), sinon null.
    Les montants sont en dollars, au prix équivalent API des appels d'agents, abonnement compris.
    """
    return budget_service.budget_state()


@router.put("/passages/reglage", responses={422: {"description": "Un montant négatif, ou des montants qui ne vont pas ensemble."}},
            summary="Change le réglage des agents : mise à jour automatique, enveloppe, plafond, part de Vany.")
def put_settings(body: AgentSettingsRequest, admin=Depends(require_admin)):
    """
    Seuls les champs envoyés changent ; le changement vaut tout de suite, sans redémarrer l'application. L'ancien
    réglage reste en base, avec le nom de l'admin qui l'a changé. Répond par le nouvel état, comme GET /passages/reglage.
    {"services_apres_etl": false} ou {"plafond_du_jour_usd": 5, "raison": "test du budget atteint"}
    Un plafond du jour ou une part de Vany plus grands que l'enveloppe du mois sont refusés (422).
    """
    sent = body.model_dump(exclude_none=True)
    reason = sent.pop("raison", None)
    changes = {SETTING_COLUMNS[field]: value for field, value in sent.items()}
    try:
        return budget_service.save_settings(changes, admin["username"], reason)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/passages/{passage_id}", responses=NOT_FOUND, summary="L'état d'un passage, catégorie par catégorie.")
def get_passage(passage_id: str, _admin=Depends(require_admin)):
    """
    Où en est un passage : la ville, l'origine (supervision, etl), l'état (en_file, en_cours, fini, echec), le coût et
    les appels lus dans llm_calls, la raison d'un échec, et pour chaque catégorie son état, son étape (recherches,
    analyse, preuves, enregistrement), son coût et le bilan de son enregistrement.
    """
    passage = passage_service.read_passage(passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage introuvable")
    return passage


@router.post("/passages/{passage_id}/reprise", status_code=202, responses=NOT_FOUND | CONFLICT,
             summary="Reprend un passage en échec, sans repayer les catégories finies.")
def post_resume(passage_id: str, background: BackgroundTasks, _admin=Depends(require_admin)):
    """
    Crée un nouveau passage qui ne refait que les catégories non finies du passage en échec (reprise_de le relie à
    lui), et le lance en tâche de fond. Une grande ville cherchée par zones reprend aussi ses zones finies sans les
    repayer. Un passage qui n'est pas en échec, ou un autre passage en cours, est refusé (409) avec le motif.
    """
    try:
        resumed = passage_service.resume_passage(passage_id, origin="supervision")
    except PassageConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    if resumed is None:
        raise HTTPException(status_code=404, detail="Passage introuvable")
    background.add_task(passage_service.run_passage, resumed)
    return passage_service.read_passage(resumed)

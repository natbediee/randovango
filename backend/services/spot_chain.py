"""
La chaîne des spots d'une ville (issue #276) : lire la source des spots, puis harmoniser, lire les ouvertures et
vérifier les spots trouvés. Elle se lance, se suit et se reprend comme les autres chaînes (services/passage_service.py).

QUATRE PARTIES, DANS CET ORDRE
    source         la source des spots relue autour de la ville : nouveaux spots, fiches à jour. Gratuite (un
                   navigateur automatique, environ 4 minutes) : le budget des agents ne la retient pas.
    harmonisation  les spots de la ville jamais harmonisés (agents/harmonize_spots.py).
    ouvertures     les spots de la ville au texte d'ouverture pas encore lu, ou changé depuis (agents/read_openings.py).
    verification   les spots de la ville marqués à vérifier et jamais vérifiés (agents/verify_spots.py).

RIEN N'EST PAYÉ DEUX FOIS
Chaque agent ne prend que les spots de la ville qui restent à faire : relancer une ville, ou reprendre une partie en
échec, ne repaie aucun spot déjà fait. Un spot raté (quota, Claude surchargé) fait passer la partie en échec, avec la
raison : la reprise ne refait que lui.

UN SEUL PASSAGE À LA FOIS, TOUTES VILLES CONFONDUES
Un spot entre deux villes voisines appartient aux deux (histo_scrap) : deux passages en même temps pourraient le payer
deux fois. Et la source des spots ne se lit qu'avec un navigateur à la fois.
"""
from agents import harmonize_spots, read_openings, verify_spots
from etl.extract.scraper_p4n import run_p4n_scraper
from etl.load.load_p4n import load_p4n_to_mysql
from etl.transform.transform_p4n import transform_p4n
from services import etl_chains
from services.etl_chains import StepFailed
from utils.db_utils import MySQLUtils

LOCK_NAME = "randovango_passage_spots"
BUSY = "Un passage de la chaîne des spots tourne déjà : attendre sa fin avant d'en lancer un autre."

PARTS = {"source": "Lecture de la source des spots", "harmonisation": "Harmonisation des descriptions",
         "ouvertures": "Lecture des ouvertures", "verification": "Vérification des spots à vérifier"}
FREE_PARTS = ("source",)
# L'agent de chaque partie, tel qu'il est noté dans llm_calls : l'étape affichée se lit dans ses appels.
AGENTS = {"harmonisation": "harmonize_spots", "ouvertures": "read_openings", "verification": "verify_spots"}


class SpotsMissed(RuntimeError):
    """Des spots de la ville n'ont pas pu être traités par l'agent : la partie échoue, la reprise ne refait qu'eux."""
    def __init__(self, missed: int, done: int, cause: Exception | None):
        super().__init__(f"{missed} spot(s) raté(s), {done} fait(s) : {cause}")
        self.missed, self.done, self.cause = missed, done, cause


def lock(city_id: int):
    """Le verrou de la chaîne, le même pour toutes les villes : un bloc « with »."""
    return etl_chains.named_lock(LOCK_NAME, BUSY)


def lock_is_free(city_id: int) -> bool:
    """Le verrou de la chaîne est-il libre ?"""
    return etl_chains.named_lock_is_free(LOCK_NAME)


def source_already_read(city_id: int) -> bool:
    """
    La source des spots a-t-elle déjà été lue pour cette ville (une ligne dans histo_scrap) ? Une ville lue avant les
    passages (#276) n'a aucune partie « source » finie dans la table passages : histo_scrap le sait quand même.
    """
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (conn, cursor):
        cursor.execute("SELECT COUNT(*) FROM histo_scrap WHERE city_id = %s", (city_id,))
        return cursor.fetchone()[0] > 0


def steps_of(part: str) -> dict:
    """L'agent d'une partie et l'étape qu'il fait ; la source n'appelle aucun agent."""
    return {AGENTS[part]: part} if part in AGENTS else {}


def agent_summary(summary: dict, key: str) -> dict:
    """
    Le bilan d'un agent devenu celui de la partie, {key: nombre de spots faits}. S'il reste des spots ratés, lève
    SpotsMissed avec la dernière erreur : la partie passe en échec avec la raison, au lieu de se dire finie.
    """
    if summary["rates"]:
        raise SpotsMissed(summary["rates"], summary["faits"], summary["erreur"])
    return {key: summary["faits"]}


# --- Les parties ---
# Chacune a la forme attendue par passage_service.Chain.run_part : (passage, partie, ville, reprise, budget) -> bilan.

def run_source(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """
    La source des spots relue autour de la ville, puis chargée ; le nombre de spots nouveaux lus en bilan.
    Une page lue dont tous les spots sont déjà en base donne un tableau vide : la partie finit avec 0 spot lu.
    """
    raw = run_p4n_scraper(city["name"], is_headless=True, save_csv=False)
    if raw is None:
        raise StepFailed("source des spots illisible (ville sans position, ou page qui ne répond pas) : relancer plus tard")
    if raw.empty:
        return {"spots_lus": 0}
    spots = transform_p4n(raw)
    load_p4n_to_mysql(spots, city["name"])
    return {"spots_lus": len(spots)}


def run_harmonization(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Les spots de la ville jamais harmonisés."""
    summary = harmonize_spots.run_sample(only_new=True, city_id=city["id"], check_budget=check_budget)
    return agent_summary(summary, "harmonises")


def run_openings(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Les spots de la ville au texte d'ouverture pas encore lu, ou changé depuis."""
    summary = read_openings.run(city_id=city["id"], check_budget=check_budget)
    return agent_summary(summary, "ouvertures_lues")


def run_verification(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Les spots de la ville marqués à vérifier et jamais vérifiés."""
    summary = verify_spots.run(only_new=True, city_id=city["id"], check_budget=check_budget)
    return agent_summary(summary, "verifies")


RUNNERS = {"source": run_source, "harmonisation": run_harmonization, "ouvertures": run_openings,
           "verification": run_verification}


def run_part(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Fait passer la partie demandée de la chaîne des spots."""
    return RUNNERS[key](passage_id, key, city, resume, check_budget)

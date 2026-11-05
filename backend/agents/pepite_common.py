"""
Ce que les deux agents de recherche des pépites de Vany ont en commun :
    - discover_places.py : les lieux d'une ville, à l'import par l'ETL ;
    - find_pepites.py    : l'agenda d'un séjour, au choix de la ville.
Ils décrivent leurs idées avec les mêmes champs (COMMON_RULES, pepite_schema), sont
contrôlés de la même façon (clean_proposal) et appellent le modèle de la même façon
(run_search). Chacun garde ses propres consignes et sa version.

UNE MODIFICATION DE COMMON_RULES OU DE THEMES CHANGE LES DEUX PROMPTS : augmenter
alors la version de chacun des deux agents.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from time import sleep
from urllib.parse import unquote, urlparse

import requests

from agents.llm_config import make_llm_service
from services import pepite_service
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_pepites")

CRENEAUX = ["journee", "soiree", "libre"]

# Thèmes d'une idée : ils diront à qui elle plaira. Les recherches restent communes à
# tous les voyageurs d'une zone ; c'est au moment du choix (choose_pepites.py) que les
# goûts d'un voyageur feront préférer une idée à une autre (voyage 100 % IA).
THEMES = {
    "nature": "site naturel, faune et flore, paysage",
    "mer": "littoral, port, plage, île, sortie en mer",
    "patrimoine": "monument, chapelle, phare, fort, mégalithe, musée d'histoire, lieu de mémoire",
    "art": "exposition, galerie, atelier d'artiste, artisanat d'art",
    "chine": "brocante, vide-grenier, puces, antiquaire",
    "terroir": "marché, producteur, dégustation, savoir-faire local",
    "fete": "concert, fest-noz, spectacle, fête locale",
    "enfants": "particulièrement adapté aux enfants",
    "sport": "activité sportive (kayak, vélo, escalade, surf...)",
}
MAX_THEMES = 3


def pepite_schema(categories: list, max_proposals: int) -> dict:
    """Forme de la réponse attendue ; seules les catégories et le nombre d'idées changent."""
    return {
        "type": "object",
        "properties": {
            "propositions": {
                "type": "array",
                "maxItems": max_proposals,
                "items": {
                    "type": "object",
                    "properties": {
                        "nom": {"type": "string"},
                        "categorie": {"type": "string", "enum": categories},
                        "description": {"type": "string", "description": "Une ou deux phrases neutres."},
                        "commune": {"type": "string"},
                        "themes": {"type": "array", "minItems": 1, "maxItems": MAX_THEMES,
                                   "items": {"type": "string", "enum": list(THEMES)}},
                        "lieu": {"type": "string", "description": "Nom exact du lieu, sans description"},
                        "adresse": {"type": ["string", "null"], "description": "Adresse postale, null pour un site naturel"},
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                        "date_debut": {"type": ["string", "null"], "description": "AAAA-MM-JJ, événement seulement"},
                        "date_fin": {"type": ["string", "null"], "description": "AAAA-MM-JJ, événement seulement"},
                        "jours_semaine": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
                        "horaires": {"type": "string", "description": "Très court : « Dès 21 h », « Jusqu'à 18 h »"},
                        "heure_debut": {"type": ["number", "null"], "description": "Heure fixe de début, 13.25 = 13 h 15"},
                        "tarif": {"type": ["string", "null"], "description": "Très court : « Gratuit », « 10 € »"},
                        "creneau": {"type": "string", "enum": CRENEAUX},
                        "duree_h": {"type": "number"},
                        "exterieur": {"type": "boolean"},
                        "permanent": {"type": "boolean"},
                        "note": {"type": "integer", "minimum": 1, "maximum": 10},
                        "sources": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["nom", "categorie", "description", "commune", "themes", "lieu", "adresse", "latitude",
                                 "longitude", "date_debut", "date_fin", "jours_semaine", "horaires", "heure_debut",
                                 "tarif", "creneau", "duree_h", "exterieur", "permanent", "note", "sources"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["propositions"],
        "additionalProperties": False,
    }


COMMON_RULES = f"""## Règles
- Uniquement ce que tu trouves pendant ta recherche, avec ses sources. N'utilise pas tes connaissances.
- À moins de {pepite_service.RADIUS_KM} km du centre de la recherche.
- Ne repropose pas les idées déjà connues listées dans le message.

## Les champs
- note : de 1 à 10. 7-8 = un bon conseil d'habitant, recommandé par l'office de tourisme ou les guides ;
  9-10 = incontournable, mérite le détour à lui seul. Ne propose rien en dessous de {pepite_service.NOTE_MIN}.
- creneau : "journee" (lieu à horaires d'ouverture), "soiree" (après 18 h), "libre" (accessible à
  toute heure : point de vue, plage, site naturel).
- duree_h : temps à prévoir sur place, en heures.
- exterieur : true si l'idée dépend de la météo.
- permanent : true pour ce qui ne change pas (monument, site naturel) ; false pour une activité,
  un événement, un marché ou un producteur, dont les horaires ou l'existence peuvent changer.
- date_debut, date_fin : les dates d'un événement ou d'une sortie programmée (une exposition dure
  plusieurs jours) ; null sinon.
- jours_semaine : jours d'ouverture, 0 = lundi ... 6 = dimanche (un marché le dimanche : [6]) ;
  liste vide si tous les jours.
- horaires : très court, pour l'affichage (« Dès 21 h », « Vers 17 h 15 », « Jusqu'à 18 h »).
- heure_debut : l'heure à laquelle il faut être là quand elle est fixe (départ d'un bateau, visite
  guidée, début d'un concert), en heures décimales : 13 h 15 = 13.25 ; null pour un lieu qu'on visite
  quand on veut pendant ses heures d'ouverture.
- tarif : très court, pour l'affichage (« Gratuit », « 10 € », « 5 à 12 € », « 10 €, sur réservation ») ;
  null si tu ne l'as pas trouvé. Le voyageur doit savoir avant d'ajouter une sortie payante.
- themes : de 1 à {MAX_THEMES} thèmes, ceux qui diront à qui l'idée plaira :
{chr(10).join(f"  {name} = {meaning}" for name, meaning in THEMES.items())}
- description : deux phrases au plus, neutres, au présent, sans prix (il va dans tarif) ni numéro
  de téléphone.
- lieu : le nom du lieu lui-même, tel qu'il est écrit sur place ou sur une carte, sans description
  (« Fort de Bertheaume », « Cinéma Le Dauphin », « Menhir de Kerloas »). Pour un événement, une
  activité ou un marché : le lieu où il se passe (la salle, le port de départ, la place du marché).
- adresse : l'adresse postale du lieu telle que la donne sa source (« 2 boulevard de la Mer, 29217
  Plougonvelin ») ; null pour un site naturel sans adresse (plage, pointe, menhir).
- latitude, longitude : ton estimation de l'emplacement du lieu.
- sources : les URL des pages réellement consultées.

Réponds en français."""


def search_header(zone: dict) -> list:
    """Premières lignes du message : la date et le centre de la recherche (spot, sinon centre-ville)."""
    lat, lon = zone["points"][0]
    center = zone["spot_name"] if zone.get("has_spot") else f"centre de {zone.get('city_name') or 'la commune'}"
    return [
        f"DATE DU JOUR : {date.today().strftime('%d/%m/%Y')}",
        f"COMMUNE : {zone.get('city_name') or 'inconnue'}",
        f"CENTRE DE LA RECHERCHE : {center} ({lat}, {lon})",
    ]


def known_ideas_lines(known_names: list) -> list:
    """Dernières lignes du message : ce qu'on connaît déjà n'est pas recherché à nouveau."""
    return ["IDÉES DÉJÀ CONNUES (ne pas reproposer) :"] + ([f"- {name}" for name in known_names] or ["(aucune)"])


def clean_proposal(proposal: dict, permanent_only: bool = False) -> dict | None:
    """
    Vérifie une idée renvoyée par l'agent avant de l'enregistrer. Le schéma JSON
    garantit la forme ; on vérifie ici le fond : note suffisante, au moins une
    source, dates lisibles, des dates pour un événement, et, si `permanent_only`,
    rien qui puisse changer (la recherche des lieux n'est pas refaite avant un an).
    """
    if proposal["note"] < pepite_service.NOTE_MIN or not proposal["sources"]:
        return None
    if permanent_only and not proposal["permanent"]:
        return None
    proposal["themes"] = list(dict.fromkeys(proposal["themes"]))
    try:
        for field in ("date_debut", "date_fin"):
            if proposal[field]:
                proposal[field] = date.fromisoformat(proposal[field])
    except ValueError:
        return None
    if proposal["categorie"] == "evenement" and not proposal["date_debut"]:
        return None
    proposal["date_fin"] = proposal["date_fin"] or proposal["date_debut"]
    return proposal


# Les sources sont affichées au voyageur (« Source : … ») : l'agent devine parfois
# l'adresse d'une page d'après celle d'un site (…/activite/cinema-le-rohan/), qui
# n'existe pas. Mesure sur 1 099 liens en base : 27 en 404, 78 sans réponse, 23
# refusés aux robots. On retire les liens morts (404, 410) et on met en tête ceux
# qui répondent ; un lien sans réponse ou refusé aux robots est gardé, après.
LINK_TIMEOUT_SECONDS = 15
DEAD_STATUSES = (404, 410)
# Interrogés à plusieurs en même temps, certains sites répondent 404 à une page qui
# existe : sur les mêmes liens, 27, 45 puis 17 « morts » selon le passage. Un lien n'est
# donc déclaré mort qu'après une seconde vérification, seul et un peu plus tard.
CONFIRM_DELAY_SECONDS = 3
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                                 " (KHTML, like Gecko) Chrome/130 Safari/537.36"}

# Sites que nos agents n'ouvrent pas. Lu le 4 novembre 2026 : Tripadvisor, le Guide Michelin, Restaurant Guru et Google
# interdisent la lecture ou la réutilisation automatisée sans accord. TheFork, Petit Futé, Gault & Millau et Pages Jaunes
# restent exclus par prudence : leurs conditions n'ont pas pu être lues. Leur robots.txt ne suffit pas à trancher : celui
# de Tripadvisor et de Michelin laisse passer ces pages alors que leurs conditions l'interdisent.
EXCLUDED_SITES = {"tripadvisor", "thefork", "lafourchette", "michelin", "restaurantguru", "restaurant-guru", "petitfute",
                  "gaultmillau", "pagesjaunes", "google", "goo"}
EXCLUDED_SITES_PROMPT = """## Les sites à ne pas utiliser
N'ouvre jamais les pages de Tripadvisor, TheFork (LaFourchette), Guide Michelin, Restaurant Guru, Petit Futé, Gault & Millau,
Pages Jaunes et Google (Maps compris). Si l'un d'eux sort dans les résultats de recherche, tu peux seulement retenir le nom du
lieu affiché dans ce résultat : n'en reprends ni note, ni avis, ni texte, et ne donne jamais son adresse. Cherche ensuite une
autre page qui parle de ce lieu : sans elle, il ne sera pas gardé."""


def is_excluded_site(url: str) -> bool:
    """Compare les parties du nom de domaine : « guide.michelin.com » est exclu, « le-michelin.fr » ne l'est pas."""
    host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    return bool(EXCLUDED_SITES & set(host.lower().split(".")))


def link_status(url: str) -> bool | None:
    """True : la page répond ; False : elle n'existe pas (404, 410) ; None : on ne sait pas."""
    if is_excluded_site(url):
        return None
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=LINK_TIMEOUT_SECONDS,
                                allow_redirects=True, stream=True)
        response.close()
    except requests.RequestException:
        return None
    if response.status_code in DEAD_STATUSES:
        return False
    return True if response.status_code < 400 else None


def check_links(urls, workers: int = 8) -> dict:
    """État de chaque lien {url: True, False ou None} (voir link_status), les morts étant confirmés."""
    urls = list(urls)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = dict(zip(urls, pool.map(link_status, urls)))
    suspects = [url for url in urls if statuses[url] is False]
    if suspects:
        sleep(CONFIRM_DELAY_SECONDS)
    for url in suspects:
        statuses[url] = link_status(url)
    return statuses


def names_the_idea(url: str, name: str) -> bool:
    """L'adresse contient-elle un mot propre au nom de l'idée ? Alors c'est sans doute sa page, pas une liste."""
    parsed = urlparse(url)
    in_url = set(pepite_service.name_key(unquote(f"{parsed.path} {parsed.query}")).split())
    words = {word for word in pepite_service.name_key(name).split()
             if len(word) >= 4 and word not in pepite_service.GENERIC_WORDS}
    return bool(words & in_url)


def sort_sources(sources: list, statuses: dict, name: str = "") -> list:
    """
    Les liens morts sont retirés. D'abord ceux qui répondent, puis ceux dont on ne sait rien ;
    à égalité, la page de l'idée avant un agenda général, que le voyageur devrait fouiller.
    """
    rank = {True: 0, None: 1}
    alive = (url for url in sources if statuses.get(url) is not False)
    return sorted(alive, key=lambda url: (rank[statuses.get(url)], not names_the_idea(url, name)))


def check_sources(ideas: list) -> list:
    """
    Vérifie les liens de toutes les idées en parallèle. Une idée dont aucun lien
    n'existe plus est gardée, sans source affichée : la page a pu disparaître alors que
    le lieu existe toujours (l'étang de la Verte Vallée, à Callac).
    """
    statuses = check_links({url for idea in ideas for url in idea["sources"]})
    for idea in ideas:
        idea["sources"] = sort_sources(idea["sources"], statuses, idea["nom"])
        if not idea["sources"]:
            logger.info(f"[pépites] {idea['nom']} : gardée sans source, aucun de ses liens n'existe plus")
    return ideas


def run_search(label: str, system: str, message: str, schema: dict, agent: str, permanent_only: bool = False) -> tuple:
    """
    Lance une recherche web de l'agent et contrôle ses idées.
    Renvoie (idées valides, modèle). Lève LLMUnavailable si l'agent n'a pas pu répondre.
    """
    service = make_llm_service(agent)
    answer = service.complete_json(system, message, schema)
    ideas = check_sources([p for p in (clean_proposal(p, permanent_only) for p in answer["propositions"]) if p])
    logger.info(
        f"[pépites] {label} : {len(ideas)} idée(s) retenue(s)"
        f" sur {len(answer['propositions'])} ({(service.last_run.get('duration_ms') or 0) / 1000:.0f} s,"
        f" outils : {', '.join(service.last_run.get('tools') or []) or 'aucun'}) :"
        f" {', '.join(i['nom'] for i in ideas) or 'rien'}"
    )
    return ideas, service.model

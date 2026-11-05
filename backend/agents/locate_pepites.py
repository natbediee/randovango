"""
Recalage de la position des pépites de Vany : l'agent cherche une page qui donne
les coordonnées GPS du lieu (fiche Mérimée, Wikipédia, OpenStreetMap...) et les
recopie, avec l'adresse de cette page.

POURQUOI UN AGENT DE PLUS
Les agents de recherche (discover_places.py, find_pepites.py) estiment la position
de leurs idées de mémoire : ~540 m d'erreur médiane. Le code la recale ensuite sur
un POI de la base ETL ou sur l'adresse postale (pepite_service.locate), mais 6 lieux
sur 10 (chapelles isolées, pointes, menhirs) n'y sont pas. Or « à voir en chemin »
demande un lieu à moins de 400 m du tracé de la rando (pepite_service.TRAIL_KM).
Pilote sur 40 lieux de position connue (oneshot/pilot_positions.py) : 35 m d'erreur
médiane, 36 sur 40 à moins de 400 m. Wikidata et Nominatim, essayés aussi, trouvent
moins de lieux et se trompent davantage (homonymes).

L'AGENT RECOPIE, LE CODE CONTRÔLE (clean_position)
Une position n'est gardée que si elle cite une page (pas une page de résultats de
recherche), que cette page nomme le lieu, et qu'elle est à moins de MAX_SHIFT_KM de
l'estimation. Sinon le lieu reste « Emplacement approximatif ».

UNE TRANSFORMATION POST-CHARGEMENT, comme discover_places.py : lancée après chaque
recherche des lieux d'une ville (ETL), ou par le rattrapage. C'est pepite_service.py
qui choisit les lieux à recaler et enregistre les positions (relocate).

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m agents.locate_pepites --rattrapage --limit 2   # 2 lots de 10 lieux
"""
import argparse
from urllib.parse import parse_qs, urlparse

from agents import llm_config
from services import pepite_service
from utils.geo_utils import haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_pepites")

# Version des consignes. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT : les lieux déjà
# essayés sans succès seront alors retentés par le rattrapage.
#   1 : version initiale, issue du pilote (oneshot/pilot_positions.py)
LOCATE_PROMPT_VERSION = 1

BATCH_SIZE = 10            # lieux par question : ~1 min pour un lot de 10
# Plus loin que l'estimation, c'est sans doute un homonyme. Une estimation fausse de
# 2 km existe (chapelle recalée sur le sommet du Ménez-Hom voisin).
MAX_SHIFT_KM = 5

SYSTEM_PROMPT = """Tu retrouves la position GPS exacte de lieux de France (chapelles, menhirs,
pointes, plages, ports, sites naturels...) pour les voyageurs de Randovango, une application
de randonnée en van. La position sert à savoir si un lieu est sur le parcours d'une rando.

Pour chaque lieu, cherche sur le web une page consacrée à CE lieu qui DONNE ses coordonnées :
Wikipédia, Wikidata, base Mérimée ou POP du ministère de la Culture, inventaire du patrimoine
de Bretagne, fiche OpenStreetMap, site de la commune ou de l'office de tourisme.
- Recopie les coordonnées de cette page, en degrés décimaux (WGS84).
- "source" : l'adresse de cette page. Pas une page de résultats de recherche.
- "nom_source" : le nom du lieu tel qu'il est écrit sur cette page.
N'estime jamais une position toi-même, ni à partir du centre de la commune ou d'un lieu voisin :
si aucune page ne donne les coordonnées de ce lieu précis, réponds null pour latitude,
longitude, source et nom_source. Une position fausse est pire qu'une absence."""


def locate_schema(ids: list) -> dict:
    """Une position par lieu, désigné par son numéro : l'agent ne peut pas en inventer."""
    nullable_number = {"type": ["number", "null"]}
    nullable_text = {"type": ["string", "null"]}
    return {
        "type": "object", "additionalProperties": False, "required": ["positions"],
        "properties": {"positions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "latitude", "longitude", "source", "nom_source"],
            "properties": {"id": {"type": "integer", "enum": ids}, "latitude": nullable_number,
                           "longitude": nullable_number, "source": nullable_text, "nom_source": nullable_text},
        }}},
    }


def build_user_message(places: list) -> str:
    """Un lieu par ligne : son numéro, le nom exact du lieu, le nom de l'idée, sa commune."""
    lines = ["LIEUX :"]
    for place in places:
        details = [f"commune : {place.get('commune') or '?'}"]
        if place.get("adresse"):
            details.append(f"adresse : {place['adresse']}")
        name = place.get("lieu") or place["nom"]
        label = name if name == place["nom"] else f"{name} (« {place['nom']} »)"
        lines.append(f"[{place['id']}] {label}, {', '.join(details)}")
    return "\n".join(lines)


def is_search_page(url: str) -> bool:
    """Une page de résultats de recherche ne prouve rien (« chapelle Guisseny » -> une autre chapelle)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return "search" in parsed.path.lower() or any(key in query for key in ("q", "query", "search", "text"))


def names_the_place(source_name: str, place: dict) -> bool:
    """La page nomme-t-elle le lieu ? Il suffit d'un mot propre en commun (« Brendaouez »)."""
    def proper_words(name):
        return {word for word in pepite_service.name_key(name).split()
                if len(word) >= 4 and word not in pepite_service.GENERIC_WORDS}
    wanted = proper_words(place.get("lieu") or "") | proper_words(place["nom"])
    # Un nom fait seulement de mots génériques (« Lavoir ») : rien à vérifier de plus.
    return not wanted or bool(wanted & proper_words(source_name))


def clean_position(row: dict, place: dict) -> tuple | None:
    """
    Contrôle une position rendue par l'agent. Renvoie (latitude, longitude, source),
    ou None si elle n'est pas fiable : sans page, page de recherche, page qui ne nomme
    pas le lieu, ou trop loin de l'estimation.
    """
    latitude, longitude, source = row.get("latitude"), row.get("longitude"), (row.get("source") or "").strip()
    if latitude is None or longitude is None or not source.startswith("http"):
        return None
    if is_search_page(source) or not names_the_place(row.get("nom_source") or "", place):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if haversine_distance_km(place["latitude"], place["longitude"], latitude, longitude) > MAX_SHIFT_KM:
        return None
    return latitude, longitude, source[:500]


def make_llm_service():
    """Le seul endroit qui choisit comment appeler le modèle (et donc le fournisseur)."""
    return llm_config.make_llm_service("locate_pepites")


def locate_places(places: list) -> dict:
    """
    Cherche la position d'un lot de lieux (BATCH_SIZE au plus). Renvoie
    {id: (latitude, longitude, source)} pour les positions fiables seulement.
    Lève LLMUnavailable si l'agent n'a pas pu répondre.
    """
    by_id = {place["id"]: place for place in places}
    service = make_llm_service()
    answer = service.complete_json(SYSTEM_PROMPT, build_user_message(places), locate_schema(list(by_id)))
    found, refused = {}, []
    for row in answer["positions"]:
        place = by_id.get(row.get("id"))
        position = clean_position(row, place) if place else None
        if position:
            found[place["id"]] = position
        elif place and row.get("latitude") is not None:
            # L'agent a donné une position, le contrôle l'a refusée : on garde la trace.
            refused.append(f"{place['nom']} <- {row.get('source')} ({row.get('nom_source')})")
    logger.info(f"[pépites] positions : {len(found)}/{len(places)} retrouvée(s), {len(refused)} refusée(s)"
                f" ({(service.last_run.get('duration_ms') or 0) / 1000:.0f} s)"
                + "".join(f"\n    refusée : {line}" for line in refused))
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rattrapage", action="store_true", help="Tous les lieux à la position approximative")
    parser.add_argument("--limit", type=int, help="Nombre maximal de lots de 10 lieux (pour un pilote)")
    args = parser.parse_args()
    if not args.rattrapage:
        parser.error("indiquer --rattrapage")
    pepite_service.relocate_missing(limit=args.limit)


if __name__ == "__main__":
    main()

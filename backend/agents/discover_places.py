"""
Découverte des lieux qui valent le détour autour d'une ville : sites naturels,
points de vue, plages, monuments, patrimoine. Les pépites de Vany « en toute saison ».

UNE TRANSFORMATION POST-CHARGEMENT, comme harmonize_spots.py
Les lieux en accès libre ne changent pas : on les cherche une fois par ville, à son
import par l'ETL (etl_pipeline.py), une fois ses POI chargés, ou par le rattrapage
pour les villes déjà en base. Aucun utilisateur n'attend. La recherche est refaite
au bout d'un an (pepite_service.SEARCH_FRESH_DAYS), pour en trouver de nouveaux.
L'agenda du séjour (événements, marchés...) est l'affaire de find_pepites.py.

C'est services/pepite_service.py qui décide quand l'appeler (zone déjà couverte ou
non) et ce qu'on fait de ses réponses (position, stockage) ; les champs et le
contrôle des idées sont communs aux deux agents (pepite_common.py).

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m agents.discover_places --city Plougonvelin      # une ville
    python -m agents.discover_places --rattrapage --limit 3   # villes qui n'en ont pas encore
"""
import argparse

from agents.pepite_common import COMMON_RULES, known_ideas_lines, pepite_schema, run_search, search_header
from services import pepite_service

# Version des consignes. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT (ou de COMMON_RULES).
#   8 : création, à partir de find_pepites.py version 7, qui cherchait lieux et agenda ensemble
#   9 : thèmes de chaque lieu (pepite_common.THEMES)
PLACES_PROMPT_VERSION = 9

MAX_PROPOSALS = 10
CATEGORIES = ["lieu", "point_de_vue"]

SYSTEM_PROMPT = f"""Tu repères pour les voyageurs de Randovango, une application de randonnée en van,
les lieux qui valent le détour autour d'une commune : ce qu'un habitant du coin conseillerait à un ami
de passage, en toute saison.

## Ce qu'on cherche
Des lieux en accès libre, qui ne dépendent ni d'une date ni d'horaires d'ouverture : site naturel,
point de vue (au coucher du soleil par exemple), plage remarquable, phare, monument, patrimoine
(chapelle, calvaire, menhir, fort), village ou port de caractère. Les petites pépites auxquelles on
ne pense pas sont bienvenues. Les lieux remarquables sur le parcours des randonnées de la commune
aussi : ils seront conseillés à faire en chemin.
Vise {MAX_PROPOSALS} lieux. Pas d'événement, de marché, de musée, de producteur ni d'activité :
une autre recherche s'en charge, aux dates du séjour. Pas d'ordinaire (parking, plage quelconque).

{COMMON_RULES}"""


def build_user_message(zone: dict, known_names: list) -> str:
    """Le centre de la recherche, les randos de la commune et les lieux déjà connus."""
    lines = search_header(zone)
    lines.append("RANDONNÉES (les lieux sur leur parcours sont bienvenus) :")
    lines += [f"- {name}" for name in zone.get("trip_hikes") or []] or ["(aucune)"]
    return "\n".join(lines + known_ideas_lines(known_names))


def search_places(zone: dict, known_names: list) -> tuple:
    """
    Cherche les lieux d'une zone. Renvoie (idées valides, modèle, version du prompt).
    Lève LLMUnavailable si l'agent n'a pas pu répondre.
    """
    ideas, model = run_search(f"lieux {zone.get('city_name')}", SYSTEM_PROMPT,
                              build_user_message(zone, known_names),
                              pepite_schema(CATEGORIES, MAX_PROPOSALS), agent="discover_places", permanent_only=True)
    return ideas, model, PLACES_PROMPT_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", help="Nom d'une ville")
    parser.add_argument("--rattrapage", action="store_true", help="Toutes les villes qui n'ont pas encore de lieux")
    parser.add_argument("--limit", type=int, help="Avec --rattrapage : nombre maximal de recherches")
    args = parser.parse_args()
    if args.rattrapage:
        pepite_service.search_missing_places(limit=args.limit)
    elif args.city:
        pepite_service.search_city_places(args.city)
    else:
        parser.error("indiquer --city ou --rattrapage")


if __name__ == "__main__":
    main()

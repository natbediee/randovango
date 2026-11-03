"""
Recherche sur le web de l'agenda d'un séjour : ce qui se passe pendant ces jours-là
autour du spot (événement, marché, sortie programmée, musée ou producteur ouvert).
Les pépites de Vany « aux dates du séjour ».

UN AGENT APPELÉ À LA DEMANDE, pendant le parcours de l'utilisateur
Il est lancé dès le choix de la ville, et tourne pendant que l'utilisateur choisit
sa rando, son spot et ses services. L'agenda change : une recherche vaut 30 jours.
Les lieux en accès libre, qui ne changent pas, sont cherchés à l'avance par
discover_places.py. Les deux étaient d'abord cherchés ensemble ; l'agenda passait
alors à la trappe (l'agent évitait les lieux déjà connus et finissait sur des
adresses de plus en plus confidentielles).

C'est services/pepite_service.py qui décide quand l'appeler (s'il manque une
recherche récente pour cette zone et ces dates) et ce qu'on fait de ses réponses
(position, filtres, choix du jour par choose_pepites.py, stockage) ; les champs et
le contrôle des idées sont communs aux deux agents (pepite_common.py).

UTILISATION (dans le conteneur backend, depuis /usr/src/app), pour tester sur un
jour déjà planifié (le spot doit être choisi) :
    python -m agents.find_pepites --plan 12 --day 2
"""
import argparse

from agents.pepite_common import COMMON_RULES, known_ideas_lines, pepite_schema, run_search, search_header
from services import pepite_service

# Version des consignes. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT (ou de COMMON_RULES).
#   1 : version initiale
#   2 : heure de début des activités à heure fixe ; description en deux phrases au plus
#   3 : "exceptionnel" remplacé par "ce qu'un habitant conseillerait" ; jusqu'à 10 idées,
#       pour tous les jours restants du séjour ; rien sur le parcours de la rando
#   4 : quelques idées à l'abri pour les jours de pluie ; recherche possible dès le choix
#       de la ville (centre de la recherche) ; randos de tout le séjour
#   5 : tarif (à connaître avant d'ajouter une sortie payante)
#   6 : les lieux sur le parcours des randos sont bienvenus (conseils « En chemin »)
#   7 : nom exact du lieu et adresse postale, pour que le code retrouve sa position
#       (les coordonnées données par l'agent étaient souvent fausses de plusieurs centaines de mètres)
#   8 : l'agenda seul ; les lieux en accès libre passent à discover_places.py
#   9 : pas de restaurant ni de bar (une crêperie arrivait parmi les pépites)
#   10 : thèmes de chaque idée (pepite_common.THEMES) ; brocantes et ateliers d'artistes,
#        des thèmes variés pour plaire à des voyageurs aux goûts différents
#   11 : citer la fiche de l'idée, pas l'agenda où elle a été vue (le voyageur devait la
#        rechercher dans la page) ; consigne propre à l'agenda : la mettre dans COMMON_RULES
#        relancerait la recherche des lieux de toutes les villes
AGENDA_PROMPT_VERSION = 11

MAX_PROPOSALS = 6
CATEGORIES = ["lieu", "activite", "evenement", "marche", "producteur"]

SYSTEM_PROMPT = f"""Tu cherches pour les voyageurs de Randovango, une application de randonnée en van,
ce qui se passe pendant leur séjour autour de leur spot de nuit : ce qu'un habitant du coin
conseillerait à un ami de passage ces jours-là.

## Ce qu'on cherche
- les événements : fest-noz, concert, fête locale, exposition, spectacle ;
- les marchés, brocantes et vide-greniers ;
- les sorties programmées : sortie en mer, visite guidée, balade nature accompagnée ;
- les lieux à horaires ouverts pendant le séjour : musée, galerie, atelier d'artiste, producteur
  local, dégustation.
Vise {MAX_PROPOSALS} idées, dont au moins 3 à l'abri pour les jours de pluie, et varie les thèmes :
les voyageurs n'ont pas tous les mêmes goûts. Les lieux en
accès libre (site, point de vue, plage, monument) sont déjà connus : ne les propose pas.
Pas de restaurant, crêperie ni bar : on se restaure partout, ce n'est pas une sortie en soi
(un repas-spectacle ou un concert dans un bar reste un événement).

L'idée doit exister pendant le séjour : vérifie la saison et les jours d'ouverture, et pour un
événement, ses dates.

Dans les sources, mets en premier la page consacrée à cette idée précise. Si tu l'as vue dans un
agenda ou une liste, ouvre sa fiche et cite-la : un agenda général ou une page d'accueil ne vient
qu'en dernier, le voyageur devrait y rechercher l'idée.

{COMMON_RULES}"""


def build_user_message(day: dict, known_names: list) -> str:
    """Les dates restantes du séjour, le centre de la recherche et les idées déjà connues."""
    lines = search_header(day)
    lines.insert(1, f"SÉJOUR : du {day['day_date'].strftime('%d/%m/%Y')} au {day['trip_end'].strftime('%d/%m/%Y')}")
    return "\n".join(lines + known_ideas_lines(known_names))


def search_agenda(day: dict, known_names: list) -> tuple:
    """
    Cherche l'agenda du séjour autour du jour. Renvoie (idées valides, modèle,
    version du prompt). Lève LLMUnavailable si l'agent n'a pas pu répondre.
    """
    label = f"agenda {day.get('spot_name') or day.get('city_name')} du {day['day_date']} au {day['trip_end']}"
    ideas, model = run_search(label, SYSTEM_PROMPT, build_user_message(day, known_names),
                              pepite_schema(CATEGORIES, MAX_PROPOSALS), agent="find_pepites")
    return ideas, model, AGENDA_PROMPT_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=int, required=True, help="Identifiant du plan")
    parser.add_argument("--day", type=int, required=True, help="Numéro du jour")
    args = parser.parse_args()
    pepite_service.prepare_day(args.plan, args.day)
    pepite_service.complete_day(args.plan, args.day)
    print(pepite_service.get_day_state(args.plan, args.day))


if __name__ == "__main__":
    main()

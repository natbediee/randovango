"""
Agents Claude de Randovango : tout ce qui fait appel à l'IA est dans ce dossier.

Les outils communs :
    - llm_service.py    : la seule porte d'accès à Claude (API Anthropic ou
                          programme `claude`) ; les agents ne l'appellent jamais
                          directement
    - mcp_randovango.py : serveur MCP, des outils de lecture de la base que les
                          agents appellent quand ils en ont besoin

Les agents, qui sont des transformations POST-CHARGEMENT (le "T" d'un ELT) :
    - harmonize_spots.py : Claude réécrit les descriptions pour un voyageur en van
    - verify_spots.py    : vérifie sur le web les situations temporaires (fermeture, travaux...)
    - dedupe_spots.py    : repère les spots saisis deux fois et les marque comme doublons
    - discover_places.py : cherche sur le web les lieux qui valent le détour autour
                           d'une ville (site, point de vue, patrimoine), une fois pour
                           toutes, après le chargement de ses POI

Des agents appelés à la demande, pendant le parcours de l'utilisateur :
    - find_pepites.py    : cherche sur le web l'agenda du séjour (événement, marché,
                           sortie...) autour du spot, dès le choix de la ville
    - choose_pepites.py  : choisit, parmi les idées possibles ce jour-là, les meilleures
                           pour la journée (météo, coucher du soleil, rando), avec une
                           phrase pour chacune
Les deux agents de recherche des pépites de Vany partagent pepite_common.py ; c'est
services/pepite_service.py qui décide quand appeler les trois et ce qu'on fait de leurs réponses.

Le pipeline principal (dossier etl/) est un ETL classique :
    extract (scraping P4N) -> transform (transform_p4n) -> load (MySQL)
Les agents travaillent ensuite sur les données DÉJÀ en base.

Pourquoi après le chargement plutôt que dans l'étape transform ?
    - la donnée brute reste en base, intacte : on peut relancer ces étapes à volonté ;
    - elles sont lentes ou payantes (appels à Claude) : elles ne doivent pas
      bloquer ni faire échouer le scraping ;
    - elles ont besoin de l'état de la base (version du prompt déjà appliquée, ensemble
      des spots pour trouver les doublons).
"""

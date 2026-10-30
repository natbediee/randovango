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

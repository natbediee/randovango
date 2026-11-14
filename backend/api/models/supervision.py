"""
Les corps des demandes de la supervision (carte #186), vérifiés par Pydantic avant d'entrer dans la route.

Un champ manquant ou d'un mauvais type est refusé (422) avec un message qui nomme le champ : la route n'a plus à le
vérifier à la main. Ce qui reste vérifié par les services, ce sont les règles du métier (une décision permise, une
note connue), pas les types. Les modèles arrivent avec la route qui les utilise.
"""
from pydantic import BaseModel


class TextCorrection(BaseModel):
    """
    Le texte « À savoir » corrigé d'une décision sur un spot (PUT /decisions/{id}) : une phrase par ligne, vide s'il
    n'y a plus rien à signaler. La décision elle-même (garder ou retirer) ne change pas.
    """
    a_savoir: str

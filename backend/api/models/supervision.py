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


class SheetCorrection(BaseModel):
    """
    Les champs corrigés de la fiche d'un service (PUT /services/{poi_id}) : seuls les champs changés sont envoyés,
    par exemple {"name": "Chez Sylvain", "maps_url": "https://maps.app.goo.gl/..."}. La valeur de chaque champ est
    contrôlée par le service (services_edit.decide_sheet), qui refuse une fiche sans changement.

    note : facultative, gardée avec la décision. file : la file de relecture d'où vient la correction (« liens »,
    « fermetures »…) ; corriger le champ que cette file met en doute la tranche. Absente, la correction vient de Modifier.
    """
    changes: dict
    note: str = ""
    file: str | None = None

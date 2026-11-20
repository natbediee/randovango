"""
Les corps des demandes de la supervision (carte #186), vérifiés par Pydantic avant d'entrer dans la route.

Un champ manquant ou d'un mauvais type est refusé (422) avec un message qui nomme le champ : la route n'a plus à le
vérifier à la main. Ce qui reste vérifié par les services, ce sont les règles du métier (une décision permise, une
note connue), pas les types. Les modèles arrivent avec la route qui les utilise.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field


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


class SpotDecision(BaseModel):
    """
    Décider sur un spot remonté par les agents (POST /decisions, "objet": "spot") : le garder ou le retirer.
    a_savoir : le texte corrigé, une phrase par ligne ; absent, celui de l'agent reste.
    pertinence et raison : la note facultative de la proposition de l'agent (carte #201) ; vides, pas de note.
    """
    objet: Literal["spot"]
    objet_id: int
    decision: Literal["garder", "retirer"]
    note: str = ""
    a_savoir: str | None = None
    pertinence: str | None = None
    raison: str | None = None


class OpeningDecision(BaseModel):
    """
    Les dates d'ouverture d'un spot (POST /decisions, "objet": "ouverture"), tapées dans Modifier.
    statut : toute l'année, une période, la saison, ou inconnue ; debut et fin (« JJ/MM ») ne servent qu'à une période.
    convention : l'admin a choisi ces dates, la fiche du spot ne les donne pas.
    """
    objet: Literal["ouverture"]
    objet_id: int
    statut: str
    debut: str | None = None
    fin: str | None = None
    convention: bool = False
    note: str = ""


class ServiceDecision(BaseModel):
    """
    Décider sur un service (POST /decisions, "objet": "service") : decision est l'action choisie (« retirer »,
    « autre_nom », « valider_lien »…), contrôlée par le service.
    objet_ids : un service, ou un lot de liens contrôlés (« valider_lien » dans la file « liens »).
    file : la file de relecture d'où vient la décision (page Services) ; absente, elle vient de Modifier.
    mois, url, nom : ce que l'admin a choisi ou tapé (mois d'ouverture, lien trouvé, nouveau nom).
    pertinence et raison : la note facultative de la proposition de l'agent (carte #201), pour un seul service.
    """
    objet: Literal["service"]
    objet_ids: list[int] = Field(min_length=1)
    decision: str
    file: str | None = None
    note: str = ""
    mois: list[int] | None = None
    url: str | None = None
    nom: str | None = None
    pertinence: str | None = None
    raison: str | None = None


# Le corps de POST /decisions : le champ « objet » dit lequel des modèles s'applique (un « discriminant »).
# Pydantic lit d'abord « objet », puis vérifie les champs du bon modèle ; /docs montre les formes possibles.
Decision = Annotated[SpotDecision | OpeningDecision | ServiceDecision, Field(discriminator="objet")]


class PassageRequest(BaseModel):
    """
    Lancer un passage d'une chaîne d'agents sur une ville (POST /passages, issue #204), toujours en vraie mise à jour :
    {"chaine": "services", "ville_id": 12, "categories": ["restaurants", "laveries"]}
    chaine : la chaîne à lancer ; seule « services » est branchée aujourd'hui, les autres viendront avec #276.
    ville_id : la ville de l'appli (cities.id). categories : celles à mettre à jour ; absentes, toutes celles de la chaîne.
    """
    chaine: str
    ville_id: int
    categories: list[str] | None = None


class AgentSettingsRequest(BaseModel):
    """
    Changer le réglage des agents (PUT /passages/reglage, issue #211). Seuls les champs envoyés changent :
    {"services_apres_etl": false} coupe la mise à jour automatique sans toucher au budget.
    services_apres_etl : la chaîne des services se lance-t-elle seule à la fin de l'ETL d'une nouvelle ville ?
    Les montants sont en euros TTC, jamais négatifs : enveloppe_du_mois_eur, plafond_du_jour_eur, et reserve_vany_eur,
    la part du mois gardée pour Vany. La dépense des agents, en dollars, est convertie au taux de la BCE (#275).
    raison : pourquoi l'admin change le réglage, en texte libre (facultatif), gardé avec le changement.
    """
    services_apres_etl: bool | None = None
    enveloppe_du_mois_eur: float | None = Field(default=None, ge=0)
    plafond_du_jour_eur: float | None = Field(default=None, ge=0)
    reserve_vany_eur: float | None = Field(default=None, ge=0)
    raison: str | None = Field(default=None, max_length=255)

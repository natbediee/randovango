"""
La notation d'une proposition de l'agent par l'humain qui la tranche (carte #201).

À côté de sa décision, la superviseuse peut dire si la proposition de l'agent était juste, à corriger ou fausse, et,
quand elle ne l'était pas, pourquoi. Ces notes, enregistrées dans decisions.pertinence et decisions.raison, forment le
jeu d'évaluation de la chaîne des services (#114) : elles disent quelle consigne de l'agent corriger en premier.

Les valeurs permises sont écrites ICI SEULEMENT : les routes de supervision les vérifient avec check_rating, la page
reçoit leurs libellés, le bilan les compte. La notation est facultative : sans elle, une décision vaut comme avant.
"""

# La proposition de l'agent, vue par l'humain : {valeur enregistrée: libellé affiché}.
PERTINENCES = {
    "juste": "juste",
    "a_corriger": "à corriger",
    "fausse": "fausse",
}

# Les pertinences qui demandent une raison : une proposition juste n'a pas d'erreur à expliquer.
NEEDS_REASON = ("a_corriger", "fausse")

# La cause de l'erreur, la même liste pour les spots et les services : {valeur enregistrée: libellé affiché}.
RAISONS = {
    "nom_adresse": "nom ou adresse faux",
    "ferme_non_vu": "fermé non vu",
    "doublon_rate": "doublon raté",
    "pas_un_service": "pas un service pour le voyageur",
    "preuve_faible": "preuve faible ou ancienne",
    "categorie": "mauvaise catégorie",
    "autre": "autre",
}


def check_rating(pertinence: str | None, raison: str | None) -> None:
    """
    Vérifie une notation reçue de la page ; lève ValueError si elle ne va pas. Rien du tout (None, None) est permis :
    une décision sans notation reste valable. Une chaîne vide compte comme rien (une liste laissée sur « — »).
    """
    # list(...) plutôt que le dictionnaire : une valeur bizarre (une liste) est refusée au lieu de faire planter la route.
    if pertinence and pertinence not in list(PERTINENCES):
        raise ValueError(f"Pertinence inconnue : {pertinence}")
    if raison and raison not in list(RAISONS):
        raise ValueError(f"Raison inconnue : {raison}")
    if raison and pertinence not in NEEDS_REASON:
        raise ValueError("Une raison ne se donne que pour une proposition à corriger ou fausse")


def labels() -> dict:
    """Les libellés de la notation, pour que la page affiche exactement les valeurs que le serveur accepte."""
    return {"pertinences": PERTINENCES, "raisons": RAISONS, "avec_raison": list(NEEDS_REASON)}

"""
Les décisions de la supervision, écrites à un seul endroit (carte #186).

Chaque geste de l'admin dans la supervision (garder ou retirer un spot, fixer son ouverture, trancher un service,
corriger un service dans « Modifier ») laisse une ligne dans la table `decisions`. Cette ligne sert à trois choses :
- tracer qui a décidé quoi et quand ;
- garder dans `detail.avant` l'état d'avant, pour que l'annulation remette tout comme avant ;
- faire primer l'humain : les agents, les règles et l'affichage relisent ces décisions et ne défont jamais ce qu'un
  humain a tranché.

Avant cette carte, sept fonctions écrivaient chacune leur propre `INSERT INTO decisions`. Elles appellent toutes
`record_decision` désormais : la note coupée à 255 caractères et le détail mis en JSON se font ici, une seule fois.
"""
import json

# Longueur de la colonne `note` dans la table `decisions` (VARCHAR(255)).
NOTE_MAX_LENGTH = 255


def clean_note(note: str | None) -> str | None:
    """
    La note libre de l'admin, prête à enregistrer : espaces en trop retirés, coupée à la taille de la colonne.
    Une note vide devient None (NULL en base), pour qu'aucune page n'affiche une note « » vide.
    """
    return (note or "").strip()[:NOTE_MAX_LENGTH] or None


def record_decision(cursor, objet_type: str, objet_id: int, decision: str, note: str | None, decided_by: str,
                    detail: dict, *, verification_id: int | None = None, a_savoir_corrige: str | None = None,
                    pertinence: str | None = None, raison: str | None = None) -> None:
    """
    Enregistre une décision de l'admin, dans la transaction du curseur reçu : c'est l'appelant qui valide (commit),
    pour que la décision et les changements qu'elle entraîne (spot, service, signaux) passent ensemble ou pas du tout.

    objet_type : ce qui est décidé (spot, ouverture, poi). decided_by : le compte admin passé par la route.
    detail : ce qu'il faut pour annuler (`avant`) et pour relire la décision plus tard ; enregistré en JSON.
    Les quatre derniers champs ne servent qu'à certaines décisions et restent vides (NULL) sinon :
    verification_id et a_savoir_corrige pour un spot, pertinence et raison pour la note donnée à la proposition de
    l'agent (carte #201).
    """
    # default=str : un détail peut contenir une date ou un nombre décimal lu en base, que JSON ne sait pas écrire seul.
    detail_json = json.dumps(detail, ensure_ascii=False, default=str)
    cursor.execute("""
        INSERT INTO decisions (objet_type, objet_id, decision, note, decided_by, decided_at, verification_id,
                               a_savoir_corrige, pertinence, raison, detail)
        VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
    """, (objet_type, objet_id, decision, clean_note(note), decided_by, verification_id, a_savoir_corrige,
          pertinence, raison, detail_json))

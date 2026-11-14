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

De même, une seule fonction annule : `cancel_decision`. Elle lit le type de la décision avant de la défaire. Avant,
chaque page avait sa propre annulation, et celle des spots acceptait n'importe quel numéro : un numéro de service
reçu par erreur était marqué annulé sans que le service soit remis comme avant.
"""
import json

from utils.db_utils import MySQLUtils

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


def read_detail(stored) -> dict:
    """
    Le détail d'une décision, lu en base. Il arrive en texte JSON, parfois déjà converti en dictionnaire par le
    connecteur, et vaut NULL pour les plus anciennes décisions sur les spots, d'avant `detail`.
    """
    if isinstance(stored, str):
        return json.loads(stored)
    return stored or {}


def cancel_decision(decision_id: int) -> None:
    """
    Annule une décision (erreur de clic, avis changé) : ce qu'elle avait changé revient comme avant, puis elle est
    marquée annulée (`annulee_at`). Elle reste en base : rien n'est effacé, l'historique garde la trace du geste.

    Refuse (ValueError, que la route rend en 422) une décision inconnue ou déjà annulée : annuler deux fois
    remettrait un état d'avant par-dessus un état qui a pu changer depuis (cas du double clic).
    """
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT objet_type, objet_id, detail FROM decisions WHERE id = %s AND annulee_at IS NULL",
                       (decision_id,))
        decision = cursor.fetchone()
        if not decision:
            raise ValueError("Décision introuvable ou déjà annulée")
        undo = _undo_function(decision["objet_type"])
        undo(cursor, decision["objet_id"], read_detail(decision["detail"]))
        cursor.execute("UPDATE decisions SET annulee_at = NOW() WHERE id = %s", (decision_id,))
        connection.commit()
        cursor.close()
    except Exception:
        # Rien de partiel : si une étape échoue, la décision et ce qu'elle avait changé restent comme avant.
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)


def _undo_function(objet_type: str):
    """
    La fonction qui défait une décision de ce type. Chacune vit à côté du code qui prend la décision, car c'est lui
    qui sait quoi remettre.
    """
    # Import ici et pas en tête du fichier : spots_review et services_review importent déjà ce fichier
    # (record_decision). Importés en tête, les deux fichiers s'attendraient l'un l'autre au démarrage.
    from services.supervision import services_review, spots_review

    undo_functions = {
        spots_review.SPOT: spots_review.undo_spot_decision,
        spots_review.OPENING_OBJECT: spots_review.undo_opening_decision,
        services_review.POI: services_review.undo_service_decision,
    }
    if objet_type not in undo_functions:
        raise ValueError(f"Type de décision inconnu : {objet_type}")
    return undo_functions[objet_type]

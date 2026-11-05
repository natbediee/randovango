"""
Les spots qu'on peut proposer à un voyageur pour une nuit donnée.

C'est la seule porte d'entrée : l'étape 3 et le voyage préparé par Vany passent ici, pour qu'un
spot écarté ne revienne jamais par un autre chemin. Sont écartés :
    - les types jamais affichés (HIDDEN_SPOT_TYPES), les doublons, les fiches disparues de p4n ;
    - les lieux où l'on ne peut pas dormir (nuit_interdite) ;
    - les spots retirés ou à relire dans /supervision (hidden_spot_ids) ;
    - les spots fermés à la date de la nuit.

Les dates d'ouverture sont remplies par agents.read_openings, qui traduit le texte de la fiche. La
décision, elle, est prise ici, sans IA, à chaque demande : elle dépend de la date du voyage.
"""
from datetime import date

from services.supervision_service import hidden_spot_ids
from utils.display_utils import HIDDEN_SPOT_TYPES

PERIOD = "periode"
SEASON = "saison"
# Convention quand la fiche donne une seule date, ou une saison sans date : ni le texte de la fiche ni
# la base ne la portent.
DEFAULT_START = "04-01"
DEFAULT_END = "10-31"


def is_open_on(status: str | None, start: str | None, end: str | None, night: date) -> bool:
    """
    Le lieu est-il ouvert cette nuit-là ? `start` et `end` au format MM-JJ, sans année.
    Seule une période ou une saison connue peut fermer un spot : on ne masque pas ce qu'on ignore.
    Une seule borne connue, ou une saison sans date : la valeur par défaut remplace ce qui manque, pour ne pas
    proposer un camping en plein hiver.
    `end` avant `start` : la période passe par le 1er janvier.
    """
    if status not in (PERIOD, SEASON) or (status == PERIOD and not (start or end)):
        return True
    day = f"{night:%m-%d}"
    start, end = start or DEFAULT_START, end or DEFAULT_END
    return start <= day <= end if start <= end else day >= start or day <= end


def proposable_spots(connection, cursor, box: tuple, night: date) -> list:
    """Les spots proposables dans `box` (lat min, lon min, lat max, lon max), triés par nom."""
    min_lat, min_lon, max_lat, max_lon = box
    type_placeholders = ",".join(["%s"] * len(HIDDEN_SPOT_TYPES))
    cursor.execute(f'''
        SELECT s.id, s.name, s.description, s.type, s.latitude, s.longitude, s.rating, s.url, s.verifie, s.address,
               s.place_label, s.city_label, s.description_ia, s.prompt_version,
               s.ouverture_statut, s.ouverture_debut, s.ouverture_fin
        FROM spots s
        WHERE s.latitude BETWEEN %s AND %s
            AND s.longitude BETWEEN %s AND %s
            AND s.type IS NOT NULL
            AND s.type NOT IN ({type_placeholders})
            AND s.duplicate_of_spot_id IS NULL
            AND s.p4n_removed = 0
            AND (s.nuit_interdite IS NULL OR s.nuit_interdite = 0)
        ORDER BY s.name ASC
    ''', (min_lat, max_lat, min_lon, max_lon, *HIDDEN_SPOT_TYPES))
    rows = cursor.fetchall()
    hidden = hidden_spot_ids(connection, cursor, night)
    return [spot for spot in rows if spot["id"] not in hidden
            and is_open_on(spot["ouverture_statut"], spot["ouverture_debut"], spot["ouverture_fin"], night)]

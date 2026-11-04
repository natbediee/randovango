"""
Enregistre ce que les vérifications disent des POI, SANS TOUCHER À LA TABLE poi :
    poi_checks  : la dernière réponse de chaque source, pour reprendre un passage interrompu ;
    poi_signals : ce qui est à relire. Rejouer un passage met le détail à jour, sans jamais
                  effacer une relecture déjà faite.
Les tables sont créées par db_init/db_randovango.py.
"""
import json
from datetime import datetime

from utils.db_utils import MySQLUtils

def save_check(cursor, poi_id: int, source: str, result: dict) -> None:
    cursor.execute(
        """INSERT INTO poi_checks (poi_id, source, checked_at, result) VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE checked_at = VALUES(checked_at), result = VALUES(result)""",
        (poi_id, source, datetime.now(), json.dumps(result, ensure_ascii=False)))


def save_signal(cursor, poi_id: int, source: str, signal_type: str, detail: dict) -> None:
    cursor.execute(
        """INSERT INTO poi_signals (poi_id, source, signal_type, detail, detected_at) VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE detail = VALUES(detail)""",
        (poi_id, source, signal_type, json.dumps(detail, ensure_ascii=False), datetime.now()))


def checked_ids(source: str) -> set:
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    cursor.execute("SELECT poi_id FROM poi_checks WHERE source = %s", (source,))
    ids = {row[0] for row in cursor.fetchall()}
    cursor.close()
    MySQLUtils.disconnect(connection)
    return ids

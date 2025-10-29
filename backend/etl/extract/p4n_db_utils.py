
from utils.mysql_utils import MySQLUtils

def p4n_id_exists(p4n_id: str) -> bool:
    """
    Vérifie si un p4n_id existe déjà dans la table spots (MySQL).
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT 1 FROM spots WHERE p4n_id = %s LIMIT 1", (p4n_id,))
    exists = cursor.fetchone() is not None
    cursor.close()
    MySQLUtils.disconnect(conn)
    return exists

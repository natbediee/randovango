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

def get_all_city_ids():
    """
    Retourne la liste de tuples (id, name) pour toutes les villes.
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT id, name FROM cities")
    rows = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(conn)
    return [(row[0], row[1]) for row in rows]

def get_histo_poi_city_ids():
    """
    Retourne la liste des city_id présents dans histo_poi.
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT DISTINCT city_id FROM histo_poi")
    ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    MySQLUtils.disconnect(conn)
    return ids

def get_histo_scrap_city_ids():
    """
    Retourne la liste des city_id présents dans histo_scrap.
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT DISTINCT city_id FROM histo_scrap")
    ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    MySQLUtils.disconnect(conn)
    return ids

def gpx_already_in_mysql(fname: str) -> bool:
    """
    Vérifie si un fichier GPX (par son nom) existe déjà dans la table hikes (MySQL).
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT 1 FROM hikes WHERE filename = %s LIMIT 1", (fname,))
    exists = cursor.fetchone() is not None
    cursor.close()
    MySQLUtils.disconnect(conn)
    return exists

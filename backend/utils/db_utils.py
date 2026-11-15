import mysql.connector
from contextlib import contextmanager
from dotenv import load_dotenv
from pathlib import Path
from utils.service_utils import ServiceUtil

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT/".env")


class MySQLUtils:
    """Utilitaire statique pour MySQL."""
    @staticmethod
    def connect():
        ServiceUtil.load_env()
        return mysql.connector.connect(
            host=ServiceUtil.get_env('DB_HOST'),
            user=ServiceUtil.get_env('DB_USER'),
            password=ServiceUtil.get_env('DB_PSWD'),
            database=ServiceUtil.get_env('DB_NAME'),
            charset='utf8mb4'
        )

    @staticmethod
    def get_cursor(conn):
        return conn.cursor()

    @staticmethod
    def disconnect(conn):
        if conn:
            conn.close()

    # POURQUOI CETTE FONCTION (issue #206)
    # Une connexion ouverte puis oubliée reste prise sur le serveur MySQL. Une fuite de ce genre a déjà bloqué
    # l'étape 3 (erreur 500, table verrouillée) : une erreur survenait avant le disconnect, qui n'était jamais appelé.
    # open_cursor s'utilise avec « with », qui garantit la fermeture :
    #
    #     with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
    #         cursor.execute("SELECT ...")
    #         rows = cursor.fetchall()
    #
    # Comment marche le « with » : Python exécute le début de la fonction (ouverture de la connexion et du curseur)
    # jusqu'au « yield », qui donne (cnx, cursor) au bloc. Puis il exécute le bloc. En sortant du bloc, de quelque
    # façon que ce soit (fin normale, return, raise HTTPException, erreur MySQL), il revient dans la fonction et
    # passe par le « finally », qui ferme le curseur puis la connexion. L'erreur éventuelle continue ensuite son
    # chemin, comme avant : rien n'est avalé.
    @staticmethod
    @contextmanager
    def open_cursor(dictionary=False):
        """Ouvre une connexion et un curseur pour un bloc « with », et les ferme tous deux à la sortie, même en cas d'erreur."""
        # connect et disconnect passent par MySQLUtils : les tests les remplacent par de fausses connexions.
        cnx = MySQLUtils.connect()
        cursor = None  # reste None si la création du curseur échoue : il n'y a alors rien à fermer de ce côté
        try:
            cursor = cnx.cursor(dictionary=dictionary)
            yield cnx, cursor
        finally:
            if cursor is not None:
                cursor.close()
            MySQLUtils.disconnect(cnx)

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

def get_histo_poi_city_ids(source: str):
    """
    Retourne la liste des city_id ayant déjà au moins un POI chargé pour la
    source donnée ('osm' ou 'wikidata'). Suivi par source (et non par ville
    seule) : une ville où seule Wikidata a réussi doit pouvoir être retentée
    pour OSM, et inversement.
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute(
        """
        SELECT DISTINCT hp.city_id
        FROM histo_poi hp
        JOIN poi p ON hp.poi_id = p.id
        JOIN sources s ON p.source_id = s.id
        WHERE s.name = %s
        """,
        (source,)
    )
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

import pandas as pd
from etl.load.load_poi_checks import save_check
from etl.transform.transform_osm import PUBLIC_FACILITY_TYPES
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils
from utils.geo_utils import address_with_commune
from utils.service_utils import ServiceUtil, SERVICE_CATEGORY_LABEL_MAP
logger = LoggerUtil.get_logger("etl_poi")

def insert_service_and_link(cursor, poi_id, type_value):
    """
    Crée le service (category+name) si besoin et lie le POI à ce service dans poi_service.
    """
    
    name_value = SERVICE_CATEGORY_LABEL_MAP.get(type_value, type_value)
    # Vérifier si la catégorie existe déjà dans services (category + name)
    cursor.execute("SELECT id FROM services WHERE category = %s AND name = %s", (type_value, name_value))
    service_res = cursor.fetchone()
    if service_res:
        service_id = service_res[0]
    else:
        cursor.execute("INSERT INTO services (category, name) VALUES (%s, %s)", (type_value, name_value))
        service_id = cursor.lastrowid
    # Lier poi et service
    cursor.execute("INSERT IGNORE INTO poi_service (poi_id, service_id) VALUES (%s, %s)", (poi_id, service_id))


def insert_histo_poi(cursor, poi_id, city_name):
    """
    Insère le lien entre un POI et une ville dans la table histo_poi, à partir du nom de la ville.
    """
    city_id = ServiceUtil.get_city_id(cursor, city_name)
    if city_id:
        cursor.execute(
            """
            INSERT IGNORE INTO histo_poi (poi_id, city_id)
            VALUES (%s, %s)
            """,
            (poi_id, city_id)
        )

def _value_or_none(value):
    """Une case vide du tableau pandas (NaN) devient None : MySQL n'accepte pas NaN."""
    return None if pd.isna(value) else value


def save_public_access(cursor, poi_id: int, row) -> None:
    """
    Écrit à qui une toilette ou une douche est ouverte (acces_osm) et si elle est payante (payant).
    Un UPDATE et pas l'INSERT : l'INSERT IGNORE ne touche pas une toilette déjà en base, qui doit être reprise
    à chaque passage de l'ETL. Une étiquette retirée dans OSM revient ainsi à NULL (issue #193).
    """
    if row.get('type') not in PUBLIC_FACILITY_TYPES:
        return
    payant = _value_or_none(row.get('payant'))
    cursor.execute("UPDATE poi SET acces_osm = %s, payant = %s WHERE id = %s",
                   (_value_or_none(row.get('access')), None if payant is None else int(payant), poi_id))


def get_or_create_source(cursor, source_name):
    cursor.execute("SELECT id FROM sources WHERE name = %s", (source_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    cursor.execute("INSERT INTO sources (name) VALUES (%s)", (source_name,))
    return cursor.lastrowid

def load_osm_poi(df_osm: pd.DataFrame, city_name: str):
    """
    Insère les POI OSM dans la table poi avec mapping explicite.
    osm_id → original_id, name → name, description → description, type → service_category, lat/lon → latitude/longitude
    """
    if df_osm is None or df_osm.empty:
        logger.warning("[load_osm_poi] : Aucun POI OSM à insérer.")
        return
    # Remplacer les NaN par None pour éviter les erreurs MySQL
    df_osm = df_osm.where(pd.notnull(df_osm), None)
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (cnx, cursor):
        source_id = get_or_create_source(cursor, 'osm')
        for _, row in df_osm.iterrows():
            # Insertion dans poi sans city_id ni type
            cursor.execute(
                """
                INSERT IGNORE INTO poi (original_id, name, description, latitude, longitude, url, source_id, verifie, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s,1, %s)
                """,
                (
                    row.get('osm_id'),
                    row.get('name'),
                    row.get('description'),
                    row.get('lat'),
                    row.get('lon'),
                    row.get('website'),
                    source_id,
                    # La commune après le code postal, le lieu-dit sur sa propre ligne (issue #184).
                    address_with_commune(row.get('address'), row.get('lat'), row.get('lon'))
                )
            )
            # Récupérer l'id du poi inséré
            poi_id = cursor.lastrowid
            if not poi_id:
                # Si déjà existant, récupérer l'id
                cursor.execute("SELECT id FROM poi WHERE original_id = %s AND source_id = %s", (row.get('osm_id'), source_id))
                res = cursor.fetchone()
                if res:
                    poi_id = res[0]
            # Insérer le lien dans histo_poi
            if poi_id:
                insert_histo_poi(cursor, poi_id, city_name)
                # Insérer le type dans la table service si besoin, puis lier dans poi_service
                if row.get('type'):
                    insert_service_and_link(cursor, poi_id, row.get('type'))
                save_public_access(cursor, poi_id, row)
                # Téléphone et horaires : pas encore de colonne dans poi, gardés pour la vérification.
                if row.get('osm_details'):
                    save_check(cursor, poi_id, 'osm', {**row.get('osm_details'), 'present': True})
        cnx.commit()
        logger.info(f"[load_osm_poi] : {len(df_osm)} POI OSM insérés pour {city_name}.")

def load_wikidata_poi(df_wiki: pd.DataFrame, city_name: str):
    """
    Insère les POI Wikidata dans la table poi avec mapping adapté.
    wikidata_id → original_id, name → name, description → description, type → service_category, lat/lon → latitude/longitude
    """
    if df_wiki is None or df_wiki.empty:
        logger.warning("[load_wikidata_poi] : Aucun POI Wikidata à insérer.")
        return
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (cnx, cursor):
        source_id = get_or_create_source(cursor, 'wikidata')
        df_wiki = df_wiki.where(pd.notnull(df_wiki), None)
        for _, row in df_wiki.iterrows():
            # Insertion dans poi sans city_id ni type
            cursor.execute(
                """
                INSERT IGNORE INTO poi (original_id, name, description, latitude, longitude, image_url, source_id, verifie)
                VALUES (%s, %s, %s, %s, %s, %s, %s,1)
                """,
                (
                    row.get('wikidata_id'),
                    row.get('name'),
                    row.get('description'),
                    row.get('lat'),
                    row.get('lon'),
                    row.get('image_url'),
                    source_id
                )
            )
            # Récupérer l'id du poi inséré
            poi_id = cursor.lastrowid
            if not poi_id:
                # Si déjà existant, récupérer l'id
                cursor.execute("SELECT id FROM poi WHERE original_id = %s AND source_id = %s", (row.get('wikidata_id'), source_id))
                res = cursor.fetchone()
                if res:
                    poi_id = res[0]
            # Insérer le lien dans histo_poi
            if poi_id:
                insert_histo_poi(cursor, poi_id, city_name)
                # Insérer le type dans la table service si besoin, puis lier dans poi_service
                if row.get('type'):
                    insert_service_and_link(cursor, poi_id, row.get('type'))
        cnx.commit()
        logger.info(f"[load_wikidata_poi] : {len(df_wiki)} POI Wikidata insérés pour {city_name}.")

import pandas as pd

from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil
from utils.db_utils import MySQLUtils

def load_p4n_to_mysql(df: pd.DataFrame, city: str) -> None:
    """
    Charge un DataFrame transformé Park4Night dans la base MySQL.
    La ville utilisée est celle passée explicitement par le pipeline (issue du GPX).
    """
    logger = LoggerUtil.get_logger("etl_p4n")
    if not isinstance(df, pd.DataFrame):
        logger.error("[load] : Le premier argument doit être un DataFrame transformé (pas de compatibilité CSV).")
        return
    logger.info(f"[load] : Chargement de {len(df)} lignes depuis DataFrame fourni")
    # Remplacer tous les NaN par None pour éviter les erreurs MySQL
    df = df.where(pd.notnull(df), None)
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    # Gestion de la source (Park4Night)
    source_name = 'Park4Night'
    cursor.execute("SELECT id FROM sources WHERE name = %s", (source_name,))
    result = cursor.fetchone()
    if result:
        source_id = result[0]
    else:
        cursor.execute("INSERT INTO sources (name) VALUES (%s)", (source_name,))
        conn.commit()
        source_id = cursor.lastrowid

    conn = MySQLUtils.connect()
    cursor = conn.cursor(buffered=True)

    # Récupère tous les p4n_id déjà présents dans spots
    cursor.execute("SELECT p4n_id FROM spots")
    existing_ids = set(str(row[0]) for row in cursor.fetchall())
    logger.info(f"[load] : {len(existing_ids)} p4n_id déjà présents dans la table spots")

    # Filtre le DataFrame pour ne garder que les nouveaux p4n_id
    df_new = df[~df['p4n_id'].astype(str).isin(existing_ids)]
    logger.info(f"[load] : {len(df_new)} nouveaux spots à insérer")

    # Prépare les requêtes
    insert_spot_sql = """
        INSERT INTO spots (name, description, type, latitude, longitude, p4n_id, rating, url, source_id, verifie)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,1)
    """
    # select_service_sql = "SELECT id FROM services WHERE name=%s"
    # insert_service_sql = "INSERT INTO services (name, category) VALUES (%s, %s)"
    insert_spot_service_sql = "INSERT IGNORE INTO spot_service (spot_id, service_id) VALUES (%s, %s)"

    # Prépare la requête pour histo_ (ou city_spot_scraped)
    insert_histo_sql = """
        INSERT IGNORE INTO histo_scrap (spot_id, city_id, scraped_at)
        VALUES (%s, %s, NOW())
    """
   
    # Utilise uniquement la ville passée explicitement (issue du GPX)
    if not city:
        logger.error("[load] : Aucune ville fournie par le pipeline. Aucune insertion ne sera effectuée.")
        return
    cursor.execute("SELECT id FROM cities WHERE name = %s", (city,))
    result = cursor.fetchone()
    if result:
        city_id = result[0]
    else:
        logger.error(f"[load] : Ville '{city}' absente de la base. Aucune insertion ne sera effectuée.")
        return

    logger.info(f"[load] : Ville utilisée pour l'insertion : {city} (id={city_id})")
    for _, row in df_new.iterrows():
        # 1. Insert spot
        spot_values = (
            row['Nom_Place'],
            row['Description'],
            row['Type_Place'],
            row['latitude'],
            row['longitude'],
            row['p4n_id'],
            row['note'],
            row['URL_fiche'],
            source_id
        )
        cursor.execute(insert_spot_sql, spot_values)
        spot_id = cursor.lastrowid
        logger.info(f"[load] : Spot inséré - Nom: {row['Nom_Place']}, p4n_id: {row['p4n_id']}, ville: {city}, spot_id: {spot_id}")

        # 2. Insert services et liaisons
        services = [s.strip() for s in str(row['Services']).split(',') if s.strip()]
        for service in services:
            service_id = ServiceUtil.get_or_create_service_with_category(cursor, service)
            cursor.execute(insert_spot_service_sql, (spot_id, service_id))
            logger.info(f"[load] : Service lié - spot_id: {spot_id}, service: {service}, service_id: {service_id}")

        # 3. Ajout dans histo_scrap (ou city_spot_scraped) avec la ville principale
        cursor.execute(insert_histo_sql, (spot_id, city_id))
        logger.info(f"[load] : Ajout dans histo_scrap - spot_id: {spot_id}, city_id: {city_id}")

    conn.commit()
    logger.info(f"[load] : {len(df_new)} nouveaux spots insérés avec services associés.")
    cursor.close()
    MySQLUtils.disconnect(conn)
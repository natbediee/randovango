import pandas as pd

from backend.utils.logger_util import LoggerUtil
from backend.utils.service_utils import ServiceUtil
from backend.utils.mysql_utils import MySQLUtils
from backend.etl.extract.api_meteo import get_or_create_city
from backend.utils.service_category_map import SERVICE_CATEGORY_MAP

def load_p4n_to_mysql(csv_path: str, table_name: str = 'p4n_spots'):
    logger = LoggerUtil.get_logger('load_p4n')
    if isinstance(csv_path, pd.DataFrame):
        df = csv_path
        logger.info(f"Chargement de {len(df)} lignes depuis DataFrame fourni")
    else:
        df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
        logger.info(f"Chargement de {len(df)} lignes depuis {csv_path}")

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
    """
    Charge un DataFrame transformé Park4Night dans la base MySQL.
    Peut aussi accepter un chemin CSV pour compatibilité, mais privilégier le DataFrame.
    La colonne 'city' doit obligatoirement être présente dans le DataFrame.
    """
    logger = LoggerUtil.get_logger('load_p4n')
    if isinstance(csv_path, pd.DataFrame):
        df = csv_path
        logger.info(f"Chargement de {len(df)} lignes depuis DataFrame fourni")
    else:
        df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
        logger.info(f"Chargement de {len(df)} lignes depuis {csv_path}")

    # Remplacer tous les NaN par None pour éviter les erreurs MySQL
    df = df.where(pd.notnull(df), None)

    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)

    # Récupère tous les p4n_id déjà présents dans spots
    cursor.execute("SELECT p4n_id FROM spots")
    existing_ids = set(str(row[0]) for row in cursor.fetchall())
    logger.info(f"{len(existing_ids)} p4n_id déjà présents dans la table spots")

    # Filtre le DataFrame pour ne garder que les nouveaux p4n_id
    df_new = df[~df['p4n_id'].astype(str).isin(existing_ids)]
    logger.info(f"{len(df_new)} nouveaux spots à insérer")

    # Prépare les requêtes
    insert_spot_sql = """
        INSERT INTO spots (name, description, type, latitude, longitude, p4n_id, rating, url, source_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    select_service_sql = "SELECT id FROM services WHERE name=%s"
    insert_service_sql = "INSERT INTO services (name, category) VALUES (%s, %s)"
    insert_spot_service_sql = "INSERT IGNORE INTO spot_service (spot_id, service_id) VALUES (%s, %s)"

    # Prépare la requête pour histo_scrapt (ou city_spot_scraped)
    insert_histo_sql = """
        INSERT IGNORE INTO histo_scrapt (spot_id, city_id, scraped_at)
        VALUES (%s, %s, NOW())
    """
   
    # La colonne city doit être présente et non vide, sinon on bloque toute insertion
    if 'city' not in df_new.columns or df_new['city'].isnull().all():
        logger.error("La colonne 'city' doit être présente et non vide dans le CSV transformé. Aucune insertion ne sera effectuée.")
        return
    main_city = df_new['city'].mode()[0]
    # Utilise les coordonnées du premier spot dont city == main_city
    match = df_new[df_new['city'] == main_city]
    if not match.empty:
        lat, lon = match.iloc[0]['latitude'], match.iloc[0]['longitude']
    else:
        lat, lon = None, None
    city_id = get_or_create_city(main_city, lat, lon)

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

        # 2. Insert services et liaisons
        services = [s.strip() for s in str(row['Services']).split(',') if s.strip()]
        for service in services:
            # Catégorisation souple (proche OSM)
            category = SERVICE_CATEGORY_MAP.get(service)
            if category is None:
                logger.warning(f"Service non mappé : '{service}' (category=NULL)")
            # Vérifie si le service existe déjà
            cursor.execute(select_service_sql, (service,))
            res = cursor.fetchone()
            if res:
                service_id = res[0]
            else:
                cursor.execute(insert_service_sql, (service, category))
                service_id = cursor.lastrowid
            # Liaison spot_service
            cursor.execute(insert_spot_service_sql, (spot_id, service_id))

        # 3. Ajout dans histo_scrapt (ou city_spot_scraped) avec la ville principale
        cursor.execute(insert_histo_sql, (spot_id, city_id))

    conn.commit()
    logger.info(f"{len(df_new)} nouveaux spots insérés avec services associés.")
    cursor.close()
    MySQLUtils.disconnect(conn)

if __name__ == "__main__":
    import sys
    ServiceUtil.load_env()
    if len(sys.argv) < 2:
        print("Usage: python3 load_p4n.py <csv_path> [table_name]")
        sys.exit(1)
    csv_path = sys.argv[1]
    table = sys.argv[2] if len(sys.argv) > 2 else 'p4n_spots'
    load_p4n_to_mysql(csv_path, table)
    print(f"Chargement terminé dans la table {table}")

import sys
import time
from pathlib import Path

from utils.logger_util import LoggerUtil
sys.path.append(str(Path(__file__).resolve().parents[1]))

import mysql.connector
from utils.db_utils import MySQLUtils
from mysql.connector import Error
from utils.service_utils import ServiceUtil
logger = LoggerUtil.get_logger("db_init")

ServiceUtil.load_env()

# base mysql
DB_HOST = ServiceUtil.get_env("DB_HOST")
DB_ROOT = ServiceUtil.get_env("DB_ROOT")
DB_ROOT_PSWD = ServiceUtil.get_env("DB_ROOT_PSWD")
DB_NAME = ServiceUtil.get_env("DB_NAME")
DB_USER = ServiceUtil.get_env("DB_USER")
DB_PSWD = ServiceUtil.get_env("DB_PSWD")


def init_database():
    max_retries = 10
    retry_delay = 2  # secondes
    
    # Attendre que MySQL soit prêt
    for attempt in range(max_retries):
        try:
            test_cnx = mysql.connector.connect(
                host=DB_HOST,
                user=DB_ROOT,
                password=DB_ROOT_PSWD
            )
            test_cnx.close()
            logger.info(f"[MySQL] :✓ MySQL est prêt après {attempt + 1} tentative(s)")
            break
        except Error as err:
            if attempt < max_retries - 1:
                logger.warning(f"[MySQL] : MySQL pas encore prêt (tentative {attempt + 1}/{max_retries}): {err}")
                time.sleep(retry_delay)
            else:
                logger.error(f"[MySQL] : ✗ ERREUR: Impossible de se connecter à MySQL après {max_retries} tentatives")
                sys.exit(1)
    
    try:
    # 1. Connexion admin pour créer la base et l'utilisateur
        admin_cnx = mysql.connector.connect(
            host=DB_HOST,
            user=DB_ROOT,
            password=DB_ROOT_PSWD
        )
        admin_cursor = admin_cnx.cursor()
        admin_cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        logger.info(f"[MySQL] : Base '{DB_NAME}' créée.")
        admin_cursor.execute(
            f"CREATE USER IF NOT EXISTS '{DB_USER}'@'%' "
            f"IDENTIFIED BY '{DB_PSWD}'"
        )
        admin_cursor.execute(
            f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* "
            f"TO '{DB_USER}'@'%'"
        )
        admin_cursor.execute("FLUSH PRIVILEGES")
        admin_cnx.commit()
        admin_cursor.close()
        admin_cnx.close()
        logger.info(f"[MySQL] : Utilisateur {DB_USER} créé.")

    # Liste des statements pour la création des tables
        statements = [
            # 1. tables de base sans dépendances
            # 1. table cities
            """
            CREATE TABLE IF NOT EXISTS cities (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                department VARCHAR(255),
                region VARCHAR(255),
                country VARCHAR(255)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 2. table sources
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 3. table services
            """
            CREATE TABLE IF NOT EXISTS services (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                category VARCHAR(100)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 4. table spots (dépend de sources)
            """
            CREATE TABLE IF NOT EXISTS spots (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                type VARCHAR(100),
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                p4n_id VARCHAR(10),
                rating FLOAT,
                url VARCHAR(512),
                source_id INT,
                verifie BOOL DEFAULT FALSE,
                UNIQUE (p4n_id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 5. tables histo scrap par rapport à spots et cities
            """
            CREATE TABLE IF NOT EXISTS histo_scrap (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                spot_id INT NOT NULL,
                city_id INT NOT NULL,
                scraped_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (spot_id, city_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 6. table spot_service (association Spot <-> services)
            """
            CREATE TABLE IF NOT EXISTS spot_service (
                spot_id INT NOT NULL,
                service_id INT NOT NULL,
                PRIMARY KEY (spot_id, service_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 7. hikes (dépend de sources, cities)
            """
            CREATE TABLE IF NOT EXISTS hikes (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                start_latitude FLOAT,
                start_longitude FLOAT,
                distance_km FLOAT,
                estimated_duration_h FLOAT,
                elevation_gain_m FLOAT,
                difficulte VARCHAR(10),
                filename VARCHAR(255),
                mongo_id VARCHAR(24),
                source_id INT,
                city_id INT,
                verifie BOOL DEFAULT FALSE,
                imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES sources(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 8. poi (dépend de cities, sources)
            """
            CREATE TABLE IF NOT EXISTS poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                description TEXT,
                latitude FLOAT,
                longitude FLOAT,
                image_url VARCHAR(512),
                url VARCHAR(512),
                original_id VARCHAR(255),
                source_id INT,
                verifie BOOL DEFAULT FALSE,
                unique (original_id, source_id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 9.table histo_poi (liaison ville <-> poi, avec date)
            """
            CREATE TABLE IF NOT EXISTS histo_poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                poi_id INT NOT NULL,
                city_id INT NOT NULL,
                inserted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (poi_id, city_id),
                FOREIGN KEY (poi_id) REFERENCES poi(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 10.table poi_service (association POI <-> services)
            """
            CREATE TABLE IF NOT EXISTS poi_service (
                poi_id INT NOT NULL,
                service_id INT NOT NULL,
                PRIMARY KEY (poi_id, service_id),
                FOREIGN KEY (poi_id) REFERENCES poi(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 11. weather (dépend de cities)
            """
            CREATE TABLE IF NOT EXISTS weather (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                date DATE NOT NULL,
                temp_max_c FLOAT,
                temp_min_c FLOAT,
                precipitation_mm FLOAT,
                wind_max_kmh FLOAT,
                weather_code INT,
                solar_energy_sum FLOAT,
                city_id INT NOT NULL,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 12. trip_plans (dépend de cities)
            """
            CREATE TABLE IF NOT EXISTS trip_plans (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                start_date DATE NOT NULL,
                duration_days INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                city_id INT NOT NULL,
                user_token VARCHAR(64),
                user_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 13. trip_days (dépend de trip_plans, hikes, poi)
            """
            CREATE TABLE IF NOT EXISTS trip_days (
                id INT PRIMARY KEY AUTO_INCREMENT,
                trip_plan_id INT NOT NULL,
                day_number INT NOT NULL,
                hike_id INT,
                spot_id INT,
                FOREIGN KEY (trip_plan_id) REFERENCES trip_plans(id) ON DELETE CASCADE,
                FOREIGN KEY (hike_id) REFERENCES hikes(id),
                FOREIGN KEY (spot_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # 14. trip_day_pois (dépend de trip_days, poi)
            """
            CREATE TABLE IF NOT EXISTS trip_day_pois (
                trip_day_id INT NOT NULL,
                poi_id INT NOT NULL,
                PRIMARY KEY (trip_day_id, poi_id),
                FOREIGN KEY (trip_day_id) REFERENCES trip_days(id),
                FOREIGN KEY (poi_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
        ]
        ("- Création des tables :")
        user_cnx = MySQLUtils.connect()
        user_cursor = user_cnx.cursor()
        for stmt in statements:
            try:
                user_cursor.execute(stmt)
                try:
                    user_cursor.fetchall()
                except Exception:
                    pass
                logger.info(f"[MySQL] :→ OK : {stmt.strip().split()[5]}")
            except Exception as table_err:
                logger.error(f"[MySQL] :✗ [ERREUR SQL] lors de la création: {table_err}\nStatement:\n{stmt}")
                user_cursor.close()
                user_cnx.close()
                sys.exit(1)
        user_cnx.commit()
        user_cursor.close()
        user_cnx.close()
        logger.info("[MySQL] : Initialisation de la base terminée avec succès.")
        return True

    except Error as err:
        logger.error(f"[MySQL] :✗ [ERREUR] {err}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[MySQL] :✗ [ERREUR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_database()

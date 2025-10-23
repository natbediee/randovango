import mysql.connector
from backend.utils.mysql_utils import connect_mysql
from mysql.connector import Error
from backend.utils.service_util import ServiceUtil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ServiceUtil.load_env()

# base mysql
DB_HOST = ServiceUtil.get_env("DB_HOST")
DB_ROOT = ServiceUtil.get_env("DB_ROOT")
DB_ROOT_PSWD = ServiceUtil.get_env("DB_ROOT_PSWD")
DB_NAME = ServiceUtil.get_env("DB_NAME")
DB_USER = ServiceUtil.get_env("DB_USER")
DB_PSWD = ServiceUtil.get_env("DB_PSWD")


def init_database():
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
        print(f"Base '{DB_NAME}' créée.")
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
        print(f"Utilisateur {DB_USER} créé.")

        # Liste des statements pour la création des tables
        statements = [
            # table cities
            """
            CREATE TABLE IF NOT EXISTS cities (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table sources
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table services
            """
            CREATE TABLE IF NOT EXISTS services (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                service_type VARCHAR(100)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table hikes (ajout explicite des champs filename, city_id et description)
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
                filename VARCHAR(255),
                mongo_id VARCHAR(24),
                source_id INT,
                city_id INT,
                FOREIGN KEY (source_id) REFERENCES sources(id),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table spots
            """
            CREATE TABLE IF NOT EXISTS spots (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(100),
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                address VARCHAR(255),
                rating FLOAT,
                url VARCHAR(512),
                city_id INT,
                source_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table spot_service
            """
            CREATE TABLE IF NOT EXISTS spot_service (
                spot_id INT NOT NULL,
                service_id INT NOT NULL,
                PRIMARY KEY (spot_id, service_id),
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table poi
            """
            CREATE TABLE IF NOT EXISTS poi (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                description TEXT,
                type VARCHAR(100),
                subtype VARCHAR(100),
                latitude FLOAT,
                longitude FLOAT,
                image_url VARCHAR(512),
                url VARCHAR(512),
                mongo_id VARCHAR(24),
                city_id INT,
                source_id INT,
                FOREIGN KEY (city_id) REFERENCES cities(id),
                FOREIGN KEY (source_id) REFERENCES sources(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table weather
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
            # table trip_plans
            """
            CREATE TABLE IF NOT EXISTS trip_plans (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                start_date DATE NOT NULL,
                duration_days INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                city_id INT NOT NULL,
                user_token VARCHAR(64),
                FOREIGN KEY (city_id) REFERENCES cities(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            # table trip_days
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
            # table trip_day_pois
            """
            CREATE TABLE IF NOT EXISTS trip_day_pois (
                trip_day_id INT NOT NULL,
                poi_id INT NOT NULL,
                PRIMARY KEY (trip_day_id, poi_id),
                FOREIGN KEY (trip_day_id) REFERENCES trip_days(id),
                FOREIGN KEY (poi_id) REFERENCES poi(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        ]
        print("- Création des tables :")
        user_cnx = connect_mysql()
        user_cursor = user_cnx.cursor()
        for stmt in statements:
            user_cursor.execute(stmt)
            try:
                user_cursor.fetchall()
            except Exception:
                pass
            print("→ OK :", stmt.strip().split()[5])
        user_cnx.commit()
        user_cursor.close()
        user_cnx.close()
        print("Initialisation de la base terminée avec succès.\n")

    except Error as err:
        print(f"[Erreur user] {err}")

if __name__ == "__main__":
    init_database()
